"""馬の特徴量を走歴から抽出する。

データ漏洩防止のため、今回レース日より前の走歴のみを使う。
"""
import re
from datetime import datetime


_ZERO_WIDTH = "\u200b"
_CLASS_MAP = str.maketrans("ＡＢＣ１２３４５６７８９０", "ABC1234567890")


def _p_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip(), "%Y/%m/%d").date()
    except ValueError:
        return None


def _p_int(s):
    if s is None or s == "":
        return None
    try:
        return int(str(s).strip())
    except (ValueError, TypeError):
        return None


def _p_float(s):
    if s is None or s == "":
        return None
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def _p_time_sec(s):
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"(\d+):(\d+\.?\d*)", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(s)
    except ValueError:
        return None


def _p_distance(s):
    if not s:
        return None
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None


def _p_surface(s):
    if not s:
        return None
    if s.startswith("ダ"):
        return "ダート"
    if s.startswith("芝"):
        return "芝"
    if "障" in s:
        return "障害"
    return None


def _p_condition(s):
    if not s:
        return None
    for c in ("不良", "稍重", "重", "良"):
        if s.startswith(c):
            return c
    return None


def _p_class(name):
    if not name:
        return None, None
    t = name.translate(_CLASS_MAP)
    m = re.search(r"([ABC])([1-3])", t)
    if m:
        rank = m.group(1)
        num = int(m.group(2))
        order = {"A": 3, "B": 2, "C": 1}[rank] * 3 + (3 - num)
        return m.group(1) + m.group(2), order
    m = re.search(r"(\d)歳", t)
    if m:
        return m.group(1) + "歳", None
    if "新馬" in name:
        return "新馬", None
    return None, None


def _parse_row(row, hmap):
    def g(key):
        i = hmap.get(key)
        return row[i] if i is not None and i < len(row) else None
    p = {}
    p["date"] = _p_date(g("年月日"))
    p["venue"] = g("競馬場")
    p["race_name"] = g("レース名")
    dist_raw = g("距離")
    p["distance"] = _p_distance(dist_raw)
    p["surface"] = _p_surface(dist_raw)
    p["condition"] = _p_condition(g("馬場(天候)"))
    p["n_runners"] = _p_int(g("頭数"))
    p["frame"] = _p_int(g("枠番"))
    p["popularity"] = _p_int(g("人気"))
    p["finish"] = _p_int(g("着順"))
    p["weight"] = _p_float(g("負担重量"))
    p["horse_weight"] = _p_int(g("馬体重"))
    p["time_sec"] = _p_time_sec(g("タイム"))
    p["agari_3f"] = _p_float(g("上3F"))
    corner = g("通過順位")
    if corner:
        m = re.match(r"(\d+)", corner)
        p["first_corner"] = int(m.group(1)) if m else None
    else:
        p["first_corner"] = None
    cls, cls_order = _p_class(p["race_name"])
    p["cls"] = cls
    p["cls_order"] = cls_order
    return p


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _min_or_none(xs):
    xs = [x for x in xs if x is not None]
    return min(xs) if xs else None


