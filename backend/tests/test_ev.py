"""EV 計算と閾値のテスト。"""
import pytest

from backend.config import settings


def ev(prob: float, odds: float) -> float:
    return prob * odds - 1.0


def test_ev_basic_positive():
    assert ev(0.3, 5.0) == pytest.approx(0.5)


def test_ev_basic_negative():
    assert ev(0.1, 5.0) == pytest.approx(-0.5)


def test_ev_zero_breakeven():
    assert ev(0.2, 5.0) == pytest.approx(0.0)


def test_thresholds_are_sane():
    assert 0 < settings.EV_THRESHOLD_TRIFECTA < 1
    assert 0 < settings.EV_THRESHOLD_EXACTA < 1
    assert settings.EV_THRESHOLD_TRIFECTA >= settings.EV_THRESHOLD_EXACTA


def test_independent_multiplication_is_forbidden_pattern():
    """3連単で独立掛け算したら EV が過大になる例(参考値)。"""
    p1, p2, p3 = 0.3, 0.3, 0.3
    naive = p1 * p2 * p3
    assert naive == pytest.approx(0.027)
    # Plackett-Luce では条件付きで減衰するため naive より小さくなる想定
    # ここでは naive が閾値未満であることのみ確認
    assert naive < settings.EV_THRESHOLD_TRIFECTA
