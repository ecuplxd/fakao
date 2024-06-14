import os
import fitz
import re
import json
import sqlite3


def main():
    conn = sqlite3.connect("D:\\kao_yan\\backend\\kaoyan.db")
    cursor = conn.cursor()
    info = {
        "民法": ["孟献贵", 12],
        "刑法": ["柏浪涛", 13],
        "民诉": ["戴鹏", 14],
        "刑诉": ["向高甲", 15],
        "行政法": ["李佳", 16],
        "三国法": ["杨帆", 17],
        "商经知": ["刘安祺", 18],
        "理论法": ["马峰", 19],
    }

    for subject in os.listdir("./dist"):
        print("create subject: ", subject)
        orders = get_orders(subject)
        cursor.execute(
            "insert into notes (title, 'order') values (?, ?)",
            (subject + "（法考）——" + info[subject][0], info[subject][1]),
        )
        subject_id = cursor.lastrowid

        for file in os.listdir("./dist/" + subject):
            if file == "main.pdf" or file == "draw":
                continue
            pdf_file = os.path.join("dist", subject, file)
            section_name = file.replace(".pdf", "").replace("_", "")
            html = parse_doc(pdf_file)
            order = orders[section_name] or 0
            cursor.execute(
                "insert into notes (title, html, pid, 'order') values (?, ?, ?, ?)",
                (section_name, html, subject_id, order),
            )
            print("\t", order, section_name, pdf_file)

    conn.commit()
    conn.close()


def get_orders(subject_name) -> list[str]:
    with open("./" + subject_name + "/main.tex", encoding="utf-8", mode="r") as f:
        lines = f.readlines()
        lines = [line for line in lines[1:] if "input" in line]
        lines = [line.split("{")[1] for line in lines]
        lines = [line.split("}")[0] for line in lines]
        lines = [line.replace(".tex", "") for line in lines]
        orders = {}

        for i, line in enumerate(lines):
            orders[line] = i

        return orders


def get_indent(text: str):
    if text.startswith("•"):
        return 4
    if text.startswith("i") or text.startswith("v"):
        return 2

    if re.match("^\d+\.", text):
        return 0
    elif re.match("\([a-z]\)", text):
        return 1
    elif re.match("^[A-Z]\.", text):
        return 3
    else:
        return None


def parse_doc(file):
    doc = fitz.open(file)
    blocks = []

    for page in doc:
        temps = page.get_text("dict")["blocks"]
        blocks += temps

    line = ""
    span = ""
    line_ops = []
    deltas = []

    for b in blocks[1:]:
        for l in b["lines"]:
            for s in l["spans"]:
                text = s["text"]
                font = s["font"]
                color = s["color"]
                text = text.strip()
                text = text.replace("→", " → ")
                text = text.replace("↑", " ↑ ")
                text = text.replace("＞", " ＞ ")
                text = text.replace("＜", " ＜ ")
                text = text.replace("||", " || ")
                text = text.replace("+", " + ")
                text = text.replace("=", " = ")
                text = text.replace("≠", " ≠ ")
                text = text.replace("×", " ×")
                text = text.replace("√", " √")
                text = text.replace("①.", "①. ")
                text = text.replace("②.", "②. ")
                text = text.replace("③.", "③. ")
                text = text.replace("④.", "④. ")
                indent = get_indent(text)

                if indent == None:
                    text = re.sub("\d+", lambda ele: " " + ele[0] + " ", text)

                if indent != None and line:
                    if span != "":
                        line_ops.append(create_span(span))
                        span = ""

                    deltas += line_ops
                    deltas.append(create_span("\n", {"indent": get_indent(line)}))
                    line = text
                    line_ops = [create_span(text + " ")]
                else:
                    line += text
                    attrs = {}

                    if color != 0:
                        color = "#{0:06X}".format(color)
                        attrs["color"] = color

                        if color == "#FFFFFF":
                            attrs["background-color"] = "#ffebcc"
                            del attrs["color"]
                        elif color == "#3333FF":
                            attrs["color"] = "#003eaa"

                    if font == "FZKTK--GBK1-0":
                        attrs["italic"] = True
                    elif font == "FZFSK--GBK1-0":
                        attrs["lz"] = True

                    if len(attrs.keys()) != 0:
                        if span != "":
                            line_ops.append(create_span(span))
                            span = ""

                        line_ops.append(create_span(text, attrs))
                    else:
                        span += text

    if span != "":
        line_ops.append(create_span(span))

    deltas += line_ops
    deltas.append(create_span("\n", {"indent": get_indent(line)}))
    ops = {"ops": deltas}

    return json.dumps(ops)


def create_span(text: str, attrs=None):
    text = text.replace("  ", " ")
    text = text.replace("。 ", "。")
    text = text.replace(" 。", "。")

    if attrs == None:
        return {"insert": text}
    else:
        return {"insert": text, "attributes": attrs}


if __name__ == "__main__":
    # parse_doc("./dist/刑诉/_基本原则.pdf")
    main()
