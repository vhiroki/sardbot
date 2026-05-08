import pandas as pd
import pytest

from sardbot.data.splits import split_by_fraction


def _df(n):
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"close": range(n)}, index=idx)


def test_split_proportions():
    sp = split_by_fraction(_df(100), oos_fraction=0.2)
    assert len(sp.in_sample) == 80
    assert len(sp.out_of_sample) == 20


def test_split_no_overlap():
    sp = split_by_fraction(_df(100), oos_fraction=0.2)
    last_in = sp.in_sample.index[-1]
    first_oos = sp.out_of_sample.index[0]
    assert first_oos > last_in


def test_split_invalid_fraction():
    with pytest.raises(ValueError):
        split_by_fraction(_df(10), oos_fraction=0.0)
    with pytest.raises(ValueError):
        split_by_fraction(_df(10), oos_fraction=1.0)
