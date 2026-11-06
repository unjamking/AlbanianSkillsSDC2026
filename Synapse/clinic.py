"""The recovery clinic: the normal values for each age, the visits, and how each result compares with them."""
import random
import re
from decimal import Decimal

from datafile import DataError, read_records
from lesion import Lesion

TESTS = ("reaction", "memory", "colorword")
KEYS = {"reaction": "reactionMs", "memory": "memoryDigits", "colorword": "colorWordSeconds"}
LOWER_IS_BETTER = {"reaction": True, "memory": False, "colorword": True}
SCALES = {"reaction": 20, "memory": 1, "colorword": 1}  # Bonus 3: what one # stands for
EXPECTED_WEAK = {  # Bonus 2: a test is expected to be weak if one of these areas stopped working
    "reaction": ("right-arm-face", "awake"),
    "memory": ("memory", "understanding"),
    "colorword": ("understanding", "left-attention", "right-vision", "left-vision"),
}
REACTION_ROUNDS = 5
WAIT_FROM = 1
WAIT_TO = 3
TOO_SOON_MS = 100
MEMORY_START = 3
MEMORY_LONGEST = 9
COLOURS = ("RED", "BLUE", "GREEN", "YELLOW")
COLOUR_ROUNDS = 10
COLOUR_MISMATCHES = 7
COLOUR_PENALTY = 2
CHANGE = Decimal("0.05")  # Bonus 1: more than 5% lower or higher is a change
DIGITS = "0123456789"
NUMBER = re.compile(r"[0-9]+(\.[0-9]+)?")
SECONDS = re.compile(r"[0-9]+(\.[0-9])?")


class Norm:
    def __init__(self, test, from_age, to_age, average, spread, line):
        self.test = test
        self.from_age = from_age
        self.to_age = to_age
        self.average = average
        self.spread = spread
        self.line = line


class Norms:
    def __init__(self, path, norms):
        self.path = path
        self.norms = norms

    @staticmethod
    def load(path):
        records = read_records(path)
        if not records:
            raise DataError(["The file is empty."])
        norms = []
        errors = []
        for number, fields in records:
            problem = Norms._problem(fields, norms)
            if problem:
                errors.append(f"{path}, line {number}: {problem}")
            else:
                norms.append(Norm(fields[1], int(fields[2]), int(fields[3]), Decimal(fields[4]), Decimal(fields[5]),
                                  number))
        if not errors:
            for test in TESTS:
                if not any(norm.test == test for norm in norms):
                    errors.append(f"There are no normal values for {test}.")
        if errors:
            raise DataError(errors)
        return Norms(path, norms)

    @staticmethod
    def _problem(fields, norms):
        if fields[0] != "NORM":
            return f'unknown record type "{fields[0]}". Expected NORM.'
        if len(fields) != 6:
            return f"NORM needs 6 fields, found {len(fields)}."
        if fields[1] not in TESTS:
            return f'unknown test "{fields[1]}". Expected reaction, memory or colorword.'
        if not fields[2].isdecimal() or not fields[3].isdecimal():
            return f'ages must be whole numbers, found "{fields[2]}" and "{fields[3]}".'
        from_age, to_age = int(fields[2]), int(fields[3])
        if from_age > to_age:
            return f"ages {from_age} to {to_age} go backwards."
        if not NUMBER.fullmatch(fields[4]):
            return f'normal average must be a number, found "{fields[4]}".'
        if not NUMBER.fullmatch(fields[5]) or Decimal(fields[5]) == 0:
            return f'spread must be a number above 0, found "{fields[5]}".'
        for other in norms:
            if other.test == fields[1] and from_age <= other.to_age and other.from_age <= to_age:
                return f"ages {from_age} to {to_age} overlap with line {other.line}."
        return None

    def for_age(self, age):
        """The normal values of every test for this age. ValueError when the file has none for it."""
        found = {}
        for norm in self.norms:
            if norm.from_age <= age <= norm.to_age:
                found[norm.test] = norm
        missing = [test for test in TESTS if test not in found]
        if len(missing) == len(TESTS):
            raise ValueError(f"No normal values for age {age}.")
        if missing:
            raise ValueError(f"No normal values for {', '.join(missing)} at age {age}.")
        return {test: found[test] for test in TESTS}


def parse_day(text):
    if not text.isdecimal() or int(text) < 1:
        raise ValueError("Days since the stroke must be a whole number of 1 or more.")
    return int(text)


