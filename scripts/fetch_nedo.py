#!/usr/bin/env python3
"""NEDO / METI(GENIAC) / JST 等の公表資料を取得して raw/nedo/ に保存する。

使い方:
  python3 scripts/fetch_nedo.py list        # NEDO AI分野の公募一覧(全ページ)を取得し koubo_index.tsv を作る
  python3 scripts/fetch_nedo.py get URL...  # 任意の公式URLを取得して保存(PDFは .txt も作る)
  python3 scripts/fetch_nedo.py text FILE   # 保存済みHTMLを本文テキストで表示
データ源は公式サイトのみ(nedo.go.jp, meti.go.jp, jst.go.jp, soumu.go.jp, nict.go.jp)。
"""
import html, os, re, subprocess, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw", "nedo")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ALLOWED = ("nedo.go.jp", "meti.go.jp", "jst.go.jp", "soumu.go.jp", "nict.go.jp")


def local_name(url):
    u = urllib.parse.urlparse(url)
    host = u.netloc.replace("www.", "")
    path = (u.path.strip("/") or "index").replace("/", "_")
    if u.query:
        path += "_" + re.sub(r"[^A-Za-z0-9]+", "_", u.query)
    if not re.search(r"\.(html?|pdf|php)$", path, re.I):
        path += ".html"
    return f"{host}__{path}"


def fetch(url, force=False):
    host = urllib.parse.urlparse(url).netloc
    if not any(host == d or host.endswith("." + d) for d in ALLOWED):
        raise SystemExit(f"公式ドメイン以外は取得しない: {url}")
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, local_name(url))
    if os.path.exists(path) and os.path.getsize(path) > 0 and not force:
        return path
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "ja,en;q=0.8"})
    data = b""
    for attempt in range(5):
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            status = r.status
        if status == 200 and data:
            break
        # meti.go.jp は 202 + 空本文を返すことがある(混雑時のWAF)。空は保存しない。
        time.sleep(10 * (attempt + 1))
    if not data:
        raise SystemExit(f"空応答(status={status})のため保存しない: {url}")
    with open(path, "wb") as f:
        f.write(data)
    time.sleep(1.0)
    if path.lower().endswith(".pdf"):
        subprocess.run(["pdftotext", "-layout", path, path[:-4] + ".txt"], check=False)
    print(f"saved {url} -> {os.path.basename(path)} ({len(data)} bytes)", file=sys.stderr)
    return path


def html_text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", "", t)
    t = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>', r" [\1] ", t)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = html.unescape(t)
    return re.sub(r"\n\s*\n+", "\n", t)


def links(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, re.S):
        yield html.unescape(m.group(1)), html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip())


