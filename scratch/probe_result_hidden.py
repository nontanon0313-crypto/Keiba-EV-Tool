"""RaceResult.doの200ケース中身と、RaceList.doのhidden inputを使った試行。"""
import os
import re
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/RaceList.do?raceDy=20230101&opTrackCd=43&sponsorCd=43&raceNb=1",
}

# 1) RaceList.do から hidden input を抽出
with open("debug_html/probe_RaceList_do.html", encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "html.parser")

print("=== RaceList.do の hidden input ===")
hidden = {}
for inp in soup.find_all("input"):
    name = inp.get("name")
    val = inp.get("value")
    typ = inp.get("type")
    if name:
        hidden[name] = val
        print(f"  name={name} type={typ} value={val}")

print("\n=== 20260923 RaceResult.do 200 の中身 ===")
p = "debug_html/probe_more_with_result_extra.html"
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        h2 = f.read()
    s2 = BeautifulSoup(h2, "html.parser")
    print(f"  len={len(h2)}")
    print(f"  title: {s2.find('title').get_text(strip=True) if s2.find('title') else ''}")
    print(f"  tables: {len(s2.find_all('table'))}")
    for i, tb in enumerate(s2.find_all("table")):
        txt = tb.get_text(" ", strip=True)
        print(f"  [{i}] class={tb.get('class')} rows={len(tb.find_all('tr'))} txt={txt[:200]}")

# 2) hidden input 付きで 20230101 の RaceResult.do
print("\n=== hidden input 付き試行 ===")
date = "20230101"
track_cd = "43"
sponsor_cd = "43"
race_nb = 1

base = f"https://www.oddspark.com/keiba/RaceResult.do"

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    # まずRaceList経由でセッション
    c.get(f"https://www.oddspark.com/keiba/RaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}")

    trials = [
        ("with_joCode_raceNo",
         base + f"?joCode={hidden.get('joCode')}&raceNo={hidden.get('raceNo')}&kaisaiBi={hidden.get('kaisaiBi')}&kyougiKubun={hidden.get('kyougiKubun')}&raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
        ("with_kaisaiBi",
         base + f"?kaisaiBi={hidden.get('kaisaiBi')}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"),
        ("post_form",
         base),
    ]

    for name, url in trials:
        print(f"\n  --- {name} ---")
        try:
            if name == "post_form":
                data = {
                    "joCode": hidden.get("joCode"),
                    "raceNo": hidden.get("raceNo"),
                    "kaisaiBi": hidden.get("kaisaiBi"),
                    "kyougiKubun": hidden.get("kyougiKubun"),
                    "raceDy": date,
                    "opTrackCd": track_cd,
                    "sponsorCd": sponsor_cd,
                    "raceNb": race_nb,
                }
                r = c.post(url, data={k: v for k, v in data.items() if v})
            else:
                r = c.get(url)
            s3 = BeautifulSoup(r.text, "html.parser")
            t = s3.find("title")
            tt = t.get_text(strip=True) if t else ""
            tables = s3.find_all("table")
            has_haraido = "払戻" in r.text
            has_finish = bool(re.search(r'>\s*1着\s*<|着順', r.text))
            has_horse = "フークサプライズ" in r.text
            print(f"    status={r.status_code} len={len(r.text)}")
            print(f"    title: {tt[:80]}")
            print(f"    払戻={has_haraido} 着順={has_finish} 馬名={has_horse} tables={len(tables)}")
            print(f"    tclasses: {[t.get('class') for t in tables][:6]}")
            if r.status_code == 200 and len(r.text) > 5000:
                fname = f"debug_html/probe_hidden_{name}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(r.text)
                print(f"    saved: {fname}")
        except Exception as e:
            print(f"    ERROR: {e}")
