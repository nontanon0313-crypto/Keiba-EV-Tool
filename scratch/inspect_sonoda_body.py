"""園田結果ページの body 全文とタグ構成を確認。"""
from bs4 import BeautifulSoup
from collections import Counter

path = "debug_html/sonoda_result_51_1.html"
with open(path, encoding="utf-8") as f:
    html = f.read()

print(f"len={len(html)}")
soup = BeautifulSoup(html, "html.parser")

tags = Counter(t.name for t in soup.find_all())
print(f"tags: {dict(tags)}")

body = soup.find("body")
txt = body.get_text("\n", strip=True) if body else soup.get_text("\n", strip=True)
print(f"\n=== body text (全 {len(txt)}文字) ===")
print(txt)

print("\n=== iframe / script src ===")
for i, ifr in enumerate(soup.find_all("iframe")):
    print(f"  iframe[{i}] src={ifr.get('src')}")
for i, sc in enumerate(soup.find_all("script")):
    s = sc.string or ""
    src = sc.get("src")
    if src:
        print(f"  script[{i}] src={src}")
    elif len(s) > 50:
        print(f"  script[{i}] inline len={len(s)} head: {s[:200]}")

print("\n=== 園田(51) と 名古屋(43) の結果ページ差分 ===")
path2 = "debug_html/result_minipay_sample.html"
import os
if os.path.exists(path2):
    with open(path2, encoding="utf-8") as f:
        h2 = f.read()
    print(f"  名古屋: len={len(h2)} tables={BeautifulSoup(h2,'html.parser').find_all('table').__len__()}")
    print(f"  園田:   len={len(html)} tables={len(soup.find_all('table'))}")
