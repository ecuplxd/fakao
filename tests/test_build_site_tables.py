import unittest
from html.parser import HTMLParser
from pathlib import Path

import build_site


class TableStructure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = 0
        self.cells = []
        self.row_cells = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows += 1
            self.row_cells.append([])
        elif tag in {"th", "td"}:
            cell = (tag, dict(attrs))
            self.cells.append(cell)
            self.row_cells[-1].append(cell)


class TableRenderingTests(unittest.TestCase):
    def test_nested_multicolumn_and_multirow_are_preserved(self):
        rendered = build_site.table_html(
            r"\multicolumn{2}{c}{\multirow{2}{*}{A & B}} & C \\"
            r"& & D \\",
            "ccc",
            "刑法",
            Path("table.tex"),
        )
        structure = TableStructure()
        structure.feed(rendered)

        self.assertIn(("th", {"colspan": "2", "rowspan": "2", "class": "align-c"}), structure.cells)
        self.assertEqual(structure.rows, 2)
        self.assertIn("A &amp; B", rendered)
        self.assertIn(">D</td>", rendered)

    def test_all_draw_tabular_sources_render_as_html_tables(self):
        paths = (
            Path("三国法/draw/涉港澳台文书送达.tex"),
            Path("刑法/draw/片面实行.tex"),
            Path("刑法/draw/认识错误.tex"),
            Path("刑法/draw/认识错误2.tex"),
        )
        for path in paths:
            with self.subTest(path=path):
                source = build_site.strip_comments(
                    (build_site.ROOT / path).read_text(encoding="utf-8")
                )
                rendered = build_site.parse_content(source, path.parts[0], build_site.ROOT / path)

                self.assertIn("<table>", rendered)
                self.assertNotIn("<svg", rendered)
                self.assertRegex(rendered, r"<(?:td|th)[^>]*>\S")

    def test_table_rules_and_blank_section_rows_are_not_rendered_as_content(self):
        rendered = build_site.table_html(
            r"\toprule A & B & C \\ \cmidrule(lr){2-3}"
            r" D & E & F \\ \bottomrule",
            "ccc",
            "刑法",
            Path("table.tex"),
        )
        structure = TableStructure()
        structure.feed(rendered)

        self.assertEqual(rendered.count("<tr"), 2)
        first_row, second_row = structure.row_cells
        self.assertIn("rule-top-heavy", first_row[0][1]["class"])
        self.assertNotIn("rule-top-light", second_row[0][1]["class"])
        self.assertIn("rule-top-light", second_row[1][1]["class"])
        self.assertIn("rule-top-light", second_row[2][1]["class"])
        self.assertIn("rule-bottom-heavy", second_row[0][1]["class"])

    def test_display_math_delimiters_inside_list_items_are_hidden(self):
        source = (
            r"\begin{enumerate}\item Before \["
            r"\begin{tabular}{cc}\toprule A & B \\ \bottomrule"
            r"\end{tabular}\] After\end{enumerate}"
        )
        rendered = build_site.parse_content(
            source, "刑法", Path("topic.tex")
        )

        self.assertNotIn("[", rendered)
        self.assertNotIn("]", rendered)
        self.assertIn("rule-top-heavy", rendered)


if __name__ == "__main__":
    unittest.main()
