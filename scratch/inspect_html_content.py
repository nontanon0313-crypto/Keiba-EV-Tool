"""読み取り専用: 保存済みHTMLの内容を確認。"""
import os
import re
from bs4 import BeautifulSoup

path = "debug_html/shutuba_nar-20230101-43-1.html"
if not os.path.exists(path):
    print(f"[NG] {path} が無い")
    raise SystemExit

with open(path, encoding="utf-8") as f:
    html = f.read()

print(f"=== file size: {len(html)} ===")
print(f"=== title ===")
soup = BeautifulSoup(html, "html.parser")
t = soup.find("title")
print(f"  {t.get_text(strip=True) if t else '(no title)'}")

print(f"\n=== 既知の馬名が含まれるか ===")
for name in ["フークサプライズ", "ハートマン", "スズカソブリン", "カツゲキツチノエネ"]:
    print(f"  {name}: {'YES' if name in html else 'NO'}")

print(f"\n=== 馬番らしき数字列のパターン ===")
for pat in [
    r'raceNb=(\d+)',
    r'RaceList\.do',
    r'Shutuba\.do',
    r'ent1',
    r'tb22',
    r'tb03',
    r'horse_name',
    r'馬名',
    r'出走',
    r'枠',
    r'馬番',
]:
    n = len(re.findall(pat, html))
    print(f"  {pat}: {n}")

print(f"\n=== 全table内のテキスト最初の60文字 ===")
for i, tb in enumerate(soup.find_all("table")):
    txt = tb.get_text(" ", strip=True)
    print(f"  [{i}] class={tb.get('class')} txt={txt[:160]}")

print(f"\n=== body先頭2000文字 (タグ除去後) ===")
body = soup.find("body")
txt = body.get_text(" ", strip=True) if body else html
print(txt[:2000])
