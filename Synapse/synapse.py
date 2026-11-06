"""Synapse stroke command center: every command of every mission. Start with: python synapse.py"""
import json
import os
import random
import sys
import time

from atlas import Atlas
from casefile import first_treatment, has_route, hospital_stay, hospital_times, last_leg, millions
from clinic import (COLOUR_PENALTY, COLOURS, KEYS, LOWER_IS_BETTER, MEMORY_LONGEST, MEMORY_START, REACTION_ROUNDS,
                    TESTS, TOO_SOON_MS, WAIT_FROM, WAIT_TO, Norms, bar_length, by_day, colour_rounds, damage,
                    digit_row, make_visit, parse_memory, parse_new_day, parse_reaction, parse_seconds, rating,
                    test_checks, trend, unexplained)
from datafile import DataError
from lesion import Lesion, risky_pipes
from route import (ABILITIES, DRUG_TIME, FAR, Roads, Route, cities, clot_minutes, fastest, find_city, load_map_file,
                   trips_from, with_ability)
from triage import (CLOSEST_MATCH_NEEDED, CLOT_MIN_SEVERITY, Case, CaseBook, SymptomList, clock, duration,
                    last_seen_well, parse_age, parse_time, parse_yes_no, percent, required)
from unit import (HEAD_SCAN_LIMIT, MAX_SCANNERS, ORDERS, SLOW, UNIT, Morning, load_events, patients_from_cases,
                  save_stays)

HELP = """Commands:
  atlas load <path>              load another atlas file (nothing changes if it has errors)
  atlas pipes                    list every pipe with its size and where it comes from
  atlas areas                    list every area with the pipes that feed it
  atlas show <name>              show one pipe or one area in full
  atlas find <word>              list areas whose name, symptoms or description contain the word
  atlas tree                     draw the whole network, starting at the heart
  atlas path <area>              list every route the blood can take from the heart to an area
  lesion block <pipe>            block a pipe (or several: a, b, c) and show what stops working
  lesion risk <area>             list every pipe that would stop the area if it alone were blocked
  lesion tree <pipe>             draw the network and mark what a blocked pipe affects
  triage symptoms                list every symptom code with its points
  triage load <path>             load another symptom list (nothing changes if it has errors)
  triage new                     create a case: asks for the patient's details one by one
  triage list                    list every case
  triage show <id>               show one case in full
  triage update <id>             add new symptoms to a case and compute everything again
  triage urgent                  list the cases that can still be treated, shortest time left first
  map load <path>                load a new roads or hospitals file (nothing changes if it has errors)
  map coverage                   for every city, the drive to the nearest drug and clot removal
  route from <city>              list every hospital with the fastest drive and the cities on the way
  route <case id>                choose the hospital for a case and save the route in the case
  route whatif <city> <ability>  the drive to clot removal for every case, if the hospital in city could do more
  unit run <file>                replay the morning at Qendra Neuro Tirana and save the hospital times
  unit compare <file>            run the same morning with 1 and with 2 CT scanners, side by side
                                 after the file: --order deadline, --scanners <n> (unit run only)
  clinic visit <id>              run the three brain tests for a case and save the visit
  clinic record <id>             save a visit from results typed in by hand
  clinic results <id>            every visit, oldest first, rated against normal values for the patient's age
  clinic check <id>              compare the latest results with the stroke damage and flag what it does not explain
  clinic chart <id> <test>       one bar per visit for reaction, memory or colorword
  clinic load <path>             load other normal values (nothing changes if it has errors)
  case <case id>                 the whole story of a case: triage, route, hospital and recovery
  case find <text>               find a case by name or city and show it
  case export <case id>          write the case to exports/<case id>.txt and exports/<case id>.json
  case board                     every case on one screen, one row each
  case cost <case id>            the brain cells lost before the first treatment, and while waiting
  help                           show this list
  exit                           quit Synapse"""

LABEL_WIDTH = 21

TITLES = {
    "clot removal": "Fastest hospital that can remove the clot",
    "drug": "Fastest hospital that can give the drug in time",
    "scan": "Fastest hospital with CT, for a scan and care",
}

ABILITY_TEXT = {"CT": "do CT scans", "DRUG": "give the drug", "CLOT": "remove clots"}

TEST_NAMES = {"reaction": "Reaction", "memory": "Memory", "colorword": "Colour words"}
CHART_TITLES = {"reaction": "Reaction time", "memory": "Memory span", "colorword": "Colour words"}
UNITS = {"reaction": "ms", "memory": "digits", "colorword": "s"}
INK = {"RED": "\033[91m", "BLUE": "\033[94m", "GREEN": "\033[92m", "YELLOW": "\033[93m"}  # terminal colour codes
RESET = "\033[0m"


def count(number, word):
    if number == 1:
        return f"1 {word}"
    return f"{number} {word}s"


def table_lines(rows):
    widths = [max(len(row[i]) for row in rows) + 3 for i in range(len(rows[0]))]
    return ["".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows]


def print_table(rows):
    for line in table_lines(rows):
        print(line)


def print_field(indent, label, value):
    print(indent + label.ljust(LABEL_WIDTH) + value)


def ask(question, parse):
    while True:
        try:
            return parse(input(question).strip())
        except ValueError as error:
            print(f"ERROR: {error}")


# Mission 3 texts

def pipe_text(case):
    if not case.likely_pipe:
        if case.closest:
            return f"unknown, no pipe matches {percent(CLOSEST_MATCH_NEEDED)}% or more of these symptoms"
        return "unknown, no single pipe matches these symptoms exactly"
    text = f"{case.likely_pipe} ({'big' if case.big_pipe else 'small'})"
    if case.closest:
        text += f", {case.match}% match"
    return text


def drug_possible_text(case, now):
    if case.drug_possible(now):
        return f"yes, until {clock(case.drug_until)} ({duration(case.drug_until - now)} left)"
    return f"no, the time limit passed at {clock(case.drug_until)}"


def clot_possible_text(case, now):
    if not case.likely_pipe:
        return "no, the blocked pipe is unknown"
    if not case.big_pipe:
        return f"no, {case.likely_pipe} is a small pipe"
    if case.severity < CLOT_MIN_SEVERITY:
        return f"no, the severity is below {CLOT_MIN_SEVERITY}"
    if not case.clot_possible(now):
        return f"no, the time limit passed at {clock(case.clot_until)}"
    return f"yes, until {clock(case.clot_until)}"


# Mission 4 texts

def path_text(trip):
    if len(trip.path) == 1:
        return "inside " + trip.path[0]
    return " -> ".join(trip.path)


def minutes_text(minutes):
    if minutes is None:
        return "no road"
    return f"{minutes} min"


def nearest_text(trip):
    if trip is None:
        return "none"
    return f"{trip.minutes} min ({trip.hospital.city})"


def needs_text(case, leaves):
    needs = []
    if case.clot_possible(leaves):
        needs.append(f"clot removal (until {clock(case.clot_until)})")
    if case.drug_possible(leaves):
        needs.append(f"drug (until {clock(case.drug_until)})")
    notes = []
    if not case.drug_possible(leaves):
        notes.append("The drug limit has passed.")
    if not case.clot_possible(leaves):
        notes.append("Clot removal is not possible.")
    text = "Needs: " + (", ".join(needs) or "a scan and care")
    if notes:
        text += ". " + " ".join(notes)
    return text


