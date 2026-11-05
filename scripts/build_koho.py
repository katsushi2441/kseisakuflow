#!/usr/bin/python3
"""分野「政府広報」（型 contracts）: RS の 5-1 支出先_支出情報 から、契約概要・事業名に広報等の語を含む契約を集める。
使い方: build_koho.py koho [--copy]
出力: data/flow/koho.json（全体・府省・支出先の一覧）と data/flow/koho/{m,s,p}_<key>.json（府省・支出先・事業のページ用）

- 補助金等の交付（契約方式等に「補助金」「交付」）は契約の一覧から外し、支出先のページに別に出す
- 入札者数・落札率の 0 と空欄は「記録なし」として扱う（0者・0% と書かない）。ここでは値をそのまま持ち、表示側で判定する
- 支出先は法人番号でまとめる（無い・9999999999999 のときは名前）。名前の一部が同じ別会社を混ぜない"""
import csv, glob, hashlib, json, os, re, shutil, sys, time, unicodedata
from collections import defaultdict, OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
XB4G_DATA = '/home/kojima/work/xb4g/giin/data'
TODAY = time.strftime('%Y-%m-%d')
FETCHED = '2026-11-05'
csv.field_size_limit(10**9)
N = lambda s: unicodedata.normalize('NFKC', s or '')

def num(s):
    s = (s or '').strip().replace(',', '')
    try:
        return float(s) if s != '' else None
    except ValueError:
        return None

def rs_file(y, prefix):
    return glob.glob(os.path.join(ROOT, 'raw', 'rs' + y, prefix + '*.csv'))[0]

def read_csv(p):
    with open(p, encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)

def payee_key(name, corp):
    """支出先のページの鍵は法人番号だけ。法人番号が無い支出先（「その他」「個人Ａ」など総称の記載が多い）と、
    国の機関（法人番号の2〜7桁目が 000012）にはページを作らない（府省・事業のページの一覧には出す）。"""
    corp = (corp or '').strip()
    if re.fullmatch(r'\d{13}', corp) and corp != '9999999999999' and corp[1:7] != '000012':
        return corp
    return ''

