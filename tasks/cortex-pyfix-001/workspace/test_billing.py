import pytest

from billing import apply_discount, split_evenly


def test_zero_discount():
    assert apply_discount(1000, 0) == 1000


def test_ten_percent():
    assert apply_discount(1000, 10) == 900


def test_full_discount():
    assert apply_discount(2500, 100) == 0


def test_split_exact():
    assert split_evenly(900, 3) == [300, 300, 300]


def test_split_with_remainder():
    got = split_evenly(1000, 3)
    assert sum(got) == 1000
    assert got == [334, 333, 333]


def test_split_rejects_zero():
    with pytest.raises(ValueError):
        split_evenly(100, 0)