def visit_drug_text(case, visit):
    if visit.drug_at is not None:
        return clock(visit.drug_at)
    if not case.drug_possible(visit.arrives + DRUG_TIME):
        return f"too late (limit {clock(case.drug_until)})"
    return "not given here, this hospital has no DRUG"


def plan_drug_text(case, visit):
    if visit.drug_at is not None:
        return "drug " + clock(visit.drug_at)
    if not case.drug_possible(visit.arrives + DRUG_TIME):
        return "drug too late"
    return "no drug here"


# Mission 5 texts

def read_options(text):
    """Splits "data/today.events --order deadline" into the file, the order and the number of scanners."""
    words = text.split()
    path = []
    order = "arrival"
    scanners = None
    while words:
        word = words.pop(0)
        if word in ("--order", "--scanners") and not words:
            raise ValueError(f"Missing value after {word}.")
        if word == "--order":
            order = words.pop(0).lower()
            if order not in ORDERS:
                raise ValueError(f'Unknown order "{order}". Use --order deadline or --order arrival.')
        elif word == "--scanners":
            value = words.pop(0)
            if not value.isdecimal() or not 1 <= int(value) <= MAX_SCANNERS:
                raise ValueError(f"--scanners must be a whole number from 1 to {MAX_SCANNERS}.")
            scanners = int(value)
        elif word.startswith("--"):
            raise ValueError(f'Unknown option "{word}". Use --order deadline or --scanners <n>.')
        else:
            path.append(word)
    if not path:
        raise ValueError("Missing file. Write it before the options, like this: data/today.events --order deadline")
    return " ".join(path).strip("\"'"), order, scanners


def time_text(minutes):
    if minutes is None:
        return "-"
    return clock(minutes)


def ids_text(stays):
    return ", ".join(stay.patient.id for stay in stays) or "none"


def door_text(stay):
    if stay.door_to_drug is None:
        return "-"
    if stay.door_to_drug > SLOW:
        return f"{stay.door_to_drug} min SLOW"
    return f"{stay.door_to_drug} min"


def stay_clot_text(stay):
    if stay.missed_clot:
        return "too late"
    return time_text(stay.clot_at)


def note_text(stay):
    patient = stay.patient
    notes = []
    if patient.kind == "head":
        notes.append("head injury")
        if stay.scan_wait > HEAD_SCAN_LIMIT:
            notes.append(f"SCANNED LATE ({stay.scan_wait} min after arrival)")
    elif patient.note:
        notes.append(patient.note)
    elif stay.drug_at is None:
        if patient.drug_until < patient.arrives:
            notes.append("drug limit passed before arrival")
        elif patient.drug_in_time(patient.arrives):
            notes.append(f"MISSED THE DRUG (limit {clock(patient.drug_until)})")
        else:
            notes.append(f"arrived too late for the drug (limit {clock(patient.drug_until)})")
    if stay.missed_clot:
        notes.append(f"MISSED CLOT REMOVAL (limit {clock(patient.clot_until)})")
    return ", ".join(notes)


def given_text(morning):
    return f"{len(morning.given_drug())} of {len(morning.could_get_drug())}"


def average_text(morning):
    average = morning.average_door_to_drug()
    if average is None:
        return "-"
    return f"{average} min"


# Mission 6: the three brain tests and their texts

def reaction_test():
    """5 rounds: the milliseconds from * to ENTER. Under 100 ms is too soon, and the round is played again."""
    print(f"Press ENTER as soon as you see *   ({REACTION_ROUNDS} rounds)")
    times = []
    while len(times) < REACTION_ROUNDS:
        print("Wait...", flush=True)
        time.sleep(random.uniform(WAIT_FROM, WAIT_TO))
        print("*", flush=True)
        start = time.perf_counter()  # perf_counter: a precise clock that never jumps
        input()
        milliseconds = (time.perf_counter() - start) * 1000
        if milliseconds < TOO_SOON_MS:
            print("Too soon!")
        else:
            times.append(int(milliseconds + 0.5))
            print(f"{times[-1]} ms")
    average = int(sum(times) / len(times) + 0.5)
    print(f"Average: {average} ms")
    return average


def memory_test():
    """Rows of 3 to 9 digits. The result is the longest row typed back correctly."""
    print("Remember the digits. They disappear after a moment.")
    longest = 0
    for length in range(MEMORY_START, MEMORY_LONGEST + 1):
        row = " ".join(digit_row(length))
        print(row, end="", flush=True)
        time.sleep(length)  # 1 second per digit
        print("\r" + " " * len(row) + "\r", end="", flush=True)  # write over the digits to hide them
        answer = "".join(input("Type the digits: ").split())
        if answer != row.replace(" ", ""):
            print("Not right.")
            break
        print("Correct.")
        longest = length
    print(f"Longest row repeated: {count(longest, 'digit')}")
    return longest


def colour_test():
    """10 words in colour. The result is the seconds for all of them, plus 2 for every wrong colour."""
    print("Type the first letter of the COLOUR of each word, not the word: r, b, g or y.")
    letters = [colour[0].lower() for colour in COLOURS]
    wrong = 0
    start = time.perf_counter()
    for word, colour in colour_rounds():
        print(INK[colour] + word + RESET)
        answer = input("> ").strip().lower()
        while answer not in letters:
            answer = input("Type r, b, g or y: ").strip().lower()
        if answer != colour[0].lower():
            wrong += 1
    seconds = round(time.perf_counter() - start, 1)
    score = round(seconds + COLOUR_PENALTY * wrong, 1)
    print(f"Time: {seconds:.1f} s, {count(wrong, 'wrong answer')} (+{COLOUR_PENALTY * wrong} s) = {score:.1f} s")
    return score


BRAIN_TESTS = (("reaction time", reaction_test), ("memory span", memory_test), ("colour words", colour_test))


def result_text(test, value):
    if test == "reaction":
        return f"{value} ms"
    if test == "memory":
        return count(value, "digit")
    return f"{value:.1f} s"


def norm_number(test, value):
    if test == "reaction":
        return str(value)
    return f"{value:.1f}"


def normal_text(norms):
    """The normal averages for the header of clinic results, with the ages they are for."""
    bands = {(norm.from_age, norm.to_age) for norm in norms.values()}
    parts = []
    for test, norm in norms.items():
        part = f"{TEST_NAMES[test].lower()} {norm_number(test, norm.average)} {UNITS[test]}"
        if len(bands) > 1:
            part += f" (ages {norm.from_age}-{norm.to_age})"
        parts.append(part)
    if len(bands) > 1:
        return "normal: " + ", ".join(parts)
    from_age, to_age = bands.pop()
    return f"normal for ages {from_age}-{to_age}: " + ", ".join(parts)


def saved_path_text(path):
    if len(path) == 1:
        return "inside " + str(path[0])
    return " -> ".join(str(city) for city in path)


