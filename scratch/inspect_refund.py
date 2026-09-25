"""RaceRefund.do と未来RaceResult の中身を確認。"""
from bs4 import BeautifulSoup

print("===== 1) RaceRefund.do =====")
path = "debug_html/probe_correct_RaceRefund_venue.html"
with open(path, encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "html.parser")
print(f"  html len: {len(html)}")
# 全タグ種別と件数
from collections import Counter
tags = Counter(t.name for t in soup.find_all())
print(f"  tags: {dict(tags)}")
# body テキスト
body = soup.find("body")
txt = body.get_text("\n", strip=True) if body else soup.get_text("\n", strip=True)
print(f"  body text len: {len(txt)}")
print(f"  --- body text 先頭3000文字 ---")
print(txt[:3000])
# scriptタグの中身
print(f"\n  --- script タグ ---")
for i, sc in enumerate(soup.find_all("script")):
    s = sc.string or ""
    if len(s) > 20:
        print(f"  script[{i}] len={len(s)}")
        print(f"    {s[:400]}")

print("\n===== 2) 20260923 の RaceResult.do =====")
path2 = "debug_html/probe_more_with_result_extra.html"
import os
if os.path.exists(path2):
    with open(path2, encoding="utf-8") as f:
        h2 = f.read()
    s2 = BeautifulSoup(h2, "html.parser")
    print(f"  title: {s2.find('title').get_text(strip=True) if s2.find('title') else ''}")
    print(f"  tables: {len(s2.find_all('table'))}")
    for i, tb in enumerate(s2.find_all("table")):
        print(f"  [{i}] class={tb.get('class')} rows={len(tb.find_all('tr'))}")
    bt = s2.find("body")
    t2 = bt.get_text("\n", strip=True) if bt else s2.get_text("\n", strip=True)
    print(f"  body text 先頭2000:")
    print(t2[:2000])