def main():
    slug = sys.argv[1]
    F = json.load(open(os.path.join(ROOT, 'fields', slug + '.json'), encoding='utf-8'))
    kw, gr = re.compile(F['contract_regex']), re.compile(F['grant_regex'])
    contracts, others = [], []          # 広報等の契約 / 支出先のページ用（同じ支出先のほかの契約・交付）
    ministry_code = {}
    for y in F['rs_years']:
        src = os.path.basename(rs_file(y, '5-1_')).replace('.csv', '')
        for a in read_csv(rs_file(y, '5-1_')):
            if not a['契約概要'].strip() or num(a['金額']) is None:
                continue
            name = a['支出先名'].strip()
            row = {'y': y, 'ex': F['exec_year'][y], 'pid': a['予算事業ID'], 'mn': a['府省庁'], 'mc': a['府省庁の建制順'],
                   'pj': a['事業名'], 'py': name, 'corp': a['法人番号'].strip(), 'k': payee_key(name, a['法人番号']),
                   'blk': a['支出先ブロック番号'], 'sm': a['契約概要'].strip(), 'amt': num(a['金額']),
                   'mt': a['契約方式等'].strip(), 'mt2': a['具体的な契約方式等'].strip(), 'bid': a['入札者数'].strip(), 'rate': a['落札率'].strip(),
                   'src': src}
            ministry_code[a['府省庁']] = a['府省庁の建制順']
            grant = bool(gr.search(row['mt']))
            hit_s, hit_p = bool(kw.search(N(row['sm']))), bool(kw.search(N(row['pj'])))
            if (hit_s or hit_p) and not grant:
                row['tier'] = 's' if hit_s else 'p'
                m = kw.search(N(row['sm'])) or kw.search(N(row['pj']))
                row['hw'] = m.group(0)
                contracts.append(row)
            else:
                row['grant'] = grant
                others.append(row)
    keys = {c['k'] for c in contracts if c['k']}
    pids = {(c['pid']) for c in contracts}
    # ---- 事業ごとの成果目標と実績（3-1）・点検（4-1）・予算（2-1）・概要（1-2）
    proj = {}
    for y in F['rs_years']:
        for a in read_csv(rs_file(y, '1-2_')):
            if a['予算事業ID'] in pids and (a['予算事業ID'], y) not in proj:
                proj[(a['予算事業ID'], y)] = {'id': a['予算事業ID'], 'y': y, 'ex': F['exec_year'][y], 'mn': a['府省庁'], 'bureau': ' '.join(x for x in [a['局・庁'], a['部'], a['課']] if x),
                                              'name': a['事業名'], 'purpose': a['事業の目的'], 'overview': a['事業の概要'][:900], 'url': a['事業概要URL'],
                                              'outcomes': OrderedDict(), 'review': None, 'budget': [], 'src12': os.path.basename(rs_file(y, '1-2_'))[:-4],
                                              'src31': os.path.basename(rs_file(y, '3-1_'))[:-4], 'src41': os.path.basename(rs_file(y, '4-1_'))[:-4], 'src21': os.path.basename(rs_file(y, '2-1_'))[:-4]}
        for a in read_csv(rs_file(y, '3-1_')):
            p = proj.get((a['予算事業ID'], y))
            kind = a['種別（アクティビティ・アウトプット・アウトカム）']
            if not p or kind not in ('アウトカム', 'アウトプット'):
                continue
            k = (a['アクティビティ・アウトプット・アウトカムの番号'], kind, a['アクティビティ／活動目標／成果目標'], a['活動指標／成果指標'])
            o = p['outcomes'].setdefault(k, {'kind': kind, 'goal': a['アクティビティ／活動目標／成果目標'], 'ind': a['活動指標／成果指標'], 'unit': a['単位'],
                                             'type': a['成果目標の種類'], 'qual': a['定性的なアウトカムに関する成果実績'], 'data': a['成果実績及び目標値の根拠として用いた統計・データ名（出典）'],
                                             'target': {}, 'actual': {}})
            vals = {k2: v.strip() for k2, v in a.items() if k2 and k2.isdigit() and (v or '').strip()}
            r = a['目標年度／目標値／実績値／達成率']
            if r.startswith('2'): o['target'] = vals
            elif r.startswith('3'): o['actual'] = vals
        for a in read_csv(rs_file(y, '4-1_')):
            p = proj.get((a['予算事業ID'], y))
            if p and p['review'] is None:
                p['review'] = {'self_result': a['事業所管部局による点検・改善ー点検結果'], 'measure': a['事業所管部局による点検・改善－目標年度における効果測定に関する評価'],
                               'ext_opinion': a['外部有識者による点検ー所見'], 'team': a['行政事業レビュー推進チームの所見'], 'team_detail': a['行政事業レビュー推進チームの所見の詳細']}
        for a in read_csv(rs_file(y, '2-1_')):
            p = proj.get((a['予算事業ID'], y))
            if p and a['会計区分'] == '' and a['予算年度']:
                p['budget'].append({'year': a['予算年度'], 'initial': num(a['当初予算（合計）']), 'current': num(a['計（歳出予算現額合計）']), 'exec': num(a['執行額（合計）'])})
    for p in proj.values():
        p['outcomes'] = list(p['outcomes'].values())
        p['n_outcome'] = sum(o['kind'] == 'アウトカム' for o in p['outcomes'])
        p['n_outcome_actual'] = sum(o['kind'] == 'アウトカム' and bool(o['actual'] or o['qual']) for o in p['outcomes'])
        p['budget'].sort(key=lambda b: b['year'], reverse=True)
    # ---- 書き出し
    out_dir = os.path.join(ROOT, 'data', 'flow', slug)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    dump = lambda name, obj: json.dump(obj, open(os.path.join(out_dir, name + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    # 府省
    ministries = []
    by_m = defaultdict(list)
    for c in contracts:
        by_m[c['mn']].append(c)
    for mn, cs in by_m.items():
        code = ministry_code.get(mn, '0')
        cs.sort(key=lambda c: (-int(c['y']), -(c['amt'] or 0)))
        st = {y: {'n': sum(c['y'] == y for c in cs), 'sum': sum(c['amt'] for c in cs if c['y'] == y),
                  'n_s': sum(c['y'] == y and c['tier'] == 's' for c in cs), 'sum_s': sum(c['amt'] for c in cs if c['y'] == y and c['tier'] == 's')} for y in F['rs_years']}
        ministries.append({'code': code, 'name': mn, 'stats': st})
        dump('m_' + code, {'name': mn, 'code': code, 'contracts': cs, 'stats': st})
    ministries.sort(key=lambda m: -m['stats'][F['rs_years'][0]]['sum'])
    # 支出先
    payees = []
    by_k = defaultdict(list)
    for c in contracts:
        if c['k']:
            by_k[c['k']].append(c)
    oth_k = defaultdict(list)
    for o in others:
        if o['k'] in keys:
            oth_k[o['k']].append(o)
    for k, cs in by_k.items():
        cs.sort(key=lambda c: (-int(c['y']), -(c['amt'] or 0)))
        names = list(OrderedDict.fromkeys(c['py'] for c in cs))
        st = {y: {'n': sum(c['y'] == y for c in cs), 'sum': sum(c['amt'] for c in cs if c['y'] == y)} for y in F['rs_years']}
        ot_all = sorted(oth_k.get(k, []), key=lambda c: (-int(c['y']), -(c['amt'] or 0)))
        ot = sorted(ot_all, key=lambda c: -(c['amt'] or 0))[:150]
        ot.sort(key=lambda c: (-int(c['y']), -(c['amt'] or 0)))
        ot_stats = {y: {'n': sum(o['y'] == y and not o['grant'] for o in ot_all), 'sum': sum(o['amt'] for o in ot_all if o['y'] == y and not o['grant']),
                        'n_grant': sum(o['y'] == y and o['grant'] for o in ot_all), 'sum_grant': sum(o['amt'] for o in ot_all if o['y'] == y and o['grant'])} for y in F['rs_years']}
        payees.append({'k': k, 'name': names[0], 'names': names, 'corp': cs[0]['corp'] if re.fullmatch(r'\d{13}', cs[0]['corp']) else '',
                       'stats': st, 'n_other': sum(not o['grant'] for o in ot_all), 'n_grant': sum(o['grant'] for o in ot_all)})
        dump('s_' + k, {'k': k, 'name': names[0], 'names': names, 'corp': payees[-1]['corp'], 'contracts': cs, 'others': ot,
                        'others_total': len(ot_all), 'others_stats': ot_stats, 'stats': st})
    y0 = F['rs_years'][0]
    payees.sort(key=lambda p: -(p['stats'][y0]['sum'] + p['stats'][F['rs_years'][1]]['sum'] * 0.001))
    # 事業
    projects = []
    by_p = defaultdict(list)
    for c in contracts:
        by_p[c['pid']].append(c)
    for pid, cs in by_p.items():
        sheets = [proj[(pid, y)] for y in F['rs_years'] if (pid, y) in proj]
        if not sheets:
            continue
        cs.sort(key=lambda c: (-int(c['y']), -(c['amt'] or 0)))
        dump('p_' + pid, {'id': pid, 'sheets': sheets, 'contracts': cs})
        s0 = sheets[0]
        projects.append({'id': pid, 'name': s0['name'], 'mn': s0['mn'], 'n': len(cs), 'sum0': sum(c['amt'] for c in cs if c['y'] == y0),
                         'n_outcome': s0['n_outcome'], 'n_outcome_actual': s0['n_outcome_actual']})
    projects.sort(key=lambda p: -p['sum0'])
    summary = {}
    for y in F['rs_years']:
        cy = [c for c in contracts if c['y'] == y]
        summary[y] = {'exec_year': F['exec_year'][y], 'n': len(cy), 'sum': sum(c['amt'] for c in cy),
                      'n_s': sum(c['tier'] == 's' for c in cy), 'sum_s': sum(c['amt'] for c in cy if c['tier'] == 's'),
                      'payees': len({c['k'] or ('n:' + c['py']) for c in cy}), 'payees_corp': len({c['k'] for c in cy if c['k']}), 'projects': len({c['pid'] for c in cy}), 'ministries': len({c['mn'] for c in cy})}
    methods = defaultdict(lambda: {'n': 0, 'sum': 0.0})
    for c in contracts:
        if c['y'] == y0:
            m = methods[c['mt'] or '（記載なし）']; m['n'] += 1; m['sum'] += c['amt']
    top = sorted([c for c in contracts if c['y'] == y0], key=lambda c: -c['amt'])[:30]
    main_ = {'type': 'contracts', 'field': {k: F[k] for k in ('slug', 'name', 'title', 'lead')}, 'words_label': F['words_label'], 'range_note': F['range_note'],
             'generated_at': TODAY, 'fetched': FETCHED, 'years': F['rs_years'], 'exec_year': F['exec_year'], 'summary': summary,
             'methods': sorted([{'name': k, **v} for k, v in methods.items()], key=lambda m: -m['n']),
             'ministries': ministries, 'payees': payees, 'projects': projects, 'top': top, 'trackers': F['trackers'],
             'sources': {y: {p: os.path.basename(rs_file(y, p))[:-4] for p in ('1-2_', '2-1_', '3-1_', '4-1_', '5-1_')} for y in F['rs_years']}}
    json.dump(main_, open(os.path.join(ROOT, 'data', 'flow', slug + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    # 分野の一覧（index.json）を更新
    ip = os.path.join(ROOT, 'data', 'flow', 'index.json')
    ix = json.load(open(ip, encoding='utf-8')) if os.path.exists(ip) else {'fields': []}
    ix['fields'] = [f for f in ix['fields'] if f['slug'] != slug]
    s0 = summary[y0]
    ix['fields'].append({'slug': slug, 'type': 'contracts', 'name': F['name'], 'title': F['title'], 'lead': F['lead'], 'generated_at': TODAY,
                         'summary': {'contracts': s0['n'], 'sum': s0['sum'], 'payees': s0['payees'], 'projects': s0['projects'], 'exec_year': s0['exec_year']},
                         'trackers': F['trackers'],
                         'card_line2': '契約先と金額、成果はどうだったか。',
                         'card_sub1': f"{s0['exec_year']}年度の広報等の契約 {s0['n']:,}件・{s0['sum']/1e8:,.1f}億円・契約先 {s0['payees']:,}",
                         'card_sub2': '行政事業レビューの支出先の記載から、府省ごとに。'})
    json.dump(ix, open(ip, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print('ministries', len(ministries), 'payees', len(payees), 'projects', len(projects), 'files', len(os.listdir(out_dir)))
    print('size main', os.path.getsize(os.path.join(ROOT, 'data', 'flow', slug + '.json')))
    if '--copy' in sys.argv:
        dst = os.path.join(XB4G_DATA, 'flow')
        shutil.copy(os.path.join(ROOT, 'data', 'flow', slug + '.json'), dst)
        shutil.copy(ip, dst)
        if os.path.isdir(os.path.join(dst, slug)):
            shutil.rmtree(os.path.join(dst, slug))
        shutil.copytree(out_dir, os.path.join(dst, slug))
        print('copied to', dst)

if __name__ == '__main__':
    main()
