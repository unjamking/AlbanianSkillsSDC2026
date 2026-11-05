"""Synapse with every mission's commands, Mission 5 stroke unit included. Start with: python start.py"""
import os
import sys

from atlas import AtlasError
from run import RouteShell
from synapse import count, print_table
from triage import clock
from unit import (HEAD_SCAN_LIMIT, MAX_SCANNERS, ORDERS, SLOW, UNIT, Morning, load_events, patients_from_cases,
                  save_stays)

UNIT_HELP = """Stroke unit commands:
  unit run <file>       replay the morning at Qendra Neuro Tirana and save the hospital times in the cases
  unit compare <file>   run the same morning with 1 and with 2 CT scanners, side by side
  Options after the file: --order deadline (deadline first), --scanners <n> (unit run only)"""


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


def clot_text(stay):
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


class UnitShell(RouteShell):
    def __init__(self):
        super().__init__()
        self.commands["unit"] = {
            "run": (self.unit_run, "<file>"),
            "compare": (self.unit_compare, "<file>"),
        }

    def run_command(self, line):
        words = line.split()
        if words and words[0].lower() == "help":
            super().run_command(line)
            print(UNIT_HELP)
            return True
        return super().run_command(line)

    def read_morning(self, text, compare=False):
        """Reads the options, the file and the cases, and prints who comes. None when the morning cannot run."""
        if not self.can_run(symptoms=False, cases=True):
            return None
        try:
            path, order, scanners = read_options(text)
            if compare and scanners is not None:
                raise ValueError("unit compare always runs 1 and 2 scanners. Leave out --scanners.")
            outside = load_events(path)
        except ValueError as error:
            print(f"ERROR: {error}")
            return None
        except AtlasError as error:
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
                         door_text(stay), clot_text(stay), note_text(stay)))
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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    shell = UnitShell()
    print('Synapse 1.0 · type "help" to see all commands')
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    shell.atlas_load(os.path.join("data", "atlas.txt"))
    shell.triage_load(os.path.join("data", "symptoms.txt"))
    shell.open_cases(os.path.join("data", "cases.json"))
    shell.map_load(os.path.join("data", "roads.txt"))
    shell.map_load(os.path.join("data", "hospitals.txt"))
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
