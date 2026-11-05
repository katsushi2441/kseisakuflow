#!/usr/bin/python3
"""raw/cao/ に保存した内閣府の公表資料から data/councils.json を作る。
fetch_cao.py で原資料を取得してから実行する。推測で埋めず、取れないものは "未取得"。"""
import os, re, json, subprocess, unicodedata, html, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
RAW = os.path.join(PROJ, 'raw', 'cao')
B = 'https://www8.cao.go.jp/cstp/ai/'
NA = '未取得'

def lp(url):
    p = url.split('://', 1)[1]
    return os.path.join(RAW, p)

def norm(s):  # PDF抽出で出る康熙部首・CJK部首補助の字形だけ通常の漢字に戻す
    return ''.join(unicodedata.normalize('NFKC', c) if 0x2E80 <= ord(c) <= 0x2FDF
                   else unicodedata.normalize('NFC', c) if 0xF900 <= ord(c) <= 0xFAFF else c for c in s)

def pdftext(url, mode='-layout', first=None, last=None):
    cmd = ['pdftotext', mode]
    if first: cmd += ['-f', str(first), '-l', str(last or first)]
    cmd += [lp(url), '-']
    return norm(subprocess.run(cmd, capture_output=True, text=True).stdout)

def npages(url):
    out = subprocess.run(['pdfinfo', lp(url)], capture_output=True, text=True).stdout
    return int(re.search(r'Pages:\s+(\d+)', out).group(1))

def page_joined(url, p):
    return re.sub(r'\n', '', pdftext(url, '-raw', p).replace('\f', ''))

def htmltext(url):
    t = open(lp(url), 'rb').read().decode('utf-8', 'replace')
    t = re.sub(r'(?s)<(script|style|head).*?</\1>', '', t)
    t = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>', r' [[\1]] ', t)
    t = re.sub(r'<[^>]+>', '\n', t)
    t = norm(html.unescape(t))
    return [l.strip() for l in t.split('\n') if l.strip()]

Z2H = str.maketrans('０１２３４５６７８９', '0123456789')
def wareki(s):
    s = s.translate(Z2H)
    m = re.search(r'(令和|平成)\s*(\d+|元)\s*年\s*(\d+)\s*月\s*(\d+)\s*日', s)
    if not m: return NA
    y = 1 if m.group(2) == '元' else int(m.group(2))
    y += 2018 if m.group(1) == '令和' else 1988
    return '%04d-%02d-%02d' % (y, int(m.group(3)), int(m.group(4)))

def absurl(base, h):
    from urllib.parse import urljoin
    return urljoin(base, h)

# ---------- 開催回 ----------
def parse_meeting_page(url):
    L = htmltext(url)
    date = NA; agenda = []; mats = []; title = NA; place = NA
    # タイトル: 「日時」の直前の行
    if '日時' in L:
        i = L.index('日時'); title = L[i - 1]
        date = wareki(L[i + 1]); datetime_raw = L[i + 1]
    if '場所' in L:
        place = L[L.index('場所') + 1]
    if '議事' in L:
        i = L.index('議事') + 1
        while i < len(L) and L[i] not in ('資料', '配布資料'):
            agenda.append(L[i]); i += 1
    start = None
    for k in ('資料', '配布資料'):
        if k in L: start = L.index(k) + 1; break
    if start:
        label = None
        for l in L[start:]:
            if l.startswith('このページの先頭へ') or l.startswith('[[#container'): break
            m = re.match(r'\[\[(.+?)\]\]\s*(.*)', l)
            if m:
                mats.append({'label': label, 'title': m.group(2).strip(), 'url': absurl(url, m.group(1))})
            elif re.match(r'^(資料|参考資料|参考|関連リンク|（会議後確定版）)', l):
                label = l
            else:
                mats.append({'label': label, 'title': l, 'url': None, 'note': 'リンクなし（ページの表記のまま）'})
    return {'title': title, 'date': date, 'datetime_raw': datetime_raw if date != NA else NA,
            'place': place, 'agenda': agenda, 'materials': mats}

def index_rows(url, linkword):
    """開催状況の表から (回, 日付, [リンク]) を取る"""
    L = htmltext(url); rows = []; cur = None
    for l in L:
        m = re.match(r'^第\s*(\d+)\s*回$', l.translate(Z2H))
        if m:
            cur = {'no': int(m.group(1)), 'date_raw': None, 'links': [], 'notes': []}; rows.append(cur); continue
        if cur is None: continue
        if cur['date_raw'] is None and ('令和' in l):
            cur['date_raw'] = l; continue
        mm = re.match(r'\[\[(.+?)\]\]\s*(.*)', l)
        if mm: cur['links'].append((absurl(url, mm.group(1)), mm.group(2)))
        elif l in ('（持ち回り開催）', '非公開', '準備中', '（準備中）'): cur['notes'].append(l)
    return rows

