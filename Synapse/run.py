"""Synapse with every mission's commands, Mission 4 routes included. Start with: python run.py"""
import os
import sys

from atlas import AtlasError
from main import TriageShell, print_field
from route import (ABILITIES, DRUG_TIME, FAR, RouteBook, Roads, Route, cities, clot_minutes, fastest, find_city,
                   load_map_file, trips_from, with_ability)
from synapse import count, print_table
from triage import clock

ROUTE_HELP = """Map and route commands:
  map load <path>                load a new roads or hospitals file (nothing changes if it has errors)
  map coverage                   for every city, the drive to the nearest drug and clot removal
  route from <city>              list every hospital with the fastest drive and the cities on the way
  route <case id>                choose the hospital for a case and save the route in the case
  route whatif <city> <ability>  the drive to clot removal for every case, if the hospital in city could do more"""

TITLES = {
    "clot removal": "Fastest hospital that can remove the clot",
    "drug": "Fastest hospital that can give the drug in time",
    "scan": "Fastest hospital with CT, for a scan and care",
}

ABILITY_TEXT = {"CT": "do CT scans", "DRUG": "give the drug", "CLOT": "remove clots"}


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


def drug_text(case, visit):
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


class RouteShell(TriageShell):
    def __init__(self):
        super().__init__()
        self.roads = None
        self.hospitals = None
        self.commands["map"] = {
            "load": (self.map_load, "<path>"),
            "coverage": (self.map_coverage, ""),
        }
        self.commands["route"] = {
            "from": (self.route_from, "<city>"),
            "whatif": (self.route_whatif, "<city and ability>"),
        }

    def run_command(self, line):
        words = line.split()
        if words and words[0].lower() == "help":
            super().run_command(line)
            print(ROUTE_HELP)
            return True
        if len(words) == 2 and words[0].lower() == "route" and words[1].lower() not in self.commands["route"]:
            self.route_case(words[1])
            return True
        return super().run_command(line)

    def open_cases(self, path):
        try:
            self.cases = RouteBook(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            reason = f"the field {error} is missing" if isinstance(error, KeyError) else str(error)
            print(f"ERROR: Could not read the cases in {path}: {reason}.")
            print("Fix or move the file, then start Synapse again. No case is saved until then.")
        else:
            if self.cases.cases:
                print(f"SUCCESS: Cases loaded from {path}: {count(len(self.cases.cases), 'case')}.")
            else:
                print(f"No saved cases yet. New cases are saved to {path}.")

    def map_ready(self):
        if self.roads is None or self.hospitals is None:
            print("ERROR: No map is loaded. Use: map load <path>, first for the roads, then for the hospitals.")
            return False
        return True

    def map_load(self, path):
        path = path.strip("\"'")
        try:
            loaded = load_map_file(path, self.roads)
        except AtlasError as error:
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
        if not self.map_ready():
            return
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
        if not self.map_ready():
            return
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
        if not self.can_run(symptoms=False, cases=True) or not self.map_ready():
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
            self.cases.set_route(case, route.to_dict())
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
            print_field("  ", "Drug:", drug_text(route.case, visit))
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
        if not self.can_run(symptoms=False, cases=True) or not self.map_ready():
            return
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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    shell = RouteShell()
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
