#!/usr/bin/env python
import csv
from icupy import icu
import sys
from datetime import datetime, UTC
from pathlib import Path
from urllib.parse import urlparse


def gen_(row, name):
    value = row.get(name, name) or ''
    return f'<div>{value}</div>'


def main(args):
    filename = args.file if (args.file is not None) else '-'
    if filename == '-':
        fin = sys.stdin
    else:
        fin = Path(filename).open('r')

    def dbquery(category):
        fin.seek(0)
        reader = csv.DictReader(fin)
        for row in reader:
            if row['category'] in category:
                yield row

    fileto = args.output if (args.output is not None) else '-'
    if fileto == '-':
        fout = sys.stdout
    else:
        fout = Path(fileto).open('w')

    ts = datetime.now(UTC)
    timestamp = ts.isoformat()

    gens = dict()
    
    print(f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ukrainian toponyms</title>
<style>
:root {{ color-scheme: light dark; --hi: #eef; }}
@media (prefers-color-scheme: dark) {{
:root {{ --hi: #433; }}
}}
.table {{
  display: grid;
  gap: 0;
  white-space: nowrap;
}}
.grid4 {{
  grid-template-columns: repeat(4, 1fr);
}}
.grid5 {{
  grid-template-columns: repeat(5, 1fr);
}}
.table .th {{
  font-weight: bolder;
  text-align: center;
}}
.table > div {{
  display: contents;
}}
.table > div > div {{
  border-right: 1px solid #ccc;
  padding: 0.1rem 0 0.1rem 1rem;
}}
.table > div:hover > div {{
    background-color: var(--hi);
}}
</style>
</head>
<body>
<div class="info">
<h1>Ukrainian toponyms</h1>
<p><a href="https://ukrainewar.carrd.co/"><img src="StandWithUkraine.svg" alt="standwithukraine"></a></p>
<div id="toc">
Contents
<ul>
<li><a href="#tableO">Oblasts (Provinces)</a></li>
<li><a href="#tableP">Raions (Districts)</a></li>
<li><a href="#tableKM">Cities</a></li>
</ul>
</div>
<p>Data compiled from <a href="https://mtu.gov.ua/">https://mtu.gov.ua/</a>.</p>
<p>Generated at {timestamp}</p>
</div>
<div>
Transliteration
<ul>
<li><code>uk-Latn-A</code>: <a href="https://uk.wikipedia.org/wiki/%D0%94%D0%A1%D0%A2%D0%A3_9112:2021">DSTU 9112:2021 System A</a></li>
<li><code>uk-Latn-B</code>: <a href="https://uk.wikipedia.org/wiki/%D0%94%D0%A1%D0%A2%D0%A3_9112:2021">DSTU 9112:2021 System B</a></li>
<li><code>uk-Latn-K</code>: <a href="https://zakon.rada.gov.ua/laws/show/55-2010-%D0%BF">KMU 55:2010</a></li>
</ul>
</div>
''', file=fout)

    oblasts = dict((row['level1'], row['name']) for row in dbquery('O'))
    raions = dict((row['level2'], row['name']) for row in dbquery('P'))
    resolver = dict(level1=oblasts, level2=raions)

    fieldnames = 'name level1 level2 name-dstua name-dstub name-kmu'.split()
    alias = dict(zip(fieldnames, ('Name', 'Oblast', 'Raion', 'uk-Latn-A', 'uk-Latn-B', 'uk-Latn-K')))

    def gen_table(title, fieldnames, /, category=None, resolver=None, unique=False):
        fn = len(fieldnames)
        print(f'''<h2 id="table{category}">{title}</h2>
<div class="table grid{fn}">''', file=fout)

        print('<div>', file=fout)
        for k in fieldnames:
            print(f'<div class="th">{alias[k]}</div>', file=fout)
        print('</div>', file=fout)

        colt = icu.Collator.create_instance(icu.Locale('uk_UA.UTF-8'))
        rows = sorted(dbquery(category), key=lambda p: colt.get_sort_key(p['name']))
        seen = set()
        for row in rows:
            if unique:
                if row['name'] in seen:
                    continue
                else:
                    seen.add(row['name'])
            print('<div>', file=fout)
            for k in fieldnames:
                gen = gens.get(k, gen_)
                if resolver and (res := resolver.get(k)) is not None:
                    q = row[k]
                    k = res.get(q) or resolver['level1'].get(q)
                val = gen(row, k)
                print(val, file=fout)
            print('</div>', file=fout)
        print('</div>\n', file=fout)

    fieldnames = 'name name-dstua name-dstub name-kmu'.split()
    gen_table('Oblast (Province)', fieldnames, category='O')

    fieldnames = 'name level1 name-dstua name-dstub name-kmu'.split()
    gen_table('Raion (District)', fieldnames, category='P', resolver=resolver)

    fieldnames = 'name level2 name-dstua name-dstub name-kmu'.split()
    gen_table('City', fieldnames, category='KM', resolver=resolver, unique=False)

    print(f'''
</body>
</html>''', file=fout)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='HTML page generator for the katodb.csv')
    parser.add_argument('file', help='the CSV file to process')
    parser.add_argument('-o', '--output', help='destination file name')
    args = parser.parse_args()
    main(args)
