import os
import unicodedata
import shutil
import PyPDF2
import edge_tts
import asyncio
from concurrent.futures import ThreadPoolExecutor, wait
import json

pool = ThreadPoolExecutor(50)
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
voice = 'zh-CN-YunxiNeural'
rate = '+0%'
volume = '+0%'
cwd = os.getcwd()


async def my_function(output, text):
    output = output.replace('.pdf', '.mp3').replace('_', '')
    if not os.path.exists(output):
        tts = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, volume=volume)
        await tts.save(output)


def to_tts(pdf_path):
    pdf_file_obj = open(pdf_path, 'rb')
    pdf_reader = PyPDF2.PdfReader(pdf_file_obj)
    page_number = len(pdf_reader.pages)
    text = ''

    for i in range(page_number):
        page_obj = pdf_reader.pages[i]
        text = text + page_obj.extract_text()
        text = text.replace('×', '错')
        text = text.replace('√', '对')
    asyncio.run(my_function(pdf_path, text))


def create_each_file(dist, file, lines):
    if file != "main.tex":
        output = os.path.join(dist, '_' + file)
        lines = lines.replace('section{', 'section*{')
        lines = lines.replace('\input{..', '% \input{..')
        # lines = lines.replace('\hz', '.或.')
        # lines = lines.replace('\dy ', '.大于.')
        # lines = lines.replace('\\xyh', '.小于.')
        # lines = lines.replace('\dui', '.对.')
        # lines = lines.replace('\cuo', '.错.')
        # lines = lines.replace('\yjt', '，')
        # lines = lines.replace('\sjt', '.以上.')
        # lines = lines.replace('\\xjt', '.以下.')
        with open(output, encoding='utf-8', mode='w+') as f_full:
            full_code = '''
\input{../../style.tex}
\geometry{landscape}
\geometry{left=0cm, right=0cm, bottom=0cm, top=0cm}
\geometry{a2paper}
\pagestyle{empty}
\\begin{document}
%s
\end{document}
''' % (lines)
            f_full.write(full_code)
            return output


def compile_tex(tex_file):
    os.chdir(os.path.join(cwd, os.path.dirname(tex_file)))
    os.system('xelatex --interaction=batchmode "' +
              os.path.basename(tex_file) + '"')
    print('done', tex_file)


def create_main(name, sections):
    code = '''
\input{../style.tex}
\\info{%s}{\\today}
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
    files = [file for file in os.listdir(folder) if file.endswith(
        '.tex') and not file.startswith('_')]

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
                f.truncate()
                f.writelines('\n'.join(lines) + '\n')


def merge():
    code = [
        '''\include{../style.tex}
\\info{法考}{\\today}
\\begin{document}
\maketitle
\\tableofcontents

'''

    ]
    outputs = []

    for subject in subjects:
        dist = os.path.join('dist', subject)
        shutil.copytree(subject, dist, dirs_exist_ok=True)
        files = filter_tex_file(dist)

        for file in files:
            print(file)
            with open(os.path.join(dist, file), encoding='utf-8', mode='r+') as f:
                lines = ''.join(f.readlines())
                lines = lines.replace('draw/', '../' + subject + '/draw/')
                f.seek(0)
                f.truncate()
                f.writelines(lines)
                outputs.append(create_each_file(dist, file, lines))

        code.append('\part{' + subject + '}\n')

        with open(os.path.join(subject, 'main.tex'), mode='r', encoding='utf-8') as f:
            lines = ''.join(f.readlines()[8:-1])
            lines = lines.replace('input{', 'input{' + subject + '/')
            code.append(lines + '\n')

    code.append('\end{document}\n')

    with open('dist/main.tex', encoding='utf-8', mode='w+') as f:
        f.writelines(code)

    all_compile_job = [pool.submit(compile_tex, output)
                       for output in outputs if output]
    wait(all_compile_job)


def clean_up():
    os.chdir(cwd)
    for root, dirs, files in os.walk('./dist'):
        for f in files:
            f_path = os.path.join(root, f)

            if '.pdf' in f:
                continue
            if '.mp3' in f:
                continue
            # if '.tex' in f and not f.startswith('_'):
            #     continue
            else:
                os.remove(f_path)


def get_law_list():
    with open('./法条.json', 'r', encoding='utf8') as fp:
        json_data = json.load(fp)
        laws = json_data['data']
        for law in laws:
            print(law['title'])
            for sublaw in law['children']:
                print('  ' + sublaw['title'])


if __name__ == "__main__":
    merge()
    clean_up()
    # [pool.submit(to_tts, './dist/民诉/' + file) for file in os.listdir('./dist/民诉')
    #  if '.pdf' in file and 'main' not in file]
    # pool.shutdown()  # 不能少
