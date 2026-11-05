"""Synapse with every mission's commands, Mission 3 triage included. Start with: python main.py"""
import os
import sys

from atlas import AtlasError
from synapse import HELP, Synapse, count, print_table
from triage import (CLOSEST_MATCH_NEEDED, CLOT_MIN_SEVERITY, Case, CaseBook, SymptomList, clock, duration,
                    last_seen_well, parse_age, parse_time, parse_yes_no, percent, required)

TRIAGE_HELP = """Triage commands:
  triage symptoms      list every symptom code with its points
  triage load <path>   load another symptom list (nothing changes if it has errors)
  triage new           create a case: asks for the patient's details one by one
  triage list          list every case
  triage show <id>     show one case in full
  triage update <id>   add new symptoms to a case and compute everything again
  triage urgent        list the cases that can still be treated, shortest time left first"""

LABEL_WIDTH = 21


def ask(question, parse):
    while True:
        try:
            return parse(input(question).strip())
        except ValueError as error:
            print(f"ERROR: {error}")


def pipe_text(case):
    if not case.likely_pipe:
        if case.closest:
            return f"unknown, no pipe matches {percent(CLOSEST_MATCH_NEEDED)}% or more of these symptoms"
        return "unknown, no single pipe matches these symptoms exactly"
    text = f"{case.likely_pipe} ({'big' if case.big_pipe else 'small'})"
    if case.closest:
        text += f", {case.match}% match"
    return text


def drug_text(case, now):
    if case.drug_possible(now):
        return f"yes, until {clock(case.drug_until)} ({duration(case.drug_until - now)} left)"
    return f"no, the time limit passed at {clock(case.drug_until)}"


def clot_text(case, now):
    if not case.likely_pipe:
        return "no, the blocked pipe is unknown"
    if not case.big_pipe:
        return f"no, {case.likely_pipe} is a small pipe"
    if case.severity < CLOT_MIN_SEVERITY:
        return f"no, the severity is below {CLOT_MIN_SEVERITY}"
    if not case.clot_possible(now):
        return f"no, the time limit passed at {clock(case.clot_until)}"
    return f"yes, until {clock(case.clot_until)}"


def print_field(indent, label, value):
    print(indent + label.ljust(LABEL_WIDTH) + value)


class TriageShell(Synapse):
    def __init__(self):
        super().__init__()
        self.symptom_list = None
        self.cases = None
        self.commands["triage"] = {
            "symptoms": (self.triage_symptoms, ""),
            "load": (self.triage_load, "<path>"),
            "new": (self.triage_new, ""),
            "list": (self.triage_list, ""),
            "show": (self.triage_show, "<id>"),
            "update": (self.triage_update, "<id>"),
            "urgent": (self.triage_urgent, ""),
        }

    def run_command(self, line):
        words = line.split()
        if words and words[0].lower() == "help":
            print(HELP)
            print(TRIAGE_HELP)
            return True
        return super().run_command(line)

    def open_cases(self, path):
        try:
            self.cases = CaseBook(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            reason = f"the field {error} is missing" if isinstance(error, KeyError) else str(error)
            print(f"ERROR: Could not read the cases in {path}: {reason}.")
            print("Fix or move the file, then start Synapse again. No case is saved until then.")
        else:
            if self.cases.cases:
                print(f"SUCCESS: Cases loaded from {path}: {count(len(self.cases.cases), 'case')}.")
            else:
                print(f"No saved cases yet. New cases are saved to {path}.")

    def can_run(self, symptoms, cases):
        if symptoms and self.symptom_list is None:
            print("ERROR: No symptom list is loaded. Use: triage load <path>")
            return False
        if cases and self.cases is None:
            print("ERROR: The cases file could not be read, so no case can be used or saved.")
            return False
        return True

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
        print_field("  ", "Drug possible:", drug_text(case, case.time_now))
        print_field("  ", "Clot removal:", clot_text(case, case.time_now))

    def triage_load(self, path):
        path = path.strip("\"'")
        try:
            self.symptom_list = SymptomList.load(path)
        except AtlasError as error:
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
        if not self.can_run(symptoms=True, cases=False):
            return
        rows = [("CODE", "POINTS", "WHAT THE CREW SEES")]
        for symptom in self.symptom_list.symptoms.values():
            rows.append((symptom.code, str(symptom.points), symptom.description))
        print_table(rows)
        print(count(len(self.symptom_list.symptoms), "symptom"))

    def triage_new(self, _):
        if not self.can_run(symptoms=True, cases=True):
            return
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
        if not self.can_run(symptoms=False, cases=True):
            return
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
        if not self.can_run(symptoms=False, cases=True):
            return
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
        print_field("", "Drug possible:", drug_text(case, case.time_now))
        print_field("", "Clot removal:", clot_text(case, case.time_now))
        if case.history:
            print("Updates:")
            for update in case.history:
                added = ", ".join(update["addedSymptoms"]) or "nothing new"
                print(f"  {update['timeNow']}  added {added}: severity {update['severityBefore']} -> "
                      f"{update['severityAfter']}, likely pipe {update['likelyPipeBefore'] or 'unknown'} -> "
                      f"{update['likelyPipeAfter'] or 'unknown'}")

    def triage_update(self, case_id):
        if not self.can_run(symptoms=True, cases=True):
            return
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
        if not self.can_run(symptoms=False, cases=True):
            return
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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    shell = TriageShell()
    print('Synapse 1.0 · type "help" to see all commands')
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    shell.atlas_load(os.path.join("data", "atlas.txt"))
    shell.triage_load(os.path.join("data", "symptoms.txt"))
    shell.open_cases(os.path.join("data", "cases.json"))
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
