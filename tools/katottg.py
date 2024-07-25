#!/usr/bin/env python
import csv
import html.parser
import os
import re
import sys
import time
import urllib.request
from email.utils import parsedate_to_datetime as parse_date
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import pathname2url


_DefaultFetchUrl = 'https://mtu.gov.ua/content/kodifikator-administrativnoteritorialnih-odinic-ta-teritoriy-teritorialnih-gromad.html'


def trace(*args, **kwargs):
    print(*args, file=sys.stderr, flush=True, **kwargs)


def resolve_cachedir(caches=None):
    return Path(caches or '.cache')


def resolve_datafile(caches):
    fns = sorted(fn for fn in caches.glob('*') if fn.suffix in ('.pdf', '.xlsx'))
    if not fns: return
    if len(fns) > 1:
        print('multiple files found:', file=sys.stderr)
        for fn in fns:
            print(fn, file=sys.stderr)
        return
    return fns[-1]


def html_extract_links(text):
    links = list()
    class Parser (html.parser.HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag in ('a', 'A'):
                for k,v in attrs:
                    if k in ('href', 'HREF') and v and v != '#':
                        links.append(v)
    parser = Parser()
    parser.feed(text)
    return links


def fetch_latest(caches):
    page_url = _DefaultFetchUrl
    page = wget(page_url)
    caches.mkdir(parents=True, exist_ok=True)
    with (caches / 'page.html').open('wb') as fp:
        fp.write(page)
    for link in html_extract_links(page.decode()):
        if link.endswith('.pdf') or link.endswith('.xlsx'):
            url = urljoin(page_url, link)
            fn = Path(url)
            name = fn.name
            ext = fn.suffix
            if re.match(r'^[Кк]одиф', name):
                ps = list(urlsplit(url))
                ps[2] = pathname2url(urlsplit(url).path)
                url = urlunsplit(ps)
                cfn = caches / ('katottg' + ext)
                wget(url, filename=cfn)
                return cfn


def wget(url, headers=None, timeout=30, filename=None):
    trace('get', url)
 
    default_headers = {'User-Agent': 'Mozilla/1.0'}
    headers = default_headers | (headers or dict())
    opener = urllib.request.build_opener()
    opener.addheaders = list(headers.items())
    urllib.request.install_opener(opener)

    delay = 1
    while True:
        try:
            if filename:
                _, headers = urllib.request.urlretrieve(url, filename=filename)
                if (ts := headers.get('Last-Modified')) is not None:
                    ts = parse_date(ts).timestamp()
                    os.utime(filename, (ts, ts))
                return filename
            else:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    trace(r.url, r.status, r.reason)
                    return r.read()
        except Exception as e:
            trace(repr(e))
            time.sleep(delay)
            delay *= 1.44


def parse_pdf(filename):
    trace('reading', str(filename))
    from pypdf import PdfReader
    reader = PdfReader(filename)
    rx = re.compile(r'^\s*((?:UA\d{17}\s+)+)(\S)\s+(.+)\s*$')
    for page in reader.pages:
        text = page.extract_text()
        for line in text.splitlines():
            m = rx.findall(line)
            if m:
                (ks,c,s), = m
                ks = ks.split()
                s = ' '.join(s.split())
                if c == 'С':
                    trace('fix cyr С:', ks[-1], repr(c), repr(s))
                    c = 'C'
                yield (ks, c, s)


def parse_xlsx(filename):
    trace('reading', str(filename))
    import openpyxl
    book = openpyxl.load_workbook(filename)
    sheet = book.active
    rx = re.compile(r'UA\d{17}')
    for row in sheet.iter_rows(values_only=True):
        s = row[0]
        if s and rx.match(s):
            *ks,c,s = row
            ks = list(filter(None, ks))
            s = ' '.join(s.split())
            if c == 'С':
                trace('fix cyr С:', ks[-1], repr(c), repr(s))
                c = 'C'
            yield (ks, c, s)


def _make_trs():
    def _transliterator(rx, sb, text):
        return rx.sub(sb, text)

    def silly(s): return s.lower()[:-1] + s.lower()[-1].upper()

    def _compile(rules):
        loabc = 'абвгґдеєжзиіїйклмнопрстуфхцчшщьюя'
        hiabc = loabc.upper()
        consonants = 'бвгґджзйклмнпрстфхцчшщ'
        vowels = 'аеєиіїоуюя'
        apos = "'\u2019\u02BC"
        default_rules = dict()
        word_start_rules = dict()
        after_cons_rules = dict()

        for key, rule in rules.items():
            lokey = key.lower()
            hikey = lokey.upper()
            if rule is None:
                rule = ''
            if isinstance(rule, dict):
                if (value := rule.get('start')) is not None:
                    word_start_rules[lokey] = value
                    word_start_rules[hikey] = value.title()
                    if len(key) > 1:
                        word_start_rules[key.title()] = value.title()
                        word_start_rules[silly(key)] = silly(value)
                if (value := rule.get('cons')) is not None:
                    after_cons_rules[lokey] = value
                    after_cons_rules[hikey] = value.title()
                value = rule.get('other', '')
                default_rules[lokey] = value
                default_rules[hikey] = value.title()
                if len(key) > 1:
                    default_rules[key.title()] = value.title()
                    default_rules[silly(key)] = silly(value)
            else:
                if "'" in key:
                    for c in apos:
                        newkey = key.replace("'", c)
                        default_rules[newkey] = rule
                else:
                    default_rules[lokey] = rule
                    default_rules[hikey] = rule.title()
                    if len(key) > 1:
                        default_rules[key.title()] = rule.title()
                        default_rules[silly(key)] = silly(rule)

        default_keyset1 = [k for k in default_rules if len(k) == 1]
        default_keyset2 = sorted([k for k in default_rules if len(k) > 1], key=len, reverse=True)
        word_start_keyset = list(word_start_rules)
        assert all(len(k) == 1 for k in word_start_keyset)
        consonants_keyset = consonants + consonants.upper()
        after_cons_keyset = list(after_cons_rules)
        assert all(len(k) == 1 for k in after_cons_keyset)
        inner1 = f'[^{loabc}{hiabc}{apos}]'
        inner2 = f'[{"".join(word_start_keyset)}]' if word_start_keyset else '\uFFFC\uFFFC'
        inner3 = f'{"|".join(default_keyset2)}' if default_keyset2 else '\uFFFC\uFFFC'
        inner4 = f'[{"".join(consonants_keyset)}]' + (f'[{"".join(after_cons_keyset)}]' if after_cons_keyset else '\uFFFC\uFFFC')
        inner5 = f'[{"".join(default_keyset1)}]'
        rx = re.compile(f'(?:(?:(?P<g1>^|{inner1})(?P<g2>{inner2}))|(?:(?P<g3>{inner3})|(?P<g4>{inner4})|(?P<g5>{inner5})))')
        # trace(repr(rx.pattern))

        def sb(m):
            gs = m.groupdict()
            if (k := gs.get('g5')):
                return default_rules[k]
            if (k := gs.get('g3')):
                return default_rules[k]
            if (k := gs.get('g4')):
                x = default_rules[k[0]]
                v = after_cons_rules[k[1]]
                return x + v
            if (k := gs.get('g2')):
                x = gs['g1']
                v = word_start_rules[k]
                return x + v

        def worker(text):
            return _transliterator(rx, sb, text)
        return worker

    base = dict(zip("'абвгґдеєжзиіїйклмнопрстуфхцчшщьюя", "'abvggdeezzyiijklmnoprstufxccssjua"))

    dstua = dict(base)
    dstua['г'] = 'ğ'
    dstua['є'] = 'je'
    dstua['ж'] = 'ž'
    dstua['ї'] = 'ï'
    dstua['й'] = dict(cons="'j", other='j')
    dstua['йа'] = "j'a"
    dstua['йе'] = "j'e"
    dstua['йу'] = "j'u"
    dstua['ч'] = 'č'
    dstua['ш'] = 'š'
    dstua['щ'] = 'ŝ'
    dstua['ь'] = dict(cons='j', other='ĵ')
    dstua['ьа'] = "j'a"
    dstua['ье'] = "j'e"
    dstua['ьу'] = "j'u"
    dstua['ю'] = 'ju'
    dstua['я'] = 'ja'
    dstua = _compile(dstua)

    dstub = dict(base)
    dstub['г'] = 'gh'
    dstub['є'] = 'je'
    dstub['ж'] = 'zh'
    dstub['ї'] = 'ji'
    dstub['й'] = dict(cons="'j", other='j')
    dstub['йа'] = "j'a"
    dstub['йе'] = "j'e"
    dstub['йі'] = "j'i"
    dstub['йу'] = "j'u"
    dstub['х'] = 'kh'
    dstub['ч'] = 'ch'
    dstub['ш'] = 'sh'
    dstub['шч'] = "sh'ch"
    dstub['щ'] = 'shch'
    dstub['ь'] = dict(cons='j', other='hj')
    dstub['ьа'] = "j'a"
    dstub['ье'] = "j'e"
    dstub['ьі'] = "j'i"
    dstub['ьу'] = "j'u"
    dstub['ю'] = 'ju'
    dstub['я'] = 'ja'
    dstub = _compile(dstub)

    kmu = dict(base)
    kmu["'"] = ''
    kmu['г'] = 'h'
    kmu['є'] = dict(start='ye', other='ie')
    kmu['ж'] = 'zh'
    kmu['зг'] = 'zgh'
    kmu['ї'] = dict(start='yi', other='i')
    kmu['й'] = dict(start='y', other='i')
    kmu['х'] = 'kh'
    kmu['ц'] = 'ts'
    kmu['ч'] = 'ch'
    kmu['ш'] = 'sh'
    kmu['щ'] = 'shch'
    kmu['ь'] = ''
    kmu['ю'] = dict(start='yu', other='iu')
    kmu['я'] = dict(start='ya', other='ia')
    kmu = _compile(kmu)

    return (dstua, dstub, kmu)


uk_lat_dstua, uk_lat_dstub, uk_lat_kmu = _make_trs()


def main(args):
    caches = resolve_cachedir(args.cache)
    if args.fetch_latest:
        filename = fetch_latest(caches)
    elif args.file:
        filename = Path(args.file)
    else:
        filename = resolve_datafile(caches)

    if filename.suffix == '.pdf':
        rows = parse_pdf(filename)
    elif filename.suffix == '.xlsx':
        rows = parse_xlsx(filename)
    else:
        raise Exception(f'could not parse {filename}')
        
    codes = list(rows)

    trace('sorting...')
    codes = sorted(codes)

    if (args.output is None) or (args.output == '-'):
        fp = sys.stdout
    else:
        fp = Path(args.output).open('w', newline='')

    trace('writing', fp.name)

    fields = 'level1 level2 level3 level4 level5 category name name-dstua name-dstub name-kmu'.split()
    writer = csv.DictWriter(fp, fieldnames=fields)
    writer.writeheader()
    for ks,c,s in codes:
        obj = dict(category=c, name=s)
        for i,k in enumerate(ks, 1):
            obj[f'level{i}'] = k
        obj['name-dstua'] = uk_lat_dstua(s)
        obj['name-dstub'] = uk_lat_dstub(s)
        obj['name-kmu'] = uk_lat_kmu(s)
        writer.writerow(obj)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Kodyfikator file processor')
    parser.add_argument('file', nargs='?', help='Kodyfikator file to parse')
    parser.add_argument('-o', '--output', help='output CSV filename')
    parser.add_argument('-c', '--cache', help='cache directory')
    parser.add_argument('-f', '--fetch-latest', action='store_true', help='download latest Kodyfikator file')
    args = parser.parse_args()

    if not args.fetch_latest and not args.file:
        caches = resolve_cachedir(args.cache)
        hasfile = resolve_datafile(caches)
        if not hasfile:
            parser.print_usage()
            exit(0)

    main(args)