def meetings_for(index_url, extra=None):
    out = []
    for r in sorted(index_rows(index_url, None), key=lambda x: x['no']):
        page = next((u for u, t in r['links'] if u.endswith('.html')), None)
        mins = next((u for u, t in r['links'] if u.endswith('.pdf')), None)
        mt = next((t for u, t in r['links'] if u.endswith('.pdf')), None)
        d = {'no': r['no'], 'date': wareki(r['date_raw'] or ''), 'agenda': NA, 'url': page or NA,
             'minutes_url': mins or NA}
        if mt: d['minutes_title'] = re.sub(r'（PDF.*', '', mt)
        if r['notes']: d['index_note'] = '・'.join(r['notes'])
        if page and os.path.exists(lp(page)):
            pm = parse_meeting_page(page)
            d['agenda'] = pm['agenda'] or NA
            if pm['date'] != NA and pm['date'] != d['date']:
                d['date_on_meeting_page'] = pm['date']
            d['datetime_raw'] = pm['datetime_raw']; d['place'] = pm['place']; d['page_title'] = pm['title']
            d['materials'] = pm['materials']
        out.append(d)
    return out

# ---------- 名簿 ----------
ORGS = [
 '東京大学未来ビジョン研究センター', '東京大学国際高等研究所東京カレッジ', '東京大学大学院法学政治学研究科', '東京大学大学院工学系研究科', '東京大学',
 '森・濱田松本法律事務所外国法共同事業', '森・濱田松本法律事務所', '株式会社ソニーリサーチ', 'ソニーグループ株式会社', '株式会社コルク',
 'さくらインターネット株式会社', '国際大学', '独立行政法人情報処理推進機構', '一橋大学', '一般社団法人日本ディープラーニング協会',
 '日本ディープラーニング協会', '一般社団法人ソフトウェア協会', '株式会社リアルソリューションズ', '公益社団法人全国消費生活相談員協会',
 '大阪大学', '長島・大野・常松法律事務所', '富士通株式会社', '一般社団法人日本経済団体連合会', '日本電気株式会社', '東北大学',
 '中央大学', '西村あさひ法律事務所・外国法共同事業', '日本電信電話株式会社', 'Sakana AI 株式会社', 'Sakana AI', '株式会社ABEJA',
 '株式会社安川電機', 'Rapidus 株式会社', '東京エレクトロン株式会社', '株式会社シナモン', 'SOMPO ホールディングス株式会社',
 '博報堂ＤＹホールディングス', '東京科学大学',
]
ORG_CANON = {  # 学部・研究科等を除いた組織名
 '東京大学未来ビジョン研究センター': '東京大学', '東京大学国際高等研究所東京カレッジ': '東京大学',
 '東京大学大学院法学政治学研究科': '東京大学', '東京大学大学院工学系研究科': '東京大学',
}
def orgs_of(aff):
    a = aff.replace('株式会社 ABEJA', '株式会社ABEJA')
    hits = []
    for o in ORGS:
        i = a.find(o)
        if i >= 0 and not any(i >= j and i + len(o) <= j + len(p) for j, p in hits):
            hits.append((i, o))
    res = []
    for i, o in sorted(hits):
        c = ORG_CANON.get(o, o)
        if c not in res: res.append(c)
    if 'GPAI 東京専門家支援センター' in a or '（GPAI）東京専門家支援' in a:
        res.append('GPAI東京専門家支援センター')
    return res

def join_lines(lines):
    s = ''
    for l in lines:
        l = re.sub(r'[ 　]+', ' ', l.strip())
        if not l: continue
        if s and re.search(r'[A-Za-z]$', s) and re.match(r'[A-Za-z]', l): s += ' ' + l
        else: s += l
    return s

def parse_roster(url, names, mode='-layout', page=None, stop=r'^(参考資料|資料|（政府側参加者）|＜目的＞|※|３．|以上$)'):
    """names: 名簿に出る順の氏名（PDFの字面の空白を含む）。氏名の行から次の氏名の行までを所属とする。"""
    txt = pdftext(url, mode, page, page) if page else pdftext(url, mode)
    L = [re.sub(r'[ 　]+', ' ', l).strip() for l in txt.replace('\f', '\n').split('\n')]
    L = [l for l in L if l]
    out = []
    for k, n in enumerate(names):
        pat = re.compile(r'^(?:○ |構 ?成 ?員 )?((?:座 ?長代理|座 ?長) )?' + re.escape(n) + r'(?: |$)')
        idx = next((i for i, l in enumerate(L) if pat.match(l)), None)
        if idx is None: raise SystemExit("名簿に氏名が見つからない: %s %s" % (n, url))
        m = pat.match(L[idx]); role = (m.group(1) or '').replace(' ', '')
        body = [L[idx][m.end():]]
        j = idx + 1
        nxt = re.compile(r'^(?:○ |構 ?成 ?員 )?((?:座 ?長代理|座 ?長) )?' + re.escape(names[k + 1]) + r'(?: |$)') if k + 1 < len(names) else None
        while j < len(L) and not (nxt and nxt.match(L[j])) and not re.match(stop, L[j]) and not re.match(r'^\d+$', L[j]):
            body.append(L[j]); j += 1
        aff = join_lines(body)
        if '【座長】' in aff:
            aff = aff.replace('【座長】', '').strip(); role = role or '座長'
        aff = re.sub(r' (?=・)|(?<=・) ', '', aff)  # 改行で割れた「品質 ・ エンジニアリング」を戻す
        os_ = orgs_of(aff)
        d = {'name': n, 'affiliation': aff, 'role': role or None, 'org': os_[0] if os_ else NA}
        if len(os_) > 1: d['orgs'] = os_
        out.append(d)
    return out

