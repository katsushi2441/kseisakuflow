#!/usr/bin/python3
"""GENIAC の公開モデルのモデルカードに、何が書かれているかを数える（2026-11-06）。→ data/model_card_audit.json

二本松哲也さん（@t_nihonmatsu）の「モデルの出自だけでなく、学習データの来歴、調整内容、評価基準、セキュリティや
バイアスの検証結果も重要。独立した第三者が検証できるように」という返信を受けて、
**何が公開され、何が不足しているか**を、モデルカード（Hugging Face の README とメタデータ）の記載の有無で並べる。

- 対象: data/outcomes.json に載っている GENIAC の公開モデル（kind=model）。
- 材料: fetch_outcomes.py が保存した Hugging Face 公開API の応答（cardData・tags）と README（raw/outcomes/ のキャッシュ）。
- 判定は機械的。項目ごとに「メタデータの欄」か「README の見出し・語」で当て、当てた根拠（欄名か見出しの行）を残す。
  **記載の有無を数えるだけで、内容の良し悪し・十分さは判定しない。** 記載が無い＝やっていない、ではない。

  /usr/bin/python3 scripts/model_card_audit.py
"""
import json, os, re, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_outcomes as FO  # noqa: E402  キャッシュ（raw/outcomes/）をそのまま使う

TODAY = time.strftime('%Y-%m-%d')

# 項目: (キー, 画面の名前, メタデータで当てる関数, README の見出しで当てる正規表現)
HEAD = r'^\s{0,3}#{1,6}\s*(?:\d+[.\s]*)?'
ITEMS = [
    ('base', '元のモデル（出自）',
     lambda cd, tags: ('base_model', cd.get('base_model')) if cd.get('base_model') else None,
     HEAD + r'.*(base model|ベースモデル|元のモデル|基盤モデル)'),
    ('data', '学習データ',
     lambda cd, tags: ('datasets', cd.get('datasets')) if cd.get('datasets') else
                      (('tags', [t for t in tags if t.startswith('dataset:')]) if any(t.startswith('dataset:') for t in tags) else None),
     HEAD + r'.*(training data|train(ing)? dataset|datasets?|学習データ|訓練データ|データセット|コーパス|corpus|pre-?training data)'),
    ('tuning', '調整の内容（学習の手順）',
     lambda cd, tags: None,
     HEAD + r'.*(training procedure|training details|fine-?tun|post-?train|instruction tun|preference (optimization|tuning)|学習方法|学習手順|学習の詳細|ファインチューニング|事後学習|追加学習|指示学習)'),
    ('eval', '評価（ベンチマーク）',
     lambda cd, tags: ('model-index', len(cd.get('model-index') or [])) if cd.get('model-index') else None,
     HEAD + r'.*(evaluation|benchmark|results|performance|評価|ベンチマーク|性能)'),
    ('safety', 'リスク・バイアス・制限',
     lambda cd, tags: None,
     HEAD + r'.*(bias|risk|limitation|safety|ethical|responsible|out-of-scope|バイアス|リスク|制限|限界|安全|倫理|注意事項|免責)'),
    ('license', 'ライセンス',
     lambda cd, tags: ('license', cd.get('license')) if cd.get('license') else None,
     None),
]


def models():
    d = json.load(open(os.path.join(ROOT, 'data', 'outcomes.json'), encoding='utf-8'))
    found = {}

    def walk(x, org=None):
        if isinstance(x, dict):
            o = x.get('org') or x.get('name') if ('hf_models' in x) else org
            if x.get('kind') == 'model' and 'base_models' in x and x.get('id'):
                found.setdefault(x['id'], {'id': x['id'], 'url': x.get('url'), 'org': org, 'license': x.get('license'),
                                           'downloads_all': x.get('downloads_all'), 'created': x.get('created')})
            for v in x.values():
                walk(v, o)
        elif isinstance(x, list):
            for v in x:
                walk(v, org)
    walk(d)
    return list(found.values())


def audit(m):
    api = FO.hf_model(m['id']) or {}
    cd = api.get('cardData') or {}
    tags = api.get('tags') or []
    readme = FO.get_text('https://huggingface.co/' + m['id'] + '/raw/main/README.md', 'hf_readme') or ''
    body = re.sub(r'^---\n.*?\n---\n', '', readme, flags=re.S)   # 先頭のメタデータ（YAML）は除く
    heads = [l.strip() for l in body.splitlines() if re.match(r'^\s{0,3}#{1,6}\s', l)]
    out = {**m, 'gated': api.get('gated'), 'readme_chars': len(body.strip()), 'has_readme': bool(body.strip()), 'items': {}}
    for key, label, meta, rx in ITEMS:
        hit = None
        mm = meta(cd, tags)
        if mm:
            hit = {'by': 'meta', 'field': mm[0], 'value': mm[1] if not isinstance(mm[1], list) else mm[1][:5]}
        elif rx:
            for h in heads:
                if re.search(rx, h, re.I):
                    hit = {'by': 'readme', 'heading': h[:120]}
                    break
        if not hit and rx and not out['has_readme'] and api.get('gated'):
            hit = {'by': 'gated'}   # 利用申請が要るモデルで README を読めない＝記載の有無を確かめられない（「記載なし」に数えない）
        out['items'][key] = hit
    return out


def main():
    ms = models()
    rows = [audit(m) for m in ms]
    rows.sort(key=lambda r: (-(sum(1 for v in r['items'].values() if v and v.get('by') != 'gated')), r['id']))
    yes = lambda v: bool(v) and v.get('by') != 'gated'
    summary = {k: sum(1 for r in rows if yes(r['items'][k])) for k, *_ in ITEMS}
    unknown = {k: sum(1 for r in rows if (r['items'][k] or {}).get('by') == 'gated') for k, *_ in ITEMS}
    gated = sum(1 for r in rows if r['gated'] and not r['has_readme'])
    res = {'generated_at': TODAY, 'n': len(rows), 'summary': summary, 'unknown': unknown, 'gated_unreadable': gated,
           'items': [{'key': k, 'label': l} for k, l, *_ in ITEMS],
           'rule': 'Hugging Face のモデルカード（メタデータの欄と README の見出し）に、その項目の記載があるかを機械的に判定。'
                   '元のモデル＝base_model 欄か見出し、学習データ＝datasets 欄・dataset タグか見出し、評価＝model-index 欄か見出し、'
                   'リスク・バイアス・制限＝見出し、調整の内容＝見出し、ライセンス＝license 欄。記載の有無だけを数え、内容の十分さは判定しない。'
                   '記載が無いことは、その作業をしていないことを意味しない（論文や別のページに書かれている場合がある）。',
           'source': 'Hugging Face Hub 公開API（cardData・tags）と各モデルの README.md（取得日は data/outcomes.json と同じ）',
           'models': rows}
    p = os.path.join(ROOT, 'data', 'model_card_audit.json')
    json.dump(res, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('models', len(rows), summary, 'unknown', unknown, 'gated', gated, '→', p)


if __name__ == '__main__':
    main()
