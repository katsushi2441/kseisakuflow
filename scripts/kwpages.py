#!/usr/bin/python3
"""PDFをページごとに -raw で抽出し、改行を除いて連結した文の中からキーワードを含む文を出す。
使い方: kwpages.py PDF KW[,KW...]  -> page<TAB>sentence"""
import sys, subprocess, re, unicodedata
def norm(s):
    return "".join(unicodedata.normalize("NFKC", c) if 0x2E80 <= ord(c) <= 0x2FDF else c for c in s)
pdf, kws = sys.argv[1], sys.argv[2].split(',')
n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout).group(1))
for p in range(1, n + 1):
    t = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-raw', pdf, '-'], capture_output=True, text=True).stdout
    t = norm(t.replace('\f', ''))
    t = re.sub(r'\n', '', t)
    for s in re.split(r'(?<=。)', t):
        if any(k in s for k in kws):
            print(f'{p}\t{s.strip()}')
