# kseisakuflow — Kurage 政策の流れトラッカー

政策が「どの会議で形づくられ → どれだけ予算がつき → だれに採択され → どう実施され → どう評価されたか」を、
公表資料だけでつないで並べるデータ作り。画面は国会トラッカーの中（xb4g/giin の lib/flow_pages.php・lib/flow_koho.php）。

- 公開: https://xb4g.com/giin/flow/ （分野: /flow/ai・/flow/koho）
- しないこと: 利益相反の有無の判断、事業・組織・人の評価、推測。同じ名前が両方に出るものを「出る」と並べるだけ。

## 分野の設定（fields/<分野>.json）

| 型 | 例 | 作るスクリプト |
|---|---|---|
| 会議→予算→採択→評価（既定） | fields/ai.json | scripts/build_flow.py |
| 契約を集める（`"type": "contracts"`） | fields/koho.json | scripts/build_koho.py |

分野を足すときは fields/ に設定を1つ足し、対応するスクリプトを回す（防災・子育てなど）。

## 作り直し

```bash
# 1. 原資料（raw/ は /mnt/data/kseisakuflow/raw への symlink。約860MB）
#    RS の CSV: https://rssystem.go.jp/files/<年度>/rs/<ファイル名>.zip を raw/rs<年度>/ に落として展開
#    （ファイル名は 1-2_RS_<年度>_基本情報_事業概要等 など。download-csv の画面の JS から読み取った型）
/usr/bin/python3 scripts/fetch_cao.py           # 内閣府の AI 関係の会議資料 → raw/cao/
/usr/bin/python3 scripts/build_councils.py      # → data/councils.json（名簿・開催・提言・利益相反の定め）
/usr/bin/python3 scripts/fetch_nedo.py build    # NEDO 等の採択・審査・評価 → data/awards.json
/usr/bin/python3 scripts/index_cao_pages.py     # 会議資料を1ページずつ文字に → raw/cao_pages.jsonl
/usr/bin/python3 scripts/fetch_kokkai.py ai     # 事業ごとの国会の発言（fields/ai.json の kokkai_terms）
/usr/bin/python3 scripts/fetch_outcomes.py all   # 採択先ごとの成果 → data/outcomes.json（下の「採択先の成果」）
# 2. 分野のデータ（--copy で xb4g/giin/data/flow/ へ写す）
/usr/bin/python3 scripts/build_flow.py ai --copy
/usr/bin/python3 scripts/build_koho.py koho --copy
# 3. カード画像と公開（xb4g 側）
cd ../xb4g/giin && /usr/bin/python3 scripts/make_ogp_flow.py
/usr/bin/python3 scripts/deploy.py --only lib/flow_pages.php lib/flow_koho.php data/flow img/og/flow.png img/og/flow-ai.png img/og/flow-koho.png
```

## 採択先の成果（2026-11-05）

採択先ごとに、公開モデル・データセット（Hugging Face 公開API）、論文（OpenAlex・ROR）、公表されたベンチマークの値、
経済産業省の中間評価報告書（案）の進捗表の記載を並べる。画面は xb4g の lib/flow_outcomes.php（/flow/ai/outcomes と、分野・事業ページの節）。

- 成果物の一覧は経済産業省 GENIAC の成果公開ページ（第2期・第3期）。Hugging Face のアカウントは、そのページか採択先の公式発表に載っているものだけ（data/outcome_sources.json の hf_accounts と根拠のURL）。アカウントの他のモデルは、モデルカードに GENIAC の記載があるものだけ。
- 論文は OpenAlex の助成番号（awards.funder_award_id。JPNP20017 など）と、ROR で機関を確かめた採択先の機関全体のAI論文（主題 1702/1707）。P20017 は通信・半導体の公募も含むので、AI 分野と採択日以降で絞る。
- ベンチマークは公表値だけ（第1期の性能評価の表は画像から転記・NII の発表・成果公開ページの「特徴」欄でベンチマーク名と数値の両方がある文）。自分で測らない。
- 採択先ごとの配分額は公表資料で確認できない（RS の支出先は NEDO の基金1行）。資源効率は比べられないと画面に書く。
- 応答のキャッシュは raw/outcomes/。取り直しは `--refresh`（OpenAlex は鍵なしだと1日の上限が共有なので連打しない）。

## 確かめ方

- `scripts/render_local.php /giin/flow/ai` … CLI で描画（警告が出ないか）
- `php -S 127.0.0.1:<18300番台の空き> scripts/router_local.php` ＋ `scripts/check_width.py` … 320/360/390 のはみ出し

## 出典

行政事業レビュー見える化サイト（PDL1.0。「出典：行政事業レビュー見える化サイト」を加工して作成）、内閣府 科学技術・イノベーション推進事務局、
NEDO・経済産業省・JST・NICT の公表資料（出所を明示して引用）、国立国会図書館 国会会議録検索システム。
