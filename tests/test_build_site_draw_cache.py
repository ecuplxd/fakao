from contextlib import ExitStack
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_site


class DrawCacheTests(unittest.TestCase):
    def test_matching_cache_skips_compile_and_source_changes_invalidate_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subject = "刑法"
            relative = Path("draw") / "示例.tex"
            source_path = root / subject / relative
            source_path.parent.mkdir(parents=True)
            source = r"\begin{forest} [原内容] \end{forest}"
            source_path.write_text(source, encoding="utf-8")
            style_source = r"\newcommand{\example}{示例}"
            (root / "style.tex").write_text(style_source, encoding="utf-8")

            cache = root / ".fakao-draw"
            cache_svg = cache / subject / relative.with_suffix(".svg")
            cache_svg.parent.mkdir(parents=True)
            cache_svg.write_text("<svg></svg>", encoding="utf-8")
            cache_svg.with_suffix(".txt").write_text("图示文字", encoding="utf-8")
            key = build_site.draw_cache_key(
                subject, relative, source, style_source, ""
            )
            cache_svg.with_suffix(".sha256").write_text(key, encoding="ascii")

            with ExitStack() as stack:
                stack.enter_context(patch.object(build_site, "ROOT", root))
                stack.enter_context(patch.object(build_site, "OUTPUT", root / "site"))
                stack.enter_context(patch.object(build_site, "CACHE", cache))
                stack.enter_context(patch.object(build_site, "SUBJECTS", [subject]))
                stack.enter_context(
                    patch("build_site.shutil.which", return_value=None)
                )
                run_checked = stack.enter_context(patch("build_site.run_checked"))
                build_site.build_draw_assets()
                run_checked.assert_not_called()

            output_svg = (
                root / "site" / "assets" / subject / relative.with_suffix(".svg")
            )
            self.assertEqual(output_svg.read_text(encoding="utf-8"), "<svg></svg>")
            self.assertEqual(
                build_site.DRAW_ASSET_TEXT[
                    (subject, relative.with_suffix(".svg").as_posix())
                ],
                "图示文字",
            )
            self.assertTrue(cache.is_dir())

            source_path.write_text(source.replace("原内容", "新内容"), encoding="utf-8")
            with ExitStack() as stack:
                stack.enter_context(patch.object(build_site, "ROOT", root))
                stack.enter_context(patch.object(build_site, "OUTPUT", root / "site"))
                stack.enter_context(patch.object(build_site, "CACHE", cache))
                stack.enter_context(patch.object(build_site, "SUBJECTS", [subject]))
                stack.enter_context(
                    patch("build_site.shutil.which", return_value="xelatex")
                )
                stack.enter_context(
                    patch(
                        "build_site.run_checked",
                        side_effect=AssertionError("stale cache must recompile"),
                    )
                )
                with self.assertRaisesRegex(AssertionError, "must recompile"):
                    build_site.build_draw_assets()

    def test_cached_diagrams_of_every_subject_are_copied_in_source_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            style_source = "style"
            (root / "style.tex").write_text(style_source, encoding="utf-8")
            cache = root / ".fakao-draw"
            cache.mkdir()
            subjects = ["刑法", "民法"]
            expected = []
            for subject in subjects:
                relative = Path("draw") / f"{subject}图.tex"
                source_path = root / subject / relative
                source_path.parent.mkdir(parents=True)
                source = r"\begin{forest} [" + subject + r"] \end{forest}"
                source_path.write_text(source, encoding="utf-8")
                cache_svg = cache / subject / relative.with_suffix(".svg")
                cache_svg.parent.mkdir(parents=True)
                cache_svg.write_text(f"<svg>{subject}</svg>", encoding="utf-8")
                cache_svg.with_suffix(".txt").write_text(
                    f"{subject} 图示", encoding="utf-8"
                )
                key = build_site.draw_cache_key(
                    subject, relative, source, style_source, ""
                )
                cache_svg.with_suffix(".sha256").write_text(key, encoding="ascii")
                expected.append((subject, relative, source_path, cache_svg))

            with ExitStack() as stack:
                stack.enter_context(patch.object(build_site, "ROOT", root))
                stack.enter_context(patch.object(build_site, "OUTPUT", root / "site"))
                stack.enter_context(patch.object(build_site, "CACHE", cache))
                stack.enter_context(patch.object(build_site, "SUBJECTS", subjects))
                stack.enter_context(
                    patch(
                        "build_site.run_checked",
                        side_effect=AssertionError("cached diagrams must not compile"),
                    )
                )
                build_site.build_draw_assets()

            self.assertEqual(
                list(build_site.DRAW_ASSETS),
                [source_path.resolve() for _, _, source_path, _ in expected],
            )
            for subject, relative, _, cache_svg in expected:
                destination = (
                    root / "site" / "assets" / subject / relative.with_suffix(".svg")
                )
                self.assertEqual(
                    destination.read_text(encoding="utf-8"),
                    cache_svg.read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    build_site.DRAW_ASSET_TEXT[
                        (subject, relative.with_suffix(".svg").as_posix())
                    ],
                    f"{subject} 图示",
                )


if __name__ == "__main__":
    unittest.main()
