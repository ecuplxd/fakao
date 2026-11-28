import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_site


def fake_run_checked(responses):
    def run(command, cwd, context):
        for prefix, output in responses:
            if command[: len(prefix)] == prefix:
                return output
        raise AssertionError(f"unexpected command: {command}")

    return run


class BranchSlugTests(unittest.TestCase):
    def test_slug_is_filename_safe_and_unique_per_ref(self):
        first = build_site.branch_slug("refs/heads/主观题")
        second = build_site.branch_slug("refs/remotes/origin/主观题")

        self.assertRegex(first, r"^[A-Za-z0-9._-]+$")
        self.assertNotEqual(first, second)
        self.assertEqual(first, build_site.branch_slug("refs/heads/主观题"))


class BranchOptionsTests(unittest.TestCase):
    def setUp(self):
        self.branches = [
            {"name": "master", "ref": "master", "slug": "master-1"},
            {"name": "主观题", "ref": "主观题", "slug": "subjective-2"},
        ]

    def test_root_page_links_to_branch_sites(self):
        options = build_site.branch_options(
            self.branches, "主观题", "主观题", False
        )

        self.assertEqual(
            options,
            [
                {"name": "master", "href": "branches/master-1/index.html"},
                {"name": "主观题", "href": ""},
            ],
        )

    def test_branch_page_links_back_to_root_and_siblings(self):
        options = build_site.branch_options(
            self.branches, "master", "主观题", True
        )

        self.assertEqual(
            options,
            [
                {"name": "master", "href": ""},
                {"name": "主观题", "href": "../../index.html"},
            ],
        )


class DiscoverBranchesTests(unittest.TestCase):
    def test_remote_duplicates_and_head_are_skipped(self):
        refs = "\n".join(
            [
                "refs/heads/master",
                "refs/heads/主观题",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/master",
                "refs/remotes/origin/main",
                "refs/remotes/origin/主观题",
            ]
        )
        run_checked = fake_run_checked(
            [
                (["git", "for-each-ref"], refs.encode("utf-8")),
                (["git", "branch", "--show-current"], b"master"),
            ]
        )

        with patch("build_site.run_checked", side_effect=run_checked):
            branches, current = build_site.discover_branches()

        self.assertEqual(current, "master")
        self.assertEqual(
            [branch["name"] for branch in branches],
            ["master", "origin/main", "主观题"],
        )
        self.assertEqual(len({branch["slug"] for branch in branches}), 3)

    def test_detached_head_becomes_selectable_entry(self):
        run_checked = fake_run_checked(
            [
                (["git", "for-each-ref"], b"refs/heads/master"),
                (["git", "branch", "--show-current"], b""),
                (["git", "rev-parse", "--short", "HEAD"], b"05638a2"),
            ]
        )

        with patch("build_site.run_checked", side_effect=run_checked):
            branches, current = build_site.discover_branches()

        self.assertEqual(current, "HEAD (05638a2)")
        self.assertEqual(
            [branch["name"] for branch in branches], ["HEAD (05638a2)", "master"]
        )
        self.assertIn("HEAD", [branch["ref"] for branch in branches])


class BuildPageTests(unittest.TestCase):
    def build_page(self, branch_name, options):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "web").mkdir()
        (root / "web" / "app.js").write_text("// app", encoding="utf-8")
        (root / "web" / "styles.css").write_text("/* css */", encoding="utf-8")
        output = root / "site"

        with patch.object(build_site, "ROOT", root), patch.object(
            build_site, "OUTPUT", output
        ), patch.object(build_site, "SUBJECTS", []), patch.object(
            build_site, "build_draw_assets"
        ):
            build_site.build(branch_name, options)
        return output, (output / "index.html").read_text(encoding="utf-8")

    def test_switcher_lists_branches_next_to_offline_status(self):
        output, page = self.build_page(
            "主观题",
            [
                {"name": "master", "href": "branches/master-1/index.html"},
                {"name": "主观题", "href": ""},
            ],
        )

        self.assertIn('id="branch-select"', page)
        self.assertIn("切换笔记版本", page)
        self.assertIn('value="branches/master-1/index.html">master</option>', page)
        self.assertIn('value="" selected>主观题</option>', page)
        self.assertNotIn('id="branch-select" aria-label="切换笔记版本" disabled', page)
        self.assertLess(
            page.index('class="offline-status"'), page.index('class="branch-switcher"')
        )
        self.assertIn('href="styles.css"', page)
        self.assertIn('src="app.js"', page)
        self.assertTrue((output / "app.js").is_file())
        self.assertTrue((output / "styles.css").is_file())

    def test_single_branch_disables_the_switcher(self):
        _, page = self.build_page(
            "当前分支", [{"name": "当前分支", "href": ""}]
        )

        self.assertIn('id="branch-select" aria-label="切换笔记版本" disabled', page)

    def test_branch_pages_are_built_with_the_official_builder(self):
        with patch.object(
            build_site,
            "run_checked",
            side_effect=lambda *args: b"05638a2",
        ), patch.object(
            build_site, "extract_branch_sources"
        ) as extract, patch(
            "build_site.subprocess.run"
        ) as run, patch(
            "build_site.shutil.copytree"
        ), patch.object(
            build_site, "SCRIPT_ROOT", Path("repo")
        ), patch.object(
            build_site, "OUTPUT", Path("repo/site")
        ):
            build_site.build_branch_sites(
                [
                    {"name": "master", "ref": "master", "slug": "master-1"},
                    {"name": "当前分支", "ref": "当前分支", "slug": "current-1"},
                ],
                "当前分支",
            )

        extract.assert_called_once()
        self.assertEqual(extract.call_args.args[0], "master")
        command = run.call_args.args[0]
        self.assertEqual(Path(command[-1]).name, "build_site.py")
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["FAKAO_BRANCH_NAME"], "master")
        self.assertEqual(environment["FAKAO_BRANCH_VARIANT"], "1")
        self.assertTrue(
            environment["FAKAO_OUTPUT_DIR"].endswith("site\\branches\\master-1")
            or environment["FAKAO_OUTPUT_DIR"].endswith("site/branches/master-1")
        )


if __name__ == "__main__":
    unittest.main()
