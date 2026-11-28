import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("FAKAO_SOURCE_ROOT", SCRIPT_ROOT)).resolve()
OUTPUT = Path(os.environ.get("FAKAO_OUTPUT_DIR", SCRIPT_ROOT / "site")).resolve()
CACHE = Path(os.environ.get("FAKAO_CACHE_DIR", SCRIPT_ROOT / ".fakao-draw")).resolve()
SUBJECTS = ["行政法", "理论法", "商经知", "三国法", "民诉", "民法", "刑诉", "刑法"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"}
ASSET_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
DRAW_ASSET_ENVIRONMENTS = {"forest", "tikzcd", "tikzpicture"}
DRAW_ASSETS = {}
DRAW_ASSET_TEXT = {}
TOKEN_RE = re.compile(
    r"\\begin\{([^}]+)\}|\\end\{([^}]+)\}|\\(?:sub)*section\*?(?=\s*\{)|"
    r"\\item(?:\[[^\]]*\])?|\\tcblower|\\\[|\\\]"
)


def strip_comments(source):
    lines = []
    for line in source.splitlines():
        result = []
        escaped = False
        for char in line:
            if char == "%" and not escaped:
                break
            result.append(char)
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        lines.append("".join(result))
    return "\n".join(lines)


def read_group(source, start):
    while start < len(source) and source[start].isspace():
        start += 1
    if start >= len(source) or source[start] != "{":
        return "", start
    depth = 1
    index = start + 1
    while index < len(source) and depth:
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
        index += 1
    return source[start + 1 : index - 1], index


def read_environment_body(source, environment, start):
    token = re.compile(
        r"\\(begin|end)\{" + re.escape(environment) + r"\}"
    )
    depth = 1
    position = start
    while match := token.search(source, position):
        position = match.end()
        if match.group(1) == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return source[start : match.start()], position
    raise ValueError(f"Unclosed LaTeX environment: {environment}")


def read_optional_group(source, start):
    while start < len(source) and source[start].isspace():
        start += 1
    if start >= len(source) or source[start] != "[":
        return "", start

    depth = 1
    brace_depth = 0
    index = start + 1
    while index < len(source) and depth:
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}" and brace_depth:
            brace_depth -= 1
        elif brace_depth == 0:
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
        index += 1
    return source[start + 1:index - 1], index


def resolve_asset(subject, source_path, target):
    candidate = (source_path.parent / target).resolve()
    if candidate.suffix.lower() == ".pdf" and candidate.with_suffix(".svg").is_file():
        candidate = candidate.with_suffix(".svg")
    options = [candidate]
    if not candidate.suffix:
        options.extend(candidate.with_suffix(ext) for ext in ASSET_EXTENSIONS)
    for path in options:
        if path.is_file() and path.suffix.lower() in ASSET_EXTENSIONS:
            relative = path.relative_to(ROOT / subject)
            destination = OUTPUT / "assets" / subject / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            return "assets/" + subject + "/" + relative.as_posix()
    generated_asset = OUTPUT / "assets" / subject / target
    if generated_asset.is_file() and generated_asset.suffix.lower() == ".svg":
        return generated_asset.relative_to(OUTPUT).as_posix()
    raise FileNotFoundError(f"Image referenced by {source_path}: {target}")


def run_checked(command, cwd, context):
    result = subprocess.run(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    if result.returncode:
        detail = result.stdout.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{context} failed (exit {result.returncode}):\n{detail[-4000:]}")
    return result.stdout


def branch_slug(ref):
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-") or "branch"
    suffix = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:8]
    return f"{safe_name}-{suffix}"


def discover_branches():
    refs = run_checked(
        [
            "git",
            "for-each-ref",
            "--format=%(refname)",
            "refs/heads",
            "refs/remotes",
        ],
        SCRIPT_ROOT,
        "Reading Git branches",
    ).decode("utf-8").splitlines()
    local_names = {
        ref[len("refs/heads/"):]
        for ref in refs
        if ref.startswith("refs/heads/")
    }
    branches = []
    for ref in refs:
        if ref.startswith("refs/heads/"):
            name = ref[len("refs/heads/"):]
            branch_ref = name
        elif ref.startswith("refs/remotes/"):
            name = ref[len("refs/remotes/"):]
            if name.endswith("/HEAD"):
                continue
            remote_branch = name.split("/", 1)[1]
            if remote_branch in local_names:
                continue
            branch_ref = name
        else:
            continue
        branches.append(
            {"name": name, "ref": branch_ref, "slug": branch_slug(branch_ref)}
        )

    current_name = run_checked(
        ["git", "branch", "--show-current"], SCRIPT_ROOT, "Reading current branch"
    ).decode("utf-8").strip()
    if not current_name:
        short_hash = run_checked(
            ["git", "rev-parse", "--short", "HEAD"], SCRIPT_ROOT, "Reading HEAD"
        ).decode("utf-8").strip()
        current_name = f"HEAD ({short_hash})"
        branches.append(
            {"name": current_name, "ref": "HEAD", "slug": branch_slug("HEAD")}
        )
    elif not any(branch["name"] == current_name for branch in branches):
        branches.append(
            {
                "name": current_name,
                "ref": current_name,
                "slug": branch_slug(current_name),
            }
        )

    for branch in branches:
        name = branch["name"]
        branch["label"] = "客观题" if name == "master" else name
    
    return sorted(branches, key=lambda branch: branch["name"]), current_name


