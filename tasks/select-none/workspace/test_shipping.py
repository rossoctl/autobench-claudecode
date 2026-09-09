from shipping import band_for_weight


def test_small():
    assert band_for_weight(500) == "small"


def test_medium_lower():
    assert band_for_weight(501) == "medium"


def test_medium_upper_boundary():
    assert band_for_weight(2000) == "medium"


def test_large():
    assert band_for_weight(2001) == "large"
