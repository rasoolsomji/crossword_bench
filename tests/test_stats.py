import pytest

from crossword_bench.stats import mcnemar_exact, wilson_interval


def test_wilson_interval_brackets_the_point_estimate():
    low, high = wilson_interval(55, 116)
    assert low == pytest.approx(0.386, abs=0.001)
    assert high == pytest.approx(0.564, abs=0.001)
    assert wilson_interval(0, 0) == (0.0, 0.0)
    assert wilson_interval(0, 10)[0] == 0.0
    assert wilson_interval(10, 10)[1] == pytest.approx(1.0)


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(25, 11) == pytest.approx(0.0288, abs=0.0001)
    assert mcnemar_exact(11, 25) == mcnemar_exact(25, 11)
    assert mcnemar_exact(6, 0) == pytest.approx(2 / 64)