class Synapse:
    def __init__(self):
        self.atlas = None
        self.symptom_list = None
        self.cases = None
        self.roads = None
        self.hospitals = None
        self.norms = None
        # each command: (method, what it takes after it, what must be loaded first)
        self.commands = {
            "atlas": {
                "load": (self.atlas_load, "<path>", ()),
                "pipes": (self.atlas_pipes, "", ("atlas",)),
                "areas": (self.atlas_areas, "", ("atlas",)),
                "show": (self.atlas_show, "<name>", ("atlas",)),
                "find": (self.atlas_find, "<word>", ("atlas",)),
                "tree": (self.atlas_tree, "", ("atlas",)),
                "path": (self.atlas_path, "<area>", ("atlas",)),
            },
            "lesion": {
                "block": (self.lesion_block, "<pipe>", ("atlas",)),
                "risk": (self.lesion_risk, "<area>", ("atlas",)),
                "tree": (self.lesion_tree, "<pipe>", ("atlas",)),
            },
            "triage": {
                "symptoms": (self.triage_symptoms, "", ("symptoms",)),
                "load": (self.triage_load, "<path>", ()),
                "new": (self.triage_new, "", ("atlas", "symptoms", "cases")),
                "list": (self.triage_list, "", ("cases",)),
                "show": (self.triage_show, "<id>", ("cases",)),
                "update": (self.triage_update, "<id>", ("atlas", "symptoms", "cases")),
                "urgent": (self.triage_urgent, "", ("cases",)),
            },
            "map": {
                "load": (self.map_load, "<path>", ()),
                "coverage": (self.map_coverage, "", ("map",)),
            },
            "route": {
                "from": (self.route_from, "<city>", ("map",)),
                "whatif": (self.route_whatif, "<city and ability>", ("cases", "map")),
            },
            "unit": {
                "run": (self.unit_run, "<file>", ("cases",)),
                "compare": (self.unit_compare, "<file>", ("cases",)),
            },
            "clinic": {
                "visit": (self.clinic_visit, "<id>", ("cases",)),
                "record": (self.clinic_record, "<id>", ("cases",)),
                "results": (self.clinic_results, "<id>", ("cases", "norms")),
                "check": (self.clinic_check, "<id>", ("atlas", "cases", "norms")),
                "chart": (self.clinic_chart, "<id and test>", ("cases", "norms")),
                "load": (self.clinic_load, "<path>", ()),
            },
            "case": {
                "find": (self.case_find, "<text>", ("cases",)),
                "export": (self.case_export, "<case id>", ("cases",)),
                "board": (self.case_board, "", ("cases",)),
                "cost": (self.case_cost, "<case id>", ("cases",)),
            },
        }

    def run_command(self, line):
        words = line.split(maxsplit=2)
        if not words:
            return True
        command = words[0].lower()
        if command in ("exit", "quit"):
            return False
        if command == "help":
            print(HELP)
        elif command == "route" and len(words) == 2 and words[1].lower() not in self.commands["route"]:
            self.route_case(words[1])  # route <case id> and case <case id> have no fixed word after them
        elif command == "case" and len(words) == 1:
            print("ERROR: Missing case id. Usage: case <case id>")
        elif command == "case" and len(words) == 2 and words[1].lower() == "find":
            print("ERROR: Search text cannot be empty.")
        elif command == "case" and len(words) == 2 and words[1].lower() not in self.commands["case"]:
            self.case_show(words[1])
        elif command in self.commands:
            subcommand = words[1].lower() if len(words) > 1 else ""
            argument = words[2].strip() if len(words) > 2 else ""
            self.run_subcommand(command, subcommand, argument)
        else:
            print(f'ERROR: Unknown command "{words[0]}". Type "help" to see all commands.')
        return True

    def run_subcommand(self, command, subcommand, argument):
        commands = self.commands[command]
        if subcommand not in commands:
            problem = f'Unknown {command} command "{subcommand}"' if subcommand else f"Missing {command} command"
            print(f"ERROR: {problem}. Use one of: {command} " + f", {command} ".join(commands))
            return
        method, usage, needs = commands[subcommand]
        missing = self.missing(needs)
        if usage and not argument:
            print(f"ERROR: Missing {usage.strip('<>')}. Usage: {command} {subcommand} {usage}")
        elif argument and not usage:
            print(f"ERROR: {command} {subcommand} takes nothing after it. Usage: {command} {subcommand}")
        elif missing:
            print("ERROR: " + missing)
        else:
            method(argument)

    def missing(self, needs):
        """The first thing a command needs that is not loaded, as an error message. None when all is there."""
        if "atlas" in needs and self.atlas is None:
            return "No atlas is loaded. Use: atlas load <path>"
        if "symptoms" in needs and self.symptom_list is None:
            return "No symptom list is loaded. Use: triage load <path>"
        if "cases" in needs and self.cases is None:
            return "The cases file could not be read, so no case can be used or saved."
        if "map" in needs and (self.roads is None or self.hospitals is None):
            return "No map is loaded. Use: map load <path>, first for the roads, then for the hospitals."
        if "norms" in needs and self.norms is None:
            return "No normal values are loaded. Use: clinic load <path>"
        return None

    # Mission 1: the brain map

    def find_area(self, name, usage):
        area = self.atlas.areas.get(name.lower())
        if area:
            return area
        if name.lower() in self.atlas.pipes:
            print(f'ERROR: "{name}" is a pipe, not an area. Usage: {usage}')
        else:
            print(f'ERROR: No area called "{name}".')
        return None

    def atlas_load(self, path):
        path = path.strip("\"'")
        try:
            self.atlas = Atlas.load(path)
        except DataError as error:
            for message in error.errors:
                print("ERROR: " + message)
            if self.atlas:
                print(f"Atlas not loaded. Still using {self.atlas.path}.")
            else:
                print("Atlas not loaded. No atlas in use.")
        else:
            summary = count(len(self.atlas.pipes), "pipe") + ", " + count(len(self.atlas.areas), "area")
            if self.atlas.bridges:
                summary += ", " + count(len(self.atlas.bridges), "bridge")
            print(f"SUCCESS: Atlas loaded from {path}: {summary}.")

    def atlas_pipes(self, _):
        rows = [("NAME", "SIZE", "COMES FROM")]
        for pipe in self.atlas.pipes.values():
            rows.append((pipe.name, pipe.size, ", ".join(pipe.parent_names) or "-"))
        print_table(rows)
        print(count(len(self.atlas.pipes), "pipe"))

    def atlas_areas(self, _):
        rows = [("NAME", "FED BY")]
        for area in self.atlas.areas.values():
            rows.append((area.name, ", ".join(area.pipe_names)))
        print_table(rows)
        print(count(len(self.atlas.areas), "area"))

    def atlas_show(self, name):
        item = self.atlas.get(name.lower())
        if item:
            print(item)
        else:
            print(f'ERROR: No pipe or area called "{name}".')

    def atlas_find(self, word):
        word = word.lower()
        areas = self.atlas.find(word)
        if not areas:
            print(f'No areas match "{word}".')
            return
        verb = "matches" if len(areas) == 1 else "match"
        print(f'{count(len(areas), "area")} {verb} "{word}":')
        print_table([("  " + area.name, area.description) for area in areas])

    def atlas_tree(self, _):
        for line in self.atlas.tree_lines():
            print(line)

    def atlas_path(self, name):
        area = self.find_area(name, "atlas path <area>")
        if area:
            routes = self.atlas.routes_to(area)
            print(f"{count(len(routes), 'route')} from the heart to {area.name}:")
            for route in routes:
                print("  " + " > ".join(route))

    # Mission 2: the lesion engine

    def find_pipes_to_block(self, text):
        pipes = []
        errors = []
        for name in [name.strip() for name in text.split(",")]:
            pipe = self.atlas.pipes.get(name.lower())
            if not name:
                errors.append("Empty pipe name in the list. Separate pipes with commas: a, b, c")
            elif pipe is self.atlas.heart:
                errors.append("The heart cannot be blocked.")
            elif pipe:
                pipes.append(pipe)
            elif name.lower() in self.atlas.areas:
                errors.append(f'"{name}" is an area, not a pipe. Only pipes can be blocked.')
            else:
                errors.append(f'No pipe called "{name}".')
        for error in errors:
            print("ERROR: " + error)
        if errors:
            return None
        return pipes

    def lesion_block(self, text):
        pipes = self.find_pipes_to_block(text)
        if not pipes:
            return
        lesion = Lesion(self.atlas, pipes)
        label = "Blocked pipe: " if len(lesion.blocked) == 1 else "Blocked pipes: "
        print(label + ", ".join(f"{pipe.name} ({pipe.size})" for pipe in lesion.blocked))
        dry = lesion.pipes_without_blood
        print(f"Pipes without blood ({len(dry)}): " + ", ".join(pipe.name for pipe in dry))
        if lesion.stopped_areas:
            print(f"Areas that stop working ({len(lesion.stopped_areas)}):")
            print_table([("  " + area.name, area.description) for area in lesion.stopped_areas])
            print(f"Expected symptoms ({len(lesion.symptoms)}): " + ", ".join(lesion.symptoms))
        else:
            print("Areas that stop working (0): none")
        if lesion.saved_by_bridge:
            saved = [f"{pipe.name} (from {lesion.blood_from[pipe].name})" for pipe in lesion.saved_by_bridge]
            print("Saved by a bridge: " + ", ".join(saved))

    def lesion_risk(self, name):
        area = self.find_area(name, "lesion risk <area>")
        if not area:
            return
        pipes = risky_pipes(self.atlas, area)
        if not pipes:
            print(f"No single blocked pipe can stop {area.name}.")
            return
        verb = "stops" if len(pipes) == 1 else "stop"
        print(f"{count(len(pipes), 'pipe')} {verb} {area.name} if blocked:")
        print_table([("  " + pipe.name, pipe.size) for pipe in pipes])

    def lesion_tree(self, text):
        pipes = self.find_pipes_to_block(text)
        if pipes:
            lesion = Lesion(self.atlas, pipes)
            for line in self.atlas.tree_lines(lesion.status):
                print(line)

    # Mission 3: triage

    def open_cases(self, path):
        try:
            self.cases = CaseBook(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            reason = f"the field {error} is missing" if isinstance(error, KeyError) else str(error)
            print(f"ERROR: The database file {path} is damaged. No cases loaded.")
            print(f"ERROR: Could not read the cases in {path}: {reason}.")
            print("Fix or move the file, then start Synapse again. No case is saved until then.")
        else:
            if self.cases.cases:
                print(f"SUCCESS: Cases loaded from {path}: {count(len(self.cases.cases), 'case')}.")
            else:
                print(f"No saved cases yet. New cases are saved to {path}.")

    def find_case(self, case_id):
        case = self.cases.get(case_id)
        if not case:
            print(f'ERROR: No case called "{case_id}".')
        return case

    def print_result(self, case, before=None):
        severity = f"{case.severity} ({case.band})"
        if before and before.severity != case.severity:
            severity += f", was {before.severity}"
        print_field("  ", "Severity:", severity)
        if case.closest:
            print("  No exact match. Closest pipes:")
            print_table([("    " + name, f"{match}%") for name, match in case.closest])
        pipe = pipe_text(case)
        if before and before.likely_pipe != case.likely_pipe:
            pipe += f", was {before.likely_pipe or 'unknown'}"
        print_field("  ", "Likely blocked pipe:", pipe)
        print_field("  ", "Drug possible:", drug_possible_text(case, case.time_now))
        print_field("  ", "Clot removal:", clot_possible_text(case, case.time_now))

    def triage_load(self, path):
        path = path.strip("\"'")
        try:
            self.symptom_list = SymptomList.load(path)
        except DataError as error:
            for message in error.errors:
                print("ERROR: " + message)
            if self.symptom_list:
                print(f"Symptoms not loaded. Still using {self.symptom_list.path}.")
            else:
                print("Symptoms not loaded. No symptom list in use.")
        else:
            symptoms = count(len(self.symptom_list.symptoms), "symptom")
            print(f"SUCCESS: Symptoms loaded from {path}: {symptoms}.")

    def triage_symptoms(self, _):
        rows = [("CODE", "POINTS", "WHAT THE CREW SEES")]
        for symptom in self.symptom_list.symptoms.values():
            rows.append((symptom.code, str(symptom.points), symptom.description))
        print_table(rows)
        print(count(len(self.symptom_list.symptoms), "symptom"))

    def triage_new(self, _):
        name = ask("Patient name: ", lambda text: required(text, "Name"))
        age = ask("Age: ", parse_age)
        city = ask("City: ", lambda text: required(text, "City"))
        time_now = ask("Time now (HH:MM): ", parse_time)
        while True:
            seen = ask("Last seen well (HH:MM): ", parse_time)
            yesterday = ask("Was that yesterday? (yes/no): ", parse_yes_no)
            try:
                seen_well = last_seen_well(seen, yesterday, time_now)
                break
            except ValueError as error:
                print(f"ERROR: {error}")
        symptoms = ask("Symptoms (comma separated): ", self.symptom_list.parse)
        case = Case(name, age, city, time_now, seen_well, symptoms)
        case.assess(self.atlas, self.symptom_list)
        try:
            self.cases.add(case)
        except OSError:
            print(f"ERROR: Could not save the case to {self.cases.path}.")
            return
        print(f"SUCCESS: Case {case.id} created and saved.")
        self.print_result(case)

    def triage_list(self, _):
        if not self.cases.cases:
            print("No cases yet.")
            return
        rows = [("ID", "NAME", "AGE", "CITY", "SEVERITY", "LIKELY PIPE")]
        for case in self.cases.cases:
            rows.append((case.id, case.name, str(case.age), case.city, f"{case.severity} {case.band}",
                         case.likely_pipe or "unknown"))
        print_table(rows)
        print(count(len(self.cases.cases), "case"))

    def triage_show(self, case_id):
        case = self.find_case(case_id)
        if not case:
            return
        print(f"=== Case {case.id}: {case.name} ===")
        print_field("", "Age:", str(case.age))
        print_field("", "City:", case.city)
        print_field("", "Created at:", clock(case.created_at))
        print_field("", "Last seen well:", clock(case.seen_well))
        print_field("", "Symptoms:", ", ".join(case.symptoms))
        print_field("", "Severity:", f"{case.severity} ({case.band})")
        if case.closest:
            print_field("", "Closest pipes:", ", ".join(f"{name} {match}%" for name, match in case.closest))
        print_field("", "Likely blocked pipe:", pipe_text(case))
        print_field("", "Drug possible:", drug_possible_text(case, case.time_now))
        print_field("", "Clot removal:", clot_possible_text(case, case.time_now))
        if case.history:
            print("Updates:")
            for update in case.history:
                added = ", ".join(update["addedSymptoms"]) or "nothing new"
                print(f"  {update['timeNow']}  added {added}: severity {update['severityBefore']} -> "
                      f"{update['severityAfter']}, likely pipe {update['likelyPipeBefore'] or 'unknown'} -> "
                      f"{update['likelyPipeAfter'] or 'unknown'}")

    def triage_update(self, case_id):
        case = self.find_case(case_id)
        if not case:
            return
        missing = self.symptom_list.missing(case.symptoms)
        if missing:
            print(f"ERROR: {case.id} has symptoms that are not in {self.symptom_list.path}: {', '.join(missing)}. "
                  "Load a symptom list that has them.")
            return
        time_now = ask("Time now (HH:MM): ", lambda text: case.check_update_time(parse_time(text)))
        symptoms = ask("New symptoms (comma separated): ", self.symptom_list.parse)
        updated = case.updated(time_now, symptoms, self.atlas, self.symptom_list)
        try:
            self.cases.replace(case, updated)
        except OSError:
            print(f"ERROR: Could not save the case to {self.cases.path}.")
            return
        print(f"SUCCESS: Case {case.id} updated.")
        self.print_result(updated, before=case)

    def triage_urgent(self, _):
        now = ask("Time now (HH:MM): ", parse_time)
        drug = [case for case in self.cases.cases if case.drug_possible(now)]
        clot = [case for case in self.cases.cases if not case.drug_possible(now) and case.clot_possible(now)]
        if not drug and not clot:
            print(f"No case can still be treated at {clock(now)}.")
            return
        print("Drug still possible:" + ("" if drug else " none"))
        if drug:
            drug.sort(key=lambda case: case.drug_until)
            print_table([("  " + case.id, case.name, "until " + clock(case.drug_until),
                          duration(case.drug_until - now) + " left") for case in drug])
        print("Only clot removal still possible:" + ("" if clot else " none"))
        if clot:
            clot.sort(key=lambda case: case.clot_until)
            print_table([("  " + case.id, case.name, "until " + clock(case.clot_until),
                          duration(case.clot_until - now) + " left") for case in clot])

    # Mission 4: route

    def map_load(self, path):
        path = path.strip("\"'")
        try:
            loaded = load_map_file(path, self.roads)
        except DataError as error:
            for message in error.errors:
                print("ERROR: " + message)
            print("Map file not loaded. Nothing changed.")
        else:
            if isinstance(loaded, Roads):
                self.roads = loaded
                roads = count(loaded.count, "road")
                print(f"SUCCESS: Roads loaded from {path}: {roads}, {len(loaded.roads)} cities.")
            else:
                self.hospitals = loaded
                print(f"SUCCESS: Hospitals loaded from {path}: {count(len(loaded.hospitals), 'hospital')}.")

    def map_coverage(self, _):
        rows = [("CITY", "NEAREST DRUG", "NEAREST CLOT REMOVAL", "")]
        far = 0
        for city in cities(self.roads, self.hospitals):
            trips = trips_from(self.roads, self.hospitals, city)
            clot = fastest(trips, "CLOT")
            is_far = clot is None or clot.minutes > FAR
            if is_far:
                far += 1
            rows.append((city, nearest_text(fastest(trips, "DRUG")), nearest_text(clot), "FAR" if is_far else ""))
        print_table(rows)
        verb = "is" if far == 1 else "are"
        print(f"{far} of {len(rows) - 1} cities {verb} more than {FAR} min from clot removal.")

    def route_from(self, name):
        city = find_city(self.roads, self.hospitals, name)
        if city is None:
            print(f'ERROR: The city "{name}" is not on the map.')
            return
        trips = trips_from(self.roads, self.hospitals, city)
        if not trips:
            print(f"ERROR: No road leads from {city} to any hospital.")
            return
        rows = [("HOSPITAL", "CITY", "CAN DO", "DRIVE", "ROUTE")]
        for trip in trips:
            hospital = trip.hospital
            rows.append((hospital.name, hospital.city, ", ".join(hospital.abilities), minutes_text(trip.minutes),
                         path_text(trip)))
        reached = [trip.hospital for trip in trips]
        for hospital in self.hospitals.hospitals:
            if hospital not in reached:
                rows.append((hospital.name, hospital.city, ", ".join(hospital.abilities), "-", "no road"))
        print_table(rows)

    def route_case(self, case_id):
        missing = self.missing(("cases", "map"))
        if missing:
            print("ERROR: " + missing)
            return
        case = self.find_case(case_id)
        if not case:
            return
        city = find_city(self.roads, self.hospitals, case.city)
        if city is None:
            print(f'ERROR: The city of case {case.id}, "{case.city}", is not on the map.')
            return
        route = Route(case, self.roads, self.hospitals, city)
        if not route.trips:
            print(f"ERROR: No road leads from {city} to any hospital.")
            return
        if not route.visits:
            print(f"ERROR: No road leads from {city} to a hospital with CT.")
            return
        print(f"Case {case.id}: {case.name}, {city}, leaves at {clock(route.leaves)}")
        print(needs_text(case, route.leaves))
        if route.plan_b:
            self.print_plans(route)
        else:
            self.print_visit(route)
        try:
            self.cases.set_routes({case: route.to_dict()})
        except OSError:
            print(f"ERROR: Could not save the route to {self.cases.path}.")
            return
        print(f"SUCCESS: Route saved for {case.id}.")

    def print_visit(self, route):
        visit = route.visits[0]
        if route.needs_clot and route.treatment != "clot removal":
            print("No hospital can remove the clot in time.")
        if route.needs_drug and route.treatment == "scan":
            print("No hospital can give the drug in time.")
        print(f"{TITLES[route.treatment]}: {visit.trip.hospital.name}")
        print_field("  ", "Route:", f"{path_text(visit.trip)}, {visit.trip.minutes} min")
        print_field("  ", "Arrives:", clock(visit.arrives))
        if route.needs_drug:
            print_field("  ", "Drug:", visit_drug_text(route.case, visit))
        if visit.clot_at is not None:
            print_field("  ", "Clot removal:", clock(visit.clot_at))

    def print_plans(self, route):
        a = route.plan_a[0]
        first, second = route.plan_b
        print(f"Plan A, straight to clot removal: {a.trip.hospital.name}")
        print(f"  Leaves {clock(a.leaves)} -> {path_text(a.trip)}, {a.trip.minutes} min")
        print(f"  Arrives {clock(a.arrives)} · {plan_drug_text(route.case, a)} · "
              f"clot removal {clock(a.clot_at)}")
        print("Plan B, drug first, then transfer:")
        print(f"  {first.trip.hospital.name} ({path_text(first.trip)}): arrives {clock(first.arrives)} · "
              f"{plan_drug_text(route.case, first)}")
        print(f"  Transfer leaves {clock(second.leaves)} -> {path_text(second.trip)}, {second.trip.minutes} min")
        print(f"  {second.trip.hospital.name}: arrives {clock(second.arrives)} · "
              f"clot removal {clock(second.clot_at)}")
        print(f"Chosen: Plan {route.chosen}. {route.reason}")

    def route_whatif(self, text):
        words = text.rsplit(maxsplit=1)
        if len(words) < 2:
            print("ERROR: Missing ability. Usage: route whatif <city> <ability>")
            return
        city = find_city(self.roads, self.hospitals, words[0])
        ability = words[1].upper()
        if city is None:
            print(f'ERROR: The city "{words[0]}" is not on the map.')
            return
        if ability not in ABILITIES:
            print(f'ERROR: Unknown ability "{words[1]}". Expected CT, DRUG or CLOT.')
            return
        here = [hospital for hospital in self.hospitals.hospitals if hospital.city == city]
        if not here:
            print(f"ERROR: {city} has no hospital.")
            return
        names = ", ".join(hospital.name for hospital in here)
        if all(ability in hospital.abilities for hospital in here):
            print(f"{names} ({city}) can already {ABILITY_TEXT[ability]}. Nothing would change.")
            return
        print(f"What if {names} ({city}) could also {ABILITY_TEXT[ability]}?")
        changed = with_ability(self.hospitals, city, ability)
        rows = [("CASE", "CITY", "NOW", "WITH THE CHANGE", "SAVED")]
        total = 0
        for case in self.cases.cases:
            if not case.clot_possible(case.created_at):
                continue
            case_city = find_city(self.roads, self.hospitals, case.city)
            if case_city is None:
                rows.append((case.id, case.city, "not on the map", "-", "-"))
                continue
            now = clot_minutes(self.roads, self.hospitals, case_city)
            after = clot_minutes(self.roads, changed, case_city)
            saved = "-"
            if now is not None and after is not None:
                saved = minutes_text(now - after)
                total += now - after
            rows.append((case.id, case_city, minutes_text(now), minutes_text(after), saved))
        if len(rows) == 1:
            print("No saved case can have clot removal, so no drive changes.")
            return
        print_table(rows)
        print(f"Total saved: {total} min over {count(len(rows) - 1, 'case')}.")

    # Mission 5: the stroke unit

    def read_morning(self, text, compare=False):
        """Reads the options, the file and the cases, and prints who comes. None when the morning cannot run."""
        try:
            path, order, scanners = read_options(text)
            if compare and scanners is not None:
                raise ValueError("unit compare always runs 1 and 2 scanners. Leave out --scanners.")
            outside = load_events(path)
        except ValueError as error:
            print(f"ERROR: {error}")
            return None
        except DataError as error:
            for message in error.errors:
                print("ERROR: " + message)
            print("Morning not run. Nothing changed.")
            return None
        inside, elsewhere, skipped = patients_from_cases(self.cases)
        case_ids = [patient.id.upper() for patient in inside]
        both = [patient.id for patient in outside if patient.id.upper() in case_ids]
        for patient_id in both:
            print(f"ERROR: {patient_id} is in {path} and also in your cases. "
                  "Give the patients in the file other ids.")
        if both:
            return None
        for message in skipped:
            print(message)
        patients = outside + inside
        if not patients:
            print("No patients arrive this morning.")
            return None
        if scanners is None:
            scanners = 1
        machines = "1 and 2 CT scanners" if compare else count(scanners, "CT scanner")
        print(f"{UNIT} · {machines} · {ORDERS[order]}")
        away = ""
        if elsewhere:
            verb = "goes to another hospital" if len(elsewhere) == 1 else "go to other hospitals"
            away = f" ({', '.join(elsewhere)} {verb})"
        print(f"{count(len(patients), 'patient')}: {len(outside)} from {os.path.basename(path)}, "
              f"{len(inside)} from your cases{away}")
        return patients, order, scanners

    def unit_run(self, text):
        morning_input = self.read_morning(text)
        if morning_input is None:
            return
        patients, order, scanners = morning_input
        morning = Morning(patients, scanners, order)
        print()
        for time, _, patient, what in morning.events:
            print(f"{clock(time)}  {patient.id} {what}")
        print()
        rows = [("PATIENT", "ARRIVES", "SCAN", "DRUG", "DOOR-TO-DRUG", "CLOT REMOVAL", "NOTE")]
        for stay in morning.stays.values():
            rows.append((stay.patient.id, clock(stay.patient.arrives), clock(stay.scan_at), time_text(stay.drug_at),
                         door_text(stay), stay_clot_text(stay), note_text(stay)))
        print_table(rows)
        print()
        given = morning.given_drug()
        could = morning.could_get_drug()
        if could:
            summary = f"Drug given to {len(given)} of {count(len(could), 'patient')} who could get it."
            if given:
                summary += f" Average door-to-drug: {average_text(morning)}."
            print(summary)
        else:
            print("No patient this morning could still get the drug.")
        if morning.heads():
            print(f"Head injuries scanned late (more than {HEAD_SCAN_LIMIT} min after arrival): "
                  f"{ids_text(morning.late_heads())}.")
        self.save_morning(morning)

    def save_morning(self, morning):
        saved = sorted(stay.patient.id for stay in morning.stays.values() if stay.patient.case)
        if not saved:
            print("No case from your database is in this morning, so nothing is saved.")
            return
        try:
            save_stays(self.cases, morning)
        except OSError:
            print(f"ERROR: Could not save the hospital times to {self.cases.path}.")
            return
        print(f"SUCCESS: Hospital times saved for {', '.join(saved)}.")

    def unit_compare(self, text):
        morning_input = self.read_morning(text, compare=True)
        if morning_input is None:
            return
        patients, order, _ = morning_input
        one = Morning(patients, 1, order)
        two = Morning(patients, 2, order)
        print()
        rows = [("", "1 SCANNER", "2 SCANNERS"),
                ("Drug given", given_text(one), given_text(two)),
                ("Average door-to-drug", average_text(one), average_text(two)),
                (f"SLOW (over {SLOW} min)", ids_text(one.slow()), ids_text(two.slow())),
                ("Missed the drug", ids_text(one.missed_drug()), ids_text(two.missed_drug()))]
        if one.heads():
            rows.append(("Head scans late", ids_text(one.late_heads()), ids_text(two.late_heads())))
        print_table(rows)

    # Mission 6: the recovery clinic

    def clinic_load(self, path):
        path = path.strip("\"'")
        try:
            self.norms = Norms.load(path)
        except DataError as error:
            for message in error.errors:
                print("ERROR: " + message)
            if self.norms:
                print(f"Normal values not loaded. Still using {self.norms.path}.")
            else:
                print("Normal values not loaded. No normal values in use.")
        else:
            print(f"SUCCESS: Normal values loaded from {path}: {count(len(self.norms.norms), 'age band')}.")

    def save_visit(self, case, visit):
        try:
            self.cases.add_visit(case, visit)
        except OSError:
            print(f"ERROR: Could not save the visit to {self.cases.path}.")
            return
        print(f"SUCCESS: Visit on day {visit['day']} saved for {case.id}.")

    def clinic_visit(self, case_id):
        case = self.find_case(case_id)
        if not case:
            return
        day = ask("Days since the stroke: ", lambda text: parse_new_day(case, text))
        results = []
        for number, (title, brain_test) in enumerate(BRAIN_TESTS, start=1):
            print()
            print(f"Test {number} of {len(BRAIN_TESTS)}: {title}")
            results.append(brain_test())
        print()
        self.save_visit(case, make_visit(day, *results))

    def clinic_record(self, case_id):
        case = self.find_case(case_id)
        if not case:
            return
        day = ask("Days since the stroke: ", lambda text: parse_new_day(case, text))
        reaction = ask("Reaction time (ms): ", parse_reaction)
        memory = ask("Memory span (digits): ", parse_memory)
        colorword = ask("Colour words (seconds): ", parse_seconds)
        self.save_visit(case, make_visit(day, reaction, memory, colorword))

    def visits_and_norms(self, case_id):
        """The case, its visits oldest first and its normal values, or None after printing why there are none."""
        case = self.find_case(case_id)
        if not case:
            return None
        if not case.visits:
            print(f"Case {case.id} has no visits yet.")
            return None
        try:
            norms = self.norms.for_age(case.age)
        except ValueError as error:
            print(f"ERROR: {error}")
            return None
        return case, by_day(case.visits), norms

    def clinic_results(self, case_id):
        found = self.visits_and_norms(case_id)
        if found is None:
            return
        case, visits, norms = found
        print(f"{case.name}, {case.age} · {normal_text(norms)}")
        print()
        rows = [("DAY", "REACTION", "", "MEMORY", "", "COLOUR WORDS", "")]
        for visit in visits:
            row = [str(visit["day"])]
            for test in TESTS:
                row += [result_text(test, visit[KEYS[test]]), rating(test, visit[KEYS[test]], norms[test])]
            rows.append(row)
        print_table(rows)
        print()
        if len(visits) < 2:
            print("Only one visit, so there is no trend yet.")
            return
        old, new = visits[-2], visits[-1]
        trends = [f"{TEST_NAMES[test].lower()} {trend(test, old[KEYS[test]], new[KEYS[test]])}" for test in TESTS]
        print(f"Trend, day {new['day']} against day {old['day']}: {', '.join(trends)}.")

    def clinic_check(self, case_id):
        found = self.visits_and_norms(case_id)
        if found is None:
            return
        case, visits, norms = found
        latest = visits[-1]
        previous = visits[-2] if len(visits) > 1 else None
        stopped = damage(self.atlas, case)
        if stopped is not None:
            print(f"Damage: {case.likely_pipe} blocked -> {', '.join(stopped) or 'no area'} stopped working")
        elif case.likely_pipe:
            print(f"Damage: unknown, {case.likely_pipe} is not in {self.atlas.path}")
        else:
            print(f"Damage: unknown, case {case.id} has no likely blocked pipe")
        rows = [("TEST", f"DAY {latest['day']}", "", "TREND", "EXPECTED WEAK")]
        flags = []
        for test, value, rated, moved, expected in test_checks(visits, norms, stopped):
            rows.append((TEST_NAMES[test], result_text(test, value), rated, moved, expected))
            if unexplained(rated, expected):
                reason = "the damage does not explain it" if stopped is not None else "no known damage explains it"
                flags.append(f"{TEST_NAMES[test]} is {rated} normal, and {reason}.")
            if moved == "worse":
                flags.append(f"{TEST_NAMES[test]} is getting worse since day {previous['day']}.")
        print_table(rows)
        for flag in flags:
            print("FLAG: " + flag)
        if flags:
            print("Advice: check the patient for a new stroke.")
        else:
            print("No flags: the damage explains every weak result, and no test is getting worse.")

    def clinic_chart(self, text):
        words = text.split()
        if len(words) != 2:
            print("ERROR: Give a case id and a test. Usage: clinic chart <id> <test>")
            return
        test = words[1].lower()
        if test not in TESTS:
            print(f'ERROR: Unknown test "{words[1]}". Use reaction, memory or colorword.')
            return
        found = self.visits_and_norms(words[0])
        if found is None:
            return
        case, visits, norms = found
        norm = norms[test]
        better = "lower" if LOWER_IS_BETTER[test] else "higher"
        low = norm_number(test, norm.average - norm.spread)
        high = norm_number(test, norm.average + norm.spread)
        print(f"{CHART_TITLES[test]} · {better} is better · "
              f"normal for age {case.age}: {low} to {high} {UNITS[test]}")
        print_table([(f"Day {visit['day']}", "#" * bar_length(test, visit[KEYS[test]]),
                      result_text(test, visit[KEYS[test]])) for visit in visits])

    # Mission 7: the case file

    def case_lines(self, case):
        """The whole story of a case, as lines of text. case <case id> prints them, case export writes them."""
        lines = [f"=== Case {case.id}: {case.name}, {case.age}, {case.city} ===", "", "TRIAGE"]
        pipe = "unknown"
        if case.likely_pipe:
            pipe = f"{case.likely_pipe} ({'big' if case.big_pipe else 'small'})"
        drug = f"Drug possible until {clock(case.drug_until)}"
        if not case.drug_possible(case.time_now):
            drug = f"Drug limit passed at {clock(case.drug_until)}"
        clot = "clot removal not possible"
        if case.clot_possible(case.time_now):
            clot = f"clot removal possible until {clock(case.clot_until)}"
        lines += table_lines([(clock(case.seen_well), "Last seen well"),
                              (clock(case.created_at), "Case created by the ambulance crew"),
                              ("", "Symptoms: " + ", ".join(case.symptoms)),
                              ("", f"Severity {case.severity} ({case.band}) · likely blocked pipe: {pipe}"),
                              ("", f"{drug} · {clot}")])
        lines += [""] + self.route_lines(case) + [""] + self.hospital_lines(case) + [""] + self.recovery_lines(case)
        return lines

    def route_lines(self, case):
        if not has_route(case):
            return [f"ROUTE: not planned yet. Run route {case.id}."]
        route = case.route
        path = route.get("path") or ["?"]
        leaves = f"Leaves {path[0]}: {saved_path_text(path)}, {route.get('driveMinutes')} min"
        events = [(str(route.get("leaves")), leaves),
                  (str(route.get("arrives")), f"Arrives at {route.get('hospital')}")]
        transfer = route.get("transfer")
        if isinstance(transfer, dict):
            if route.get("drugAt"):
                events.append((str(route["drugAt"]), f"Drug at {route.get('hospital')}"))
            path = transfer.get("path") or ["?"]
            events.append((str(transfer.get("leaves")),
                           f"Transfer: {saved_path_text(path)}, {transfer.get('driveMinutes')} min"))
            events.append((str(transfer.get("arrives")), f"Arrives at {transfer.get('hospital')}"))
        return ["ROUTE"] + table_lines(events)

    def hospital_lines(self, case):
        if not has_route(case):
            return ["HOSPITAL: no route yet, so no hospital stay."]
        times = hospital_times(case)
        if hospital_stay(case) is None:
            planned = [f"{step.lower()}: {clock(when)}" for step, when, _ in times if when is not None]
            plan = f"Planned {', '.join(planned)}." if planned else "No treatment was planned."
            if last_leg(case.route).get("hospital") == UNIT:
                return ["HOSPITAL", f"Not recorded yet: run unit run <file>. {plan}"]
            return ["HOSPITAL", f"Not recorded: only {UNIT} is simulated. {plan}"]
        rows = [("HOSPITAL", "PLANNED", "ACTUAL", "WAITED")]
        for step, planned, actual in times:
            waited = "-"
            if planned is not None and actual is not None:
                waited = f"{actual - planned} min"
            rows.append((step, time_text(planned), time_text(actual), waited))
        return table_lines(rows)

    def recovery_lines(self, case):
        if not case.visits:
            return ["RECOVERY", "No clinic visits yet."]
        norms = None
        if self.norms is not None:
            try:
                norms = self.norms.for_age(case.age)
            except ValueError:
                norms = None
        if norms is None:
            header = f"RECOVERY (no normal values for age {case.age})"
        else:
            band = norms["reaction"]
            header = f"RECOVERY (normal for ages {band.from_age}-{band.to_age})"
        rows = []
        for visit in by_day(case.visits):
            row = [f"Day {visit['day']}"]
            for test in TESTS:
                value = visit[KEYS[test]]
                text = f"{TEST_NAMES[test].lower()} {value if test == 'memory' else result_text(test, value)}"
                if norms is not None:
                    text += " " + rating(test, value, norms[test])
                row.append(text if test == "reaction" else "· " + text)
            rows.append(row)
        return [header] + table_lines(rows)

    def case_show(self, case_id):
        missing = self.missing(("cases",))
        if missing:
            print("ERROR: " + missing)
            return
        case = self.find_case(case_id)
        if case:
            for line in self.case_lines(case):
                print(line)

    def case_find(self, text):
        word = text.lower()
        found = [case for case in self.cases.cases if word in case.name.lower() or word in case.city.lower()]
        if not found:
            print(f'No cases match "{text}".')
            return
        if len(found) == 1:
            print(f'1 case matches "{text}". Opening it.')
            self.case_show(found[0].id)
            return
        print(f'{count(len(found), "case")} match "{text}":')
        print_table([(f"{number}. {case.id}", case.name, str(case.age), case.city)
                     for number, case in enumerate(found, start=1)])

        def choice(answer):
            if not answer:
                return None
            if not answer.isdecimal() or not 1 <= int(answer) <= len(found):
                raise ValueError(f"Enter a number from 1 to {len(found)}, or press ENTER to go back.")
            return found[int(answer) - 1]

        picked = ask("Enter a number to open, or press ENTER to go back: ", choice)
        if picked:
            self.case_show(picked.id)

    def case_export(self, case_id):
        case = self.find_case(case_id)
        if not case:
            return
        text_path = os.path.join("exports", case.id + ".txt")
        json_path = os.path.join("exports", case.id + ".json")
        try:
            os.makedirs("exports", exist_ok=True)
            with open(text_path, "w", encoding="utf-8") as file:
                file.write("\n".join(self.case_lines(case)) + "\n")
            with open(json_path, "w", encoding="utf-8") as file:
                json.dump(case.to_dict(), file, indent=2, ensure_ascii=False)
        except OSError as error:
            print(f"ERROR: Could not write the export files: {error.strerror}.")
            return
        print(f"SUCCESS: Wrote {text_path} and {json_path}.")

    def is_flagged(self, case):
        """Bonus 2 of Mission 6: a weak result the damage does not explain, or a test getting worse."""
        if not case.visits or self.atlas is None or self.norms is None:
            return False
        try:
            norms = self.norms.for_age(case.age)
        except ValueError:
            return False
        checks = test_checks(by_day(case.visits), norms, damage(self.atlas, case))
        return any(unexplained(rated, expected) or moved == "worse" for _, _, rated, moved, expected in checks)

    def last_visit_text(self, case):
        if not case.visits:
            return "no visits"
        visit = by_day(case.visits)[-1]
        try:
            norms = self.norms.for_age(case.age)
        except (AttributeError, ValueError):
            return f"day {visit['day']}: no normal values"
        weak = sum(1 for test in TESTS if rating(test, visit[KEYS[test]], norms[test]) != "normal")
        if weak == 0:
            return f"day {visit['day']}: all normal"
        return f"day {visit['day']}: {weak} below normal"

    def case_board(self, _):
        if not self.cases.cases:
            print("No cases yet.")
            return
        rows = [("ID", "NAME", "WENT TO", "FIRST TREATMENT", "WAITED", "LAST VISIT", "")]
        for case in self.cases.cases:
            went = last_leg(case.route).get("hospital") if has_route(case) else "no route"
            first = first_treatment(case)
            treatment = "none"
            waited = "-"
            if first is not None:
                name, when, planned, actual = first
                treatment = f"{name} {clock(when)}" + ("" if actual is not None else " planned")
                if actual is None:
                    waited = "not recorded"
                elif planned is not None:
                    waited = f"{actual - planned} min"
            rows.append((case.id, case.name, str(went), treatment, waited, self.last_visit_text(case),
                         "!" if self.is_flagged(case) else ""))
        print_table(rows)
        print("! = check for a new stroke")

    def case_cost(self, case_id):
        case = self.find_case(case_id)
        if not case:
            return
        first = first_treatment(case)
        if first is None:
            print(f"No treatment was planned or recorded for {case.id}, so there is nothing to count yet.")
            return
        name, when, planned, actual = first
        minutes = when - case.seen_well
        kind = "" if actual is not None else ", planned"
        print(f"Last seen well {clock(case.seen_well)} -> first treatment {clock(when)} ({name}{kind}): "
              f"{minutes} min")
        print(f"About {millions(minutes)} million brain cells lost before treatment, at 1.9 million a minute.")
        if actual is None:
            print("The time spent waiting in the hospital line is not recorded for this case.")
        elif planned is None:
            print("There was no planned time to compare with, so the waiting time is not known.")
        elif actual - planned > 0:
            print(f"{actual - planned} of those minutes were spent waiting in the hospital line: "
                  f"about {millions(actual - planned)} million.")
        else:
            print("No minutes were spent waiting in the hospital line.")
        print("The 1.9 million figure is a published average for large strokes, used here as an estimate.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    shell = Synapse()
    print('Synapse 1.0 · type "help" to see all commands')
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # so data/... paths work wherever it is started from
    shell.atlas_load(os.path.join("data", "atlas.txt"))
    shell.triage_load(os.path.join("data", "symptoms.txt"))
    shell.open_cases(os.path.join("data", "cases.json"))
    shell.map_load(os.path.join("data", "roads.txt"))
    shell.map_load(os.path.join("data", "hospitals.txt"))
    shell.clinic_load(os.path.join("data", "norms.txt"))
    while True:
        try:
            line = input("\nsynapse> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        try:
            if not shell.run_command(line):
                break
        except KeyboardInterrupt:
            print("\nCancelled.")
        except EOFError:
            print()
            break
        except Exception as error:
            print(f"ERROR: Unexpected problem: {error}")


if __name__ == "__main__":
    main()
