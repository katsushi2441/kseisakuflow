#!/usr/bin/python3
"""分野の設定（fields/<分野>.json）から、会議→予算→採択→評価→国会 をつないだ JSON を作る。
使い方: build_flow.py ai   → data/flow/ai.json（xb4g/giin/data/flow/ai.json へも写す: --copy）

**しないこと**: 利益相反の有無の判断・評価語。組織名が同じものを「同じ組織名が出る」と並べるだけ。
数字はすべて公表資料（RS の CSV・NEDO/経産省の公表資料・内閣府の会議資料・国会会議録）からそのまま取る。"""
import csv, glob, hashlib, json, os, re, shutil, sqlite3, sys, time, unicodedata
from collections import defaultdict, OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
XB4G_DATA = '/home/kojima/work/xb4g/giin/data'
TODAY = time.strftime('%Y-%m-%d')
csv.field_size_limit(10**9)

def N(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s or ''))

def num(s):
    s = (s or '').strip().replace(',', '')
    if s == '':
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None

def rs_file(y, prefix):
    f = glob.glob(os.path.join(ROOT, 'raw', 'rs' + y, prefix + '*.csv'))
    return f[0] if f else None

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)

def rs_source(y, prefix):
    p = rs_file(y, prefix)
    return {'title': '行政事業レビュー見える化サイト（RSシステム） ' + os.path.basename(p).replace('.csv', ''),
            'url': 'https://rssystem.go.jp/download-csv/' + y, 'file': os.path.basename(p), 'fetched': '2026-11-05'}

# ---------------------------------------------------------------- 組織名のそろえ方（重なりの照合用）
LEGAL = ['国立研究開発法人', '独立行政法人', '国立大学法人', '公立大学法人', '大学共同利用機関法人', '学校法人',
         '一般社団法人', '公益社団法人', '一般財団法人', '公益財団法人', '特定非営利活動法人', '株式会社', '有限会社',
         '合同会社', '(株)', '㈱']
def org_key(s):
    t = N(s).lower()
    for w in LEGAL:
        t = t.replace(unicodedata.normalize('NFKC', w).lower(), '')
    t = re.sub(r'[・,.、。()（）「」\'"]', '', t)
    return t

