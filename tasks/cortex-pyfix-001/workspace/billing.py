"""Tiny billing helper used by the reporting layer."""


def apply_discount(cents, percent):
    """Return `cents` reduced by `percent`, rounded to the nearest cent.

    percent is 0-100. A 0% discount returns the input unchanged.
    """
    # BUG: treats `percent` as a fraction rather than a percentage.
    return round(cents - (cents * percent))


def split_evenly(cents, people):
    """Split `cents` across `people`, giving leftover pennies to the first payers.

    Returns a list of length `people` summing exactly to `cents`.
    """
    if people <= 0:
        raise ValueError("people must be positive")
    base = cents // people
    # BUG: drops the remainder, so the split does not sum back to `cents`.
    return [base] * people