def koubo_list():
    rows = {}
    for p in range(1, 40):
        url = f"https://www.nedo.go.jp/form/event.php?f=koubo.html&p={p}&o=-date&category=AI"
        path = fetch(url)
        t = open(path, encoding="utf-8", errors="replace").read()
        # 行ごとに日付とリンクを拾う
        found = 0
        for tr in re.findall(r"(?s)<tr.*?</tr>", t):
            m = re.search(r'href="(/koubo/[A-Z0-9_]+\.html)"[^>]*>(.*?)</a>', tr, re.S)
            if not m:
                continue
            title = html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip())
            dates = re.findall(r"20\d\d年\d+月\d+日", re.sub(r"<[^>]+>", " ", tr))
            rows[m.group(1)] = (" / ".join(dates), title)
            found += 1
        if not found:
            break
    out = os.path.join(RAW, "koubo_index.tsv")
    with open(out, "w", encoding="utf-8") as f:
        for k, (d, ti) in rows.items():
            f.write(f"https://www.nedo.go.jp{k}\t{d}\t{ti}\n")
    print(f"{len(rows)} 件 -> {out}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        koubo_list()
    elif cmd == "get":
        for u in sys.argv[2:]:
            print(fetch(u))
    elif cmd == "text":
        print(html_text(sys.argv[2]))
    elif cmd == "links":
        for h, s in links(sys.argv[2]):
            print(h, "|", s)
    elif cmd == "build":
        pass  # ファイル末尾で build() を呼ぶ（定義がこの後にあるため）


def koubo_summary(url):
    """公募/実施体制決定ページの要点(日付・応募件数・詳細資料PDF)を出す。"""
    path = fetch(url)
    t = html_text(path)
    i = t.find("決定\n")
    body = t[t.find("\n", t.find("[#search]")):]
    m = re.search(r"(?s)(「.*?について)\n(20\d\d年\d+月\d+日)", body)
    out = {"url": url}
    if m:
        out["title"], out["date"] = m.group(1).strip(), m.group(2)
    m = re.search(r"(\d+)件の(提案|申請|応募)", body)
    if m:
        out["applications"] = m.group(0)
    out["pdfs"] = re.findall(r"\[(/content/\d+\.pdf)\]\s*\n([^\n]+)", body)
    return out, body


# ---------------------------------------------------------------------------
# awards.json の組み立て
# 採択先・テーマは「実施予定先一覧」PDF から書き写したもの。build() で
# 各法人名・テーマ名が原資料 PDF の本文(空白除去)に含まれるかを機械照合し、
# 照合できないものがあれば止まる。金額は個別の公表がないため "未取得"。
# ---------------------------------------------------------------------------
import json, unicodedata, datetime

N = "https://www.nedo.go.jp"


def C(pid):
    return f"{N}/content/{pid}.pdf"


def raw_text(url):
    """PDF をセル順(-raw)で読んだ本文。"""
    path = fetch(url)
    rp = path[:-4] + ".raw.txt"
    if not os.path.exists(rp):
        subprocess.run(["pdftotext", "-raw", path, rp], check=True)
    return open(rp, encoding="utf-8", errors="replace").read()


def squash(s):
    return re.sub(r"\s+", "", s)


def committee(url):
    t = unicodedata.normalize("NFKC", raw_text(url))
    chair, members = None, []
    for role, name in re.findall(r"^(委員長|委員)\s*(\S+ \S+)", t, re.M):
        if role == "委員長":
            chair = name
        else:
            members.append(name)
    return {"list_url": url, "chair": chair, "members": members,
            "note": "所属・役職は委員一覧PDFのとおり（審査会開催時点の所属）"}


def coi_from_youryou(url):
    """公募要領の「利害関係の確認について」の原文を取り出す。"""
    path = fetch(url)
    lines = open(path[:-4] + ".txt", encoding="utf-8", errors="replace").read().split("\n")
    s = next((i for i, l in enumerate(lines) if l.strip().endswith("利害関係の確認について")), None)
    if s is None:
        return None
    e = next(i for i in range(s, min(s + 60, len(lines)))
             if "ご協力をお願いいたします" in squash("".join(lines[s:i + 1])))
    body = [l.strip() for l in lines[s:e + 1] if l.strip() and not re.fullmatch(r"\d+", l.strip())]
    text = "".join(body).replace("➢", "\n・").strip()
    return text


def review_method_text(url):
    """公募要領の「審査の方法」の節を原文で取り出す（次の「審査基準」の見出しまで）。"""
    lines = open(fetch(url)[:-4] + ".txt", encoding="utf-8", errors="replace").read().split("\n")
    s = next((i for i, l in enumerate(lines) if re.match(r"^\s*[（(]\s*1\s*[）)]\s*審査の方法", l) and ".." not in l), None)
    if s is None:
        return None
    e = next((i for i in range(s + 1, min(s + 40, len(lines))) if "審査基準" in lines[i]), None)
    if e is None:
        return None
    body = [re.sub(r"\s+", " ", l).strip() for l in lines[s:e] if l.strip() and not re.fullmatch(r"\d+", l.strip())]
    return "\n".join(body)


def has_criteria(url):
    path = fetch(url)
    t = open(path[:-4] + ".txt", encoding="utf-8", errors="replace").read()
    return bool(re.search(r"審査基準", t))


UNK_LEAD = "未取得（代表の区別は公表なし）"


def M(listed, theme, note=None):
    """実施予定先が併記され、代表・共同の区別が公表されていないもの。"""
    d = {"org": UNK_LEAD, "co_orgs": [], "orgs_listed": listed, "theme": theme, "amount": "未取得"}
    if note:
        d["note"] = note
    return d


def A(org, theme, co=None, note=None):
    d = {"org": org, "co_orgs": co or [], "theme": theme, "amount": "未取得"}
    if note:
        d["note"] = note
    return d


GENIAC_PARENT = "ポスト5G情報通信システム基盤強化研究開発事業"

PROGRAMS = [
  {
    "id": "geniac-1a", "agency": "NEDO", "geniac_round": "第1期",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／ポスト5G情報通信システムの開発（g3）競争力ある生成AI基盤モデルの開発（助成）",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/IT2_100304.html",
    "call_period": "2023年11月10日～2023年12月11日",
    "award_date": "2024年2月2日", "applications": "16件の提案",
    "project_period": "2024年2月15日から2024年8月15日まで",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／ポスト5G情報通信システムの開発」に係る実施体制の決定について",
    "source_url": f"{N}/koubo/IT3_100304.html", "list_url": C(100971659),
    "related_urls": ["https://www.meti.go.jp/press/2023/02/20240202003/20240202003.html",
                     "https://geniac.meti.go.jp/selection_1/index.html"],
    "awards": [
      A("株式会社 ABEJA", "LLM の社会実装に向けた特化型モデルの元となる汎化的LLM に関する研究開発"),
      A("Sakana AI 株式会社", "自律型エージェントシステム向け高効率基盤モデルの開発"),
      A("大学共同利用機関法人情報・システム研究機構", "オープンかつ日本語に強い GPT-3 級大規模言語モデルの構築"),
      A("ストックマーク株式会社", "厳密さが要求されるビジネス用途におけるハルシネーションを大幅抑止した基盤モデル"),
      A("Turing 株式会社", "完全自動運転に向けたマルチモーダル基盤モデルの開発"),
      A("国立大学法人東京大学", "多様な日本語能力の向上を目指した公開型の基盤モデル開発"),
      A("株式会社 Preferred Elements", "100B/1T パラメータからなる大規模マルチモーダル基盤モデルの構築"),
    ],
    "committee_pdf": C(100971615), "youryou": C(100968509),
  },
  {
    "id": "geniac-1b", "agency": "NEDO", "geniac_round": "第1期（2024年2月公募分）",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／ポスト5G情報通信システムの開発（g3）競争力ある生成AI基盤モデルの開発（助成）",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/IT2_100316.html",
    "call_period": "2024年2月16日～2024年3月18日",
    "award_date": "2024年5月17日", "applications": "8件の提案",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／ポスト5G情報通信システムの開発」に係る実施体制の決定について",
    "source_url": f"{N}/koubo/IT3_100316.html", "list_url": C(100977022),
    "related_urls": ["https://geniac.meti.go.jp/selection_1/index.html"],
    "round_note": "経済産業省GENIACサイトの「採択事業者のご紹介」（第1期）には geniac-1a の7者とこの3者の計10者が掲載。NEDOニュースリリース（2024年10月10日）は「第1期（計算資源の提供支援の開発期間：2024年2月～8月）においては、計10件の開発テーマで基盤モデルの開発に取り組みました」と記載。",
    "awards": [
      A("株式会社 ELYZA", "モデル組み合わせによる日本語大規模基盤モデル開発と半自動データ作成フレームの構築"),
      A("株式会社 Kotoba Technologies Japan", "End-to-End 音声基盤モデルの開発"),
      A("富士通株式会社", "論理推論を可能とする大規模言語モデルの研究開発"),
    ],
    "committee_pdf": C(100977023), "youryou": C(100972367),
  },
  {
    "id": "geniac-2", "agency": "NEDO", "geniac_round": "第2期",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／ポスト5G情報通信システムの開発（助成）（g3）競争力ある生成AI基盤モデルの開発",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/IT2_100331.html",
    "call_period": "2024年7月16日～2024年8月23日",
    "award_date": "2024年10月10日", "applications": "35件の申請",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／ポスト5G情報通信システムの開発（助成）」に係る実施体制の決定について",
    "source_url": f"{N}/koubo/IT3_100331.html", "list_url": C(800014611),
    "related_urls": [f"{N}/news/press/AA5_101790.html", C(800014462),
                     "https://geniac.meti.go.jp/selection_2/index.html"],
    "awards": [
      A("株式会社 ABEJA", "特化型モデル開発のためのモデルの小型化"),
      A("株式会社 AIdeaLab", "動画生成 AI 基盤モデルと動画生成 AI プラットフォームの開発"),
      A("AiHUB 株式会社", "日本のアニメ産業活性化の為のアニメ分野特化型基盤モデル開発"),
      A("AI inside 株式会社", "生成 AI 基盤による非定型帳票の革新と自律促進"),
      A("株式会社 EQUES", "薬学分野・製薬業務に特化した LLM の開発"),
      A("株式会社 Kotoba Technologies Japan", "リアルタイム音声基盤モデルの開発と日本市場における実用化"),
      A("NABLAS 株式会社", "食品・流通小売領域の専門知識を取り込んだマルチモーダルな大規模モデルの開発"),
      A("株式会社 Preferred Elements", "世界最大規模の高品質データセットの構築およびそれを用いた大規模言語モデルの開発",
        ["株式会社 Preferred Networks（【共同提案者】）"]),
      A("SyntheticGestalt 株式会社", "AI創薬を実現させる分子情報特化基盤モデル開発"),
      A("Turing 株式会社", "完全自動運転に向けた身体性を持つマルチモーダル基盤モデルの開発"),
      A("ウーブン・バイ・トヨタ株式会社", "都市時空間理解に向けたマルチモーダル基盤モデルの開発"),
      A("株式会社オルツ", "パーソナル AI の実現を目標とした世界最高性能の日本語言語処理技術の研究"),
      A("国立研究開発法人海洋研究開発機構", "地域気候サービスのための生成 AI 基盤モデルの開発"),
      A("カラクリ株式会社", "日本のカスタマーサポートのための高品質 AI エージェントモデルの開発"),
      A("ストックマーク株式会社", "ハルシネーションを抑止したドキュメント読解基盤モデルの構築"),
      A("株式会社データグリッド", "ユーザー意図を反映する選択的編集能力を備えたVision 系基盤モデルの開発",
        ["大学共同利用機関法人 情報・システム研究機構 国立情報学研究所（【共同研究先】）"]),
      A("株式会社ヒューマノーム研究所", "創薬を加速する遺伝子発現量の基盤モデル開発"),
      A("フューチャー株式会社", "日本語とソフトウェア開発に特化した基盤モデルの構築",
        ["国立大学法人東北大学（【共同研究先】）", "国立大学法人奈良先端科学技術大学院大学（【共同研究先】）",
         "公立大学法人会津大学（【共同研究先】）"]),
      A("株式会社リコー", "企業の知の結晶である様々なドキュメント群を読み取るマルチモーダル LLM の開発"),
      A("株式会社ユビタス", "観光産業用向け４０５Ｂ ＬＬＭ／基盤モデル開発",
        ["株式会社 Deepreneur（【共同提案者】）"]),
    ],
    "committee_pdf": C(800013575), "youryou": C(100979615),
  },
  {
    "id": "geniac-3", "agency": "NEDO", "geniac_round": "第3期",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／競争力ある生成AI基盤モデルの開発（GENIAC）",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/CD2_100397.html",
    "call_period": "2025年3月14日～2025年5月8日",
    "award_date": "2025年7月15日", "applications": "43件の申請",
    "budget_in_call": "公募要領「助成額（ＮＥＤＯ負担分）は、事業期間全体かつ採択事業者の合計で１００億円以内（※）とし、」",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／競争力ある生成AI基盤モデルの開発（GENIAC）」に係る実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100397.html", "list_url": C(800028443),
    "related_urls": [C(800028445), "https://geniac.meti.go.jp/selection_3/index.html"],
    "awards": [
      A("株式会社 ABEJA", "ロングコンテキスト対応小規模言語基盤モデルと AIエージェント構築に関する研究開発"),
      A("株式会社 AIdeaLab", "時空間 MoE を用いた動画生成 AI 基盤モデルの研究開発と当該プラットフォームの満足度検証"),
      A("AI inside 株式会社", "一貫性のある日本語 Full-Duplex-Speech マルチモーダル LLM の研究開発"),
      A("Airion 株式会社", "PLC 制御におけるラダープログラム生成用大規模言語モデルの研究開発"),
      A("Degas 株式会社", "リモートセンシング用視覚言語モデルの研究開発"),
      A("Direava 株式会社", "外科手術支援のための視覚・言語統合型 AI 基盤モデルの開発"),
      A("株式会社 Kotoba Technologies Japan", "大規模データを用いたリアルタイム音声基盤モデルの精度・機能向上による実用化加速"),
      A("NABLAS 株式会社", "Factcheck RM とエージェントの開発研究"),
      A("株式会社 NexaScience", "自律駆動 R&D のための AI エージェントアダプターの研究開発"),
      A("Nishika 株式会社", "要約タスク等を目標に出力形式への追従能力を高めた LLM の開発・データセット構築"),
      A("ＯＮＥＳＴＲＵＣＴＩＯＮ株式会社", "openBIM における BIM 情報要件の生成基盤モデルの研究開発"),
      A("株式会社 Preferred Networks", "自律稼働デバイスに向けた高精度軽量 VLM の開発"),
      A("Ｓａｎｓａｎ株式会社", "視覚接地した文書特化型視覚言語基盤モデルの構築"),
      A("SDio 株式会社", "映像を産業の活力へ:長尺コンテクストを理解する国産大規模映像基盤モデルの開発"),
      A("SyntheticGestalt 株式会社", "AIによる分子の発明を実現させるタンパク質-リガンド分子相互作用基盤モデルの開発"),
      A("Turing 株式会社", "完全自動運転に向けた車載可能なフィジカル基盤モデルの開発"),
      A("Zen Intelligence 株式会社", "建築現場の施工管理を自動化する AI 基盤モデルの開発",
        note="一覧の表記「(2025 年 7 月に株式会社 SoftRoid から社名変更)」"),
      A("アリヴェクシス株式会社", "低分子化合物の生物活性を世界最高精度で予測する、創薬生成 AI 基盤モデルの研究開発"),
      A("カラクリ株式会社", "日本のカスタマーサポートのためのオムニモーダルエージェントモデルの開発"),
      A("ストックマーク株式会社", "暗黙知の抽出を目指した業界特化のドキュメント読解基盤モデルの開発"),
      A("株式会社野村総合研究所", "中規模（10B-40B）の業界・タスク特化型 LLMの研究開発"),
      A("株式会社プレシジョン", "医師兼 AI 研究者による医療用 SIP LLM-jp をベースとした用途特化 LLM の開発"),
      A("楽天グループ株式会社", "長期記憶メカニズムと対話型学習を融合した最先端の生成 AI 基盤モデルの研究開発"),
      A("株式会社リコー", "企業ドキュメント群の高度な解析を通じて知の活用を支援するマルチモーダル LLM"),
    ],
    "committee_pdf": C(800028444), "youryou": C(800022006),
  },
  {
    "id": "geniac-4-model", "agency": "NEDO", "geniac_round": "第4期（領域特化モデル開発）",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／競争力ある生成AI基盤モデルの開発（GENIAC）〔(g3)領域特化生成AI基盤モデルの開発（GENIAC）〕",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/CD2_100421.html",
    "call_period": "2026年01月27日～2026年03月19日",
    "award_date": "2026年6月4日", "applications": "50件の申請",
    "budget_in_call": "公募要領「本公募の予算規模は 100 億円程度（その他公募事業の状況に応じて変動があり得る）であり、予算の範囲内で採択先を決定します。」",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／競争力ある生成AI基盤モデルの開発（GENIAC）」の実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100421.html", "list_url": C(800056193),
    "related_urls": [C(800056327), "https://geniac.meti.go.jp/selection_4/model/index.html"],
    "awards": [
      A("株式会社アジラ", "大規模独自映像データを活用した防犯ドメイン特化VLM 基盤モデルの研究開発"),
      A("株式会社 ABEJA", "自動車整備領域特化型 AI エージェントの開発"),
      A("Epigenetic AI 株式会社", "老化を測定するエピゲノム生成 AI 基盤モデルの新規開発と長寿医療への応用実証"),
      A("株式会社 Elith", "金融業務特化型 AI ガードレールモデル FinGuard の開発"),
      A("KDDI 株式会社", "ドローンインフラ×AI インフラを基盤とした多用途対応VLM 基盤の研究開発"),
      A("Sakana AI 株式会社", "日本の制度・慣習・言語実務に適合したエージェント型基盤 AI の開発"),
      A("Sansan 株式会社", "文書に特化した指示追従能力の高い視覚言語モデルの開発"),
      A("シェルパ・アンド・カンパニー株式会社", "金融領域に向けた非定型文書解析・根拠生成モデルの構築"),
      A("株式会社 Spectee", "災害検知 LLM（LMM）と AI エージェントによる次世代防災・危機管理基盤の開発"),
      A("株式会社 DubGuild", "人間らしい対話を実現する音声基盤モデルの開発とその社会実装"),
      A("Direava 株式会社", "手術安全性向上のための『外科手術未来予測モデル』の開発と実証"),
      A("newmo 株式会社", "Fast/Slow 連携アーキテクチャによる自動運転タクシーの実現"),
      A("株式会社 biomy", "次世代創薬の戦略的自律性を確立するマルチモーダル空間 AI：Virtual Cell 基盤モデルの開発"),
      A("株式会社 Preferred Networks", "現実世界の再現を目指す材料基盤モデルの研究開発"),
      A("株式会社メルカリ", "Generative Retrieval 技術を用いた二次流通市場向け高精度検索・推薦基盤モデルの開発"),
      A("ONESTRUCTION 株式会社", "世界モデルの社会実装を見据えた、BIM 生成統合型建設ドメイン特化基盤モデルの研究開発"),
    ],
    "committee_pdf": C(800056194), "youryou": C(800046928),
  },
  {
    "id": "geniac-4-ai-ready", "agency": "NEDO", "geniac_round": "第4期（AI-Ready化）",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／製造業データ等のAI-Ready化に関する研究開発（GENIAC）",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/CD2_100422.html",
    "call_period": "2026年01月27日～2026年02月26日",
    "award_date": "2026年5月13日", "applications": "36件の提案",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／製造業データ等のAI-Ready化に関する研究開発（GENIAC）」の実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100422.html", "list_url": C(800054839),
    "related_urls": ["https://geniac.meti.go.jp/selection_4/ai_ready/index.html"],
    "awards": [
      A("AIONA 株式会社", "製造業設計ナレッジの統合的 AI-Ready 化 ―コンテキスト構造化とマルチモーダルデータ変換―の研究開発"),
      A("アイクリスタル株式会社", "プロセスインフォマティクスを加速する AI 駆動プロセス設計プラットフォームの開発"),
      A("SyntheticGestalt 株式会社", "分子基盤モデルを活用した低分子化合物デー タの AI-Ready 化手法の確立と異業種横断実証"),
      A("ストックマーク株式会社", "製造業における非構造化データの多層的構造化とヒアリング Agent による暗黙知の形式知化・自律運用プロセスの研究開発"),
      A("株式会社日立製作所", "オンデマンド型フォーマライゼーションによる製造業データの AI・産業データスペース対応化に向けた研究開発"),
      A("FastLabel 株式会社", "生産技能者が保有する暗黙知の構造データ化に係る技術開発及び産業汎用性の検証に関する研究開発"),
      A("FairyDevices 株式会社", "巡回型作業における実施品質記述データ基盤の構築"),
      A("株式会社フツパー", "AI-Driven Manufacturing 基盤の研究開発"),
      A("株式会社フライウィール", "多層構造・疎結合アーキテクチャに基づく汎用的 AI-Ready 化ツールの研究開発"),
    ],
    "committee_pdf": C(800054840), "youryou": C(800048496),
  },
  {
    "id": "geniac-4-robot-1", "agency": "NEDO", "geniac_round": "第4期（ロボット基盤モデル）",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／ロボット基盤モデルの研究開発（GENIAC）（補助）",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/CD2_100427.html",
    "call_period": "2026年02月20日～2026年03月23日",
    "award_date": "2026年5月14日", "applications": "3件の提案",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／ロボット基盤モデルの研究開発（GENIAC）（補助）」の実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100427.html", "list_url": C(800054044),
    "related_urls": ["https://geniac.meti.go.jp/selection_4/ai_robo/index.html"],
    "awards": [
      A("Turing 株式会社", "完全自動運転に向けたフィジカル基盤モデルの開発と車載 E2E システムの実装"),
      A("株式会社ロボトラック", "世界モデルと Diffusion Planner によるレベル 4 自動運転トラック向け基盤モデルの研究開発"),
    ],
    "committee_pdf": C(800054045), "youryou": C(800049208),
  },
  {
    "id": "geniac-4-robot-2", "agency": "NEDO", "geniac_round": "第4期（ロボット基盤モデル・多用途ロボット等）",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／ロボット基盤モデルの研究開発（GENIAC）（補助）（多用途ロボット等を含む）",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/CD2_100434.html",
    "call_period": "2026年5月18日～2026年6月16日",
    "award_date": "2026年9月9日", "applications": "29件の申請",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／ロボット基盤モデルの研究開発（GENIAC）（補助）」（多用途ロボット等を含む）の実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100434.html", "list_url": C(800068757),
    "related_urls": [C(800068805), "https://geniac.meti.go.jp/selection_4/ai_robo/index.html"],
    "awards": [
      A("株式会社アトム", "製造・物流現場の省人化とGX実現を目的とする、5本指ハンド搭載国産双腕二足ヒューマノイドによる触覚つきVLAモデルの研究開発"),
      A("SB Intuitions株式会社", "製造業の量産ライン工程を代替する双腕ロボット向け失敗予見型高速VLA基盤モデルおよび遠隔協調運用システムの開発"),
      A("株式会社XNOVA", "建設・製造現場の電動工具作業を代替する電動工具特化型の双腕ロボット用AI基盤モデル（Tool-VLA）の研究開発"),
      A("KDDI株式会社", "小売物流業等の現場業務を代替するモバイルマニピュレーター・ヒューマノイド向けロボット基盤モデルの研究開発"),
      A("Telexistence株式会社", "国産ヒューマノイドを活用した領域特化型ロボット基盤モデルの研究開発"),
      A("株式会社Highlanders", "自動車製造の位置合わせを対象とするヒューマノイド向けVLA/物理状態世界モデルの研究開発"),
      A("日立建機株式会社", "岩石等支障物除去工程、土砂掘削積込工程の自律作業を実現する自走式汎用マニピュレータ向けVLAモデルの開発"),
      A("FastLabel株式会社", "プラント産業の巡視点検業務高度化ソリューション構築に向けた4足歩行ロボットロコマニピ ュレーション技術及びVLAモデル開発"),
      M(["株式会社Preferred Networks", "株式会社Preferred Robotics"], "環境高度理解基盤モデルの開発と屋内移動ロボット業務への適用"),
      A("株式会社MW", "日本住宅環境に特化したロボット基盤モデルの研究開発－ AI Data Factory による大規模行 動データ収集とVLA(視覚言語行動モデル)の構築 －"),
      A("Muso Action株式会社", "物流倉庫のピッキング・ソーター投⼊におけるスライダー式ロボットアーム向け、多品種対応の ためのロボット基盤モデルとデータ収集デバイスの開発・実証"),
      A("株式会社メルカリ", "AIロボットを活用した出品および検品作業の自動化に関わる研究開発"),
      A("ugo株式会社", "双腕セミヒューマノイドによるコンタクトリッチな製造組立作業の自律化に向けたVTLAモデルの開発"),
    ],
    "committee_pdf": C(800068758), "youryou": C(800055089),
  },
  {
    "id": "geniac-4-data", "agency": "NEDO", "geniac_round": "第4期（データエコシステム）",
    "name": "ポスト5G情報通信システム基盤強化研究開発事業／データエコシステムの構築等に関する研究開発（GENIAC）",
    "parent_project": GENIAC_PARENT,
    "call_url": f"{N}/koubo/CD2_100430.html",
    "call_period": "2026年03月25日～2026年04月23日",
    "award_date": "2026年7月2日", "applications": "36件の申請",
    "source_title": "「ポスト5G情報通信システム基盤強化研究開発事業／データエコシステムの構築等に関する研究開発（GENIAC）」の実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100430.html", "list_url": C(800057699),
    "related_urls": [C(800057700), "https://geniac.meti.go.jp/selection_data_4/index.html"],
    "list_note": "実施予定先欄に複数者が併記されたテーマは代表・共同の区別の記載がない（一覧はアルファベット・五十音順表記）。その場合 org は未取得とし、orgs_listed に公表順で全者を入れた。",
    "awards": [
      A("一般社団法人ＡＩロボット協会", "実家庭におけるロボット動作データの自律的拡大に向けたデータエコシステムの研究開発"),
      A("株式会社ＥＬＥＭＥＮＴＳ", "フィジカル AI 基盤モデル高度化に向けた製造業マルチモーダルデータ基盤の構築"),
      M(["川崎重工業株式会社", "国立大学法人大阪大学", "ファナック株式会社", "株式会社ＦｉｎｇｅｒＶｉｓｉｏｎ", "株式会社安川電機"], "製造現場視触覚データ収集による VTLA 基盤モデルに向けたデータセットの構築"),
      A("国立大学法人神戸大学", "AI-OP（AI ロボット手術）を実現するための多元データエコシステムの研究開発"),
      M(["株式会社小松製作所", "国立研究開発法人産業技術総合研究所"], "工場の生産計画と実績管理の自動化・自律化を加速するデータエコシステムの研究開発"),
      A("ＳＴＡＴＩＯＮ Ａｉ株式会社", "作業者マルチモーダルデータ収集による製造業向けフィジカル AI ロボット活用のためのデータエコシステム構築"),
      M(["ＤＭＧ森精機株式会社", "国立研究開発法人産業技術総合研究所", "株式会社ＷＡＬＣ"], "高精度・高信頼加工を支える生産設備データエコシステムの構築と製造フィジカル AI に資する基盤モデルの研究開発"),
      M(["学校法人法政大学", "パシフィックコンサルタンツ株式会社", "宇宙サービスイノベーションラボ事業協同組合"], "インフラ点検効率化と自律型ロボット制御を支援する AI レディなハイブリッド空間・合成データセットの構築"),
      A("株式会社ベアーズ", "家事代行サービスにおける熟練スタッフの行動データエコシステム"),
    ],
    "committee_pdf": C(800057533), "youryou": C(800052070),
  },
  {
    "id": "nedo-ai-safety", "agency": "NEDO",
    "name": "ＡＩの安全性確保に関する研究開発・検証等の推進事業／AI セーフティ強化に関する研究開発",
    "parent_project": "ＡＩの安全性確保に関する研究開発・検証等の推進事業",
    "call_url": f"{N}/koubo/CD2_100393.html",
    "call_period": "2025年2月14日～2025年3月17日",
    "award_date": "2025年4月30日", "applications": "3件の提案",
    "source_title": "「AIセーフティ強化に関する研究開発」に係る実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100393.html", "list_url": C(800024943),
    "list_note": "1テーマに3者が併記（五十音順・代表の区別の記載なし）。orgs_listed に公表順で全者を入れた。",
    "awards": [
      M(["株式会社コーピー", "株式会社 Citadel AI", "国立研究開発法人産業技術総合研究所"], "AI セーフティ強化に関する研究開発"),
    ],
    "committee_pdf": C(800024944), "youryou": C(800020812),
  },
  {
    "id": "nedo-multimodal-physical-ai", "agency": "NEDO",
    "name": "AIロボット・フィジカルAIを見据えたマルチモーダル基盤モデル開発事業",
    "parent_project": "AIロボット・フィジカルAIを見据えたマルチモーダル基盤モデル開発事業（P26013）",
    "call_url": f"{N}/koubo/CD2_100431.html",
    "call_period": "2026年3月24日～2026年4月22日",
    "award_date": "2026年6月30日", "applications": "15件の申請",
    "source_title": "「AIロボット・フィジカルAIを見据えたマルチモーダル基盤モデル開発事業」の実施体制の決定について",
    "source_url": f"{N}/koubo/CD3_100431.html", "list_url": C(800057515),
    "related_urls": [C(800057655)],
    "awards": [
      M(["Noetra 株式会社", "国立研究開発法人産業技術総合研究所"], "実世界ネイティブに資するフィジカル AI 基盤技術の研究開発",
        note="一覧の Noetra 株式会社の表記「（旧名：株式会社日本ＡＩ基盤モデル開発）」"),
    ],
    "committee_pdf": C(800057516), "youryou": C(800051828),
  },
  {
    "id": "nedo-remote-ai-2021", "agency": "NEDO",
    "name": "人工知能活用による革新的リモート技術開発",
    "parent_project": "人工知能活用による革新的リモート技術開発（P21004）",
    "call_period": "未取得",
    "award_date": "2021年7月8日（ニュースリリース日）", "applications": "未取得",
    "project_period": "2021年度～2024年度（予定）",
    "budget_published": "ニュースリリース「全体予算：4.7億円（2021年度）」",
    "source_title": "「人工知能活用による革新的リモート技術開発」事業を開始",
    "source_url": f"{N}/news/press/AA5_101456.html", "list_url": None,
    "list_note": "ニュースリリースは委託予定先をテーマごとに五十音順で併記し、代表者の区別を記載していない。org は未取得とし、orgs_listed に公表順で全者を入れた。",
    "awards": [
      M(["オムロン株式会社", "株式会社Adansons", "国立研究開発法人産業技術総合研究所", "国立大学法人筑波大学", "国立大学法人東北大学"], "極薄ハプティックMEMSによる双方向リモート触覚伝達AIシステムの開発"),
      M(["国立研究開発法人理化学研究所", "国立大学法人東海国立大学機構　名古屋大学", "豊田合成株式会社"], "Contact Realityの実現による遠隔触診システム開発"),
      M(["株式会社エブリハ", "国立研究開発法人産業技術総合研究所", "国立大学法人京都大学", "国立大学法人東京大学", "セイコーエプソン株式会社"], "遠隔リハビリのための多感覚XR-AI技術基盤構築と保健指導との互恵ケア連携"),
      M(["国立研究開発法人産業技術総合研究所", "国立大学法人東京大学"], "AI・XR活用による空のアバターを実現する『革新的ドローンリモート技術』の研究開発"),
      A("国立大学法人東北大学", "動作ユニットAIによる人の感情推定とキャラクタの感情豊かな動作生成による遠隔コミュニケーション環境の構築",
        note="委託予定先は1者のみ記載"),
    ],
    "committee_pdf": None, "youryou": None,
  },
]

NEDO_EVAL_RULE = {
    "title": "NEDO技術委員・技術委員会等規程（研究評価委員会関係部分抜粋版）第35条",
    "url": C(100864110),
}

# NEDO 研究評価委員会の評価報告書（AI関連）。評点は報告書「評点結果」の表を
# build() で原文から読み取る（ここでは書かない）。
NEDO_EVALS = [
    ("P18002", "次世代人工知能・ロボットの中核となるインテグレート技術開発", "中間評価", "2020年度（報告書 2021年1月）", 100935431, f"{N}/introducing/iinkai/ZZBF_100406.html"),
    ("P18010", "人工知能技術適用によるスマート社会の実現", "中間評価", "2020年度（報告書 2021年1月）", 100935432, f"{N}/introducing/iinkai/ZZBF_100406.html"),
    ("P15009", "次世代人工知能・ロボット中核技術開発", "事後評価", "2020年度（報告書 2021年3月）", 100935449, f"{N}/introducing/iinkai/ZZBF_100406.html"),
    ("P20006", "人と共に進化する次世代人工知能に関する技術開発事業", "中間評価", "2022年度（報告書 2023年1月）", 100964383, f"{N}/introducing/iinkai/ZZBF_100492.html"),
    ("P19001", "Connected Industries推進のための協調領域データ共有・AIシステム開発促進事業", "事後評価", "2022年度（報告書 2023年1月）", 100964396, f"{N}/introducing/iinkai/ZZBF_100492.html"),
    ("P18010", "人工知能技術適用によるスマート社会の実現", "終了時評価", "2023年度（報告書 2024年3月）", 100977446, f"{N}/introducing/iinkai/ZZBF_100613.html"),
    ("P18002", "次世代人工知能・ロボットの中核となるインテグレート技術開発", "終了時評価", "2024年度（報告書 2025年3月）", 800026061, f"{N}/introducing/iinkai/ZZBF_100731.html"),
    ("P20006", "人と共に進化する次世代人工知能に関する技術開発事業", "終了時評価", "2025年度（報告書 2026年1月）", 800048523, f"{N}/introducing/iinkai/ZZBF_100786.html"),
    ("P21004", "人工知能活用による革新的リモート技術開発", "終了時評価", "2025年度（報告書 2026年3月）", 800055526, f"{N}/introducing/iinkai/ZZBF_100786.html"),
]


def nedo_eval_scores(txt):
    """評点結果の表を「項目: 評点（各委員の評価）」の形で原文から取り出す。"""
    lines = txt.split("\n")
    idx = [i for i, l in enumerate(lines) if re.search(r"評点結果\s*$", l)]
    if not idx:
        return None
    blk = lines[idx[-1] + 1: idx[-1] + 45]
    # 旧形式は「評価項目 平均値 素点」の表、新形式は「評価項目・評価結果 各委員の評価 評点」の表
    h = next((i for i, l in enumerate(blk) if re.search(r"素点|各委員の評価", l)), None)
    if h is None:
        return None
    labels, scores, major = [], [], ""
    for l in blk[h + 1:]:
        if re.search(r"判定基準|^\s*（注）", l):
            break
        l2 = re.sub(r"\s+", " ", l).strip()
        if not l2:
            continue
        m = re.search(r"(\d\.\d)\s+((?:[A-D]\s*){3,})$", l2) or re.search(r"((?:[A-D]\s+){3,}[A-D])\s+(\d\.\d)$", l2)
        text = l2
        if m:
            if re.match(r"\d", m.group(1)):
                avg, raw = m.group(1), m.group(2).strip()
            else:
                avg, raw = m.group(2), m.group(1).strip()
            scores.append((avg, raw))
            text = l2[:m.start()].strip()
        if re.match(r"^\(\d\)", text):
            labels.append((major + " " if major else "") + text)
        elif re.match(r"^[0-9]\s*[.．]", text):
            major = re.sub(r"\s+", "", text)
        elif re.match(r"^[１-９]．", text):
            labels.append(text)
        elif text and labels and re.match(r"^[１-９]．", labels[-1]) and not re.match(r"^[\d.]", text):
            labels[-1] = labels[-1] + text  # 折り返した項目名の続き
        elif text and labels and not re.match(r"^\d", text):
            labels[-1] = labels[-1] + text
    if not scores:
        return None
    # 新形式は大項目(1. 2. 3.)の行に評点がないので、評点つきの小項目だけを数える
    sub = labels
    out = []
    for i, (avg, raw) in enumerate(scores):
        lab = sub[i] if i < len(sub) else f"項目{i+1}"
        out.append(f"{lab} {avg}（各委員: {raw}）")
    return out


def first_paragraph(txt, heads):
    lines = txt.split("\n")
    starts = [i for i, l in enumerate(lines) if any(re.match(r"^\s*" + h, l) for h in heads)]
    if not starts:
        return None
    # 目次の行を飛ばすため、後ろの見出しから本文が続くものを使う
    for s in starts:
        body = []
        for l in lines[s + 1:s + 30]:
            if not l.strip():
                if body:
                    break
                continue
            if "･･･" in l or "…" in l or "·····" in l or re.search(r"\d+-\d+\s*$", l):
                body = []
                break
            if re.match(r"^\s*[＜<]", l):
                continue
            body.append(l.strip())
        if len(body) >= 3:
            return "".join(body)
    return None


def quote(s, n=160):
    s = s.strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    j = cut.rfind("。")
    return cut[:j + 1] if j > 40 else cut + "…"


def build_evaluations():
    evs = []
    for code, name, typ, year, pid, page in NEDO_EVALS:
        path = fetch(C(pid))
        txt = open(path[:-4] + ".txt", encoding="utf-8", errors="replace").read()
        head = squash(txt[:600])
        assert squash(name)[:12] in head or squash(name)[:8] in head, (pid, head[:80])
        scores = nedo_eval_scores(txt)
        para = first_paragraph(txt, [r"１．総合評価\s*$", r"１．１ 意義・アウトカム"])
        tl = txt.split("\n")
        notes = [squash(tl[i] + (tl[i + 1] if not tl[i].rstrip().endswith("。") else ""))
                 for i, l in enumerate(tl) if "A=3、B=2、C=1、D=0" in l][:1]
        conv = ("。原文注記:" + notes[0]) if notes else ""
        conv2 = ""
        ev = {
            "project": f"{name}（{code}）", "agency": "NEDO（研究評価委員会）", "type": typ, "year": year,
            "url": C(pid), "list_page": page,
            "summary_quote": quote(para) if para else "未取得",
            "score": ("評点結果（原文の表から）: " + " / ".join(scores) + conv + conv2) if scores else "未取得",
        }
        if "利害関係はないとする" in txt:
            m = re.search(r"注[＊*]?[:：]?.{0,200}?利害関係はないとする。", squash(txt))
            ev["coi_note"] = m.group(0) if m else "報告書に第35条（利害関係者の排除）に基づく記載あり"
        evs.append(ev)
    return evs


METI_POST5G_2023 = "https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/kenkyu_innovation/hyoka_wg/pdf/065_02_00.pdf"
METI_POST5G_2026 = "https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/innovation/evaluation_wg/pdf/005_01_03.pdf"


METI_POST5G_2023_SUPP = "https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/kenkyu_innovation/hyoka_wg/pdf/065_h01_00.pdf"


def scope_note_2023():
    """補足説明資料の「評価対象とする期間」の記述を原文で引く。取れなければ未取得。"""
    try:
        t = open(fetch(METI_POST5G_2023_SUPP)[:-4] + ".txt", encoding="utf-8", errors="replace").read()
    except SystemExit:
        return "未取得（補足説明資料 065_h01_00.pdf を取得できなかった）"
    tl = t.split("\n")
    for i, l in enumerate(tl):
        if re.search(r"2021年6月30日までに公募を開始", l):
            ctx = squash("".join(tl[max(0, i - 3):i + 1]))
            j = ctx.rfind("。", 0, ctx.find("2021年6月30日"))
            sent = ctx[j + 1:] if j >= 0 else ctx
            return "補足説明資料（" + METI_POST5G_2023_SUPP + "）の原文:「" + sent + "」"
    return "未取得（補足説明資料に該当の記述を見つけられなかった）"


def meti_post5g_eval():
    evs = []
    path = fetch(METI_POST5G_2023)
    txt = open(path[:-4] + ".txt", encoding="utf-8", errors="replace").read()
    lines = txt.split("\n")
    # 第2部 第1章 A（ポスト５Ｇ情報通信システムの開発）の評点表 = 本文中1つ目の「３．評点法による評点結果」
    i = [k for k, l in enumerate(lines) if l.strip().startswith("３．評点法による評点結果") and "·" not in l][0]
    rows = []
    for l in lines[i + 1:i + 25]:
        m = re.match(r"^\s*([１-７]．\S+)\s+(\d\.\d)\s+(.*)$", l)
        if m:
            each = re.sub(r"\s+", " ", m.group(3)).strip()
            rows.append(f"{m.group(1)} {m.group(2)}（各委員: {each}）")
    crit = [k for k, l in enumerate(lines) if "【評価項目の判定基準】" in l]
    critq = ""
    if crit:
        cl = [re.sub(r"\s+", " ", x).strip() for x in lines[crit[0]:crit[0] + 7] if x.strip()]
        critq = " / ".join(cl)
    s = [k for k, l in enumerate(lines) if re.match(r"^Ａ\s+ポスト５Ｇ情報通信システムの開発", l.strip()) and "·" not in l]
    para = first_paragraph("\n".join(lines[s[-1]:]), [r"１．総合評価\s*$"]) if s else None
    evs.append({
        "project": "ポスト５Ｇ情報通信システム基盤強化研究開発事業（複数課題プログラム）／Ａ ポスト５Ｇ情報通信システムの開発",
        "agency": "経済産業省（産業構造審議会 産業技術環境分科会 研究開発・イノベーション小委員会 評価ワーキンググループ）",
        "type": "中間評価（技術評価報告書（案）・第65回評価WG資料2）",
        "year": "2022年度（2022年11月30日 第1回中間評価検討会、報告書案 2023年2月）",
        "url": METI_POST5G_2023,
        "related_urls": ["https://www.meti.go.jp/policy/tech_evaluation/c00/C0000000R04/221130_post5g_1st/221130_post5g_1st.html",
                         "https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/kenkyu_innovation/hyoka_wg/065.html"],
        "scope_note": scope_note_2023(),
        "summary_quote": quote(para) if para else "未取得",
        "score": ("評点法による評点結果（3点満点）: " + " / ".join(rows) + (("。原文の判定基準: " + critq) if critq else "")) if rows else "未取得",
    })
    # 2026年6月 中間評価報告書（案）。meti.go.jp の WAF で取得できない場合は未取得と記す。
    try:
        p2 = fetch(METI_POST5G_2026)
        t2 = open(p2[:-4] + ".txt", encoding="utf-8", errors="replace").read()
        status = "取得済み"
    except SystemExit:
        t2, status = "", "未取得"
    ev2 = {
        "project": "ポスト５Ｇ情報通信システム基盤強化研究開発事業（AI 基盤モデル及び先端半導体関連技術開発事業）",
        "agency": "経済産業省（産業構造審議会 イノベーション・環境分科会 イノベーション小委員会 評価ワーキンググループ）",
        "type": "中間評価（中間評価報告書（案）・第5回評価WG資料）",
        "year": "2026年6月（報告書案の表紙の日付）",
        "url": METI_POST5G_2026,
        "summary_quote": "未取得", "score": "未取得",
    }
    if not t2:
        ev2["fetch_status"] = ("未取得: meti.go.jp が自動取得に WAF チャレンジ（HTTP 202・本文なし）を返し、"
                               "本文を取得できなかった。題名・日付は検索結果に表示された PDF の表題による。")
    else:
        ev2["fetch_status"] = status
        ev2["year"] = "2026年6月（報告書案の日付。評価WG委員名簿は「２０２６年６月１日現在」）"
        lines2 = t2.split("\n")
        k = next(i for i, l in enumerate(lines2) if l.strip() == "１．評点法による評価結果")
        rows, major = [], ""
        for l in lines2[k + 1:k + 30]:
            if "判定基準" in l:
                break
            l2 = re.sub(r"\s+", " ", l).strip()
            m = re.match(r"^(\(\d\) \S+) ((?:[A-D] ){4,}[A-D]) (\d\.\d)$", l2)
            if m:
                rows.append(f"{major} {m.group(1)} {m.group(3)}（委員A～E: {m.group(2)}）")
            elif re.match(r"^[１-９]．", l2):
                major = l2
        note = next((squash(l) for l in lines2 if "A=3、B=2、C=1、D=0" in l), "")
        ev2["score"] = "評点法による評価結果: " + " / ".join(rows) + ("。原文注記:" + note if note else "")
        q = next(i for i, l in enumerate(lines2) if "国のリーダーシップにより網羅的に技術開発が進められている" in l)
        ev2["summary_quote"] = "評価コメント（意義・アウトカム【肯定的意見】の一つ）: " + squash(lines2[q]).lstrip("")
        ev2["quote_note"] = "報告書は評価WG委員のコメントを委員ごとに列記する形式で、総合評価の文章は置かれていない。GENIAC への言及は「評価コメントに対する対処方針」（事業担当部署の回答）にある。"
        ev2["scope_note"] = "事業名に「AI 基盤モデル」を含む。第２章の評価対象事業に係る資料に「領域特化モデルの開発︓GENIAC」の記載あり。"
    evs.append(ev2)
    return evs


NICT_EVAL = {
    "project": "多言語音声翻訳高度化のためのディープラーニング技術の研究開発（副題 深層学習によるマルチモーダル文脈理解と機械翻訳の高度化・採択番号19701）",
    "agency": "NICT（委託研究 終了評価）",
    "type": "終了評価",
    "year": "令和2年度",
    "url": "https://www.nict.go.jp/collabo/commission/itaku_hyoka_r02last.html#19701",
}


def nict_eval():
    path = fetch("https://www.nict.go.jp/collabo/commission/itaku_hyoka_r02last.html")
    t = html_text(path)
    t = "\n".join(l.strip() for l in t.split("\n") if l.strip())
    i = t.index("\n19701\n")
    seg = t[i:i + 2000].split("\n")
    comment = [x for x in seg if len(x) > 40 and not x.startswith("[")]
    grade = next((x for x in seg[5:] if re.fullmatch(r"[SABCD][+-]?", x)), None)
    ev = dict(NICT_EVAL)
    ev["summary_quote"] = quote(comment[0]) if comment else "未取得"
    ev["score"] = f"総合評価 {grade}（終了評価結果（概要）の表の「総合評価」欄）" if grade else "未取得"
    return ev


def jst_program():
    url = "https://www.jst.go.jp/kisoken/crest/project/1111128/1111128_2025.html"
    t = html_text(fetch(url))
    t = re.sub(r"\n\s*", "\n", t)
    awards = []
    for m in re.finditer(r"\n([^\n]+)\nグラント番号：(\S+)\n研究代表者：\n([^\n]+)\n([^\n]+)\n(.*?)(?:\n主たる共同研究者\n(.*?))?\n研究概要", t, re.S):
        co = (m.group(6) or "").split("\n")
        pairs = [f"{co[k + 1]}（{co[k]}）" for k in range(0, len(co) - 1, 2)] if m.group(6) else []
        awards.append({"org": m.group(4), "lead_researcher": m.group(3), "grant_no": m.group(2),
                       "co_orgs": pairs, "theme": m.group(1), "amount": "未取得",
                       "note": "org は研究代表者の所属機関。co_orgs は主たる共同研究者の「所属（氏名）」"})
    area = html_text(fetch("https://www.jst.go.jp/kisoken/crest/research_area/bunya2025-2.html"))
    area = [l.strip() for l in area.split("\n") if l.strip()]
    i = area.index("研究総括")
    adv_i = area.index("領域アドバイザー")
    end = area.index("採択課題一覧")
    adv = area[adv_i + 1:end]
    advisers = [f"{adv[k]}（{adv[k + 1]}）" for k in range(0, len(adv) - 1, 2)]
    youryou = "https://www.jst.go.jp/kisoken/crest/application/pdf/2025youkou.pdf"
    yt = open(fetch(youryou)[:-4] + ".txt", encoding="utf-8", errors="replace").read().split("\n")
    s = next(k for k, l in enumerate(yt) if "選考に関わる者の利益相反マネジメント" in l)
    e = next(k for k in range(s, len(yt)) if "その他 JST が利害関係者と判断した者" in yt[k])
    coi = "".join(l.strip() for l in yt[s:e + 1] if l.strip() and not re.fullmatch(r"\d+|第 5 章.*", l.strip()))
    return {
        "id": "jst-crest-2025-real-world-intelligence", "agency": "JST",
        "name": "戦略的創造研究推進事業 CREST 研究領域「実環境知能システムを実現する基礎理論と基盤技術の創出」2025年度採択課題",
        "parent_project": "戦略的創造研究推進事業（CREST）",
        "call_period": "2025年4月8日（研究提案の募集開始）～2025年6月3日正午（CREST 受付締切）",
        "award_date": "2025年9月18日（科学技術振興機構報 第1793号）",
        "applications": "未取得（領域別の応募件数は未取得。機構報はCREST全体で826件の応募、60件採択と記載）",
        "source_title": "[実環境知能システム] 2025年度採択課題 | CREST",
        "source_url": url,
        "related_urls": ["https://www.jst.go.jp/pr/info/info1793/index.html",
                         "https://www.jst.go.jp/kisoken/crest/research_area/bunya2025-2.html"],
        "awards": awards,
        "review": {"committee": {"type": "研究総括が領域アドバイザーらの協力を得ながら選考（機構報の記載）",
                                 "research_supervisor": f"{area[i + 1]}（{area[i + 2]}）",
                                 "advisers": advisers,
                                 "list_url": "https://www.jst.go.jp/kisoken/crest/research_area/bunya2025-2.html"},
                   "criteria_url": youryou, "criteria_note": "2025年度 戦略的創造研究推進事業（CREST・さきがけ・ACT-X）募集要項"},
        "coi": {"status": "あり", "documents": [{"title": "2025年度 戦略的創造研究推進事業 募集要項 5.1.1 ①選考に関わる者の利益相反マネジメント",
                                                 "url": youryou, "text": coi}]},
    }


def nict_program():
    url = "https://www.nict.go.jp/press/2018/05/31-1.html"
    t = html_text(fetch(url))
    for s in ["国立大学法人東京工業大学", "株式会社時事通信社", "村上仁己", "平成30年4月16日（月）から平成30年5月11日（金）"]:
        assert s in t, s
    return {
        "id": "nict-2018-multilingual-dl", "agency": "NICT（総務省所管）",
        "name": "高度通信・放送研究開発委託研究／多言語音声翻訳高度化のためのディープラーニング技術の研究開発（課題197）",
        "parent_project": "高度通信・放送研究開発委託研究",
        "call_period": "平成30年4月16日（月）～平成30年5月11日（金）",
        "award_date": "2018年5月31日（ニュースリリース日）",
        "applications": "未取得",
        "project_period": "平成30年度から平成32年度まで（3年間）",
        "source_title": "平成30年度新規委託研究（1課題）の受託者を決定",
        "source_url": url,
        "related_urls": ["https://www.nict.go.jp/collabo/commission/k_197.html", "https://www.nict.go.jp/press/2018/04/16-1.html"],
        "awards": [{"org": "国立大学法人東京工業大学", "co_orgs": ["国立大学法人東京大学", "国立大学法人愛媛大学", "日本放送協会",
                                                       "一般財団法人NHKエンジニアリングシステム", "株式会社時事通信社"],
                    "theme": "深層学習によるマルチモーダル文脈理解と機械翻訳の高度化", "amount": "未取得",
                    "note": "ニュースリリースで「○印： 代表研究者」が付いているのは国立大学法人東京工業大学"}],
        "review": {"committee": "学識経験者で構成される評価委員会（委員長: 村上仁己 成蹊大学元教授）。委員名簿は未取得",
                   "criteria_url": "未取得"},
        "coi": {"status": "公表資料では確認できなかった", "documents": [],
                "note": "取得したのはニュースリリースと終了評価ページのみ。公募要領は未取得"},
    }


def build():
    out_programs = []
    total_awards = 0
    for p in PROGRAMS:
        p = dict(p)
        src_txt = None
        if p.get("list_url"):
            src_txt = squash(raw_text(p["list_url"]))
        else:
            src_txt = re.sub(r"※\d+", "", squash(html_text(fetch(p["source_url"]))))  # 注釈記号を除いて照合
        for a in p["awards"]:
            for o in ([a["org"]] if a["org"] != UNK_LEAD else []) + a.get("orgs_listed", []) + [re.sub(r"（【.*?】）$", "", c) for c in a["co_orgs"]]:
                assert squash(o) in src_txt, (p["id"], "org", o)
            assert squash(a["theme"]) in src_txt, (p["id"], "theme", a["theme"])
        # 実施体制決定ページの応募件数・日付を照合
        page = squash(html_text(fetch(p["source_url"])))
        if p.get("applications", "未取得") != "未取得":
            assert squash(p["applications"]) in page, (p["id"], p["applications"])
        assert squash(p["award_date"].split("（")[0]) in page, (p["id"], p["award_date"])
        if p.get("call_url") and p.get("call_period", "未取得") != "未取得":
            ct = squash(html_text(fetch(p["call_url"])))
            assert squash(p["call_period"]) in ct, (p["id"], p["call_period"])
        cp = p.pop("committee_pdf")
        yy = p.pop("youryou")
        if cp:
            review = {"committee": committee(cp)}
        else:
            review = {"committee": "未取得"}
        if yy:
            review["criteria_url"] = yy if has_criteria(yy) else "未取得"
            review["criteria_note"] = "公募要領（「審査基準」の節）"
            mt = review_method_text(yy)
            if mt:
                review["method_text"] = mt
            text = coi_from_youryou(yy)
            p["coi"] = {"status": "あり" if text else "公表資料では確認できなかった",
                        "documents": ([{"title": "公募要領「（※）利害関係の確認について」", "url": yy, "text": text}] if text else [])}
        else:
            review["criteria_url"] = "未取得"
            p["coi"] = {"status": "未取得", "documents": [],
                        "note": "この公募の公募要領・採択審査委員名簿は取得していない。下の文書は研究評価委員会の評価に適用される規程で、採択審査のものではない"}
        p["review"] = review
        p["coi"]["documents"].append({
            "title": NEDO_EVAL_RULE["title"] + "（評価における利害関係者の排除。研究評価委員会の評価に適用）",
            "url": NEDO_EVAL_RULE["url"], "text": nedo_eval_rule_text()})
        out_programs.append(p)
        total_awards += len(p["awards"])
    out_programs.append(jst_program())
    out_programs.append(nict_program())
    evals = build_evaluations()
    for e in evals:
        if e["url"].endswith("100935449.pdf"):
            e["note"] = "公表PDFの評点表の値（平均値・各委員の素点）は、P18002 中間評価報告書（100935431.pdf）の評点表と同一（2026-11-05 にPDFの該当ページを目視確認）。"
    evals += meti_post5g_eval()
    evals.append(nict_eval())
    data = {
        "fetched_at": datetime.date.today().isoformat(),
        "notes": [
            "公表資料（nedo.go.jp, meti.go.jp, jst.go.jp, nict.go.jp）から取得。原資料は raw/nedo/ に保存。",
            "採択額は、個別の採択先ごとの金額が公表資料に見当たらないため amount は「未取得」。公募要領の予算規模の記載は budget_in_call に原文で入れた。",
            "法人名・テーマ名は実施予定先一覧PDFの表記どおり（PDFから抽出した文字列。改行のみ除去）。build() で原資料の本文と機械照合済み。",
            "代表・共同の区別が公表されていない併記は org を「未取得（代表の区別は公表なし）」とし orgs_listed に全者を入れた。",
            "NEDO 実施体制決定ページの採択審査委員会委員一覧は review.committee（氏名のみ。所属は list_url のPDF）。",
        ],
        "programs": out_programs,
        "evaluations": evals,
        "evaluation_rules": [{"title": NEDO_EVAL_RULE["title"], "url": NEDO_EVAL_RULE["url"], "text": nedo_eval_rule_text()},
                             {"title": "NEDO 技術評価実施規程", "url": C(100794847)},
                             {"title": "NEDO 事業評価実施規程", "url": C(100794848)}],
    }
    out = os.path.join(ROOT, "data", "awards.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"programs={len(out_programs)} nedo_awards={total_awards} evaluations={len(evals)} -> {out}")


def nedo_eval_rule_text():
    t = open(fetch(NEDO_EVAL_RULE["url"])[:-4] + ".txt", encoding="utf-8", errors="replace").read().split("\n")
    s = next(k for k, l in enumerate(t) if "評価における利害関係者の排除" in l)
    e = next(k for k in range(s, len(t)) if "その他機構が利害関係者と判断した者" in t[k])
    return "\n".join(re.sub(r"\s+", " ", l).strip() for l in t[s:e + 1] if l.strip())


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "build":
    build()
