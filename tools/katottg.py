#!/usr/bin/env python
import csv
import html.parser
import os
import re
import shutil
import ssl
import sys
import time
import uklatn
import urllib.error
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
    sslc = ssl.create_default_context()

    delay = 1
    while True:
        try:
            if filename:
                # _, rheaders = urllib.request.urlretrieve(url, filename=filename, context=sslc)
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout, context=sslc) as r:
                    with open(filename, 'wb') as fp:
                        shutil.copyfileobj(r, fp)
                if (ts := r.headers.get('Last-Modified')) is not None:
                    ts = parse_date(ts).timestamp()
                    os.utime(filename, (ts, ts))
                return filename
            else:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout, context=sslc) as r:
                    trace(r.url, r.status, r.reason)
                    return r.read()
        except urllib.error.URLError as e:
            trace(repr(e))
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                trace('disable host verification')
                sslc.check_hostname = False
                sslc.verify_mode = ssl.CERT_NONE
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
        obj['name-dstua'] = uklatn.encode(s, uklatn.DSTU_9112_A)
        obj['name-dstub'] = uklatn.encode(s, uklatn.DSTU_9112_B)
        obj['name-kmu'] = uklatn.encode(s, uklatn.KMU_55)
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
