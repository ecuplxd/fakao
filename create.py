
import os
import unicodedata
import shutil

subjects = ['刑法', '刑诉', '民法', '民诉', '行政法', '商经知', '三国法', '理论法']
sections = [
    '法的本体',
    '法的运行',
    '法的演进、法与社会',
    '立法法',
    '习近平法治思想的重大意义',
    '习近平法治思想的核心要义与实践要求',
    '宪法的基本理论',
    '国家的基本制度',
    '公民的基本权利和义务',
    '国家机构',
    '宪法的实施及其保障',
    '中国法制史',
    '西方同时期法治文化背景',
    '司法制度和法律职业道德概述',
    '审判制度与法官职业道德',
    '检察制度和检察官职业道德',
    '律师制度和律师职业道德',
    '法律援助和公证制度',
]


def create_main(name, sections):
    code = '''\input{../style.tex}
\\title{%s}
\\author{ecuplxd}
\date{\\today}
\\begin{document}
\maketitle
\\tableofcontents

%s
\printindex
\end{document}

''' % (name, sections)
    return code


def main():
    name = '理论法'
    section_inputs = []

    for section in sections:
        file_path = os.path.join(name, section + '.tex')
        section_inputs.append('\input{' + section + '.tex}\n')
        with open(file_path, 'w+', encoding='utf-8') as f:
            f.writelines('\section{' + section + '}\n')

    with open(os.path.join(name, 'main.tex'), 'w+', encoding='utf-8') as f:
        f.writelines(create_main(name, ''.join(section_inputs)))


def is_chinese(char):
    return 'CJK' in unicodedata.name(char)


def filter_tex_file(folder):
    files = [file for file in os.listdir(folder) if file.endswith('.tex')]

    return files


def add_comma():
    for subject in subjects:
        files = filter_tex_file(subject)

        for file in files:
            with open(os.path.join(subject, file), encoding='utf-8', mode='r+') as f:
                lines = [line.rstrip() for line in f.readlines()]

                for i, line in enumerate(lines):
                    if not line or '\section' in line or '\chapter' in line or '\\title' in line:
                        continue

                    if is_chinese(line[-1]):
                        lines[i] = line + '。'
                    elif line[-1] == '}' and is_chinese(line[-2]):
                        lines[i] = line + '。'
                    elif line[-1] == '）':
                        lines[i] = line + '。'

                f.seek(0)
                f.writelines('\n'.join(lines) + '\n')


def merge():
    code = [
        '''\include{../style.tex}
\\title{法考}
\\author{ecuplxd}
\date{\\today}
\\begin{document}
\maketitle
\\tableofcontents

'''

    ]

    for subject in subjects:
        dist = os.path.join('dist', subject)
        shutil.copytree(subject, dist, dirs_exist_ok=True)
        files = filter_tex_file(dist)

        for file in files:
            with open(os.path.join(dist, file), encoding='utf-8', mode='r+') as f:
                lines = ''.join(f.readlines())
                lines = lines.replace('draw/', '../' + subject + '/draw/')
                f.seek(0)
                f.writelines(lines)

        code.append('\part{' + subject + '}\n')

        with open(os.path.join(subject, 'main.tex'), mode='r', encoding='utf-8') as f:
            lines = ''.join(f.readlines()[8:-1])
            lines = lines.replace('input{', 'input{' + subject + '/')
            code.append(lines + '\n')

    code.append('\end{document}\n')

    with open('dist/main.tex', encoding='utf-8', mode='w+') as f:
        f.writelines(code)


if __name__ == "__main__":
    merge()