def branch_options(branches, selected_name, root_name, nested):
    options = []
    for branch in branches:
        if branch["name"] == selected_name:
            href = ""
        elif nested and branch["name"] == root_name:
            href = "../../index.html"
        elif nested:
            href = f"../{branch['slug']}/index.html"
        else:
            href = f"branches/{branch['slug']}/index.html"
        options.append({"name": branch["name"], "label": branch["label"], "href": href})
    return options


def extract_branch_sources(branch_ref, destination):
    archive_path = destination.parent / "branch.tar"
    command = [
        "git",
        "archive",
        "--format=tar",
        branch_ref,
        "style.tex",
        *SUBJECTS,
    ]
    with archive_path.open("wb") as archive_file:
        result = subprocess.run(
            command, cwd=SCRIPT_ROOT, stdout=archive_file, stderr=subprocess.PIPE
        )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Exporting branch {branch_ref} failed "
            f"(exit {result.returncode}):\n{detail[-4000:]}"
        )
    with tarfile.open(archive_path, "r:") as archive:
        destination_root = destination.resolve()
        members = archive.getmembers()
        for member in members:
            target = (destination_root / member.name).resolve()
            if os.path.commonpath((destination_root, target)) != str(destination_root):
                raise RuntimeError(f"Unsafe path in branch archive: {member.name}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"Unsupported symlink in branch archive: {member.name}")
        archive.extractall(destination_root, members=members)


def build_branch_sites(branches, current_name):
    for branch in branches:
        if branch["name"] == current_name:
            continue
        with tempfile.TemporaryDirectory(prefix="fakao-branch-") as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "source"
            source_root.mkdir()
            extract_branch_sources(branch["ref"], source_root)
            shutil.copytree(
                SCRIPT_ROOT / "web", source_root / "web", dirs_exist_ok=True
            )
            options = branch_options(branches, branch["name"], current_name, True)
            environment = os.environ.copy()
            environment.update(
                {
                    "FAKAO_SOURCE_ROOT": str(source_root),
                    "FAKAO_OUTPUT_DIR": str(OUTPUT / "branches" / branch["slug"]),
                    "FAKAO_CACHE_DIR": str(CACHE),
                    "FAKAO_BRANCH_NAME": branch["name"],
                    "FAKAO_BRANCH_OPTIONS": json.dumps(options, ensure_ascii=False),
                    "FAKAO_BRANCH_VARIANT": "1",
                }
            )
            subprocess.run(
                [sys.executable, "-B", str(SCRIPT_ROOT / "build_site.py")],
                cwd=SCRIPT_ROOT,
                env=environment,
                check=True,
            )


def draw_cache_key(subject, relative, source, style_source, extra_package):
    digest = hashlib.sha256()
    for value in (
        "fakao-draw-cache-v1",
        subject,
        relative.as_posix(),
        source,
        style_source,
        extra_package,
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def build_draw_assets():
    global DRAW_ASSETS, DRAW_ASSET_TEXT
    tools = ("xelatex", "pdfcrop", "pdftocairo", "pdftotext", "pdfinfo")
    DRAW_ASSETS = {}
    DRAW_ASSET_TEXT = {}
    draw_sources = []
    style_source = (ROOT / "style.tex").read_text(encoding="utf-8")
    for subject in SUBJECTS:
        draw_dir = ROOT / subject / "draw"
        if not draw_dir.is_dir():
            continue
        for path in sorted(draw_dir.rglob("*.tex")):
            source = strip_comments(path.read_text(encoding="utf-8"))
            if re.search(
                r"\\begin\{(?:"
                + "|".join(DRAW_ASSET_ENVIRONMENTS)
                + r")\}",
                source,
            ):
                draw_sources.append((subject, path, source))
            elif re.search(r"\\begin\{tabular\}", source):
                old_svg = OUTPUT / "assets" / subject / path.relative_to(
                    ROOT / subject
                ).with_suffix(".svg")
                if old_svg.is_file():
                    old_svg.unlink()

    CACHE.mkdir(exist_ok=True)
    entries = []
    for index, (subject, path, source) in enumerate(draw_sources):
        relative = path.relative_to(ROOT / subject)
        asset_path = relative.with_suffix(".svg").as_posix()
        extra_package = "\\usepackage{tikz-qtree}\n" if r"\Tree" in source else ""
        cache_svg = CACHE / subject / relative.with_suffix(".svg")
        cache_svg.parent.mkdir(parents=True, exist_ok=True)
        entries.append(
            {
                "index": index,
                "subject": subject,
                "path": path,
                "source": source,
                "relative": relative,
                "asset_path": asset_path,
                "extra_package": extra_package,
                "key": draw_cache_key(
                    subject, relative, source, style_source, extra_package
                ),
                "cache_svg": cache_svg,
                "cache_text": cache_svg.with_suffix(".txt"),
                "cache_stamp": cache_svg.with_suffix(".sha256"),
            }
        )

    def cache_stamp_matches(entry):
        return (
            entry["cache_svg"].is_file()
            and entry["cache_text"].is_file()
            and entry["cache_stamp"].is_file()
            and entry["cache_stamp"].read_text(encoding="ascii").strip()
            == entry["key"]
        )

    for entry in entries:
        entry["cached"] = cache_stamp_matches(entry)

    if not all(entry["cached"] for entry in entries):
        missing = [tool for tool in tools if not shutil.which(tool)]
        if missing:
            raise RuntimeError(
                "Rendering TeX diagrams requires these commands on PATH: "
                + ", ".join(missing)
            )

    def render(entry):
        subject = entry["subject"]
        relative = entry["relative"]
        if entry["cached"]:
            transcript = entry["cache_text"].read_text(encoding="utf-8")
        else:
            index = entry["index"]
            wrapper_name = f"draw-{index:03d}.tex"
            wrapper = CACHE / wrapper_name
            wrapper.write_text(
                "\\input{../style.tex}\n"
                + entry["extra_package"]
                + "\\pagestyle{empty}\n"
                + "\\begin{document}\n"
                + f"\\input{{../{subject}/{relative.as_posix()}}}\n"
                + "\\end{document}\n",
                encoding="utf-8",
            )
            run_checked(
                [
                    "xelatex",
                    "-interaction=batchmode",
                    "-halt-on-error",
                    wrapper_name,
                ],
                CACHE,
                f"XeLaTeX ({subject}/{relative.as_posix()})",
            )

            pdf_path = CACHE / f"draw-{index:03d}.pdf"
            page_info = run_checked(
                ["pdfinfo", pdf_path.name],
                CACHE,
                f"PDF inspection ({relative.name})",
            ).decode("utf-8", errors="replace")
            page_match = re.search(r"^Pages:\s+(\d+)", page_info, re.MULTILINE)
            if not page_match or page_match.group(1) != "1":
                raise RuntimeError(
                    f"Expected one PDF page for {subject}/{relative.as_posix()}"
                )

            cropped_pdf = CACHE / f"draw-{index:03d}-cropped.pdf"
            run_checked(
                ["pdfcrop", "--hires", pdf_path.name, cropped_pdf.name],
                CACHE,
                f"PDF cropping ({relative.name})",
            )
            svg_path = CACHE / f"draw-{index:03d}.svg"
            run_checked(
                ["pdftocairo", "-svg", cropped_pdf.name, svg_path.name],
                CACHE,
                f"SVG conversion ({relative.name})",
            )
            transcript = run_checked(
                ["pdftotext", "-layout", "-enc", "UTF-8", cropped_pdf.name, "-"],
                CACHE,
                f"Diagram text extraction ({relative.name})",
            ).decode("utf-8", errors="replace").strip()

            shutil.copy2(svg_path, entry["cache_svg"])
            entry["cache_text"].write_text(transcript, encoding="utf-8")
            entry["cache_stamp"].write_text(entry["key"], encoding="ascii")

        destination = OUTPUT / "assets" / subject / entry["asset_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry["cache_svg"], destination)
        return entry["path"].resolve(), subject, entry["asset_path"], transcript

    workers = os.cpu_count() or 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(render, entries))

    for path, subject, asset_path, transcript in results:
        DRAW_ASSETS[path] = asset_path
        DRAW_ASSET_TEXT[(subject, asset_path)] = transcript
    cache_hits = sum(1 for entry in entries if entry["cached"])
    print(
        f"Rendered {len(draw_sources) - cache_hits} TeX diagrams; "
        f"reused {cache_hits} cached SVGs."
    )


def expand_inputs(subject, source_path, stack=()):
    source_path = source_path.resolve()
    if source_path in stack:
        raise ValueError(f"Cyclic TeX input: {source_path}")
    source = strip_comments(source_path.read_text(encoding="utf-8"))
    pattern = re.compile(r"\\input\{([^}]+)\}")

    def replace(match):
        relative = match.group(1)
        path = (source_path.parent / relative).with_suffix(".tex")
        if not path.is_file():
            return ""
        if path.resolve() in DRAW_ASSETS:
            return f"\\drawasset{{{DRAW_ASSETS[path.resolve()]}}}"
        return expand_inputs(subject, path, (*stack, source_path))

    return pattern.sub(replace, source)


def inline(source, subject, source_path):
    output = []
    index = 0
    while index < len(source):
        if source[index : index + 2] in {r"\[", r"\]"}:
            index += 2
            continue

        if source[index] != "\\":
            next_command = source.find("\\", index)
            if next_command == -1:
                next_command = len(source)
            output.append(html.escape(source[index:next_command]).replace("\n", " "))
            index = next_command
            continue

        if source.startswith("\\\\", index):
            output.append("<br>")
            index += 2
            continue

        match = re.match(r"\\([A-Za-z]+)(\*)?", source[index:])
        if not match:
            escaped = {"\\&": "&amp;", "\\%": "%", "\\_": "_", "\\#": "#", "\\$": "$"}
            token = source[index : index + 2]
            output.append(
                escaped.get(token, html.escape(source[index + 1 : index + 2]))
            )
            index += 2
            continue

        command = match.group(1)
        index += len(match.group(0))
        if command == "drawasset":
            target, index = read_group(source, index)
            url = resolve_asset(subject, source_path, target)
            transcript = DRAW_ASSET_TEXT.get((subject, target), "")
            details = (
                '<details class="diagram-transcript"><summary>查看图示文字</summary>'
                f"<pre>{html.escape(transcript)}</pre></details>"
                if transcript
                else ""
            )
            output.append(
                f'<figure><img src="{html.escape(url, quote=True)}" '
                f'alt="{html.escape(Path(target).stem, quote=True)}" loading="lazy">'
                f"<figcaption>{html.escape(Path(target).stem)}</figcaption>{details}</figure>"
            )
            continue

        if command in {"cuo", "dui"}:
            note = ""
            if index < len(source) and source[index] == "[":
                end = source.find("]", index + 1)
                if end >= 0:
                    index = end + 1
            if index < len(source) and source[index] == "{":
                note, index = read_group(source, index)
            symbol = "×" if command == "cuo" else "√"
            output.append(f'<span class="symbol">{symbol}</span>')
            if note:
                output.append(
                    f'<span class="inline-note">{inline(note, subject, source_path)}</span>'
                )
            continue

        if command == "includegraphics":
            if index < len(source) and source[index] == "[":
                end = source.find("]", index + 1)
                if end >= 0:
                    index = end + 1
            target, index = read_group(source, index)
            url = resolve_asset(subject, source_path, target)
            if Path(url).suffix.lower() == ".pdf":
                output.append(
                    f'<figure><iframe class="diagram-pdf" src="{html.escape(url, quote=True)}" '
                    f'title="{html.escape(Path(target).stem, quote=True)}"></iframe>'
                    f"<figcaption>{html.escape(Path(target).stem)}</figcaption></figure>"
                )
            else:
                output.append(
                    f'<figure><img src="{html.escape(url, quote=True)}" '
                    f'alt="{html.escape(Path(target).stem, quote=True)}" loading="lazy">'
                    f"<figcaption>{html.escape(Path(target).stem)}</figcaption></figure>"
                )
            continue

        wrappers = {
            "al": ("span", "example"),
            "zd": ("span", "key-point"),
            "bs": ("span", "memory-tip"),
            "zx": ("span", "blue-point"),
            "xhx": ("u", ""),
            "scx": ("del", ""),
            "textbf": ("strong", ""),
            "emph": ("em", ""),
            "textit": ("em", ""),
            "underline": ("u", ""),
            "lzi": ("span", "green-text"),
            "hzi": ("span", "magenta-text"),
            "fangsong": ("span", "example"),
            "kaishu": ("span", "example"),
        }
        if command in wrappers:
            content, index = read_group(source, index)
            tag, class_name = wrappers[command]
            class_attr = f' class="{class_name}"' if class_name else ""
            output.append(
                f"<{tag}{class_attr}>{inline(content, subject, source_path)}</{tag}>"
            )
            continue

        if command == "textcolor":
            _, index = read_group(source, index)
            content, index = read_group(source, index)
            output.append(inline(content, subject, source_path))
            continue

        if command in {"frac", "dfrac", "tfrac"}:
            numerator, index = read_group(source, index)
            denominator, index = read_group(source, index)
            output.append(
                f'<span class="fraction">{inline(numerator, subject, source_path)}'
                f"<span>{inline(denominator, subject, source_path)}</span></span>"
            )
            continue

        if command in {"footnote", "text", "mbox", "makecell"}:
            content, index = read_group(source, index)
            output.append(inline(content, subject, source_path))
            continue

        replacements = {
            "yjt": "→",
            "zyjt": "↔",
            "sjt": "↑",
            "xjt": "↓",
            "dy": "＞",
            "xyh": "＜",
            "ydy": "≈",
            "bdy": "≠",
            "dydy": "≥",
            "xydy": "≤",
            "hz": "||",
            "blh": "~",
            "yi": "①.",
            "er": "②.",
            "san": "③.",
            "si": "④.",
            "times": "×",
            "cdot": "·",
            "ldots": "…",
            "quad": "　",
            "qquad": "　　",
            "LaTeX": "LaTeX",
        }
        if command in replacements:
            output.append(
                f'<span class="green-text">{replacements[command]}</span>'
                if command in {"yi", "er", "san", "si"}
                else replacements[command]
            )
            continue

        if command in {"hspace", "vspace", "raisebox", "scalebox", "linewidth"}:
            if index < len(source) and source[index] == "[":
                end = source.find("]", index + 1)
                if end >= 0:
                    index = end + 1
            if index < len(source) and source[index] == "{":
                _, index = read_group(source, index)
            if (
                command in {"raisebox", "scalebox"}
                and index < len(source)
                and source[index] == "{"
            ):
                content, index = read_group(source, index)
                output.append(inline(content, subject, source_path))
            continue

        if command in {"char", "index", "label", "indexprologue"}:
            if index < len(source) and source[index] == "{":
                _, index = read_group(source, index)
            continue

        if command in {"ensuremath", "mathrm", "mathbf", "operatorname"}:
            content, index = read_group(source, index)
            output.append(inline(content, subject, source_path))
            continue

        if command in {"textbackslash", "%"}:
            output.append("%" if command == "%" else "\\")
        elif command in {"_", "#", "&", "$"}:
            output.append(html.escape(command))
        elif command in {"par", "newline"}:
            output.append("<br>")
        elif index < len(source) and source[index] == "{":
            content, index = read_group(source, index)
            output.append(inline(content, subject, source_path))

    return "".join(output)


def paragraph(source, subject, source_path):
    text = " ".join(source.split())
    if not text:
        return ""
    return f"<p>{inline(text, subject, source_path)}</p>"


def split_table_rows(source):
    rule_pattern = re.compile(
        r"\\(?:(toprule|midrule|bottomrule|hline)\b|"
        r"(cmidrule|cline)(?:\([^)]*\))?\s*\{(\d+)\s*-\s*(\d+)\})"
    )
    rows = []
    rules = []
    cells = []
    cell = []
    depth = 0
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\":
            rule_match = rule_pattern.match(source, index) if depth == 0 else None
            if rule_match:
                kind = rule_match.group(1) or rule_match.group(2)
                start_column = int(rule_match.group(3) or 1)
                end_column = int(rule_match.group(4) or 0)
                rules.append(
                    (len(rows), kind, start_column, end_column)
                )
                index = rule_match.end()
                continue
            if depth == 0 and source.startswith("\\\\", index):
                cells.append("".join(cell).strip())
                rows.append(cells)
                cells, cell = [], []
                index += 2
                _, index = read_optional_group(source, index)
                continue
            cell.append(source[index : index + 2])
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        elif char == "&" and depth == 0:
            cells.append("".join(cell).strip())
            cell = []
            index += 1
            continue
        cell.append(char)
        index += 1
    if cell or cells:
        cells.append("".join(cell).strip())
        rows.append(cells)
    return rows, rules


def unwrap_table_cell(source, default_alignment):
    source = source.strip()
    colspan = 1
    rowspan = 1
    alignment = default_alignment
    while match := re.match(r"\\(multicolumn|multirow)\*?", source):
        index = match.end()
        if match.group(1) == "multicolumn":
            span, index = read_group(source, index)
            column_spec, index = read_group(source, index)
            source, index = read_group(source, index)
            colspan = int(span.strip())
            alignment = next(
                (char for char in column_spec if char in "lcr"), alignment
            )
        else:
            span, index = read_group(source, index)
            _, index = read_group(source, index)
            source, index = read_group(source, index)
            rowspan = int(span.strip())
        source = source.strip()
    return source, colspan, rowspan, alignment


def table_html(source, column_spec, subject, source_path):
    column_alignments = [
        char if char in "lcr" else "l"
        for char in column_spec
        if char in "lcrpmb"
    ]
    rows, rules = split_table_rows(source)
    active_rowspans = {}
    rendered_rows = []
    all_cells = []
    section_start = False

    for row_index, row in enumerate(rows):
        is_empty = all(not cell for cell in row)
        if is_empty and not active_rowspans:
            if rendered_rows:
                section_start = True
            continue

        is_header = (
            not rendered_rows
            or section_start
            or any(kind == "toprule" and boundary == row_index for boundary, kind, _, _ in rules)
        )
        rendered_cells = []
        column_index = 0
        next_rowspans = {
            column: remaining - 1
            for column, remaining in active_rowspans.items()
            if remaining > 1
        }

        for cell in row:
            default_alignment = (
                column_alignments[column_index]
                if column_index < len(column_alignments)
                else "l"
            )
            content, colspan, rowspan, alignment = unwrap_table_cell(
                cell, default_alignment
            )
            if column_index in active_rowspans:
                if content:
                    raise ValueError("A table cell overlaps an active multirow span")
                column_index += colspan
                continue

            cell_data = {
                "tag": "th" if is_header else "td",
                "column": column_index,
                "colspan": colspan,
                "rowspan": rowspan,
                "row_index": row_index,
                "classes": [f"align-{alignment}"],
            }
            if rowspan > 1:
                for covered_column in range(column_index, column_index + colspan):
                    next_rowspans[covered_column] = rowspan - 1
            if colspan > 1:
                cell_data["colspan_attr"] = f' colspan="{colspan}"'
            else:
                cell_data["colspan_attr"] = ""
            if rowspan > 1:
                cell_data["rowspan_attr"] = f' rowspan="{rowspan}"'
            else:
                cell_data["rowspan_attr"] = ""
            cell_html = inline(content, subject, source_path) or "&nbsp;"
            cell_data["html"] = cell_html
            rendered_cells.append(cell_data)
            all_cells.append(cell_data)
            column_index += colspan

        rendered_rows.append(
            {
                "source_index": row_index,
                "section_start": section_start,
                "cells": rendered_cells,
            }
        )
        active_rowspans = next_rowspans
        section_start = False

    def add_rule(cell, direction, weight):
        rule_class = f"rule-{direction}-{weight}"
        if rule_class not in cell["classes"]:
            cell["classes"].append(rule_class)

    for boundary, kind, start_column, end_column in rules:
        if kind == "toprule":
            direction, weight = "top", "heavy"
        elif kind == "bottomrule":
            direction, weight = "bottom", "heavy"
        elif kind == "hline" and boundary >= len(rows):
            direction, weight = "bottom", "light"
        else:
            direction, weight = "top", "light"

        if end_column == 0:
            end_column = max(
                (cell["column"] + cell["colspan"] for cell in all_cells),
                default=len(column_alignments),
            )
        start = start_column - 1
        end = end_column

        if direction == "top":
            target_row = next(
                (
                    row
                    for row in rendered_rows
                    if row["source_index"] >= boundary
                ),
                None,
            )
            if target_row is None:
                direction = "bottom"
            else:
                for cell in target_row["cells"]:
                    cell_start = cell["column"]
                    cell_end = cell_start + cell["colspan"]
                    if cell_start < end and cell_end > start:
                        add_rule(cell, direction, weight)
                continue

        if direction == "bottom":
            matching_cells = [
                cell
                for cell in all_cells
                if cell["row_index"] + cell["rowspan"] == boundary
                and cell["column"] < end
                and cell["column"] + cell["colspan"] > start
            ]
            if not matching_cells:
                preceding_cells = [
                    cell
                    for cell in all_cells
                    if cell["row_index"] < boundary
                    and cell["column"] < end
                    and cell["column"] + cell["colspan"] > start
                ]
                if preceding_cells:
                    latest_edge = max(
                        cell["row_index"] + cell["rowspan"]
                        for cell in preceding_cells
                    )
                    matching_cells = [
                        cell
                        for cell in preceding_cells
                        if cell["row_index"] + cell["rowspan"] == latest_edge
                    ]
            for cell in matching_cells:
                add_rule(cell, direction, weight)

    rendered = []
    for row in rendered_rows:
        cells = []
        for cell in row["cells"]:
            attrs = (
                cell["colspan_attr"]
                + cell["rowspan_attr"]
                + f' class="{" ".join(cell["classes"])}"'
            )
            cells.append(
                f'<{cell["tag"]}{attrs}>{cell["html"]}</{cell["tag"]}>'
            )
        rendered.append(f"<tr>{''.join(cells)}</tr>")

    return (
        '<div class="table-wrap"><table><tbody>'
        + "".join(rendered)
        + "</tbody></table></div>"
    )


def parse_forest(source, subject, source_path):
    start = source.find("[")
    if start < 0:
        return ""

    def node_at(index):
        index += 1
        label = []
        children = []
        while index < len(source):
            char = source[index]
            if char == "\\":
                label.append(source[index : index + 2])
                index += 2
            elif char == "[":
                child, index = node_at(index)
                children.append(child)
            elif char == "]":
                break
            else:
                label.append(char)
                index += 1
        label_text = re.sub(
            r",\s*(?:align|base|tier|calign|l|s sep|s l sep)\s*=.*$",
            "",
            "".join(label),
            flags=re.S,
        )
        label_html = inline(label_text.strip(), subject, source_path)
        child_html = "<ul>" + "".join(children) + "</ul>" if children else ""
        return f"<li>{label_html}{child_html}</li>", index + 1

    tree, _ = node_at(start)
    return f'<div class="tree-diagram"><ul>{tree}</ul></div>'


def parse_content(source, subject, source_path):
    output = []
    cursor = 0
    series_counters = {}

    def parse_list(start, environment, options=""):
        token = re.compile(r"\\begin\{([^}]+)\}|\\end\{([^}]+)\}|\\item(?:\[[^\]]*\])?")
        series_match = re.search(r"(?:^|,)\s*series\s*=\s*([^,\s]+)", options)
        resume_match = re.search(r"(?:^|,)\s*resume\*?\s*=\s*([^,\s]+)", options)
        series_name = series_match.group(1) if series_match else None
        resume_name = resume_match.group(1) if resume_match else None
        resume_start = series_counters.get(resume_name, 0) + 1 if resume_name else 1
        if series_name:
            series_counters[series_name] = 0
        list_start = f' start="{resume_start}"' if resume_name and resume_start > 1 else ""
        result = [
            f"<ol{list_start}>" if environment == "enumerate" else "<ul>"
        ]
        item_open = False
        item_count = 0
        position = start
        while True:
            match = token.search(source, position)
            if match is None:
                break
            result.append(
                paragraph(source[position : match.start()], subject, source_path)
            )
            position = match.end()
            if match.group(1):
                inner, position = parse_environment(match.group(1), position)
                result.append(inner)
            elif match.group(2):
                if match.group(2) == environment:
                    if item_open:
                        result.append("</li>")
                    result.append("</ol>" if environment == "enumerate" else "</ul>")
                    if series_name:
                        series_counters[series_name] = item_count
                    elif resume_name:
                        series_counters[resume_name] = resume_start - 1 + item_count
                    return "".join(result), position
            else:
                if item_open:
                    result.append("</li>")
                result.append("<li>")
                item_open = True
                item_count += 1
        if item_open:
            result.append("</li>")
        result.append("</ol>" if environment == "enumerate" else "</ul>")
        return "".join(result), position

    def parse_environment(environment, start):
        if environment in {"enumerate", "itemize"}:
            options, start = read_optional_group(source, start)
            return parse_list(start, environment, options)

        if environment == "kk":
            title, start = read_group(source, start)
            inner, end = parse_until_environment("kk", start)
            return (
                f'<aside class="callout"><h3>{inline(title, subject, source_path)}</h3>'
                f"{inner}</aside>",
                end,
            )

        if environment == "tabular":
            column_spec, start = read_group(source, start)
            content, end = read_environment_body(source, "tabular", start)
            return table_html(content, column_spec, subject, source_path), end

        if environment == "forest":
            content, end = parse_until_environment("forest", start)
            return parse_forest(content, subject, source_path), end

        if environment in {"tikzcd", "tikzpicture"}:
            content, end = parse_until_environment(environment, start)
            if environment == "tikzcd":
                rows = re.sub(r"\\arrow(?:\[[^]]*\])?\{?[^}]*\}?", "", content)
                labels = [
                    cell.strip()
                    for cell in re.split(r"&|\\\\", rows)
                    if cell.strip() and not cell.strip().startswith("[")
                ]
                labels = [
                    re.sub(r"\\[a-zA-Z]+(?:\{[^}]*\})?", "", label).strip()
                    for label in labels
                ]
                chips = "".join(
                    f"<span>{inline(label, subject, source_path)}</span>"
                    for label in labels
                    if label
                )
                return (
                    f'<div class="diagram-labels" aria-label="图示节点">{chips}</div>',
                    end,
                )
            labels = re.findall(
                r"\\node(?:\[[^]]*\])?\s*\([^)]*\)\s*at\s*\([^)]*\)\s*\{([^}]*)\}",
                content,
            )
            if labels:
                return '<div class="diagram-labels">' + "".join(
                    f"<span>{inline(label, subject, source_path)}</span>"
                    for label in labels
                ) + "</div>", end
            return '<p class="diagram-note">此处原笔记包含示意图。</p>', end

        if environment == "center":
            inner, end = parse_until_environment("center", start)
            return inner, end

        inner, end = parse_until_environment(environment, start)
        return inner, end

    def parse_until_environment(environment, start):
        pieces = []
        position = start
        while True:
            match = TOKEN_RE.search(source, position)
            if match is None:
                pieces.append(paragraph(source[position:], subject, source_path))
                return "".join(pieces), len(source)
            pieces.append(
                paragraph(source[position : match.start()], subject, source_path)
            )
            position = match.end()
            if match.group(1):
                inner, position = parse_environment(match.group(1), position)
                pieces.append(inner)
            elif match.group(2):
                if match.group(2) == environment:
                    return "".join(pieces), position
            elif match.group(0).startswith("\\section"):
                title, position = read_group(source, position)
                pieces.append(f"<h2>{inline(title, subject, source_path)}</h2>")
            elif match.group(0).startswith("\\item"):
                pieces.append(f"<p>{inline(match.group(0), subject, source_path)}</p>")
            elif match.group(0) == "\\tcblower":
                pieces.append("<div class='hr'></div>")
            else:
                pieces.append("<br>" if match.group(0) == "\\\\" else "")

    while cursor < len(source):
        match = TOKEN_RE.search(source, cursor)
        if match is None:
            output.append(paragraph(source[cursor:], subject, source_path))
            break
        output.append(paragraph(source[cursor : match.start()], subject, source_path))
        cursor = match.end()
        if match.group(1):
            rendered, cursor = parse_environment(match.group(1), cursor)
            output.append(rendered)
        elif match.group(2):
            continue
        elif match.group(0).startswith("\\section"):
            title, cursor = read_group(source, cursor)
            # output.append(f"<h2>{inline(title, subject, source_path)}</h2>")
        elif match.group(0).startswith("\\item"):
            output.append(f"<p>{inline(match.group(0), subject, source_path)}</p>")
        elif match.group(0) == "\\tcblower":
            output.append("<div class='hr'></div>")
        else:
            output.append("")
    return "".join(output)


def main_file_contents(subject):
    main_path = ROOT / subject / "main.tex"
    source = strip_comments(main_path.read_text(encoding="utf-8"))
    groups = []
    current_group = {"title": subject, "topics": []}
    for match in re.finditer(r"\\chapter\{([^}]+)\}|\\input\{([^}]+)\}", source):
        if match.group(1):
            if current_group["topics"]:
                groups.append(current_group)
            current_group = {"title": match.group(1), "topics": []}
            continue
        filename = match.group(2)
        if filename.startswith("../") or filename == "../style.tex":
            continue
        path = (ROOT / subject / filename).with_suffix(".tex")
        if path.is_file():
            current_group["topics"].append(path)
    if current_group["topics"]:
        groups.append(current_group)

    included = set()

    def collect_inputs(path):
        path = path.resolve()
        if path in included:
            return
        included.add(path)
        nested_source = strip_comments(path.read_text(encoding="utf-8"))
        for reference in re.findall(r"\\input\{([^}]+)\}", nested_source):
            nested_path = (path.parent / reference).with_suffix(".tex")
            if nested_path.is_file():
                collect_inputs(nested_path)

    for group in groups:
        for path in group["topics"]:
            collect_inputs(path)

    # extras = [
    #     path
    #     for path in sorted((ROOT / subject).glob("*.tex"), key=lambda item: item.name)
    #     if path.name != "main.tex"
    #     and not path.name.startswith("_")
    #     and path.resolve() not in included
    # ]
    # if extras:
    #     groups.append({"title": "其他笔记（未编入）", "topics": extras})
    return groups


def build(branch_name=None, switch_options=None):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    build_draw_assets()
    (OUTPUT / "app.js").write_text(
        (ROOT / "web" / "app.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (OUTPUT / "styles.css").write_text(
        (ROOT / "web" / "styles.css").read_text(encoding="utf-8"), encoding="utf-8"
    )

    data = []
    for subject in SUBJECTS:
        groups = []
        for group in main_file_contents(subject):
            topics = []
            for path in group["topics"]:
                title = path.stem
                body = parse_content(expand_inputs(subject, path), subject, path)
                topics.append(
                    {
                        "id": f"{subject}/{title}",
                        "title": title,
                        "html": body,
                        "text": html.unescape(re.sub(r"<[^>]+>", " ", body)),
                    }
                )
            groups.append({"title": group["title"], "topics": topics})
        data.append({"name": subject, "groups": groups})

    serialized = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    branch_name = branch_name or "当前分支"
    switch_options = switch_options or [
        {"name": branch_name, "href": ""}
    ]
    branch_select_options = "\n".join(
        f'<option value="{html.escape(option["href"], quote=True)}"'
        f'{" selected" if option["name"] == branch_name else ""}>'
        f'{html.escape(option["label"])}</option>'
        for option in switch_options
    )
    branch_select_disabled = " disabled" if len(switch_options) < 2 else ""
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#153a32">
  <meta name="description" content="法考 LaTeX 笔记的离线浏览、全文搜索与个人批注">
  <title>法考笔记 · 离线阅读</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar" id="sidebar">
      <a class="brand" href="#" aria-label="法考笔记首页">
        <span class="brand-mark">法</span><span><strong>法考笔记</strong><small>PERSONAL STUDY LIBRARY</small></span>
      </a>
      <div class="sidebar-caption">科目导航</div>
      <nav id="navigation" aria-label="笔记科目"></nav>
      <div class="sidebar-bottom">
        <div class="offline-status"><span class="offline-dot"></span><span>本地离线 · 内容仅在此设备打开</span></div>
        <label class="branch-switcher" title="切换笔记版本">
          <select id="branch-select" aria-label="切换笔记版本"{branch_select_disabled}>
            {branch_select_options}
          </select>
        </label>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <button id="menu-button" class="icon-button menu-button" aria-label="打开科目导航">☰</button>
        <div class="search-wrap">
          <span class="search-icon" aria-hidden="true">⌕</span>
          <input id="search" type="search" placeholder="搜索所有笔记…" autocomplete="off" aria-label="搜索所有笔记">
          <kbd>Ctrl K</kbd>
        </div>
        <button id="export-notes" class="toolbar-button" title="导出批注备份">导出批注</button>
        <label class="toolbar-button import-button" title="导入批注备份">导入批注<input id="import-notes" type="file" accept="application/json,.json" hidden></label>
      </header>
      <aside class="article-toc" id="article-toc" hidden aria-label="目录"></aside>
      <section id="search-results" class="search-results" hidden></section>
      <div class="reading-layout">
        <article class="reader" id="reader">
          <div class="welcome" id="welcome">
            <div class="eyebrow">PERSONAL STUDY LIBRARY</div>
            <h1>把重点，重新读一遍。</h1>
            <p>从科目导航开始，或搜索全部笔记。选中正文即可添加自己的批注。</p>
            <div class="welcome-stats" id="welcome-stats"></div>
          </div>
          <div id="article" hidden></div>
        </article>
        <aside class="annotation-panel" id="annotation-panel" hidden>
          <div class="annotation-heading"><div><span class="eyebrow">YOUR NOTES</span><h2>我的批注</h2></div>
            <button id="close-annotations" class="icon-button" aria-label="关闭批注">×</button></div>
          <p class="annotation-hint">批注保存在当前浏览器中。</p>
          <div id="annotation-list"></div>
        </aside>
      </div>
      <div class="selection-bar" id="selection-bar" hidden>
        <span id="selection-preview"></span><button id="annotate-selection">添加批注</button>
      </div>
      <div class="modal-backdrop" id="annotation-modal" hidden>
        <form class="annotation-form" id="annotation-form">
          <div class="annotation-heading"><div><span class="eyebrow">ANNOTATION</span><h2>写下你的批注</h2></div>
            <button type="button" class="icon-button" id="cancel-annotation" aria-label="取消">×</button></div>
          <blockquote id="quoted-text"></blockquote>
          <label for="annotation-input">批注内容</label>
          <textarea id="annotation-input" rows="4" placeholder="补充理解、记忆提示或疑问…" required></textarea>
          <div class="form-actions"><button type="button" class="toolbar-button" id="discard-annotation">取消</button>
            <button class="primary-button" type="submit">保存批注</button></div>
        </form>
      </div>
    </main>
  </div>
  <script id="notes-data" type="application/json">{serialized}</script>
  <script src="app.js"></script>
</body>
</html>
"""
    (OUTPUT / "index.html").write_text(page, encoding="utf-8")
    count = sum(len(group["topics"]) for subject in data for group in subject["groups"])
    print(
        f"Built {OUTPUT / 'index.html'} with {len(data)} subjects and {count} topics."
    )


if __name__ == "__main__":
    if os.environ.get("FAKAO_BRANCH_VARIANT") == "1":
        build(
            os.environ.get("FAKAO_BRANCH_NAME"),
            json.loads(os.environ["FAKAO_BRANCH_OPTIONS"]),
        )
    else:
        branches, current_name = discover_branches()
        build(
            current_name,
            branch_options(branches, current_name, current_name, False),
        )
        build_branch_sites(branches, current_name)