# ---------------------------------------------------------------- RS
def load_rs(field):
    rx = re.compile(field['rs_match']['regex'])
    projects = OrderedDict()
    for y in field['rs_years']:              # 新しい年度から。同じ予算事業IDは新しいシートを使う
        for a in read_csv(rs_file(y, '1-2_')):
            pid = a['予算事業ID']
            if pid in projects:
                continue
            name_txt = N(''.join(a[k] for k in field['rs_match']['name_fields']))
            body_txt = N(''.join(a[k] for k in field['rs_match']['body_fields']))
            tier = 'name' if rx.search(name_txt) else ('body' if rx.search(body_txt) else None)
            if not tier:
                continue
            m = rx.search(name_txt) or rx.search(body_txt)
            projects[pid] = {
                'id': pid, 'sheet': y, 'tier': tier, 'hit_word': m.group(0),
                'ministry': a['府省庁'], 'bureau': ' '.join(x for x in [a['局・庁'], a['部'], a['課']] if x),
                'name': a['事業名'], 'purpose': a['事業の目的'], 'issue': a['現状・課題'], 'overview': a['事業の概要'],
                'url': a['事業概要URL'], 'start': a['事業開始年度'], 'end': a['事業終了（予定）年度'] or ('終了予定なし' if a['終了予定なし'] else ''),
                'kubun': a['事業区分'], 'old_no': a['旧事業番号'],
                'budget': [], 'payees': [], 'outcomes': [], 'review': None, 'plans': [],
                'council_refs': [], 'programs': [], 'evaluations': [], 'kokkai': [], 'kokkai_total': 0,
                'source': rs_source(y, '1-2_'),
            }
    by_sheet = defaultdict(set)
    for p in projects.values():
        by_sheet[p['sheet']].add(p['id'])
    for y, ids in by_sheet.items():
        # 予算・執行（サマリの合計行＝会計区分が空の行）
        for a in read_csv(rs_file(y, '2-1_')):
            if a['予算事業ID'] in ids and a['会計区分'] == '' and a['予算年度']:
                projects[a['予算事業ID']]['budget'].append({
                    'year': a['予算年度'], 'initial': num(a['当初予算（合計）']), 'supplementary': num(a['補正予算（合計）']),
                    'carried_in': num(a['前年度からの繰越し（合計）']), 'current': num(a['計（歳出予算現額合計）']),
                    'exec': num(a['執行額（合計）']), 'rate': a['執行率'], 'request_next': num(a['翌年度要求額（合計）'])})
        # 支出先（支出先名と支出先ごとの合計がある行）
        seen = set()
        for a in read_csv(rs_file(y, '5-1_')):
            pid = a['予算事業ID']
            if pid not in ids or not a['支出先名'].strip() or num(a['支出先の合計支出額']) is None:
                continue
            k = (pid, a['支出先ブロック番号'], a['支出先名'].strip())
            if k in seen:
                continue
            seen.add(k)
            projects[pid]['payees'].append({'block': a['支出先ブロック番号'], 'block_name': a['支出先ブロック名'].strip(),
                                           'name': a['支出先名'].strip(), 'corp_no': a['法人番号'].strip(),
                                           'amount': num(a['支出先の合計支出額']), 'role': a['事業を行う上での役割'].strip()})
        # 目標・実績（アウトカムとアウトプット）
        oc = OrderedDict()
        for a in read_csv(rs_file(y, '3-1_')):
            pid = a['予算事業ID']
            if pid not in ids:
                continue
            kind = a['種別（アクティビティ・アウトプット・アウトカム）']
            if kind not in ('アウトカム', 'アウトプット'):
                continue
            k = (pid, a['アクティビティ・アウトプット・アウトカムの番号'], kind, a['アクティビティ／活動目標／成果目標'], a['活動指標／成果指標'])
            o = oc.setdefault(k, {'kind': kind, 'goal': a['アクティビティ／活動目標／成果目標'], 'indicator': a['活動指標／成果指標'],
                                  'unit': a['単位'], 'qual': a['定性的なアウトカムに関する成果実績'], 'kpi_doc': a['事業に関連するKPIが定められている閣議決定等の名称'],
                                  'target_year': None, 'target': {}, 'actual': {}})
            row = a['目標年度／目標値／実績値／達成率']
            vals = {k2: v for k2, v in a.items() if k2 and k2.isdigit() and (v or '').strip()}
            if row.startswith('1'):
                o['target_year'] = next(iter(vals), None)
            elif row.startswith('2'):
                o['target'] = vals
            elif row.startswith('3'):
                o['actual'] = vals
        for (pid, *_), o in oc.items():
            projects[pid]['outcomes'].append(o)
        # 点検・評価
        for a in read_csv(rs_file(y, '4-1_')):
            pid = a['予算事業ID']
            if pid in ids and projects[pid]['review'] is None:
                projects[pid]['review'] = {
                    'self_result': a['事業所管部局による点検・改善ー点検結果'], 'self_direction': a['事業所管部局による点検・改善ー改善の方向性'],
                    'ext_year': a['外部有識者による点検ー最終実施年度'], 'ext_target': a['外部有識者による点検ー点検対象'],
                    'ext_reason': a['外部有識者による点検ー対象の理由'], 'ext_opinion': a['外部有識者による点検ー所見'],
                    'team': a['行政事業レビュー推進チームの所見'], 'team_detail': a['行政事業レビュー推進チームの所見の詳細'],
                    'reflect': a['所見を踏まえた改善点／概算要求における反映状況'], 'reflect_detail': a['所見を踏まえた改善点／概算要求における反映状況の詳細'],
                    'source': rs_source(y, '4-1_')}
        # 関係する計画・通知
        for a in read_csv(rs_file(y, '1-3_')):
            pid = a['予算事業ID']
            if pid in ids and a['計画通知名'].strip():
                t = a['計画通知名'].strip()
                if t not in [x['title'] for x in projects[pid]['plans']]:
                    projects[pid]['plans'].append({'title': t, 'url': a['計画通知等URL'].strip()})
    for p in projects.values():
        p['budget'].sort(key=lambda b: b['year'], reverse=True)
        p['payees'].sort(key=lambda x: -(x['amount'] or 0))
        p['payee_count'] = len(p['payees'])
        p['outcomes'] = p['outcomes'][:8]
    return projects

