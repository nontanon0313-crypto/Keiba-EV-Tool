"""三連単確率から他券種の確率を派生計算する。"""
from collections import defaultdict


def _sorted_key(parts):
    return "-".join(sorted(parts, key=lambda x: int(x)))


def trio_probs(trifecta_list):
    """三連複: 3頭の組み合わせ(順不同)。三連単の6通りを合算。"""
    acc = defaultdict(float)
    for t in trifecta_list:
        parts = t.combo.split("-")
        if len(parts) != 3:
            continue
        acc[_sorted_key(parts)] += t.prob
    return sorted(({"combo": k, "prob": v} for k, v in acc.items()), key=lambda x: x["prob"], reverse=True)


def exacta_probs(trifecta_list):
    """馬単: 1-2着 順序あり。三連単の3着目を合算。"""
    acc = defaultdict(float)
    for t in trifecta_list:
        parts = t.combo.split("-")
        if len(parts) != 3:
            continue
        acc[parts[0] + "-" + parts[1]] += t.prob
    return sorted(({"combo": k, "prob": v} for k, v in acc.items()), key=lambda x: x["prob"], reverse=True)


def quinella_probs(trifecta_list):
    """馬連: 1-2着 順不同。馬単の2通りを合算。"""
    acc = defaultdict(float)
    for t in trifecta_list:
        parts = t.combo.split("-")
        if len(parts) != 3:
            continue
        acc[_sorted_key(parts[:2])] += t.prob
    return sorted(({"combo": k, "prob": v} for k, v in acc.items()), key=lambda x: x["prob"], reverse=True)


def wide_probs(trifecta_list):
    """ワイド: 3着以内の2頭組み合わせ。三連単の全3ペアを合算。"""
    from itertools import combinations
    acc = defaultdict(float)
    for t in trifecta_list:
        parts = t.combo.split("-")
        if len(parts) != 3:
            continue
        for pair in combinations(parts, 2):
            acc[_sorted_key(pair)] += t.prob
    return sorted(({"combo": k, "prob": v} for k, v in acc.items()), key=lambda x: x["prob"], reverse=True)
