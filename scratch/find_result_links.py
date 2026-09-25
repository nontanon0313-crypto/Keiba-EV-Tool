"""RaceList.do から結果・払戻ページへのリンクhrefを抽出。"""
import re
from bs4 import BeautifulSoup

path = "debug_html/probe_RaceList_do.html"
with open(path, encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

print("=== 'レース結果' を含む全 <a> タグ ===")
for a in soup.find_all("a"):
    txt = a.get_text(strip=True)
    if "結果" in txt or "払戻" in txt:
        print(f"  txt='{txt}' href='{a.get('href')}' onclick='{a.get('onclick')}'")

print("\n=== 'RaceResult' を含む文字列を行番号付き ===")
for m in re.finditer(r'[^"\']*RaceResult[^"\']*', html):
    print(f"  {m.group(0)[:200]}")

print("\n=== 'Payback' / 'Haraido' / 'Result' を含む href ===")
for a in soup.find_all("a", href=True):
    h = a["href"]
    if any(k in h for k in ("Result", "Payback", "Haraido", "Result", "result")):
        print(f"  txt='{a.get_text(strip=True)}' href='{h}'")

print("\n=== form の action ===")
for form in soup.find_all("form"):
    print(f"  action='{form.get('action')}' method='{form.get('method')}'")

print("\n=== 'RaceList.do' を含む href の種類（重複除去） ===")
hrefs = set()
for a in soup.find_all("a", href=True):
    h = a["href"]
    if "RaceList.do" in h or "do?" in h:
        hrefs.add(h)
for h in sorted(hrefs)[:30]:
    print(f"  {h}")

print("\n=== onchange / onclick に 'do' を含む ===")
for el in soup.find_all(attrs={"onchange": True}):
    oc = el.get("onchange")
    if "do" in oc.lower():
        print(f"  tag={el.name} onchange={oc[:160]}")

print("\n=== 印刷画面 / 結果ボタン周辺のテキスト ===")
body = soup.get_text(" ", strip=True)
for kw in ["レース結果", "払戻金一覧", "成績", "確定"]:
    idx = body.find(kw)
    if idx >= 0:
        print(f"  '{kw}': ...{body[max(0,idx-40):idx+80]}...")
