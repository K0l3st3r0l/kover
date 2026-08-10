from app.options_math.ticks import (
    calculate_target_price,
    captured_pct,
    round_to_tick,
    take_profit_targets,
)


class TestRoundToTick:
    def test_penny_tick(self):
        assert round_to_tick(0.123, 0.01) == 0.12

    def test_nickel_tick_rounds_to_valid_price(self):
        # 0.13 no es un precio válido en una clase que cotiza de 5 en 5.
        assert round_to_tick(0.13, 0.05) == 0.15
        assert round_to_tick(0.12, 0.05) == 0.10

    def test_up_and_down(self):
        assert round_to_tick(0.11, 0.05, mode="up") == 0.15
        assert round_to_tick(0.14, 0.05, mode="down") == 0.10

    def test_no_floating_point_garbage(self):
        assert round_to_tick(0.15, 0.05) == 0.15
        assert str(round_to_tick(0.15, 0.05)) == "0.15"


class TestCalculateTargetPrice:
    def test_example_from_spec(self):
        # entry 0.50 → TP80 = 0.10, TP75 = 0.125→0.13, TP70 = 0.15
        assert calculate_target_price(0.50, 80, 0.01) == 0.10
        assert calculate_target_price(0.50, 75, 0.01) == 0.13
        assert calculate_target_price(0.50, 70, 0.01) == 0.15

    def test_rounds_up_so_the_order_can_fill(self):
        # 0.22 al 77% da 0.0506: hacia abajo (0.05) el target queda por debajo del
        # valor real y la orden no se llena.
        assert calculate_target_price(0.22, 77, 0.01) == 0.06

    def test_respects_nickel_tick(self):
        assert calculate_target_price(0.50, 80, 0.05) == 0.10
        assert calculate_target_price(1.00, 75, 0.05) == 0.25

    def test_returns_none_when_target_reaches_entry(self):
        # Prima de 1 centavo: no queda nada que capturar sobre un tick de 1 centavo.
        assert calculate_target_price(0.01, 80, 0.01) is None

    def test_returns_none_on_invalid_input(self):
        assert calculate_target_price(0, 80, 0.01) is None
        assert calculate_target_price(0.5, 0, 0.01) is None
        assert calculate_target_price(0.5, 100, 0.01) is None
        assert calculate_target_price(None, 80, 0.01) is None


class TestTakeProfitTargets:
    def test_all_three(self):
        targets = take_profit_targets(0.50, 0.01)
        assert targets == {70: 0.15, 75: 0.13, 80: 0.10}


class TestCapturedPct:
    def test_spec_example(self):
        # Vendida a 0.22, ask 0.05 → 77.3% capturado
        assert captured_pct(0.22, 0.05) == 77.27

    def test_zero_ask_is_full_capture(self):
        assert captured_pct(0.50, 0.0) == 100.0

    def test_unknown_price_returns_none_not_zero(self):
        assert captured_pct(0.50, None) is None
        assert captured_pct(0, 0.05) is None
