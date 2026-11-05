#!/usr/bin/python3
"""採択先ごとの成果（公開モデル・論文・ベンチマーク・他研究での利用）を公開データから集める。→ data/outcomes.json

使い方:
  /usr/bin/python3 scripts/fetch_outcomes.py all      # 下の順に全部（取得済みの応答は raw/outcomes/ のキャッシュを使う）
  /usr/bin/python3 scripts/fetch_outcomes.py meti     # 経済産業省 GENIAC の成果公開ページ → 成果物の一覧
  /usr/bin/python3 scripts/fetch_outcomes.py hf       # Hugging Face 公開API（鍵なし）→ ダウンロード・いいね・公開日・ライセンス・派生モデル数
  /usr/bin/python3 scripts/fetch_outcomes.py openalex # ROR と OpenAlex（鍵なし）→ 助成番号つきの論文・機関のAI論文数と被引用
  /usr/bin/python3 scripts/fetch_outcomes.py build    # まとめて data/outcomes.json
  --refresh を付けると HF / OpenAlex を取り直す（同じ日に何度も叩かない）。

**しないこと**: スコアを自分で測る・順位を付ける・費用対効果の判断。数字は API・公表資料の値をそのまま、出典と取得日つきで置く。
組織名の対応（Hugging Face のアカウント）は、経済産業省の成果公開ページか、採択先の公式発表に載っているものだけ（data/outcome_sources.json）。
"""
import glob, hashlib, html, json, os, re, subprocess, sys, time, unicodedata, urllib.parse
from collections import defaultdict, OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
RAW = os.path.join(ROOT, 'raw', 'outcomes')
TODAY = time.strftime('%Y-%m-%d')
REFRESH = '--refresh' in sys.argv
UA = 'kseisakuflow/1.0 (https://xb4g.com/giin/flow/; mailto:info@exbridge.jp)'

def N(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s or ''))

LEGAL = ['国立研究開発法人', '独立行政法人', '国立大学法人', '公立大学法人', '大学共同利用機関法人', '学校法人',
         '一般社団法人', '公益社団法人', '一般財団法人', '公益財団法人', '特定非営利活動法人', '株式会社', '有限会社', '合同会社', '(株)', '㈱']
def org_key(s):
    t = N(s).lower()
    for w in LEGAL:
        t = t.replace(unicodedata.normalize('NFKC', w).lower(), '')
    return re.sub(r'[・,.、。()（）「」\'"]', '', t)

# 事業者名の表記ゆれ（経済産業省のページの表記 → 採択一覧の表記）。ページの誤記「Prefererred」もそのまま受ける
ALIAS = {'prefererrednetworks': 'preferrednetworks', 'prefererredelements': 'preferredelements'}
# 同じ法人の表記違い（採択一覧の中）。情報・システム研究機構と、その中の国立情報学研究所の併記は同じ法人
ORG_MERGE = {'情報システム研究機構国立情報学研究所': '情報システム研究機構'}

def get(url, kind, refresh=REFRESH, sleep=0.6):
    """GET してキャッシュ（raw/outcomes/<kind>/<md5>.json）。JSON でなければ None。"""
    d = os.path.join(RAW, kind)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, hashlib.md5(url.encode()).hexdigest()[:16] + '.json')
    if os.path.exists(p) and not refresh:
        return json.load(open(p, encoding='utf-8'))['body']
    body = None
    for wait in (0, 8, 40):
        time.sleep(wait)
        out = subprocess.run(['curl', '-s', '-L', '-A', UA, '-w', '\n%{http_code}', url], capture_output=True, text=True, timeout=120).stdout
        txt, _, code = out.rpartition('\n')
        if code == '404':
            body = {'_status': 404}; break
        try:
            body = json.loads(txt)
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict) and body.get('error') and 'rate' in str(body.get('error', '')).lower():
            body = None; continue
        break
    time.sleep(sleep)
    if body is not None:
        json.dump({'url': url, 'fetched': TODAY, 'body': body}, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return body

def get_text(url, kind, refresh=REFRESH):
    d = os.path.join(RAW, kind)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, hashlib.md5(url.encode()).hexdigest()[:16] + '.txt')
    if os.path.exists(p) and not refresh:
        return open(p, encoding='utf-8').read()
    r = subprocess.run(['curl', '-s', '-L', '-A', UA, '-w', '\n%{http_code}', url], capture_output=True, text=True, timeout=120)
    txt, _, code = r.stdout.rpartition('\n')
    time.sleep(0.4)
    txt = txt if code == '200' else ''
    open(p, 'w', encoding='utf-8').write(txt)
    return txt