def extract_features(horse_payload, race_date, race_info):
    feats = {}
    if not horse_payload:
        return feats
    hist = horse_payload.get("history") or {}
    header = hist.get("header") or []
    rows = hist.get("rows") or []
    if not header or not rows:
        return feats
    hmap = {}
    for i, h in enumerate(header):
        hmap[str(h).replace(_ZERO_WIDTH, "").strip()] = i
    parsed = []
    for row in rows:
        if len(row) < len(header):
            continue
        p = _parse_row(row, hmap)
        if p["date"] and p["date"] < race_date:
            parsed.append(p)
    parsed.sort(key=lambda x: x["date"], reverse=True)
    if not parsed:
        return feats

    # 通算
    finishes = [p["finish"] for p in parsed if p["finish"]]
    feats["n_starts"] = len(parsed)
    feats["n_wins"] = sum(1 for f in finishes if f == 1)
    feats["n_2nd"] = sum(1 for f in finishes if f == 2)
    feats["n_3rd"] = sum(1 for f in finishes if f == 3)
    if finishes:
        feats["win_rate"] = feats["n_wins"] / len(finishes)
        feats["place_rate"] = (feats["n_wins"] + feats["n_2nd"]) / len(finishes)
        feats["show_rate"] = (feats["n_wins"] + feats["n_2nd"] + feats["n_3rd"]) / len(finishes)
        feats["avg_finish"] = _avg(finishes)
    feats["avg_agari_3f"] = _avg([p["agari_3f"] for p in parsed])
    feats["best_agari_3f"] = _min_or_none([p["agari_3f"] for p in parsed])
    time_norms = [p["time_sec"] / p["distance"] * 1000 for p in parsed if p["time_sec"] and p["distance"]]
    feats["avg_time_norm"] = _avg(time_norms)
    feats["best_time_norm"] = _min_or_none(time_norms)

    # 直近
    recent5 = parsed[:5]
    recent3 = parsed[:3]
    feats["recent5_avg_finish"] = _avg([p["finish"] for p in recent5])
    feats["recent5_avg_agari"] = _avg([p["agari_3f"] for p in recent5])
    feats["recent5_avg_pop"] = _avg([p["popularity"] for p in recent5])
    feats["recent3_avg_finish"] = _avg([p["finish"] for p in recent3])
    feats["recent1_finish"] = recent5[0]["finish"] if recent5 else None
    feats["recent1_pop"] = recent5[0]["popularity"] if recent5 else None
    feats["recent1_agari"] = recent5[0]["agari_3f"] if recent5 else None

    # ローテーション
    days = (race_date - parsed[0]["date"]).days
    feats["days_since_last"] = days
    feats["is_renntou"] = 1 if days <= 7 else 0
    feats["is_long_break"] = 1 if days >= 90 else 0

    # 条件別
    cur_dist = race_info.get("distance")
    cur_cond = race_info.get("track_condition")
    cur_venue = race_info.get("venue")
    cur_surface = race_info.get("surface")
    if cur_dist:
        same_dist = [p for p in parsed if p["distance"] and abs(p["distance"] - cur_dist) <= 200]
        f = [p["finish"] for p in same_dist if p["finish"]]
        if f:
            feats["same_dist_n"] = len(f)
            feats["same_dist_place_rate"] = sum(1 for x in f if x <= 2) / len(f)
            feats["same_dist_avg_finish"] = _avg(f)
    if cur_cond:
        same_cond = [p for p in parsed if p["condition"] == cur_cond]
        f = [p["finish"] for p in same_cond if p["finish"]]
        if f:
            feats["same_cond_n"] = len(f)
            feats["same_cond_place_rate"] = sum(1 for x in f if x <= 2) / len(f)
    if cur_venue:
        same_venue = [p for p in parsed if p["venue"] and p["venue"].strip() == str(cur_venue).strip()]
        f = [p["finish"] for p in same_venue if p["finish"]]
        if f:
            feats["same_venue_n"] = len(f)
            feats["same_venue_place_rate"] = sum(1 for x in f if x <= 2) / len(f)
    if cur_surface:
        same_surf = [p for p in parsed if p["surface"] == cur_surface]
        f = [p["finish"] for p in same_surf if p["finish"]]
        if f:
            feats["same_surface_n"] = len(f)
            feats["same_surface_place_rate"] = sum(1 for x in f if x <= 2) / len(f)

    # クラス
    cur_cls, cur_cls_order = _p_class(race_info.get("race_name"))
    feats["current_class"] = cur_cls
    feats["current_class_order"] = cur_cls_order
    last_cls_order = parsed[0].get("cls_order") if parsed else None
    feats["last_class_order"] = last_cls_order
    if cur_cls_order is not None and last_cls_order is not None:
        feats["class_change"] = cur_cls_order - last_cls_order

    # 馬体重トレンド
    weights = [p["horse_weight"] for p in parsed[:5] if p["horse_weight"]]
    if weights:
        feats["recent_avg_horse_weight"] = sum(weights) / len(weights)
    # 馬体重変化
    if len(weights) >= 2:
        feats["horse_weight_trend"] = weights[0] - weights[-1]

    # 脚質（直近5走の最初の通過順位 / 頭数 の平均）
    corner_ratios = []
    for p in parsed[:5]:
        if p["first_corner"] and p["n_runners"]:
            corner_ratios.append(p["first_corner"] / p["n_runners"])
    if corner_ratios:
        feats["avg_corner_ratio"] = sum(corner_ratios) / len(corner_ratios)
        r = feats["avg_corner_ratio"]
        if r < 0.2:
            feats["style"] = "逃げ"
        elif r < 0.4:
            feats["style"] = "先行"
        elif r < 0.7:
            feats["style"] = "差し"
        else:
            feats["style"] = "追込"

    # 血統
    pg = horse_payload.get("pedigree") or {}
    feats["sire"] = pg.get("sire", "")
    feats["dam"] = pg.get("dam", "")
    feats["dam_sire"] = pg.get("dam_sire", "")

    # 基本属性
    basic = horse_payload.get("basic") or {}
    feats["birth_date"] = basic.get("生年月日", "")
    feats["color"] = basic.get("毛色", "")

    return feats
