"""Triage: the symptom list, patient cases, their time limits, and the file the cases are saved in."""
import json
import os
import re

from atlas import NAME, NAME_RULE, AtlasError
from lesion import Lesion

MINUTES_PER_DAY = 24 * 60
DRUG_WINDOW = 4 * 60 + 30
CLOT_WINDOW = 24 * 60
CLOT_MIN_SEVERITY = 5
CLOSEST_MATCH_NEEDED = 0.6
TIME = re.compile(r"([0-9]{1,2}):([0-9]{2})")


class Symptom:
    def __init__(self, code, points, description):
        self.code = code
        self.points = points
        self.description = description


class SymptomList:
    def __init__(self, path, symptoms):
        self.path = path
        self.symptoms = symptoms

    @staticmethod
    def load(path):
        try:
            with open(path, encoding="utf-8-sig") as file:
                lines = [line.strip() for line in file]
        except FileNotFoundError:
            raise AtlasError([f"File not found: {path}"])
        except UnicodeDecodeError:
            raise AtlasError([f"Cannot read {path}: it is not a UTF-8 text file."])
        except OSError as error:
            raise AtlasError([f"Cannot read {path}: {error.strerror}"])
        symptoms = {}
        first_line = {}
        errors = []
        for number, text in enumerate(lines, start=1):
            if not text or text.startswith("#"):
                continue
            fields = [field.strip() for field in text.split("|")]
            if fields[0] != "SYMPTOM":
                problem = f'unknown record type "{fields[0]}". Expected SYMPTOM.'
            elif len(fields) != 4:
                problem = f"SYMPTOM needs 4 fields, found {len(fields)}."
            elif not NAME.fullmatch(fields[1]):
                problem = f'invalid code "{fields[1]}". {NAME_RULE}'
            elif fields[1] in symptoms:
                problem = f'"{fields[1]}" is defined twice (first on line {first_line[fields[1]]}).'
            elif not fields[2].isdecimal():
                problem = f'points must be a whole number, found "{fields[2]}".'
            elif not fields[3]:
                problem = f'symptom "{fields[1]}" is missing "what the crew sees".'
            else:
                problem = None
                symptoms[fields[1]] = Symptom(fields[1], int(fields[2]), fields[3])
                first_line[fields[1]] = number
            if problem:
                errors.append(f"{path}, line {number}: {problem}")
        if not symptoms and not errors:
            errors.append("The file is empty.")
        if errors:
            raise AtlasError(errors)
        return SymptomList(path, symptoms)

    def parse(self, text):
        codes = []
        for code in text.split(","):
            code = code.strip().lower()
            if code and code not in codes:
                codes.append(code)
        if not codes:
            raise ValueError("Enter at least one symptom.")
        unknown = self.missing(codes)
        if len(unknown) == 1:
            raise ValueError(f'Unknown symptom "{unknown[0]}". Type triage symptoms to see the list.')
        if unknown:
            names = ", ".join(f'"{code}"' for code in unknown)
            raise ValueError(f"Unknown symptoms {names}. Type triage symptoms to see the list.")
        return codes

    def severity(self, codes):
        return sum(self.symptoms[code].points for code in codes)

    def missing(self, codes):
        return [code for code in codes if code not in self.symptoms]


def parse_time(text):
    match = TIME.fullmatch(text)
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ValueError(f'Invalid time "{text}". Use HH:MM, for example 08:10.')
    return int(match.group(1)) * 60 + int(match.group(2))


def clock(minutes):
    text = f"{minutes % MINUTES_PER_DAY // 60:02d}:{minutes % 60:02d}"
    day = minutes // MINUTES_PER_DAY
    if day < 0:
        return text + " yesterday"
    if day > 0:
        return text + " tomorrow"
    return text


def duration(minutes):
    return f"{minutes // 60} h {minutes % 60:02d} min"


def last_seen_well(seen, yesterday, now):
    if yesterday:
        return seen - MINUTES_PER_DAY
    if seen > now:
        raise ValueError(f"Last seen well ({clock(seen)}) is after the time now ({clock(now)}). Was it yesterday?")
    return seen


def parse_age(text):
    if not text.isdecimal() or int(text) > 120:
        raise ValueError("Age must be a whole number from 0 to 120.")
    return int(text)


def parse_yes_no(text):
    if text.lower() not in ("yes", "no"):
        raise ValueError('Answer "yes" or "no".')
    return text.lower() == "yes"


def required(text, field):
    if not text:
        raise ValueError(f"{field} cannot be empty.")
    return text


def band(severity):
    if severity >= 10:
        return "severe"
    if severity >= 5:
        return "moderate"
    return "minor"


def percent(similarity):
    return int(similarity * 100 + 0.5)


def rank_pipes(atlas, codes):
    wanted = set(codes)
    ranked = []
    for order, pipe in enumerate(atlas.pipes.values()):
        if pipe is atlas.heart:
            continue
        lesion = Lesion(atlas, [pipe])
        found = set(lesion.symptoms)
        similarity = len(wanted & found) / len(wanted | found)
        ranked.append((similarity, len(lesion.pipes_without_blood), order, pipe))
    ranked.sort(key=lambda match: (-match[0], match[1], match[2]))
    return [(pipe, similarity) for similarity, _, _, pipe in ranked]


