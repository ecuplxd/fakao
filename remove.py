import os
import re

subjects = ['刑法', '刑诉', '民法', '民诉', '行政法', '商经知', '三国法', '理论法']
removes = ['zd', 'zx', 'bs']


def main():
    for subject in subjects:
        for file in os.listdir(subject):
            if '.tex' not in file:
                continue
            if 'main' in file:
                continue

            tex_file = os.path.join('./', subject, file)
            tex_file = os.path.normcase(tex_file)

            with open(tex_file, encoding='utf-8', mode='r+') as f:
                content = custom_latex_to_text(f.read())
                f.seek(0)
                f.truncate()
                f.write(content)

def custom_latex_to_text(input_latex):
    pos = []

    for item in removes:
      pattern = re.compile(r'\\' + item + r'\{(.*?)\}')
      for m in re.finditer(pattern, input_latex):
          pos.append({
              'type': 'start',
              'value': m.start(0)
          })
          pos.append({
              'type': 'end',
              'value': m.end(0) - 1
          })
    pos.sort(key = lambda x: x['value'], reverse=True)

    for item in pos:
        s = item['value']
        e = item['value'] + 1

        if item['type'] == 'start':
            e = s + 4

        input_latex = input_latex[:s] + input_latex[e:]

    return input_latex

if __name__ == "__main__":
    main()
