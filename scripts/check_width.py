#!/usr/bin/python3
"""端末幅（320/360/390）で開き、documentElement.scrollWidth が幅を超えないかを実測する。スクショは outputs/shots/。
使い方: check_width.py <ベースURL> <パス>..."""
import os, sys
from playwright.sync_api import sync_playwright
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'outputs', 'shots')
os.makedirs(OUT, exist_ok=True)
base, paths = sys.argv[1].rstrip('/'), sys.argv[2:]
bad = 0
with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (320, 360, 390):
        ctx = b.new_context(viewport={'width': w, 'height': 800}, device_scale_factor=1, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        for path in paths:
            pg.goto(base + path, wait_until='domcontentloaded', timeout=60000)
            sw = pg.evaluate('document.documentElement.scrollWidth')
            wide = pg.evaluate('''(w)=>[...document.querySelectorAll("body *")].filter(e=>{const r=e.getBoundingClientRect();return r.right>w+1&&r.width>0&&getComputedStyle(e).position!=="fixed"}).slice(0,5).map(e=>e.tagName+"."+e.className+" "+Math.round(e.getBoundingClientRect().right))''', w)
            name = path.strip('/').replace('/', '_') or 'top'
            try:
                pg.screenshot(path=os.path.join(OUT, f'{name}_{w}.png'), full_page=False, timeout=15000)
            except Exception as e:
                print('  (スクショ失敗)', str(e)[:60])
            ok = sw <= w
            bad += not ok
            print(w, path, 'scrollWidth', sw, 'OK' if ok else 'NG', '' if ok else wide)
        ctx.close()
    b.close()
sys.exit(1 if bad else 0)
