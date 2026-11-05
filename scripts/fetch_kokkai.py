#!/usr/bin/python3
"""分野の設定（fields/<分野>.json）の kokkai_terms で国会会議録APIを引き、raw/kokkai/ に保存する。
使い方: fetch_kokkai.py ai   （取得済みの語は取り直さない。--force で取り直す）"""
import hashlib, json, os, sys, time, urllib.parse, urllib.request
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
API = 'https://kokkai.ndl.go.jp/api/speech'

def cache_path(term):
    return os.path.join(ROOT, 'raw', 'kokkai', hashlib.md5(term.encode()).hexdigest()[:12] + '.json')

def fetch(term, force=False):
    p = cache_path(term)
    if os.path.exists(p) and not force:
        return json.load(open(p, encoding='utf-8'))
    recs, start = [], 1
    while True:
        q = urllib.parse.urlencode({'any': term, 'from': '2016-01-01', 'maximumRecords': 100,
                                    'startRecord': start, 'recordPacking': 'json'})
        req = urllib.request.Request(API + '?' + q, headers={'User-Agent': 'kseisakuflow/0.1 (+https://xb4g.com/giin/flow/)'})
        d = json.load(urllib.request.urlopen(req, timeout=60))
        recs += d.get('speechRecord', [])
        nxt = d.get('nextRecordPosition')
        time.sleep(1.5)
        if not nxt or len(recs) >= 300:
            total = d.get('numberOfRecords', len(recs))
            break
        start = nxt
    out = {'term': term, 'fetched_at': time.strftime('%Y-%m-%d'), 'numberOfRecords': total, 'speechRecord': recs}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return out

if __name__ == '__main__':
    field = json.load(open(os.path.join(ROOT, 'fields', sys.argv[1] + '.json'), encoding='utf-8'))
    force = '--force' in sys.argv
    for pid, l in field.get('project_links', {}).items():
        for t in l.get('kokkai_terms', []):
            d = fetch(t, force)
            print(pid, t, d['numberOfRecords'], len(d['speechRecord']))
