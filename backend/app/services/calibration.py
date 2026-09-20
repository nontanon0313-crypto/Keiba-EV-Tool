# Platt scaling / isotonic mock - 後で学習データで置換
def calibrate(prob: float, enabled: bool=False) -> float:
    if not enabled:
        return prob
    # 簡易補正: 極端な確率を中央寄せ
    return 0.1 + 0.8 * prob
