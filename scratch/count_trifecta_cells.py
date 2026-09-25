"""hn=4 の3連単HTMLで実際にオッズが何点表示されているか数える。"""
import re
from bs4 import BeautifulSoup

for hn in [4, 7]:
    path = f"debug_html/trifecta_hn{hn}.html"
    with open(path, encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")

    print(f"\n===== hn={hn} =====")
    # オッズは 'tb73 w100pr' テーブル群に行列で入っている
    tables = soup.select("table.tb73")
    print(f"  tb73 テーブル数: {len(tables)}")
    total_cells = 0
    cells_with_num = 0
    dash_cells = 0
    empty_cells = 0
    samples = []
    for ti, tb in enumerate(tables):
        rows = tb.find_all("tr")
        for ri, row in enumerate(rows):
            cells = row.find_all(["td", "th"])
            for ci, c in enumerate(cells):
                txt = c.get_text(" ", strip=True)
                total_cells += 1
                if re.match(r'^\d+\.?\d*$', txt):
                    cells_with_num += 1
                    if len(samples) < 20:
                        samples.append((ti, ri, ci, txt))
                elif txt in ("-", "—", "‑", "−"):
                    dash_cells += 1
                elif not txt:
                    empty_cells += 1
    print(f"  総セル: {total_cells}")
    print(f"  数値セル: {cells_with_num}")
    print(f"  ダッシュ: {dash_cells}")
    print(f"  空欄: {empty_cells}")
    print(f"  サンプル(数値): {samples[:10]}")

    # 1つの tb73 テーブルを可視化
    if tables:
        tb = tables[0]
        print(f"\n  table[0] の内容:")
        for ri, row in enumerate(tb.find_all("tr")[:3]):
            cells = row.find_all(["td", "th"])
            texts = [c.get_text(" ", strip=True)[:8] for c in cells]
            print(f"    row{ri} n={len(cells)}: {texts}")
