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


def quinella_probs_direct(win_probs):
    """単勝確率から馬連確率を直接計算（truncation不要）。
    P(A,B) = P(A)*P(B|A) + P(B)*P(A|B)
           = P(A)*P(B)/(1-P(A)) + P(B)*P(A)/(1-P(B))
    """
    from collections import defaultdict
    acc = defaultdict(float)
    probs = {p.horse_number: p.win_prob for p in win_probs}
    nums = list(probs.keys())
    for i, a in enumerate(nums):
        pa = probs[a]
        if pa >= 1: continue
        for b in nums[i+1:]:
            pb = probs[b]
            if pb >= 1: continue
            p_ab = pa * pb / (1 - pa) + pb * pa / (1 - pb)
            key = "-".join(sorted([str(a), str(b)], key=lambda x: int(x)))
            acc[key] += p_ab
    return sorted(({"combo": k, "prob": v} for k, v in acc.items()),
                  key=lambda x: x["prob"], reverse=True)


def trio_probs_direct(win_probs):
    """3連複を単勝確率から直接計算。
    P({A,B,C}) = 全6順列のP(A→B→C)の合算
    P(A→B→C) = P(A)*P(B|A)*P(C|A,B)  (PL順位モデル)"""
    from collections import defaultdict
    from itertools import permutations
    probs = {p.horse_number: p.win_prob for p in win_probs}
    nums = list(probs.keys())
    acc = defaultdict(float)
    for a in nums:
        pa = probs[a]
        for b in nums:
            if b == a: continue
            pb = probs[b]
            for c in nums:
                if c in (a, b): continue
                pc = probs[c]
                rem1 = 1 - pa
                if rem1 <= 0: continue
                p_b = pb / rem1
                rem2 = 1 - pa - pb
                if rem2 <= 0: continue
                p_c = pc / rem2
                prob = pa * p_b * p_c
                key = "-".join(sorted([str(a), str(b), str(c)], key=lambda x: int(x)))
                acc[key] += prob
    return sorted(({"combo": k, "prob": v} for k, v in acc.items()),
                  key=lambda x: x["prob"], reverse=True)


def exacta_probs_direct(win_probs):
    """馬単を単勝確率から直接計算。P(A→B) = P(A)*P(B)/(1-P(A))"""
    from collections import defaultdict
    probs = {p.horse_number: p.win_prob for p in win_probs}
    nums = list(probs.keys())
    out = []
    for a in nums:
        pa = probs[a]
        if pa >= 1: continue
        for b in nums:
            if b == a: continue
            pb = probs[b]
            p_ab = pa * pb / (1 - pa)
            out.append({"combo": f"{a}-{b}", "prob": p_ab})
    return sorted(out, key=lambda x: x["prob"], reverse=True)


def wide_probs_direct(win_probs):
    """ワイドを単勝確率から直接計算。P(A,B両方3着以内)"""
    from collections import defaultdict
    from itertools import combinations
    probs = {p.horse_number: p.win_prob for p in win_probs}
    nums = list(probs.keys())
    acc = defaultdict(float)
    # P(A,B両方3着以内) = P(A→B→任意) + P(B→A→任意) + P(A→任意→B) + P(B→任意→A) + P(任意→A→B) + P(任意→B→A)
    # ただし3着以内の並びは6通りすべて
    for a in nums:
        pa = probs[a]
        for b in nums:
            if b == a: continue
            pb = probs[b]
            for c in nums:
                if c in (a, b): continue
                pc = probs[c]
                rem1 = 1 - pa
                if rem1 <= 0: continue
                p_b = pb / rem1
                rem2 = 1 - pa - pb
                if rem2 <= 0: continue
                p_c = pc / rem2
                prob = pa * p_b * p_c
                # 3頭の中の2頭組 (3通り)
                for x, y in [(a, b), (a, c), (b, c)]:
                    key = "-".join(sorted([str(x), str(y)], key=lambda z: int(z)))
                    acc[key] += prob
    return sorted(({"combo": k, "prob": v} for k, v in acc.items()),
                  key=lambda x: x["prob"], reverse=True)
