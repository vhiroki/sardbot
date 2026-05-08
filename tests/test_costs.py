from sardbot.engine.costs import CostModel


def test_cost_zero_with_zero_bps():
    cm = CostModel(fee_bps=0, slippage_bps=0)
    assert cm.apply(10_000) == 0.0


def test_cost_basic_math():
    cm = CostModel(fee_bps=10, slippage_bps=5)
    # 15 bps total of 10_000 = 15.0
    assert cm.apply(10_000) == 15.0


def test_cost_uses_absolute_notional():
    cm = CostModel(fee_bps=10, slippage_bps=5)
    assert cm.apply(-10_000) == 15.0