SEN = ['江間有沙', '岡田 淳', '川原圭博', '北野宏明', '佐渡島庸平', '田中邦裕', '松尾 豊', '山口真一']
KEN = ['松尾 豊', '村上 明子', '生貝 直人', '岡田隆太朗', '岡本浩一郎', '柿沼 由佳', '工藤 郁子', '殿村 桂司', '中尾 悠里',
       '永沼 美保', '原山 優子', '平野 晋', '福岡真之介', '松原実穂子']
EXP = ['生貝直人', '伊藤 錬', '江間有沙', '岡田 淳', '岡田陽介', '川原圭博', '北野宏明', '佐渡島庸平', '田中邦裕', '永沼美保',
       '原山優子', '福岡真之介', '松尾 豊', '村上明子', '森 正弥', '山口真一']
SEMI = ['伊藤 錬', '岡田 陽介', '久保田 由美恵', '小池 淳義', '瀬川 澄江', '時田 隆仁', '平野 未来', '松尾 豊', '村上 明子', '吉田 憲一郎']
SEIDO = ['宍戸 常寿', '生貝 直人', '岡崎 直観', '岡田 淳', '岡田 陽介', '殿村 桂司', '永沼 美保']

def roster(url, names, title, as_of, used_at, note=None, **kw):
    r = {'as_of': as_of, 'source_title': title, 'source_url': url, 'used_at_meetings': used_at,
         'members': parse_roster(url, names, **kw)}
    r['as_of_basis'] = '名簿PDFに日付の記載なし。この版が最初に配付された会議の開催日' if note is None else note
    return r

# ---------- 提言の引用 ----------
def quote(url, page, text, printed=None):
    pj = page_joined(url, page)
    if text not in pj:
        raise SystemExit('引用が原文に見つからない: %s p%d %s' % (url, page, text[:40]))
    q = {'text': text, 'page': page}
    if printed is not None: q['printed_page'] = printed
    return q