class Case:
    def __init__(self, name, age, city, time_now, seen_well, symptoms):
        self.id = None
        self.name = name
        self.age = age
        self.city = city
        self.created_at = time_now
        self.time_now = time_now
        self.seen_well = seen_well
        self.symptoms = symptoms
        self.history = []
        self.severity = 0
        self.band = ""
        self.likely_pipe = None
        self.big_pipe = False
        self.match = None
        self.closest = []

    def assess(self, atlas, symptom_list):
        self.severity = symptom_list.severity(self.symptoms)
        self.band = band(self.severity)
        self.likely_pipe = None
        self.big_pipe = False
        self.match = None
        self.closest = []
        ranked = rank_pipes(atlas, self.symptoms)
        if not ranked:
            return
        best, similarity = ranked[0]
        if similarity < 1:
            self.closest = [[pipe.name, percent(score)] for pipe, score in ranked[:3]]
        if similarity >= CLOSEST_MATCH_NEEDED:
            self.likely_pipe = best.name
            self.big_pipe = best.size == "big"
            self.match = percent(similarity)

    @property
    def drug_until(self):
        return self.seen_well + DRUG_WINDOW

    @property
    def clot_until(self):
        return self.seen_well + CLOT_WINDOW

    def drug_possible(self, now):
        return now <= self.drug_until

    def clot_possible(self, now):
        return now <= self.clot_until and self.big_pipe and self.severity >= CLOT_MIN_SEVERITY

    def check_update_time(self, now):
        if now < self.time_now:
            raise ValueError(f"Time now ({clock(now)}) is before the last time of this case "
                             f"({clock(self.time_now)}).")
        return now

    def updated(self, time_now, new_symptoms, atlas, symptom_list):
        case = Case.from_dict(self.to_dict())
        added = [code for code in new_symptoms if code not in case.symptoms]
        case.time_now = time_now
        case.symptoms = case.symptoms + added
        case.assess(atlas, symptom_list)
        case.history.append({
            "timeNow": clock(time_now),
            "addedSymptoms": added,
            "severityBefore": self.severity,
            "severityAfter": case.severity,
            "likelyPipeBefore": self.likely_pipe,
            "likelyPipeAfter": case.likely_pipe,
        })
        return case

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "age": self.age,
            "city": self.city,
            "createdAt": clock(self.created_at),
            "timeNow": clock(self.time_now),
            "lastSeenWell": clock(self.seen_well % MINUTES_PER_DAY),
            "lastSeenWellYesterday": self.seen_well < 0,
            "symptoms": self.symptoms,
            "severity": self.severity,
            "band": self.band,
            "likelyPipe": self.likely_pipe,
            "bigPipe": self.big_pipe,
            "match": self.match,
            "closestPipes": self.closest,
            "drugUntil": clock(self.drug_until),
            "drugPossible": self.drug_possible(self.time_now),
            "clotUntil": clock(self.clot_until),
            "clotPossible": self.clot_possible(self.time_now),
            "history": self.history,
        }

    @staticmethod
    def from_dict(data):
        seen_well = parse_time(data["lastSeenWell"])
        if data["lastSeenWellYesterday"] is True:
            seen_well -= MINUTES_PER_DAY
        case = Case(str(data["name"]), int(data["age"]), str(data["city"]), parse_time(data["timeNow"]),
                    seen_well, [str(code) for code in data["symptoms"]])
        case.id = str(data["id"])
        case.created_at = parse_time(data["createdAt"])
        case.severity = int(data["severity"])
        case.band = str(data["band"])
        case.likely_pipe = data["likelyPipe"]
        case.big_pipe = data["bigPipe"] is True
        case.match = data["match"]
        case.closest = [[str(name), int(match)] for name, match in data["closestPipes"]]
        case.history = list(data["history"])
        return case


class CaseBook:
    def __init__(self, path):
        self.path = path
        self.cases = []
        self.next_number = 1
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
                raise ValueError("it is not a Synapse cases file")
            self.cases = [Case.from_dict(item) for item in data["cases"]]
            numbers = [int(case.id[2:]) for case in self.cases]
            self.next_number = max([int(data["nextNumber"])] + [number + 1 for number in numbers])

    def get(self, case_id):
        for case in self.cases:
            if case.id == case_id.upper():
                return case
        return None

    def add(self, case):
        case.id = f"P-{self.next_number:04d}"
        self.cases.append(case)
        self.next_number += 1
        try:
            self.save()
        except OSError:
            self.cases.pop()
            self.next_number -= 1
            case.id = None
            raise

    def replace(self, old, new):
        index = self.cases.index(old)
        self.cases[index] = new
        try:
            self.save()
        except OSError:
            self.cases[index] = old
            raise

    def save(self):
        data = {"nextNumber": self.next_number, "cases": [case.to_dict() for case in self.cases]}
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        os.replace(temp_path, self.path)
