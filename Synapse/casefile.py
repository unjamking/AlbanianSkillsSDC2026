"""The case file: the planned and actual times saved in a case, its first treatment, and what the time cost."""
from triage import parse_clock
from unit import UNIT

CELLS_PER_MINUTE = 1900000  # Bonus 3: a published average for large strokes


def saved_time(text):
    """A time saved by clock(), as minutes. None when it is missing or cannot be read."""
    try:
        return parse_clock(text)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def has_route(case):
    return isinstance(case.route, dict)


def last_leg(route):
    """The part of a saved route that ends at the hospital where the patient stays."""
    if isinstance(route.get("transfer"), dict):
        return route["transfer"]
    return route


def hospital_stay(case):
    stay = case.route.get("hospitalStay")
    if isinstance(stay, dict) and last_leg(case.route).get("hospital") == UNIT:
        return stay
    return None


def hospital_times(case):
    """(step, planned, actual) at the stroke unit, as minutes or None. Mission 4 plans no scan."""
    leg = last_leg(case.route)
    stay = hospital_stay(case) or {}
    return [("Scan", None, saved_time(stay.get("scanAt"))),
            ("Drug", saved_time(leg.get("drugAt")), saved_time(stay.get("drugAt"))),
            ("Clot removal", saved_time(leg.get("clotRemovalAt")), saved_time(stay.get("clotRemovalAt")))]


def first_treatment(case):
    """The earliest drug or clot removal as (name, minutes, planned, actual), using the actual time when it was
    recorded and else the planned one. None when no treatment was planned or recorded."""
    if not has_route(case):
        return None
    stay = hospital_stay(case) or {}
    # the drug is planned at the first hospital (plan B gives it before the transfer), clot removal at the last
    candidates = [("drug", saved_time(case.route.get("drugAt")), saved_time(stay.get("drugAt"))),
                  ("clot removal", saved_time(last_leg(case.route).get("clotRemovalAt")),
                   saved_time(stay.get("clotRemovalAt")))]
    treatments = []
    for name, planned, actual in candidates:
        when = actual if actual is not None else planned
        if when is not None:
            treatments.append((when, name, planned, actual))
    if not treatments:
        return None
    when, name, planned, actual = min(treatments, key=lambda treatment: treatment[0])
    return name, when, planned, actual


def millions(minutes):
    """Brain cells lost in so many minutes, in millions."""
    return f"{minutes * CELLS_PER_MINUTE / 1000000:g}"