def main():
    S = B + 'ai_senryaku/'
    councils = []
    # ===== AI戦略会議 =====
    sen = {'id': 'ai-senryaku', 'name': 'ＡＩ戦略会議',
      'name_note': '内閣府AI戦略トップの一覧表記は「AI戦略会議（イノベーション政策強化推進のための有識者会議）」。第10回資料では「イノベーション政策強化推進のための有識者会議「ＡＩ戦略」（ＡＩ戦略会議）」',
      'basis': {'summary': '「イノベーション政策強化推進のための有識者会議」の枠組み（平成30年7月27日統合イノベーション戦略推進会議決定。有識者会議は課題毎に設置し、課題・構成員は統合イノベーション戦略推進会議議長が決定）。ＡＩ戦略会議そのものの開催決定文書（令和5年）は公表資料では未取得',
                'documents': [
                  {'title': '「イノベーション政策強化推進のための有識者会議」の設置について（平成30年7月27日統合イノベーション戦略推進会議決定）', 'url': B + 'senryaku/1kai/sanko1.pdf', 'note': '前身のAI戦略実行会議 第1回の参考資料1として掲載されたもの'},
                  {'title': '「ＡＩ制度研究会」の設置について（案）（第10回資料1）', 'url': S + '10kai/shiryo1.pdf', 'text': '「統合イノベーション戦略 2024」(2024 年 6 月 4 日閣議決定)に基づき、イノベーション政策強化推進のための有識者会議「ＡＩ戦略」（ＡＩ戦略会議）の下、'}],
                'own_founding_document': NA},
      'url': S + 'ai_senryaku.html'}
    sen['rosters'] = [
      roster(S + '1kai/shiryo1.pdf', SEN, 'ＡＩ戦略会議 構成員名簿（第1回 資料1）', '2023-05-11', [1, 2, 3, 4, 5],
             note='名簿PDFに日付の記載なし。第1回（2023-05-11）配付。第2回参考資料1・第3〜5回参考資料も構成員欄は同一（第2回版は政府側参加者の欄のみ異なる）'),
      roster(S + '6kai/kouseiin.pdf', SEN, 'AI戦略会議 構成員名簿（第6回 参考資料1）', '2023-11-07', [6, 7, 8, 9]),
      roster(S + '10kai/sanko.pdf', SEN, 'AI戦略会議 構成員名簿（第10回 参考資料）', '2024-07-19', [10, 11, 12, 13],
             note='名簿PDFに日付の記載なし。第10回（2024-07-19 持ち回り）配付。中間とりまとめ（2025-02-04）巻末の名簿も同じ表記'),
      roster(S + '14kai/sankou.pdf', SEN, 'AI戦略会議 構成員名簿（第14回 参考資料）', '2025-06-02', [14]),
    ]
    sen['rosters'][0]['government_participants_note'] = '第1回名簿には「（政府側参加者）」欄（内閣総理大臣ほか）があるが、構成員ではないため members に入れていない'
    sen['meetings'] = meetings_for(S + 'ai_senryaku.html')
    for m in sen['meetings']:
        if m['no'] in (11, 12, 13): m['joint_with'] = 'ai-seido-kenkyukai'
    sen['outputs'] = [
      {'title': 'AIに関する暫定的な論点整理', 'date': '2023-05-26', 'url': B + 'ronten_honbun.pdf',
       'also_at': [S + '2kai/ronten.pdf'], 'issuer': 'AI戦略会議',
       'quotes': [
         quote(B + 'ronten_honbun.pdf', 15, '政府が AI の開発支援を行う際は、AI 開発におけるインフラとも言うべき、計算資源とデータの整備・拡充を行うことが最も重要である。'),
         quote(B + 'ronten_honbun.pdf', 15, '足下では、国内の開発需要に比して、計算資源の供給量は圧倒的に不足している。'),
         quote(B + 'ronten_honbun.pdf', 15, '諸外国に劣後しないためには、政府が十分に計算資源に対する支援を行うべきである。'),
         quote(B + 'ronten_honbun.pdf', 15, '世界で計算資源の獲得競争が生じており、政府も関与しつつ、可及的速やかに計算資源の整備・拡充が必要である。'),
         quote(B + 'ronten_honbun.pdf', 15, 'このため、いま生成 AI によって世界の変革がもたらされようとしている中、可及的速やかに生成 AIに関する基盤的な研究力・開発力を国内に醸成することが重要である。'),
         quote(B + 'ronten_honbun.pdf', 16, 'また、技術の公開を通じて新たな技術革新が生み出される可能性を踏まえ、計算資源やデータのほか、オープンに利用可能な基盤技術等を提供する環境を整備し、世界からトップ人材が集まり切磋琢磨できる研究・人材育成環境の構築や産学官の基盤開発力の強化を進めていくことが期待される。'),
       ],
       'quotes_note': '「GENIAC」「予算」の語は本文に出現しない（全文検索）'},
      {'title': '「AI制度に関する考え方」について', 'date': '2024-05-22', 'url': S + '9kai/shiryo2-1.pdf', 'issuer': 'AI戦略会議（第9回 資料2-1）',
       'quotes': [], 'quotes_note': '予算・研究開発支援・計算資源整備・基盤モデル開発支援に触れた箇所は確認できなかった（「基盤モデル」は米国大統領令の報告義務対象・高リスクAIの例としてのみ出現）'},
      {'title': 'AI戦略会議・AI制度研究会 中間とりまとめ', 'date': '2025-02-04', 'url': B + 'interim_report.pdf',
       'also_at': [B + 'interim_report_gaiyo.pdf'], 'issuer': 'AI戦略会議・AI制度研究会',
       'quotes': [
         quote(B + 'interim_report.pdf', 8, 'AI の研究開発には大量の学習データやこれを取り扱うことのできる大規模な情報処理、情報通信、データ保管等の施設や設備が必要となる。', printed=6),
         quote(B + 'interim_report.pdf', 8, 'スタートアップ企業を含め、多様な主体がこのような施設や設備を活用することによりイノベーション促進が図られるようにする観点から、政府による整備を進めることが重要である。', printed=6),
         quote(B + 'interim_report.pdf', 9, '政府等では、既に質の高い日本語データ等を整備・拡充し我が国企業等に適切な形で提供する取組を行うとともに、データセンターの整備や、電力の確保に向けた検討のほか、AI 半導体の支援を進めている。', printed=7),
         quote(B + 'interim_report.pdf', 9, '引き続き、様々な側面から研究開発支援を実施すべきである。', printed=7),
       ],
       'quotes_note': '「GENIAC」「予算」の語は本文に出現しない（全文検索）'},
    ]
    # ===== AI制度研究会 =====
    K = B + 'ai_kenkyu/'
    ken = {'id': 'ai-seido-kenkyukai', 'name': 'ＡＩ制度研究会', 'parent': 'ai-senryaku',
      'basis': {'summary': '「ＡＩ制度研究会」の設置について（ＡＩ戦略会議決定。第10回ＡＩ戦略会議〔2024-07-19 持ち回り〕資料1は「（案）令和６年７月〇〇日」の表記）',
                'documents': [{'title': '「ＡＩ制度研究会」の設置について（案）', 'url': S + '10kai/shiryo1.pdf'}]},
      'url': K + 'ai_kenkyu.html'}
    ken['rosters'] = [
      roster(S + '10kai/shiryo1.pdf', KEN, '「ＡＩ制度研究会」の設置について（案）別紙「ＡＩ制度研究会」座長、座長代理及び構成員について（第10回ＡＩ戦略会議 資料1）', '2024-07-19', [],
             note='設置文書（案）の別紙。第10回ＡＩ戦略会議（2024-07-19 持ち回り）資料'),
      roster(S + '11kai/sanko2.pdf', KEN, 'ＡＩ制度研究会 構成員名簿（ＡＩ戦略会議第11回・ＡＩ制度研究会第1回 参考資料2）', '2024-08-02', [1, 2]),
      roster(K + '3kai/sankou.pdf', KEN, 'AI制度研究会 構成員名簿（第3回 参考資料）', '2024-09-10', [3, 4]),
      roster(K + '5kai/sankou1.pdf', KEN, 'ＡＩ制度研究会 構成員名簿（第5回 参考資料1）', '2024-12-26', [5, 6]),
      roster(S + '13kai/sankou2.pdf', KEN, 'ＡＩ制度研究会 構成員名簿（ＡＩ戦略会議第13回・ＡＩ制度研究会第7回 参考資料2）', '2025-02-04', [7]),
    ]
    ken['rosters_note'] = '構成員の顔ぶれは全版で同じ。版の違いは表記（村上明子氏の「セーフティー」/「セーフティ」、中尾悠里氏の役職）'
    km = meetings_for(K + 'ai_kenkyu.html')
    for m in km:
        if m['no'] in (1, 6, 7):
            m['joint_with'] = 'ai-senryaku'
            m['joint_note'] = {1: 'ＡＩ戦略会議（第11回）と合同開催', 6: 'ＡＩ戦略会議（第12回）と合同開催', 7: 'ＡＩ戦略会議（第13回）と合同開催'}[m['no']]
    ken['meetings'] = km
    ken['outputs'] = [{'title': 'AI戦略会議・AI制度研究会 中間とりまとめ', 'date': '2025-02-04', 'url': B + 'interim_report.pdf',
                       'same_as': 'ai-senryaku の outputs を参照（引用も同じ）', 'quotes': sen['outputs'][2]['quotes']}]
    # ===== 人工知能戦略本部 =====
    H = B + 'ai_hq/'
    hq = {'id': 'ai-hq', 'name': '人工知能戦略本部',
      'basis': {'summary': '人工知能関連技術の研究開発及び活用の推進に関する法律（令和七年法律第五十三号。ＡＩ法）第十九条（内閣に置く）',
                'documents': [{'title': 'ＡＩ法（e-Gov法令API）', 'url': 'https://laws.e-gov.go.jp/api/1/lawdata/507AC0000000053',
                               'text': '人工知能関連技術の研究開発及び活用の推進に関する施策を総合的かつ計画的に推進するため、内閣に、人工知能戦略本部（以下「本部」という。）を置く。', 'article': '第十九条'},
                              {'title': '設置根拠：AI法（内閣府ページ）', 'url': H + 'konkyo.html'}]},
      'url': H + 'ai_hq.html'}
    hl = htmltext(H + 'ai_hq.html')
    i = hl.index('人工知能戦略本部　構成員')
    hq_members = []
    for role, line in (('本部長', hl[i + 2]), ('副本部長', hl[i + 4]), ('副本部長', hl[i + 5])):
        nm, title = line.rsplit('　', 1)
        hq_members.append({'name': nm, 'affiliation': title, 'role': role, 'org': None})
    hq_members.append({'name': None, 'affiliation': hl[i + 7], 'role': hl[i + 6], 'org': None})
    hq['rosters'] = [{'as_of': NA, 'as_of_basis': 'ページに日付の記載なし（2026-11-05 取得時点の掲載内容）', 'source_title': '人工知能戦略本部　構成員（内閣府ページ）',
                      'source_url': H + 'ai_hq.html', 'members': hq_members,
                      'note': '本部は国務大臣で構成（ＡＩ法第二十一〜二十四条）。org は組織名に当たらないため null'}]
    hq['meetings'] = meetings_for(H + 'kaisai.html')
    hq['outputs'] = [
      {'title': '人工知能基本計画', 'date': '2025-12-23', 'date_note': '閣議決定（本部第3回〔2025-12-19〕で案を審議）', 'url': B + 'ai_plan/aiplan_20251223.pdf',
       'quotes': [
         quote(B + 'ai_plan/aiplan_20251223.pdf', 9, '我が国が独自にＡＩを研究開発し、自律的な運用もできる能力を強化するため、データやデータセンター、基盤モデル、アプリを含むＡＩエコシステムについて、エコシステム全体を俯瞰しつつ戦略的かつ統合的に日本国内で構築する。'),
         quote(B + 'ai_plan/aiplan_20251223.pdf', 9, 'ＡＩ研究開発の強化及び利活用基盤の増強・確保のため、十分な計算資源とその基盤となる半導体の開発及び供給、データセンター及びクラウド環境の整備、それらを支える通信ネットワークの構築、安定的な電力供給体制の確保等、ＡＩインフラの戦略的な整備を加速する。'),
         quote(B + 'ai_plan/aiplan_20251223.pdf', 11, '③ エネルギー効率を重視したＡＩエコシステムの実現に向けた基盤モデル開発を推進する。'),
         quote(B + 'ai_plan/aiplan_20251223.pdf', 11, '① データセンターの整備、ＡＩの研究開発に必要な計算資源の確保、効率的な電力・通信インフラの整備（ワット・ビット連携）、オール光ネットワークの導入及び次世代情報通信基盤（Beyond 5G）の研究開発を推進する。'),
       ], 'quotes_note': '「GENIAC」の語は本文に出現しない（全文検索）'},
      {'title': '人工知能関連技術の研究開発及び活用の適正性確保に関する指針', 'date': '2025-12-19', 'date_note': '本部決定', 'url': B + 'ai_guideline/ai_gl_2025.pdf',
       'quotes': [], 'quotes_note': '予算・計算資源・基盤モデル開発支援に触れた箇所は確認できなかった（適正性確保の指針）'},
      {'title': 'バーティカルＡＩ領域別戦略 中間とりまとめ', 'date': '2026-07-10', 'date_note': '本部第5回の資料2-2', 'url': H + '5kai/shiryo2_2.pdf',
       'quotes': [
         quote(H + '5kai/shiryo2_2.pdf', 4, '・ 重点支援領域ごとに戦略的に、人材、データを含めたＡＩ基盤への官民投資を促進する。'),
         quote(H + '5kai/shiryo2_2.pdf', 51, '官民協働による「富岳」の次世代フラッグシップシステムの着実な開発・整備や、国内の大学・研究機関等における共用計算資源の段階的増強を通じて、2030 年度までに共用計算資源を 10 倍以上に増強することを目指す。'),
       ]},
      {'title': '人工知能基本計画（第Ⅱ期）', 'date': '2026-07-14', 'date_note': '閣議決定（本部第5回〔2026-07-10〕で案を審議）', 'url': B + 'ai_plan/aiplan_20260714.pdf',
       'quotes': [
         quote(B + 'ai_plan/aiplan_20260714.pdf', 11, 'ＡＩエコシステムが持続可能な形で発展できるよう、官民が連携して、経済安全保障施策や中小企業施策、特定生産性向上設備等投資促進税制や研究開発税制等も活用し、民間投資を積極的に呼び込みながら、研究開発や、インフラ整備等に戦略的・集中的に投資する。'),
         quote(B + 'ai_plan/aiplan_20260714.pdf', 12, 'なお、バーティカルＡＩ、フィジカルＡＩ（特にＡＩロボット）、フィジカル・インテリジェント・システムの中核を担う半導体に係る官民投資額は、2040 年度まででそれぞれ23.1 兆円、10.5 兆円、68.0 兆円を想定。'),
         quote(B + 'ai_plan/aiplan_20260714.pdf', 12, 'ロボット基盤モデルの開発能力を強化するため、フィジカルＡＩ基盤モデルを国内で開発する。'),
         quote(B + 'ai_plan/aiplan_20260714.pdf', 14, '③ 日本の強みである現場のデータを活用し、またエネルギー効率に優れたフィジカルＡＩを世界に先駆けて実装しＧＸを実現するべく、その開発基盤となるマルチモーダル基盤モデルの開発を推進する。'),
       ], 'quotes_note': '「GENIAC」の語は本文に出現しない（全文検索）'},
    ]
    # ===== 人工知能戦略専門調査会 =====
    E = B + 'ai_expert_panel/'
    exp = {'id': 'ai-expert-panel', 'name': '人工知能戦略専門調査会', 'parent': 'ai-hq',
      'basis': {'summary': '人工知能戦略本部令（令和七年政令第二百八十一号）第一条、及び「人工知能戦略専門調査会の設置について」（令和７年９月12日人工知能戦略本部決定）',
                'documents': [
                  {'title': '人工知能戦略本部令（e-Gov法令API）', 'url': 'https://laws.e-gov.go.jp/api/1/lawdata/507CO0000000281', 'article': '第一条',
                   'text': '人工知能戦略本部（次条において「本部」という。）は、専門の事項を調査させるため必要があるときは、その議決により、専門調査会を置くことができる。'},
                  {'title': '人工知能戦略専門調査会の設置について（設置紙）', 'url': E + '1kai/ai_ep_settigami.pdf'},
                  {'title': '人工知能戦略専門調査会の設置について（第1回 資料1-1）', 'url': E + '1kai/shiryo1_1.pdf'}]},
      'url': E + 'ai_expert_panel.html'}
    exp['rosters'] = [roster(E + '1kai/shiryo1_2.pdf', EXP, '人工知能戦略専門調査会 委員名簿（第1回 資料1-2）', '2025-09-19', [1],
                             note='名簿PDFに日付の記載なし。第1回（2025-09-19）配付。以後の回に名簿の再配付はない（各回の議事概要の出席者欄では所属表記が変わっている委員がいるが、名簿としては公表されていない）')]
    exp['meetings'] = meetings_for(E + 'ai_expert_panel.html')
    exp['outputs'] = []
    exp['outputs_note'] = '専門調査会名義の提言・取りまとめは公表資料では確認できなかった。人工知能基本計画・指針・バーティカルＡＩ領域別戦略の案は専門調査会で審議されたうえで本部が決定（ai-hq の outputs を参照）'
    # ===== 制度の在り方検討WG =====
    W = B + 'ai_expert_wg/'
    wg = {'id': 'ai-expert-wg-seido', 'name': '制度の在り方検討ワーキンググループ', 'parent': 'ai-expert-panel',
      'basis': {'summary': '人工知能戦略専門調査会の下に設置（第1回 資料1）。「人工知能戦略専門調査会の設置について」第5項（専門調査会はワーキンググループを置くことができる）。WG固有の設置決定文書は公表資料では未取得',
                'documents': [{'title': '本ワーキンググループ開催に係る背景と目的（第1回 資料1）', 'url': W + 'seido_1kai/shiryo1.pdf',
                               'text': '既存のAIに関する法制度の見直しを含め、制度の在り方を議論・検討することを目的として、「制度の在り方検討WG」を人工知能戦略専門調査会※の下に設置する。', 'page': 6}]},
      'url': W + 'ai_expert_wg.html'}
    wg['rosters'] = [roster(W + 'seido_1kai/shiryo1.pdf', SEIDO, '本ワーキンググループ開催に係る背景と目的（第1回 資料1）＜構成員＞', '2026-10-28', [1], page=6,
                            note='資料1の6ページ（スライド番号4）に「＜構成員＞※敬称略」として掲載。日付は第1回開催日')]
    wg['meetings'] = meetings_for(W + 'ai_expert_wg.html')
    for m in wg['meetings']:
        if m['no'] == 1:
            t = pdftext(W + 'seido_1kai/shiryo1.pdf', '-raw', 2)
            m['agenda'] = [l.strip() for l in t.split('\n') if re.match(r'^\d\. ', l.strip())]
            m['agenda_source'] = W + 'seido_1kai/shiryo1.pdf（2ページ「次 第」。会議ページに議事欄が無いため）'
    wg['outputs'] = []
    # ===== AI・半導体WG =====
    SW = B + 'ai-semi_wg/'
    semi = {'id': 'ai-semi-wg', 'name': 'ＡＩ・半導体ワーキンググループ',
      'basis': {'summary': '「ＡＩ・半導体ワーキンググループの開催について」（令和８年２月１２日 内閣府特命担当大臣・経済産業大臣申合せ）。日本成長戦略会議におけるＡＩ・半導体分野の検討のため開催',
                'documents': [{'title': 'ＡＩ・半導体ワーキンググループの開催について（第1回 資料2）', 'url': SW + '1kai/shiryo2.pdf'},
                              {'title': '「ＡＩ・半導体ワーキンググループの開催について」の一部改正について（第2回 参考。令和８年４月１４日施行）', 'url': SW + '2kai/sanko.pdf'}]},
      'url': SW + 'ai-semi_wg.html'}
    semi['rosters'] = [roster(SW + '1kai/shiryo2.pdf', SEMI, 'ＡＩ・半導体ワーキンググループの開催について（第1回 資料2）２．構成員', '2026-02-12', [1, 2],
                              note='開催文書（令和８年２月１２日申合せ）の構成員欄。共同座長・座長代理は大臣・副大臣・政務官の職名のみのため members に入れていない')]
    semi['rosters'][0]['amendments'] = [{'date': '2026-04-14', 'url': SW + '2kai/sanko.pdf', 'text': '吉田 憲一郎 ソニーグループ株式会社代表執行役会長 → 吉田 憲一郎 ソニーグループ株式会社会長'}]
    semi['meetings'] = meetings_for(SW + 'ai-semi_wg.html')
    for m in semi['meetings']:
        if m['agenda'] == NA:
            src = {1: SW + '1kai/shiryo1.pdf', 2: SW + '2kai/siryo1.pdf'}[m['no']]
            t = pdftext(src, '-raw')
            body = t.split('〔配付資料〕')[0]
            items = [l.strip() for l in body.split('\n') if re.match(r'^[１-９0-9]．|^（[０-９0-9１-９]+）', l.strip())]
            m['agenda'] = items; m['agenda_source'] = src + '（議事次第。会議ページに議事欄が無いため）'
    semi['outputs'] = []
    semi['outputs_note'] = '第2回資料3「ＡＩ・半導体官民投資ロードマップ（案）」はページ上「非公開」。WG名義の公表された取りまとめは確認できなかった'
    for c in (sen, ken, hq, exp, wg, semi): councils.append(c)
    # ===== 利益相反 =====
    coi_docs = {
      'ai-senryaku': [B + 'senryaku/1kai/sanko1.pdf', S + '10kai/shiryo1.pdf', S + 'ai_senryaku.html'],
      'ai-seido-kenkyukai': [S + '10kai/shiryo1.pdf', K + 'ai_kenkyu.html'],
      'ai-hq': ['https://laws.e-gov.go.jp/api/1/lawdata/507AC0000000053', 'https://laws.e-gov.go.jp/api/1/lawdata/507CO0000000281', H + '1kai/shiryo1_1.pdf', H + '1kai/shiryo1_2.pdf', H + '1kai/shiryo1_3.pdf', H + '1kai/shiryo1_4.pdf', H + 'ai_hq.html', H + 'konkyo.html'],
      'ai-expert-panel': ['https://laws.e-gov.go.jp/api/1/lawdata/507CO0000000281', E + '1kai/ai_ep_settigami.pdf', E + '1kai/shiryo1_1.pdf', E + '1kai/shiryo1_3.pdf', E + 'ai_expert_panel.html'],
      'ai-expert-wg-seido': [W + 'seido_1kai/shiryo1.pdf', E + '1kai/shiryo1_1.pdf', E + '1kai/shiryo1_3.pdf', W + 'ai_expert_wg.html'],
      'ai-semi-wg': [SW + '1kai/shiryo2.pdf', SW + '1kai/shiryo3.pdf', SW + '2kai/sanko.pdf', SW + 'ai-semi_wg.html'],
    }
    disclosure = {
      'ai-senryaku': [('「イノベーション政策強化推進のための有識者会議」の設置について', B + 'senryaku/1kai/sanko1.pdf', '４．有識者会議は原則として非公開とする。ただし、座長が会議を公開することが適当であるとしたときは、この限りではない。')],
      'ai-seido-kenkyukai': [('「ＡＩ制度研究会」の設置について（案）', S + '10kai/shiryo1.pdf', '３．研究会は原則として非公開とする。')],
      'ai-hq': [('人工知能戦略本部の運営について（案）', H + '1kai/shiryo1_1.pdf', '本部会合は非公開とし、議事概要は、原則として、本部会合終了後公開する。')],
      'ai-expert-panel': [('人工知能戦略専門調査会運営規則', E + '1kai/shiryo1_3.pdf', '第４条 議事は原則、非公開とする。')],
      'ai-expert-wg-seido': [],
      'ai-semi-wg': [('ＡＩ・半導体ワーキンググループ運営要領', SW + '1kai/shiryo3.pdf', '第４条 議事は原則、非公開とする。')],
    }
    allpdf = sum(1 for r, d, f in os.walk(os.path.join(RAW, 'www8.cao.go.jp', 'cstp', 'ai')) for x in f if x.endswith('.pdf'))
    for c in councils:
        c['coi'] = {'status': '公表資料では確認できなかった',
                    'documents': [],
                    'note': '設置・運営に関する文書に、構成員（委員）の利益相反・利害関係の申告、審議からの除外等の定めは見当たらない。あるのは会議・議事概要・資料の公開/非公開の定めのみ（related_rules）。補助確認として、取得した内閣府AI関係PDF全%d件のテキストを「利益相反」「利害関係」で全文検索したが、構成員に関する定めは無かった（ヒットは事業者の「利害関係者」等の一般用語のみ）' % allpdf,
                    'related_rules': [{'title': t, 'url': u, 'text': x} for t, u, x in disclosure[c['id']]],
                    'checked': coi_docs[c['id']]}
        for r in c['coi']['related_rules']:
            if r['url'].endswith('.pdf'):
                flat = re.sub(r'\s+', '', pdftext(r['url'], '-raw'))
                if re.sub(r'\s+', '', r['text']) not in flat:
                    raise SystemExit('規定の原文が見つからない: ' + r['url'] + r['text'])
    out = {'fetched_at': '2026-11-05',
           'source_note': '内閣府 https://www8.cao.go.jp/cstp/ai/ 配下と e-Gov 法令API から取得。原資料は raw/cao/ に保存。PDFの文字は pdftotext で抽出し、康熙部首等の字形（例: ⽣→生）とCJK互換漢字（例: U+F9DC→隆。正準等価）だけ通常の漢字に戻した（内閣府のHTMLにも康熙部首の字形があり同様に処理）。氏名中の半角空白はPDFの文字位置から出たもので、原本の空白の種類（全角/半角）は判別できない。quotes の page はPDFの物理ページ（1始まり）、printed_page は紙面に印字されたページ番号。',
           'scope_note': '対象: ＡＩ戦略会議（2023-05〜）、その下のＡＩ制度研究会、ＡＩ法に基づく人工知能戦略本部、その下の人工知能戦略専門調査会と制度の在り方検討ワーキンググループ、ＡＩ・半導体ワーキンググループ。対象外: 人工知能戦略推進会議（関係府省の職員のみで構成）、AISI関係府省庁等連絡会議、AI戦略会議より前の会議（AI戦略実行会議等）',
           'councils': councils}
    os.makedirs(os.path.join(PROJ, 'data'), exist_ok=True)
    json.dump(out, open(os.path.join(PROJ, 'data', 'councils.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for c in councils:
        print(c['id'], 'rosters', len(c['rosters']), 'members(latest)', len(c['rosters'][-1]['members']), 'meetings', len(c['meetings']), 'outputs', len(c['outputs']))

if __name__ == '__main__':
    main()