# ---------------------------------------------------------------- 会議資料
def council_url_index(councils):
    idx = {}
    for c in councils['councils']:
        for o in c.get('outputs') or []:
            if o.get('url'):
                idx[o['url']] = {'council': c['name'], 'council_id': c['id'], 'kind': '提言・取りまとめ', 'title': o['title'], 'date': o.get('date'), 'meeting_url': c.get('url')}
        for m in c.get('meetings') or []:
            base = {'council': c['name'], 'council_id': c['id'], 'meeting_no': m.get('no'), 'date': m.get('date'), 'meeting_url': m.get('url')}
            if m.get('minutes_url') and m['minutes_url'].startswith('http'):
                idx.setdefault(m['minutes_url'], dict(base, kind='議事要旨', title=m.get('minutes_title') or '議事要旨'))
            for mt in m.get('materials') or []:
                if mt.get('url'):
                    t = re.sub(r'（PDF形式[^）]*）', '', mt.get('title') or '')
                    idx.setdefault(mt['url'], dict(base, kind='配付資料', title=((mt.get('label') or '') + ' ' + t).strip()))
    return idx

def council_refs(projects, field, councils):
    pages = [json.loads(l) for l in open(os.path.join(ROOT, 'raw', 'cao_pages.jsonl'), encoding='utf-8')]
    idx = council_url_index(councils)
    links = field.get('project_links', {})
    minlen = field.get('council_name_min_len', 10)
    for p in projects.values():
        nm = N(p['name'])
        core = re.split(r'[（(]', nm)[0]
        queries = []
        if len(core) >= minlen:
            queries.append(('事業名', [core]))
        for terms in links.get(p['id'], {}).get('council_terms', []):
            queries.append(('関連語', [N(t) for t in terms]))
        refs = OrderedDict()
        for how, terms in queries:
            for pg in pages:
                if all(t in pg['text'] for t in terms):
                    meta = idx.get(pg['url'])
                    if not meta:
                        continue
                    k = pg['url']
                    r = refs.setdefault(k, dict(meta, url=pg['url'], pages=[], how=how, terms=terms))
                    if pg['page'] not in r['pages']:
                        r['pages'].append(pg['page'])
        p['council_refs'] = sorted(refs.values(), key=lambda r: (r.get('date') or ''))

# ---------------------------------------------------------------- 採択・評価
def attach_awards(projects, field, awards):
    links = field.get('project_links', {})
    prog_by_id = {p['id']: p for p in awards['programs']}
    linked_prog = {}
    for pid, l in links.items():
        if pid not in projects:
            continue
        for gid in l.get('programs', []):
            if gid in prog_by_id:
                projects[pid]['programs'].append(gid)
                linked_prog[gid] = pid
        projects[pid]['programs_basis'] = l.get('programs_basis', '')
        for key in l.get('evaluations', []):
            name, _, typ = key.partition('|')
            for i, e in enumerate(awards['evaluations']):
                if N(e['project']).startswith(N(name)) and (not typ or typ in e.get('type', '')):
                    projects[pid]['evaluations'].append(i)
        projects[pid]['evaluations_basis'] = l.get('evaluations_basis', '')
    return linked_prog