# ---------------------------------------------------------------- 採択先の一覧
def awardees():
    aw = json.load(open(os.path.join(ROOT, 'data', 'awards.json'), encoding='utf-8'))
    orgs = OrderedDict()
    for g in aw['programs']:
        for a in g.get('awards', []):
            names = []
            if a.get('org') and not a['org'].startswith('未取得'):
                names.append((a['org'], '代表' if not a.get('orgs_listed') else ''))
            names += [(o, '') for o in a.get('orgs_listed') or []]
            if g['agency'] != 'JST':      # JST の co_orgs は個人の所属と氏名なので使わない
                names += [(re.sub(r'（【[^】]*】）', '', o), '共同') for o in a.get('co_orgs') or []]
            for nm, role in names:
                k = org_key(nm)
                k = ORG_MERGE.get(k, k)
                o = orgs.setdefault(k, {'key': k, 'name': nm.strip(), 'awards': []})
                o['awards'].append({'program_id': g['id'], 'program': g['name'], 'agency': g['agency'], 'geniac_round': g.get('geniac_round'),
                                    'award_date': g.get('award_date'), 'theme': a.get('theme', ''), 'role': role,
                                    'source_title': g.get('source_title'), 'source_url': g.get('source_url')})
    return aw, orgs

def adate(a):
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', a.get('award_date') or '')
    return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))) if m else None

