#!/usr/bin/python3
"""内閣府 AI 関連会議の公表資料を取得して raw/cao/ に保存する。
使い方: fetch_cao.py URL [URL...]   (取得済みならスキップ)
        fetch_cao.py --crawl SECTION   (SECTION の index ページ→各回ページ→PDF を取得)
保存先パスは URL のホスト以降をそのままディレクトリにする。"""
import sys, os, re, time, urllib.request, urllib.parse
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'raw', 'cao')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'

def local_path(url):
    p = urllib.parse.urlparse(url)
    path = p.path.lstrip('/') or 'index.html'
    if path.endswith('/'):
        path += 'index.html'
    return os.path.normpath(os.path.join(ROOT, p.netloc, path))

def fetch(url, force=False):
    lp = local_path(url)
    if os.path.exists(lp) and not force:
        return lp
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except Exception as e:
        print('ERR', url, e, file=sys.stderr)
        return None
    open(lp, 'wb').write(data)
    time.sleep(0.5)
    if lp.endswith('.pdf'):
        os.system('pdftotext -layout %r %r' % (lp, lp[:-4] + '.txt'))
    print('GOT', url, len(data), file=sys.stderr)
    return lp

def links(url):
    lp = fetch(url)
    if not lp:
        return []
    t = open(lp, 'rb').read().decode('utf-8', 'replace')
    out = []
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', t, re.S):
        h = m.group(1)
        if h.startswith('#') or h.startswith('mailto'):
            continue
        txt = re.sub(r'\s+', ' ', re.sub('<[^>]+>', '', m.group(2))).strip()
        out.append((urllib.parse.urljoin(url, h), txt))
    return out

def crawl(index_url):
    base = index_url.rsplit('/', 1)[0] + '/'
    for u, t in links(index_url):
        u = u.split('#')[0]
        if not u.startswith(base):
            continue
        if u.endswith('.html'):
            for u2, t2 in links(u):
                u2 = u2.split('#')[0]
                if u2.startswith(base) and u2.endswith('.pdf'):
                    fetch(u2)
        elif u.endswith('.pdf'):
            fetch(u)

if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--crawl':
        for u in a[1:]:
            crawl(u)
    elif a and a[0] == '--links':
        for u, t in links(a[1]):
            print(u, '|', t)
    else:
        for u in a:
            print(fetch(u))