def parse_new_day(case, text):
    day = parse_day(text)
    if any(visit["day"] == day for visit in case.visits):
        raise ValueError(f"{case.id} already has a visit on day {day}.")
    return day


def parse_reaction(text):
    if not text.isdecimal() or int(text) < 1:
        raise ValueError("Reaction time must be a whole number of milliseconds above 0.")
    return int(text)


def parse_memory(text):
    if not text.isdecimal() or int(text) > MEMORY_LONGEST:
        raise ValueError(f"Memory span must be a whole number of digits from 0 to {MEMORY_LONGEST}.")
    return int(text)


def parse_seconds(text):
    if not SECONDS.fullmatch(text):
        raise ValueError("Colour words must be a number of seconds with at most one decimal, for example 22.5.")
    return float(text)


def make_visit(day, reaction, memory, colorword):
    return {"day": day, "reactionMs": reaction, "memoryDigits": memory, "colorWordSeconds": colorword}


def visit_from_dict(data):
    """A saved visit, checked with the same rules as a visit typed in by hand."""
    seconds = f"{data['colorWordSeconds']:.1f}"  # a big number is saved as 1e+17, this writes it out in full again
    return make_visit(parse_day(str(data["day"])), parse_reaction(str(data["reactionMs"])),
                      parse_memory(str(data["memoryDigits"])), parse_seconds(seconds))


def by_day(visits):
    return sorted(visits, key=lambda visit: visit["day"])


def digit_row(length):
    """Random digits, never the same digit twice in a row."""
    row = [random.choice(DIGITS)]
    while len(row) < length:
        row.append(random.choice([digit for digit in DIGITS if digit != row[-1]]))
    return row


def colour_rounds():
    """The (word, colour) of each round. At most 3 rounds print a word in its own colour."""
    same = random.sample(range(COLOUR_ROUNDS), random.randint(0, COLOUR_ROUNDS - COLOUR_MISMATCHES))
    rounds = []
    for number in range(COLOUR_ROUNDS):
        word = random.choice(COLOURS)
        if number in same:
            rounds.append((word, word))
        else:
            rounds.append((word, random.choice([colour for colour in COLOURS if colour != word])))
    return rounds


def rating(test, value, norm):
    """normal, below or well below: how many spreads the result is worse than the normal average."""
    worse = Decimal(str(value)) - norm.average  # Decimal: exactly 2 spreads is exactly 2, not 2.0000000000000004
    if not LOWER_IS_BETTER[test]:
        worse = -worse
    if worse <= norm.spread:
        return "normal"
    if worse <= 2 * norm.spread:
        return "below"
    return "well below"


def trend(test, old, new):
    """Bonus 1: improving, worse or steady from the older result to the newer one."""
    old, new = Decimal(str(old)), Decimal(str(new))
    if test == "memory":
        if new > old:
            return "improving"
        if new < old:
            return "worse"
        return "steady"
    if new < old * (1 - CHANGE):
        return "improving"
    if new > old * (1 + CHANGE):
        return "worse"
    return "steady"


def damage(atlas, case):
    """Bonus 2: the areas that stopped working because of the case's likely blocked pipe. None if it is unknown."""
    if not case.likely_pipe or case.likely_pipe not in atlas.pipes:
        return None
    return [area.name for area in Lesion(atlas, [atlas.pipes[case.likely_pipe]]).stopped_areas]


def expected_weak(test, stopped):
    return any(area in stopped for area in EXPECTED_WEAK[test])


def bar_length(test, value):
    """Bonus 3: the number of # for a result, rounded to the nearest whole # (half goes up)."""
    return int(Decimal(str(value)) / SCALES[test] + Decimal("0.5"))


def test_checks(visits, norms, stopped):
    """Bonus 2 for the latest visit: (test, result, rating, trend, expected weak) for every test."""
    latest = visits[-1]
    previous = visits[-2] if len(visits) > 1 else None
    checks = []
    for test in TESTS:
        value = latest[KEYS[test]]
        moved = "-" if previous is None else trend(test, previous[KEYS[test]], value)
        if stopped is None:
            expected = "unknown"
        else:
            expected = "yes" if expected_weak(test, stopped) else "no"
        checks.append((test, value, rating(test, value, norms[test]), moved, expected))
    return checks


def unexplained(rated, expected):
    """A weak result that the damage does not explain."""
    return rated != "normal" and expected != "yes"
