#!/usr/bin/python3
"""raw/cao/ の PDF をページごとに文字にして raw/cao_pages.jsonl に書く（会議資料の全文検索用）。
ファイルの場所は URL と同じ（raw/cao/www8.cao.go.jp/... → https://www8.cao.go.jp/...）。"""
import json, os, re, subprocess, sys, unicodedata
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = os.path.join(ROOT, 'raw', 'cao')
OUT = os.path.join(ROOT, 'raw', 'cao_pages.jsonl')

def norm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s))

n = 0
with open(OUT, 'w', encoding='utf-8') as w:
    for d, _, fs in os.walk(SRC):
        for f in sorted(fs):
            if not f.lower().endswith('.pdf'):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, SRC).replace(os.sep, '/')
            url = 'https://' + rel
            t = subprocess.run(['pdftotext', '-layout', p, '-'], capture_output=True, text=True, errors='replace').stdout
            for i, pg in enumerate(t.split('\f'), 1):
                s = norm(pg)
                if s:
                    w.write(json.dumps({'url': url, 'page': i, 'text': s}, ensure_ascii=False) + '\n')
                    n += 1
print('pages', n)
