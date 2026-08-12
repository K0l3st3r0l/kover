"""Tests del Market Safety Score (Stage 3 del scanner).

Todo sintético y determinístico: nada de red. La aserción central es de
ordenamiento (una serie tranquila debe puntuar más alto que una volátil), no
de un número exacto — los umbrales son heurísticos declarados, no una
calibración que estos tests deban proteger número a número.
"""

from datetime import date, timedelta

from app.scanner.market_risk import (
    Bar,
    _safer_below,
    compute_market_safety_score,
    compute_metrics,
)


def _bar(d, close, open_=None, high=None, low=None, volume=1_000_000):
    open_ = open_ if open_ is not None else close
    high = high if high is not None else max(open_, close) * 1.005
    low = low if low is not None else min(open_, close) * 0.995
    return Bar(bar_date=d, open=open_, high=high, low=low, close=close, volume=volume)


def _series(start_price: float, daily_moves: list[float], start_date: date, gap_every: int | None = None) -> list[Bar]:
    """`daily_moves` son retornos fraccionarios día a día (0.01 = +1%)."""
    bars = []
    price = start_price
    d = start_date
    prev_close = start_price
    for i, move in enumerate(daily_moves):
        d = d + timedelta(days=1)
        while d.weekday() >= 5:
            d = d + timedelta(days=1)
        price = prev_close * (1 + move)
        open_ = prev_close
        if gap_every and i > 0 and i % gap_every == 0:
            open_ = prev_close * 1.06  # gap grande deliberado
        bars.append(_bar(d, close=price, open_=open_))
        prev_close = price
    return bars


CALM_MOVES = ([0.002, -0.001, 0.001, -0.002, 0.0015] * 24)[:120]
VOLATILE_MOVES = ([0.06, -0.08, 0.05, -0.10, 0.04, 0.07, -0.06] * 18)[:120]


class TestComputeMetrics:
    def test_insufficient_bars_returns_note(self):
        bars = _series(15.0, [0.001] * 5, date(2026, 1, 1))
        metrics = compute_metrics(bars)
        assert metrics.bars_used == 5
        assert "_all" in metrics.missing

    def test_calm_series_has_low_vol_and_small_drawdown(self):
        bars = _series(15.0, CALM_MOVES, date(2026, 1, 1))
        metrics = compute_metrics(bars)
        assert metrics.bars_used == 120
        assert metrics.realized_vol_20 is not None
        assert metrics.realized_vol_20 < 0.20
        assert metrics.max_drawdown_30d is not None
        assert metrics.max_drawdown_30d < 0.05

    def test_volatile_series_has_high_vol_and_big_drawdown(self):
        bars = _series(15.0, VOLATILE_MOVES, date(2026, 1, 1))
        metrics = compute_metrics(bars)
        assert metrics.realized_vol_20 is not None
        assert metrics.realized_vol_20 > 0.80
        assert metrics.max_drawdown_30d is not None
        assert metrics.max_drawdown_30d > 0.15

    def test_missing_high_low_skips_atr_with_reason(self):
        bars = [
            Bar(bar_date=date(2026, 1, i + 1), open=15.0, high=None, low=None, close=15.0 + i * 0.01, volume=100_000)
            for i in range(20)
        ]
        metrics = compute_metrics(bars)
        assert metrics.atr14 is None
        assert "atr14" in metrics.missing

    def test_gap_frequency_counts_large_opens(self):
        bars = _series(15.0, CALM_MOVES, date(2026, 1, 1), gap_every=5)
        metrics = compute_metrics(bars)
        assert metrics.gap_frequency is not None
        assert metrics.gap_frequency > 0.10  # 1 de cada 5 sesiones tiene gap forzado


class TestMarketSafetyScore:
    def test_calm_scores_higher_than_volatile(self):
        calm = compute_market_safety_score(compute_metrics(_series(15.0, CALM_MOVES, date(2026, 1, 1))))
        volatile = compute_market_safety_score(
            compute_metrics(_series(15.0, VOLATILE_MOVES, date(2026, 1, 1)))
        )
        assert calm.score is not None
        assert volatile.score is not None
        assert calm.score > volatile.score
        assert calm.score - volatile.score > 15
        assert calm.score > 60

    def test_insufficient_data_yields_none_score(self):
        result = compute_market_safety_score(compute_metrics(_series(15.0, [0.001] * 5, date(2026, 1, 1))))
        assert result.score is None

    def test_components_are_explainable(self):
        result = compute_market_safety_score(compute_metrics(_series(15.0, CALM_MOVES, date(2026, 1, 1))))
        names = {c.name for c in result.components}
        assert names == {"atr_pct", "realized_vol_20", "max_drawdown_30d", "gap_frequency", "worst_day_20d"}
        for c in result.components:
            if c.normalized is not None:
                assert 0.0 <= c.normalized <= 1.0


class TestSaferBelow:
    def test_safe_at_boundary_is_one(self):
        assert _safer_below(0.03, 0.03, 0.10) == 1.0

    def test_risky_at_boundary_is_zero(self):
        assert _safer_below(0.10, 0.03, 0.10) == 0.0

    def test_midpoint_is_interpolated(self):
        mid = _safer_below(0.065, 0.03, 0.10)
        assert 0.4 < mid < 0.6

    def test_none_passes_through(self):
        assert _safer_below(None, 0.03, 0.10) is None