# ---------------------------------------------------------------- 国会
def kokkai_cache(term):
    p = os.path.join(ROOT, 'raw', 'kokkai', hashlib.md5(term.encode()).hexdigest()[:12] + '.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None

def excerpt(body, term, w=70):
    b = body.replace('\r', '').replace('\n', '')
    words = [t for t in re.split(r'[\s　]+', term) if t]
    i = b.find(words[0]) if words else -1
    if i < 0:
        return b[:w * 2] + '…'
    s = max(0, i - w)
    return ('…' if s > 0 else '') + b[s:i + w] + '…'

def attach_kokkai(projects, field):
    for pid, l in field.get('project_links', {}).items():
        if pid not in projects:
            continue
        seen = set()
        for t in l.get('kokkai_terms', []):
            d = kokkai_cache(t)
            if not d:
                continue
            projects[pid]['kokkai_total'] += int(d.get('numberOfRecords') or 0)
            for s in d['speechRecord']:
                if s['speechID'] in seen or s.get('speaker') in ('会議録情報',):
                    continue
                seen.add(s['speechID'])
                projects[pid]['kokkai'].append({'date': s['date'], 'house': s['nameOfHouse'], 'meeting': s['nameOfMeeting'],
                                                'issue': s.get('issue', ''), 'speaker': s['speaker'], 'position': s.get('speakerPosition') or '',
                                                'group': s.get('speakerGroup') or '', 'url': s['speechURL'], 'term': t,
                                                'excerpt': excerpt(s['speech'], t), 'fetched': d['fetched_at']})
        projects[pid]['kokkai'].sort(key=lambda x: x['date'], reverse=True)
        projects[pid]['kokkai_terms'] = l.get('kokkai_terms', [])

def tracker_stats(field):
    db = os.path.join(XB4G_DATA, 'giin.sqlite')
    tr = {t['key']: t for t in json.load(open(os.path.join(XB4G_DATA, 'trackers.json'), encoding='utf-8'))}
    out = []
    con = sqlite3.connect(db)
    for k in field.get('trackers', []):
        c = con.execute("SELECT COUNT(*), SUM(kind='q'), SUM(kind='a'), MIN(date), MAX(date) FROM tracker_speech WHERE tracker=?", (k,)).fetchone()
        out.append({'key': k, 'name': tr.get(k, {}).get('name', k), 'count': c[0], 'q': c[1] or 0, 'a': c[2] or 0, 'from': c[3], 'to': c[4]})
    return out

# ---------------------------------------------------------------- 重なり
def overlaps(projects, councils, awards, linked_prog):
    members = defaultdict(list)
    for c in councils['councils']:
        for r in c.get('rosters') or []:
            for m in r.get('members') or []:
                orgs = m.get('orgs') or ([m['org']] if m.get('org') else [])
                for o in orgs:
                    k = org_key(o)
                    if len(k) < 2:
                        continue
                    ent = {'council': c['name'], 'council_id': c['id'], 'name': m['name'], 'affiliation': m.get('affiliation', ''),
                           'org': o, 'as_of': r.get('as_of'), 'source_title': r.get('source_title'), 'source_url': r.get('source_url')}
                    if not any(e['council'] == ent['council'] and e['name'] == ent['name'] for e in members[k]):
                        members[k].append(ent)
    hits = defaultdict(lambda: {'payees': [], 'awards': []})
    for p in projects.values():
        for py in p['payees']:
            k = org_key(py['name'])
            if k in members:
                hits[k]['payees'].append({'project_id': p['id'], 'project': p['name'], 'ministry': p['ministry'], 'payee': py['name'],
                                          'block': py['block'], 'amount': py['amount'], 'sheet': p['sheet'], 'source': rs_source(p['sheet'], '5-1_')})
    for g in awards['programs']:
        for a in g.get('awards', []):
            for o in [a.get('org')] + list(a.get('co_orgs') or []) + list(a.get('orgs_listed') or []):
                if not o or str(o).startswith('未取得'):
                    continue
                k = org_key(o)
                if k in members and not any(x['program_id'] == g['id'] and x['org'] == o for x in hits[k]['awards']):
                    hits[k]['awards'].append({'program_id': g['id'], 'program': g['name'], 'org': o, 'theme': a.get('theme', ''),
                                              'award_date': g.get('award_date'), 'source_title': g.get('source_title'), 'source_url': g.get('source_url'),
                                              'project_id': linked_prog.get(g['id'])})
    out = []
    for k, h in hits.items():
        out.append({'key': k, 'members': members[k], 'payees': h['payees'], 'awards': h['awards']})
    out.sort(key=lambda o: (-(len(o['payees']) + len(o['awards'])), o['key']))
    for p in projects.values():
        p['overlap_keys'] = sorted({o['key'] for o in out for x in o['payees'] if x['project_id'] == p['id']}
                                   | {o['key'] for o in out for x in o['awards'] if x.get('project_id') == p['id']})
    return out

def committee_text(list_url):
    m = re.search(r'/content/(\d+)\.pdf', list_url or '')
    if not m:
        return []
    for suf in ('.raw.txt', '.txt'):
        f = os.path.join(ROOT, 'raw', 'nedo', 'nedo.go.jp__content_' + m.group(1) + suf)
        if os.path.exists(f):
            return [l.strip() for l in open(f, encoding='utf-8', errors='replace').read().splitlines() if l.strip()]
    return []

def person_overlaps(councils, awards, linked_prog):
    """会議の構成員名簿と、採択審査委員会の委員一覧に、同じ氏名が出るもの。所属は各資料の記載のまま。"""
    mem = defaultdict(list)
    for c in councils['councils']:
        for r in c.get('rosters') or []:
            for m in r.get('members') or []:
                k = N(m['name'])
                if not any(e['council'] == c['name'] for e in mem[k]):
                    mem[k].append({'council': c['name'], 'council_id': c['id'], 'name': m['name'], 'affiliation': m.get('affiliation', ''),
                                   'as_of': r.get('as_of'), 'source_title': r.get('source_title'), 'source_url': r.get('source_url')})
    out = defaultdict(list)
    for g in awards['programs']:
        rv = g.get('review') if isinstance(g.get('review'), dict) else {}
        com = rv.get('committee') if isinstance(rv.get('committee'), dict) else {}
        names = ([('委員長', com['chair'])] if com.get('chair') else []) + [('委員', x) for x in (com.get('members') or [])]
        lines = committee_text(com.get('list_url'))
        for role, nm in names:
            k = N(nm)
            if k not in mem:
                continue
            aff = ''
            for i, l in enumerate(lines):
                if k in N(l):
                    rest = N(l).split(k, 1)[1]
                    j = i + 1
                    while len(rest) < 4 and j < len(lines) and not N(lines[j]).startswith('委員'):
                        rest += ' ' + lines[j].strip(); j += 1
                    while j < len(lines) and j <= i + 3 and not N(lines[j]).startswith('委員') and not N(lines[j]).startswith('（'):
                        rest += ' ' + lines[j].strip(); j += 1
                    aff = rest.strip()
                    break
            out[k].append({'program_id': g['id'], 'program': g['name'], 'role': role, 'name': nm, 'affiliation_in_list': aff or '未取得',
                           'list_url': com.get('list_url'), 'award_date': g.get('award_date'), 'source_title': g.get('source_title'),
                           'source_url': g.get('source_url'), 'project_id': linked_prog.get(g['id'])})
    return [{'key': k, 'members': mem[k], 'committees': v} for k, v in out.items()]

# ---------------------------------------------------------------- まとめ
def stage_count(p):
    return sum([bool(p['council_refs']), bool(p['budget']), bool(p['payees']), bool(p['programs']),
                bool(p['review'] and (p['review']['self_result'] or p['review']['ext_opinion'])) or bool(p['evaluations']), bool(p['kokkai'])])

def main():
    slug = sys.argv[1]
    field = json.load(open(os.path.join(ROOT, 'fields', slug + '.json'), encoding='utf-8'))
    councils = json.load(open(os.path.join(ROOT, field['councils_file']), encoding='utf-8'))
    awards = json.load(open(os.path.join(ROOT, field['awards_file']), encoding='utf-8'))
    projects = load_rs(field)
    council_refs(projects, field, councils)
    linked_prog = attach_awards(projects, field, awards)
    attach_kokkai(projects, field)
    ov = overlaps(projects, councils, awards, linked_prog)
    pov = person_overlaps(councils, awards, linked_prog)
    for p in projects.values():
        p['stages'] = stage_count(p)
    plist = sorted(projects.values(), key=lambda p: (-p['stages'], -(len(p['programs']) > 0), -(len(p['council_refs']) > 0),
                                                     -max([b['initial'] or 0 for b in p['budget'] if b['year'] == '2025'] or [0])))
    def ysum(key, year, tier=None):
        return sum((b[key] or 0) for p in projects.values() if tier in (None, p['tier'])
                   for b in p['budget'] if b['year'] == year and p['sheet'] == '2025')
    summary = {
        'projects': len(projects), 'projects_name': sum(p['tier'] == 'name' for p in projects.values()),
        'projects_body': sum(p['tier'] == 'body' for p in projects.values()),
        'projects_2025': sum(p['sheet'] == '2025' for p in projects.values()), 'projects_2024only': sum(p['sheet'] == '2024' for p in projects.values()),
        'initial_2025': ysum('initial', '2025'), 'initial_2025_name': ysum('initial', '2025', 'name'),
        'current_2024': ysum('current', '2024'), 'exec_2024': ysum('exec', '2024'),
        'current_2024_name': ysum('current', '2024', 'name'), 'exec_2024_name': ysum('exec', '2024', 'name'),
        'payee_rows': sum(len(p['payees']) for p in projects.values()),
        'with_council_ref': sum(bool(p['council_refs']) for p in projects.values()),
        'with_programs': sum(bool(p['programs']) for p in projects.values()),
        'with_ext_review': sum(bool(p['review'] and p['review']['ext_opinion']) for p in projects.values()),
        'with_review': sum(bool(p['review'] and p['review']['self_result']) for p in projects.values()),
        'with_kokkai': sum(bool(p['kokkai']) for p in projects.values()),
        'programs': len(awards['programs']), 'award_rows': sum(len(g.get('awards', [])) for g in awards['programs']),
        'evaluations': len(awards['evaluations']), 'overlaps': len(ov), 'person_overlaps': len(pov),
        'councils': len(councils['councils']),
        'meetings': sum(len(c.get('meetings') or []) for c in councils['councils']),
        'outputs': len({o['url'] for c in councils['councils'] for o in (c.get('outputs') or []) if o.get('url')}),
        'members': len({N(m['name']) for c in councils['councils'] for r in (c.get('rosters') or []) for m in (r.get('members') or [])}),
    }
    out = {'field': {k: field[k] for k in ('slug', 'name', 'title', 'lead')}, 'words_label': field['rs_match']['words_label'],
           'generated_at': TODAY, 'summary': summary,
           'councils': councils['councils'], 'councils_meta': {k: councils.get(k) for k in ('fetched_at', 'source_note', 'scope_note')},
           'programs': awards['programs'], 'evaluations': awards['evaluations'], 'evaluation_rules': awards.get('evaluation_rules'),
           'awards_meta': {'fetched_at': awards.get('fetched_at'), 'notes': awards.get('notes')},
           'linked_programs': linked_prog, 'unlinked_programs_note': field.get('unlinked_programs_note', ''),
           'projects': plist, 'overlaps': ov, 'person_overlaps': pov, 'trackers': tracker_stats(field),
           'rs_sources': {y: {k: rs_source(y, k) for k in ('1-2_', '2-1_', '3-1_', '4-1_', '5-1_', '1-3_')} for y in field['rs_years']}}
    os.makedirs(os.path.join(ROOT, 'data', 'flow'), exist_ok=True)
    dst = os.path.join(ROOT, 'data', 'flow', slug + '.json')
    json.dump(out, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print('wrote', dst, os.path.getsize(dst))
    # 分野の一覧（入口のページと、国会トラッカーからの相互リンクが読む軽い索引）
    # 自分の分野の行だけを差し替える（契約型の分野は build_koho.py が書く）
    ip = os.path.join(ROOT, 'data', 'flow', 'index.json')
    ix = json.load(open(ip, encoding='utf-8')) if os.path.exists(ip) else {'fields': []}
    ent = {'slug': slug, 'name': field['name'], 'title': field['title'], 'lead': field['lead'],
           'generated_at': TODAY, 'summary': summary, 'trackers': field.get('trackers', [])}
    ix['fields'] = [ent if f['slug'] == slug else f for f in ix['fields']] if any(f['slug'] == slug for f in ix['fields']) else ix['fields'] + [ent]
    json.dump(ix, open(ip, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if '--copy' in sys.argv:
        os.makedirs(os.path.join(XB4G_DATA, 'flow'), exist_ok=True)
        for fn in (slug + '.json', 'index.json'):
            shutil.copy(os.path.join(ROOT, 'data', 'flow', fn), os.path.join(XB4G_DATA, 'flow', fn))
        print('copied to', os.path.join(XB4G_DATA, 'flow'))

if __name__ == '__main__':
    main()
