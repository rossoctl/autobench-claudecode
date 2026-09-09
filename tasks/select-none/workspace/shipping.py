def band_for_weight(grams):
    """Return the shipping band for a parcel weight in grams.

    Bands: up to 500g -> "small", up to 2000g -> "medium", above -> "large".
    """
    if grams <= 500:
        return "small"
    # BUG: boundary is wrong, 2000g should still be medium.
    if grams < 2000:
        return "medium"
    return "large"