def first_date(o):
    ds = []
    for a in o['awards']:
        m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', a.get('award_date') or '')
        if m:
            ds.append('%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))))
    return min(ds) if ds else None

# ---------------------------------------------------------------- 経済産業省 GENIAC の成果公開ページ
METI_PAGES = [
    {'phase': 2, 'url': 'https://geniac.meti.go.jp/selection_2/result_2/index.html', 'file': 'selection_2_result_2_index.html',
     'title': '経済産業省 GENIAC「生成AI基盤モデル開発 第2期 成果物（モデル・データセット）公開」'},
    {'phase': 3, 'url': 'https://geniac.meti.go.jp/selection_3/result_3/index.html', 'file': 'selection_3_result_3_index.html',
     'title': '経済産業省 GENIAC「生成AI基盤モデル開発 第3期 成果物（モデル・データセット）公開」'},
]

def page_lines(path):
    t = open(path, encoding='utf-8', errors='replace').read()
    s = re.sub(r'<script.*?</script>|<style.*?</style>', '', t, flags=re.S)
    s = re.sub(r'<(br|/p|/li|/h\d|/tr|/div|/td|/th|/dt|/dd)[^>]*>', '\n', s)
    s = re.sub(r'<a [^>]*href="([^"]*)"[^>]*>', r' [[\1]] ', s)
    s = html.unescape(re.sub(r'<[^>]+>', '', s)).replace('​', '')
    return [re.sub(r'[ \t]+', ' ', l).strip() for l in s.split('\n') if l.strip()]

LABELS = ['事業者名', '会社名', '用途', '特徴', '概要', '注記', '公開形態・ライセンス', '公開リンク', 'データ形式・モダリティ', 'URL', 'url']

def parse_meti(pg):
    """第2期は「事業者名: X」の1行形式、第3期はラベルと値が別の行の形式。どちらも「事業者名」の直前の行が成果物の名前。"""
    L = page_lines(os.path.join(ROOT, 'raw', 'geniac', pg['file']))
    sec = ''
    out = []
    cur = None
    def flush():
        if cur:
            out.append(cur)
    i = 0
    while i < len(L):
        l = L[i]
        if l in ('モデル', '学習用データセット', '評価用データセット'):
            sec = l
        m = re.match(r'^(事業者名|会社名)\s*[:：]\s*(.+)$', l)
        if m or l in ('事業者名', '会社名'):
            flush()
            org = m.group(2) if m else (L[i + 1] if i + 1 < len(L) else '')
            name = L[i - 1]
            if name.startswith('[[') or name in LABELS:
                name = L[i - 2]
            cur = {'phase': pg['phase'], 'section': sec, 'name': re.sub(r'\s*[:：]$', '', name), 'org': org.strip(), 'fields': {}, 'links': [],
                   'source_title': pg['title'], 'source_url': pg['url']}
            i += 1 if m else 2
            lab = None
            while i < len(L):
                l = L[i]
                if re.match(r'^(事業者名|会社名)(\s*[:：]|$)', l) or l in ('[[javascript:void(0);]] 閉じる', '[[#pagetop]]') or l.startswith('[[javascript:void(0);]] ×'):
                    break
                if l in ('モデル', '学習用データセット', '評価用データセット'):
                    break
                mm = re.match(r'^(%s)\s*[:：]\s*(.*)$' % '|'.join(map(re.escape, LABELS)), l)
                if l in LABELS:
                    lab = l; i += 1; continue
                if mm:
                    lab = mm.group(1); l = mm.group(2)
                for u in re.findall(r'\[\[(https?://[^\]]+)\]\]', l):
                    if u not in cur['links']:
                        cur['links'].append(u)
                txt = re.sub(r'\[\[[^\]]*\]\]', '', l).strip()
                if lab and txt and not re.match(r'^https?://', txt):
                    cur['fields'][lab] = (cur['fields'].get(lab, '') + ' ' + txt).strip()
                i += 1
            # 次の成果物の名前の行は含めない（第2期は名前が次の「事業者名」の直前に来る）
            if i < len(L) and re.match(r'^(事業者名|会社名)', L[i]):
                nm = L[i - 1]
                for lab2, v in list(cur['fields'].items()):
                    if v.endswith(nm):
                        cur['fields'][lab2] = v[: -len(nm)].strip()
            continue
        i += 1
    flush()
    # 第3期は一覧（名前＋事業者）と詳細（モーダル）が分かれている。区分は一覧の見出し（モデル／学習用・評価用データセット）から取る
    secmap, sec2 = {}, ''
    for l in L:
        if l in ('モデル', '学習用データセット', '評価用データセット'):
            sec2 = l
        elif re.match(r'^(事業者名|会社名)(\s*[:：]|$)', l):
            break
        elif sec2:
            secmap.setdefault(l, sec2)
    for e in out:
        for l, s2 in secmap.items():
            if l.startswith(e['name']):
                e['section'] = s2; break
    # 第3期は一覧（名前＋事業者）と詳細（モーダル）が両方あり、詳細の方だけ「事業者名」ラベルを持つ。名前で重複を除く
    seen, res = set(), []
    for e in out:
        k = (e['phase'], e['name'])
        if k in seen:
            continue
        seen.add(k)
        res.append(e)
    return res

def meti_org_keys(org):
    parts = re.split(r'[/／]', org)
    ks = []
    for p in parts:
        k = org_key(p)
        ks.append(ALIAS.get(k, k))
    return ks

def hf_ref(u):
    p = urllib.parse.urlparse(u)
    if p.netloc not in ('huggingface.co', 'www.huggingface.co'):
        return None
    seg = [x for x in p.path.split('/') if x]
    if not seg:
        return None
    if seg[0] == 'datasets' and len(seg) >= 3:
        return ('dataset', seg[1] + '/' + seg[2])
    if seg[0] == 'collections' and len(seg) >= 3:
        return ('collection', seg[1] + '/' + seg[2])
    if seg[0] in ('spaces', 'papers', 'docs', 'blog'):
        return None
    if len(seg) >= 2:
        return ('model', seg[0] + '/' + seg[1])
    return None

BENCH_RX = re.compile(r'(?i)bench|ベンチマーク|harness|mmlu|jaster|llm-jp-eval|leaderboard|スコア')

def bench_sentences(text):
    """「特徴」欄のうち、ベンチマーク名と小数の値を両方含む文だけ（値の無い「〜を上回る」だけの文は取らない）"""
    out = []
    for s in re.split(r'(?<=[。．])', text or ''):
        s = s.strip()
        if s and BENCH_RX.search(s) and re.search(r'\d+\.\d+', s):
            out.append(s)
    return out

def cmd_meti():
    items = []
    for pg in METI_PAGES:
        items += parse_meti(pg)
    json.dump(items, open(os.path.join(RAW, 'meti_items.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for e in items:
        print(e['phase'], e['section'] or '-', '|', e['name'][:40], '|', e['org'], '|', [hf_ref(u) for u in e['links'] if hf_ref(u)][:3])
    print(len(items), 'items')
    return items

# ---------------------------------------------------------------- 中間評価報告書（案）の進捗表（採択先ごとの「結果/状況」）
MIDTERM = {'file': os.path.join(ROOT, 'raw', 'nedo', 'meti.go.jp__shingikai_sankoshin_sangyo_gijutsu_innovation_evaluation_wg_pdf_005_01_03.txt'),
           'url': 'https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/innovation/evaluation_wg/pdf/005_01_03.pdf',
           'title': '経済産業省 産業構造審議会 評価WG 第5回 資料「ポスト５Ｇ情報通信システム基盤強化研究開発事業（AI 基盤モデル及び先端半導体関連技術開発事業）中間評価報告書（案）」の「研究開発計画① 進捗状況」の表'}
STATUS = ['目標達成', '目標未達', '計画通り', '計画遅延', '前倒し']

TR = str.maketrans({'⻑': '長', 'ー': '-', '－': '-', '‐': '-', '︓': ':', '⻭': '歯', '⻘': '青', '⻄': '西', '⻝': '食'})
def NM(s):
    return N(s).translate(TR)

def midterm_status(aw):
    """進捗表で、採択一覧の題名（NFKC・空白除去）の先頭12字を含む行を探し、その行から3行以内の「結果/状況」の語を取る。
    12字で見つからないときだけ、先頭10字＋同じ行の事業者名で探す（題名が報告書で少し変わっている場合。例: ABEJA 第3期）。"""
    if not os.path.exists(MIDTERM['file']):
        return {}
    raw = open(MIDTERM['file'], encoding='utf-8', errors='replace').read()
    pages = [p.split('\n') for p in raw.split('\f')]
    def find(test):
        for pno, lines in enumerate(pages, 1):
            for i, l in enumerate(lines):
                if not test(l):
                    continue
                st = next((s for j in range(i, min(i + 4, len(lines))) for s in STATUS if s in lines[j]), None)
                if not st:
                    continue
                end = None
                for j in range(max(0, i - 3), i + 1):
                    m = re.search(r'令和(\d+)年度終了', lines[j])
                    if m:
                        end = '令和' + m.group(1) + '年度終了予定'
                return {'status': st, 'end': end, 'page': pno}
        return None
    res = {}
    for g in aw['programs']:
        if not g['id'].startswith('geniac-') or g['id'].startswith('geniac-4'):
            continue
        for a in g['awards']:
            th = NM(a.get('theme', ''))
            if len(th) < 8:
                continue
            ok = org_key(a.get('org') or '')[:6]
            r = find(lambda l: th[:12] in NM(l)) or find(lambda l: th[:10] in NM(l) and ok and ok in org_key(l))
            if r:
                res[(g['id'], N(a.get('org') or '') + '|' + N(a.get('theme', '')))] = r
    return res

# ---------------------------------------------------------------- Hugging Face
def hf_model(mid):
    q = '&'.join('expand[]=' + x for x in ('downloads', 'downloadsAllTime', 'likes', 'createdAt', 'lastModified', 'cardData', 'tags', 'gated', 'pipeline_tag', 'private'))
    return get('https://huggingface.co/api/models/' + mid + '?' + q, 'hf')

def hf_dataset(did):
    q = '&'.join('expand[]=' + x for x in ('downloads', 'downloadsAllTime', 'likes', 'createdAt', 'cardData', 'tags', 'gated'))
    return get('https://huggingface.co/api/datasets/' + did + '?' + q, 'hf')

def hf_derived(mid):
    """この公開モデルを元にした（base_model に指定した）Hugging Face 上のモデル数。上限1000件まで数える"""
    d = get('https://huggingface.co/api/models?filter=base_model:' + urllib.parse.quote(mid, safe='/') + '&limit=1000', 'hf')
    if not isinstance(d, list):
        return None, []
    others = [m['id'] for m in d if not m['id'].lower().startswith(mid.split('/')[0].lower() + '/')]
    return len(d), others

def lic(m):
    for t in m.get('tags') or []:
        if t.startswith('license:'):
            return t.split(':', 1)[1]
    cd = m.get('cardData') or {}
    return cd.get('license') or cd.get('license_name')

def hf_record(kind, rid, basis):
    m = hf_model(rid) if kind == 'model' else hf_dataset(rid)
    if not isinstance(m, dict) or m.get('_status') == 404 or m.get('error'):
        return {'kind': kind, 'id': rid, 'url': 'https://huggingface.co/' + ('datasets/' if kind == 'dataset' else '') + rid,
                'status': '取得できなかった（API が見つからないと返した）', 'basis': basis}
    r = {'kind': kind, 'id': m.get('id', rid), 'url': 'https://huggingface.co/' + ('datasets/' if kind == 'dataset' else '') + m.get('id', rid),
         'downloads_30d': m.get('downloads'), 'downloads_all': m.get('downloadsAllTime'), 'likes': m.get('likes'),
         'created': (m.get('createdAt') or '')[:10], 'license': lic(m), 'gated': m.get('gated'), 'pipeline': m.get('pipeline_tag'),
         'base_models': [t.split(':', 2)[-1] for t in (m.get('tags') or []) if t.startswith('base_model:') and t.count(':') == 1],
         'basis': basis, 'fetched': TODAY}
    if kind == 'model':
        n, others = hf_derived(r['id'])
        r['derived'] = n
        r['derived_other_authors'] = len(others)
    return r

def hf_collection(cid):
    d = get('https://huggingface.co/api/collections/' + cid, 'hf')
    if not isinstance(d, dict):
        return []
    return [(it.get('type') or it.get('repoType'), it.get('id')) for it in d.get('items', []) if it.get('id')]

def readme_mentions_geniac(mid):
    t = get_text('https://huggingface.co/' + mid + '/raw/main/README.md', 'hf_readme')
    return bool(re.search(r'GENIAC|ＧＥＮＩＡＣ', t or ''))

def cmd_hf(orgs, items, sources):
    recs = defaultdict(list)
    done = set()
    # 1) 経済産業省の成果公開ページに載っているもの
    for e in items:
        ks = [k for k in meti_org_keys(e['org']) if k in orgs]
        if not ks:
            print('  ! 事業者名が採択一覧と合わない:', e['org'])
            continue
        basis = {'type': 'meti', 'title': e['source_title'], 'url': e['source_url'], 'item': e['name']}
        refs = [hf_ref(u) for u in e['links']]
        refs = [r for r in refs if r]
        exp = []
        for kind, rid in refs:
            if kind == 'collection':
                exp += [(t if t in ('model', 'dataset') else 'model', i) for t, i in hf_collection(rid)]
            else:
                exp.append((kind, rid))
        for kind, rid in exp:
            if (kind, rid) in done:
                continue
            done.add((kind, rid))
            r = hf_record(kind, rid, basis)
            for k in ks:
                recs[k].append(r)
            print('  ', ks[0], kind, rid, r.get('downloads_all'), r.get('derived'))
    # 2) 採択先の公式発表に載っている Hugging Face アカウント → モデルカードに GENIAC の記載があるモデル
    for s in sources.get('hf_accounts', []):
        acc = s['account']
        lst = get('https://huggingface.co/api/models?author=' + acc + '&limit=1000&expand[]=createdAt', 'hf')
        if not isinstance(lst, list):
            continue
        since = s.get('since', '2024-02-01')
        for m in lst:
            mid = m['id']
            if ('model', mid) in done or (m.get('createdAt') or '')[:10] < since:
                continue
            if not readme_mentions_geniac(mid):
                continue
            done.add(('model', mid))
            r = hf_record('model', mid, {'type': 'account', 'title': s['basis_title'], 'url': s['basis_url'],
                                         'note': 'このアカウントのモデルのうち、モデルカード（README）に GENIAC の記載があるもの'})
            for ok in s.get('org_keys') or [s['org_key']]:
                recs[ok].append(r)
            print('  ', s['org_key'], 'model', mid, r.get('downloads_all'), r.get('derived'))
    json.dump(recs, open(os.path.join(RAW, 'hf_records.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return recs

# ---------------------------------------------------------------- OpenAlex
OA = 'https://api.openalex.org'
MAILTO = 'mailto=info@exbridge.jp'
AI_SUBFIELDS = '1702|1707'   # OpenAlex の分類: Artificial Intelligence / Computer Vision and Pattern Recognition

# 法人の中の大学名で引く（東海国立大学機構の名古屋大学）
QUERY_FIX = {'東海国立大学機構　名古屋大学': '名古屋大学', '東海国立大学機構 名古屋大学': '名古屋大学'}

def ror_lookup(name):
    q = re.sub(r'^(%s)' % '|'.join(map(re.escape, LEGAL)), '', name.strip())
    for w in LEGAL:
        q = q.replace(w, '')
    q = QUERY_FIX.get(q.strip(), q.strip())
    d = get('https://api.ror.org/v2/organizations?affiliation=' + urllib.parse.quote(q), 'ror', sleep=0.5)
    for it in (d or {}).get('items', []) if isinstance(d, dict) else []:
        o = it['organization']
        cc = (o.get('locations') or [{}])[0].get('geonames_details', {}).get('country_code')
        if it.get('chosen') and cc == 'JP':
            return {'ror': o['id'], 'ror_names': [n['value'] for n in o['names']][:4], 'query': q, 'how': 'ROR affiliation 照合（chosen）'}
    # 照合で決まらないときは名前検索。ROR の名前のどれかが、法人の種類を除いた名前と完全に一致するものだけ（似た名前は取らない）
    d = get('https://api.ror.org/v2/organizations?query=' + urllib.parse.quote(q), 'ror', sleep=0.5)
    for o in (d or {}).get('items', []) if isinstance(d, dict) else []:
        cc = (o.get('locations') or [{}])[0].get('geonames_details', {}).get('country_code')
        if cc == 'JP' and any(org_key(re.sub(r'\s*\(Japan\)$', '', n['value'])) == org_key(q) for n in o['names']):
            return {'ror': o['id'], 'ror_names': [n['value'] for n in o['names']][:4], 'query': q, 'how': 'ROR 名前検索（名前が完全一致）'}
    return None

def cmd_openalex(orgs, sources):
    # 1) 機関の対応（ROR の affiliation 照合で chosen=True・日本の機関だけ。誤対応は sources の ror_exclude で外す）
    excl = set(sources.get('ror_exclude', {}).keys())
    force = sources.get('ror_force', {})
    inst = {}
    for k, o in orgs.items():
        if k in force:
            inst[k] = force[k]; continue
        r = ror_lookup(o['name'])
        if r and r['ror'] not in excl:
            inst[k] = r
    rors = sorted({v['ror'] for v in inst.values()})
    oa = {}
    for i in range(0, len(rors), 40):
        chunk = rors[i:i + 40]
        d = get(OA + '/institutions?filter=ror:' + '|'.join(chunk) + '&per_page=50&select=id,ror,display_name,works_count&' + MAILTO, 'openalex')
        for x in (d or {}).get('results', []):
            oa[x['ror']] = {'openalex': x['id'].split('/')[-1], 'display_name': x['display_name']}
    for k, v in inst.items():
        v.update(oa.get(v['ror'], {}))
    # 2) 助成番号つきの論文（NEDO のプロジェクト番号・JST の課題番号）
    grants = sources.get('grants', [])
    gworks = {}
    for g in grants:
        rows, cursor = [], '*'
        while cursor:
            d = get(OA + '/works?filter=awards.funder_award_id:' + g['award_id'] + '&per_page=200&cursor=' + cursor +
                    '&select=id,doi,title,publication_date,type,cited_by_count,authorships,primary_location,primary_topic&' + MAILTO, 'openalex')
            if not isinstance(d, dict) or 'results' not in d:
                break
            rows += d['results']
            cursor = (d.get('meta') or {}).get('next_cursor')
            if not d['results']:
                break
        gworks[g['award_id']] = rows
        print('  grant', g['award_id'], len(rows))
    # 3) 機関ごとの AI 論文数（採択日以降）と被引用の合計
    stats = {}
    for k, v in inst.items():
        if not v.get('openalex'):
            continue
        since = first_date(orgs[k]) or '2024-01-01'
        base = (OA + '/works?filter=authorships.institutions.id:' + v['openalex'] + ',from_publication_date:' + since +
                ',primary_topic.subfield.id:' + AI_SUBFIELDS + ',type:article|preprint|review|book-chapter')
        # 被引用の多い順に取り、件数が2000本以下なら全部たどって被引用を合計する（多いときは合計を出さない）
        cites, n, cursor, pages, top = 0, None, '*', 0, []
        while cursor and pages < 10:
            d = get(base + '&sort=cited_by_count:desc&per_page=200&cursor=' + cursor + '&select=id,title,publication_date,cited_by_count,doi&' + MAILTO, 'openalex')
            if not isinstance(d, dict) or 'results' not in d:
                break
            n = d['meta']['count']
            for w in d['results']:
                cites += w.get('cited_by_count') or 0
                top.append(w)
            if n > 2000:
                break
            cursor = d['meta'].get('next_cursor') if d['results'] else None
            pages += 1
        complete = n is not None and len(top) >= n
        stats[k] = {'since': since, 'count': n, 'cited_sum': cites if complete else None, 'cited_sum_partial': None if complete else cites,
                    'counted': len(top), 'top': [{'title': w['title'], 'date': w['publication_date'], 'cited': w['cited_by_count'],
                                                   'url': w.get('doi') or w['id']} for w in top[:3]],
                    'query_url': base.replace(OA + '/works?', 'https://api.openalex.org/works?'), 'fetched': TODAY}
        print('  inst', k, v.get('display_name'), n, cites)
    json.dump({'inst': inst, 'grant_works': gworks, 'stats': stats}, open(os.path.join(RAW, 'openalex_records.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return inst, gworks, stats

# ---------------------------------------------------------------- まとめ
def cmd_build(aw, orgs, items, sources):
    hf = json.load(open(os.path.join(RAW, 'hf_records.json'), encoding='utf-8'))
    oa = json.load(open(os.path.join(RAW, 'openalex_records.json'), encoding='utf-8'))
    inst, gworks, stats = oa['inst'], oa['grant_works'], oa['stats']
    mid = midterm_status(aw)
    bench = defaultdict(list)
    for b in sources.get('benchmarks', []):
        bench[b['org_key']].append(b)
    for e in items:
        for s in bench_sentences(e['fields'].get('特徴', '')):
            for k in meti_org_keys(e['org']):
                if k in orgs:
                    bench[k].append({'org_key': k, 'model': e['name'], 'text': s, 'kind': 'quote',
                                     'source_title': e['source_title'] + '「特徴」欄（事業者による記載）', 'source_url': e['source_url'], 'as_of': '公開ページの記載（取得 ' + TODAY + '）'})
    # 経済産業省ページの成果物のうち、Hugging Face 以外（GitHub・マーケットプレイス・非公開）も一覧に残す
    other = defaultdict(list)
    for e in items:
        if any(hf_ref(u) for u in e['links']):
            continue
        for k in meti_org_keys(e['org']):
            if k in orgs:
                other[k].append({'name': e['name'], 'section': e['section'], 'license': e['fields'].get('公開形態・ライセンス', ''),
                                 'links': e['links'][:3], 'source_title': e['source_title'], 'source_url': e['source_url']})
    # 助成番号の論文を採択先にひも付ける（著者の所属の OpenAlex 機関ID が一致するもの）
    oid2key = defaultdict(list)
    for k, v in inst.items():
        if v.get('openalex'):
            oid2key[v['openalex']].append(k)
    gpapers = defaultdict(list)
    grant_meta = {g['award_id']: g for g in sources.get('grants', [])}
    grant_summary = []
    for gid, rows in gworks.items():
        matched = 0
        for w in rows:
            ks = set()
            for a in w.get('authorships') or []:
                for ins in a.get('institutions') or []:
                    for k in oid2key.get((ins.get('id') or '').split('/')[-1], []):
                        ks.add(k)
            # 番号の事業に入る公募でこの採択先が採択された日以降の、AI分野（OpenAlex の主題 1702/1707）の論文だけをひも付ける。
            # P20017 は通信・半導体の公募も含むので、分野と日付で絞らないと別の公募の論文が混ざる
            sub = str(((w.get('primary_topic') or {}).get('subfield') or {}).get('id', '')).split('/')[-1]
            gprogs = set(grant_meta.get(gid, {}).get('programs', []))
            ks = {k for k in ks if (not grant_meta.get(gid, {}).get('ai_only') or sub in AI_SUBFIELDS.split('|')) and any(
                a['program_id'] in gprogs and (w.get('publication_date') or '') >= (adate(a) or '') for a in orgs[k]['awards'])}
            if ks:
                matched += 1
            for k in ks:
                gpapers[k].append({'award_id': gid, 'title': w['title'], 'date': w['publication_date'], 'type': w.get('type'),
                                   'cited': w.get('cited_by_count'), 'url': w.get('doi') or w['id']})
        grant_summary.append(dict(grant_meta.get(gid, {}), works=len(rows), cited_sum=sum(w.get('cited_by_count') or 0 for w in rows),
                                  matched=matched, fetched=TODAY))
    cards = []
    for k, o in orgs.items():
        models = [r for r in hf.get(k, []) if r['kind'] == 'model']
        datasets = [r for r in hf.get(k, []) if r['kind'] == 'dataset']
        ms = []
        for a in o['awards']:
            st = None
            for (pid, kk), v in mid.items():
                if pid == a['program_id'] and kk.endswith('|' + N(a['theme'])):
                    st = v
            if st:
                ms.append(dict(st, program_id=a['program_id'], theme=a['theme']))
        gp = sorted(gpapers.get(k, []), key=lambda x: -(x['cited'] or 0))
        card = {'key': k, 'name': o['name'], 'awards': o['awards'], 'since': first_date(o),
                'hf_models': sorted(models, key=lambda r: -(r.get('downloads_all') or 0)),
                'hf_datasets': sorted(datasets, key=lambda r: -(r.get('downloads_all') or 0)),
                'other_outputs': other.get(k, []),
                'hf_account_note': next((s.get('note') for s in sources.get('hf_unverified', []) if s['org_key'] == k), None),
                'institution': inst.get(k), 'papers_inst': stats.get(k), 'papers_grant': gp,
                'benchmarks': bench.get(k, []), 'midterm': ms,
                'amount': '公表資料では確認できなかった'}
        card['has'] = {'models': len(card['hf_models']), 'datasets': len(card['hf_datasets']), 'papers_grant': len(gp),
                       'papers_inst': (stats.get(k) or {}).get('count'), 'bench': len(card['benchmarks'])}
        cards.append(card)
    cards.sort(key=lambda c: (-(c['has']['models'] + c['has']['datasets']), -len(c['papers_grant']), -(len(c['benchmarks'])), c['name']))
    tot_models = [r for c in cards for r in c['hf_models']]
    summary = {
        'orgs': len(cards), 'orgs_with_hf': sum(1 for c in cards if c['hf_models'] or c['hf_datasets']),
        'orgs_with_models': sum(1 for c in cards if c['hf_models']),
        'hf_models': len(tot_models), 'hf_datasets': sum(len(c['hf_datasets']) for c in cards),
        'downloads_all': sum(r.get('downloads_all') or 0 for r in tot_models), 'derived': sum(r.get('derived') or 0 for r in tot_models),
        'orgs_with_inst': sum(1 for c in cards if c['institution'] and c['institution'].get('openalex')),
        'orgs_with_grant_papers': sum(1 for c in cards if c['papers_grant']),
        'orgs_with_bench': sum(1 for c in cards if c['benchmarks']),
        'orgs_with_midterm': sum(1 for c in cards if c['midterm']),
        'meti_items': len(items),
    }
    out = {'generated_at': TODAY, 'summary': summary, 'grants': grant_summary, 'cards': cards,
           'sources': {'meti_pages': [{'title': p['title'], 'url': p['url']} for p in METI_PAGES] + [{'title': '経済産業省 GENIAC「GENIAC事業 第1期 性能評価結果公開」', 'url': 'https://geniac.meti.go.jp/selection_1/result_1/index.html'}],
                       'midterm': {'title': MIDTERM['title'], 'url': MIDTERM['url']},
                       'hf_api': 'Hugging Face Hub 公開API（https://huggingface.co/api/models ・ /api/datasets。鍵なし）',
                       'openalex': 'OpenAlex API（https://api.openalex.org。鍵なし）・ROR API（https://api.ror.org）',
                       'ai_subfields': 'OpenAlex の分類で主題が Artificial Intelligence（1702）または Computer Vision and Pattern Recognition（1707）の論文（論文・プレプリント・レビュー・本の章）'},
           'notes': sources.get('notes', [])}
    dst = os.path.join(ROOT, 'data', 'outcomes.json')
    json.dump(out, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print('wrote', dst)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    os.makedirs(RAW, exist_ok=True)
    aw, orgs = awardees()
    sources = json.load(open(os.path.join(ROOT, 'data', 'outcome_sources.json'), encoding='utf-8'))
    if cmd == 'orgs':
        for k, o in orgs.items():
            print(k, '|', o['name'], '|', first_date(o), '|', ','.join(a['program_id'] for a in o['awards']))
        print(len(orgs)); return
    items = cmd_meti() if cmd in ('meti', 'all', 'hf', 'build') else None
    if cmd in ('hf', 'all'):
        cmd_hf(orgs, items, sources)
    if cmd in ('openalex', 'all'):
        cmd_openalex(orgs, sources)
    if cmd == 'mid':
        for k, v in midterm_status(aw).items():
            print(k, v)
    if cmd in ('build', 'all'):
        cmd_build(aw, orgs, items, sources)

if __name__ == '__main__':
    main()
