"""RaceList.do 内に着順・払戻があるか徹底確認。"""
import re
from bs4 import BeautifulSoup

path = "debug_html/probe_RaceList_do.html"
with open(path, encoding="utf-8") as f:
    html = f.read()

print(f"=== len={len(html)} ===")
soup = BeautifulSoup(html, "html.parser")

print("\n=== '着順' '払戻' '確定' を含む要素の親 ===")
for kw in ["着順", "払戻", "確定", "レース結果"]:
    print(f"\n--- '{kw}' ---")
    for m in re.finditer(kw, html):
        i = m.start()
        # 前後300文字
        seg = html[max(0,i-150):i+250]
        # タグを整理
        seg2 = re.sub(r'\s+', ' ', seg)
        print(f"  @{i}: {seg2[:400]}")

print("\n=== id/class 一覧 ===")
ids = {}
for el in soup.find_all(attrs={"id": True}):
    ids[el["id"]] = el.name
print(f"  ids: {list(ids.items())[:50]}")

print("\n=== table 全部 (class と行数と先頭テキスト) ===")
for i, tb in enumerate(soup.find_all("table")):
    txt = tb.get_text(" ", strip=True)
    print(f"  [{i}] class={tb.get('class')} id={tb.get('id')} rows={len(tb.find_all('tr'))} txt={txt[:120]}")

print("\n=== div の class 全部 ===")
classes = {}
for el in soup.find_all(["div", "section"]):
    c = el.get("class")
    if c:
        key = " ".join(c)
        classes[key] = classes.get(key, 0) + 1
for k, v in sorted(classes.items(), key=lambda x: -x[1])[:30]:
    print(f"  {k}: {v}")
