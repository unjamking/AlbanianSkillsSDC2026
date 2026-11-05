"""Route: the roads, the hospitals, the fastest drive to each hospital, and where the ambulance takes a case."""
import heapq
import json
import os

from atlas import AtlasError
from triage import CaseBook, clock

ABILITIES = ("CT", "DRUG", "CLOT")
OWN_CITY_DRIVE = 10
DRUG_TIME = 30
CLOT_TIME = 60
TRANSFER_LEAVES = 45
CLOT_AFTER_TRANSFER = 30
FAR = 120


class Roads:
    def __init__(self, path, roads, count):
        self.path = path
        self.roads = roads  # city -> [(next city, minutes)], cities in the order they first appear
        self.count = count

    @staticmethod
    def read(path, records):
        roads = {}
        seen = set()
        errors = []
        for number, fields in records:
            if fields[0] != "ROAD":
                problem = f'unknown record type "{fields[0]}". Expected ROAD.'
            elif len(fields) != 4:
                problem = f"ROAD needs 4 fields, found {len(fields)}."
            elif not fields[1] or not fields[2]:
                problem = "a city name is missing."
            elif fields[1] == fields[2]:
                problem = f'the road starts and ends in "{fields[1]}".'
            elif not fields[3].isdecimal() or int(fields[3]) == 0:
                problem = f'minutes must be a whole number above 0, found "{fields[3]}".'
            elif tuple(sorted(fields[1:3])) in seen:
                problem = f"the road {fields[1]} - {fields[2]} is listed twice."
            else:
                problem = None
                a, b, minutes = fields[1], fields[2], int(fields[3])
                roads.setdefault(a, []).append((b, minutes))
                roads.setdefault(b, []).append((a, minutes))
                seen.add(tuple(sorted((a, b))))
            if problem:
                errors.append(f"{path}, line {number}: {problem}")
        if errors:
            raise AtlasError(errors)
        return Roads(path, roads, len(seen))


class Hospital:
    def __init__(self, name, city, abilities):
        self.name = name
        self.city = city
        self.abilities = abilities


class Hospitals:
    def __init__(self, path, hospitals):
        self.path = path
        self.hospitals = hospitals

    @staticmethod
    def read(path, records, roads):
        if roads is None:
            raise AtlasError([f"Cannot check {path}: load the roads first, every hospital must be on a road."])
        hospitals = []
        first_line = {}
        errors = []
        for number, fields in records:
            abilities = [ability.strip().upper() for ability in fields[-1].split(",")]
            unknown = [ability for ability in abilities if ability not in ABILITIES]
            if fields[0] != "HOSPITAL":
                problem = f'unknown record type "{fields[0]}". Expected HOSPITAL.'
            elif len(fields) != 4:
                problem = f"HOSPITAL needs 4 fields, found {len(fields)}."
            elif not fields[1]:
                problem = "a hospital name is missing."
            elif fields[1] in first_line:
                problem = f'"{fields[1]}" is listed twice (first on line {first_line[fields[1]]}).'
            elif fields[2] not in roads.roads:
                problem = f'city "{fields[2]}" is not on any road.'
            elif not fields[3]:
                problem = f'hospital "{fields[1]}" is missing "can do".'
            elif unknown:
                problem = f'unknown ability "{unknown[0]}". Expected CT, DRUG or CLOT.'
            elif len(set(abilities)) != len(abilities):
                problem = "an ability is listed twice."
            elif "DRUG" in abilities and "CT" not in abilities:
                problem = "a hospital that gives the DRUG must also have CT."
            else:
                problem = None
                hospitals.append(Hospital(fields[1], fields[2], abilities))
                first_line[fields[1]] = number
            if problem:
                errors.append(f"{path}, line {number}: {problem}")
        if errors:
            raise AtlasError(errors)
        return Hospitals(path, hospitals)


def load_map_file(path, roads):
    """Reads a roads or a hospitals file. The first ROAD or HOSPITAL record says which of the two it is."""
    try:
        with open(path, encoding="utf-8-sig") as file:
            lines = [line.strip() for line in file]
    except FileNotFoundError:
        raise AtlasError([f"File not found: {path}"])
    except UnicodeDecodeError:
        raise AtlasError([f"Cannot read {path}: it is not a UTF-8 text file."])
    except OSError as error:
        raise AtlasError([f"Cannot read {path}: {error.strerror}"])
    records = []
    for number, text in enumerate(lines, start=1):
        if text and not text.startswith("#"):
            records.append((number, [field.strip() for field in text.split("|")]))
    if not records:
        raise AtlasError(["The file is empty."])
    for number, fields in records:
        if fields[0] == "ROAD":
            return Roads.read(path, records)
        if fields[0] == "HOSPITAL":
            return Hospitals.read(path, records, roads)
    number, fields = records[0]
    raise AtlasError([f'{path}, line {number}: unknown record type "{fields[0]}". Expected ROAD or HOSPITAL.'])


def cities(roads, hospitals):
    """The cities on the roads, then any hospital city that a new roads file left without a road."""
    names = list(roads.roads)
    for hospital in hospitals.hospitals:
        if hospital.city not in names:
            names.append(hospital.city)
    return names


def find_city(roads, hospitals, name):
    for city in cities(roads, hospitals):
        if city.lower() == name.lower():
            return city
    return None


class Trip:
    def __init__(self, hospital, path, minutes):
        self.hospital = hospital
        self.path = path
        self.minutes = minutes


def trips_from(roads, hospitals, start):
    """Every hospital that can be reached from start, fastest first. Equal times keep the order of the file."""
    # Dijkstra: always go on from the closest city that is not finished yet
    minutes = {start: 0}
    came_from = {}
    queue = [(0, start)]
    while queue:
        time, city = heapq.heappop(queue)
        if time > minutes[city]:
            continue  # an old entry, a faster way to this city was found after it was added
        for next_city, road_minutes in roads.roads.get(city, []):
            if next_city not in minutes or time + road_minutes < minutes[next_city]:
                minutes[next_city] = time + road_minutes
                came_from[next_city] = city
                heapq.heappush(queue, (minutes[next_city], next_city))
    trips = []
    for hospital in hospitals.hospitals:
        if hospital.city == start:
            trips.append(Trip(hospital, [start], OWN_CITY_DRIVE))
        elif hospital.city in minutes:
            path = [hospital.city]
            while path[-1] != start:
                path.append(came_from[path[-1]])
            trips.append(Trip(hospital, path[::-1], minutes[hospital.city]))
    trips.sort(key=lambda trip: trip.minutes)
    return trips


def fastest(trips, ability, in_time=lambda trip: True):
    for trip in trips:
        if ability in trip.hospital.abilities and in_time(trip):
            return trip
    return None


def clot_minutes(roads, hospitals, city):
    trip = fastest(trips_from(roads, hospitals, city), "CLOT")
    if trip is None:
        return None
    return trip.minutes


def with_ability(hospitals, city, ability):
    """A copy of the hospitals in which those in city can also do ability. The hospitals in use stay the same."""
    changed = []
    for hospital in hospitals.hospitals:
        if hospital.city == city and ability not in hospital.abilities:
            hospital = Hospital(hospital.name, hospital.city, hospital.abilities + [ability])
        changed.append(hospital)
    return Hospitals(hospitals.path, changed)


def clock_or_none(minutes):
    if minutes is None:
        return None
    return clock(minutes)


class Visit:
    def __init__(self, trip, leaves):
        self.trip = trip
        self.leaves = leaves
        self.arrives = leaves + trip.minutes
        self.drug_at = None
        self.clot_at = None

    def to_dict(self):
        return {
            "hospital": self.trip.hospital.name,
            "path": self.trip.path,
            "driveMinutes": self.trip.minutes,
            "leaves": clock(self.leaves),
            "arrives": clock(self.arrives),
            "drugAt": clock_or_none(self.drug_at),
            "clotRemovalAt": clock_or_none(self.clot_at),
        }


class Route:
    """Where the ambulance takes a case. Clot removal is better than the drug, the drug is better than a scan."""

    def __init__(self, case, roads, hospitals, city):
        self.case = case
        self.leaves = case.created_at
        self.needs_clot = case.clot_possible(self.leaves)
        self.needs_drug = case.drug_possible(self.leaves)
        self.trips = trips_from(roads, hospitals, city)
        self.treatment = None  # "clot removal", "drug" or "scan"; None when no hospital with CT can be reached
        self.visits = []  # the chosen plan: one hospital, or two with a transfer between them
        self.plan_a = None
        self.plan_b = None
        self.chosen = "A"
        self.reason = ""
        clot = fastest(self.trips, "CLOT", lambda trip: case.clot_possible(self.leaves + trip.minutes + CLOT_TIME))
        drug = fastest(self.trips, "DRUG", lambda trip: case.drug_possible(self.leaves + trip.minutes + DRUG_TIME))
        scan = fastest(self.trips, "CT")
        if clot:
            self.treatment = "clot removal"
            self.plan_a = [self._visit(clot)]
            self.plan_a[0].clot_at = self.plan_a[0].arrives + CLOT_TIME
            self.plan_b = self._drug_then_transfer(roads, hospitals)
            self.chosen, self.reason = self._choose()
            self.visits = self.plan_b if self.chosen == "B" else self.plan_a
        elif drug:
            self.treatment = "drug"
            self.visits = [self._visit(drug)]
        elif scan:
            self.treatment = "scan"
            self.visits = [self._visit(scan)]

    def _visit(self, trip):
        visit = Visit(trip, self.leaves)
        if "DRUG" in trip.hospital.abilities and self.case.drug_possible(visit.arrives + DRUG_TIME):
            visit.drug_at = visit.arrives + DRUG_TIME
        return visit

    def _drug_then_transfer(self, roads, hospitals):
        """Bonus 1, plan B: the drug at the fastest hospital that gives it, then a transfer to clot removal."""
        drug = fastest(self.trips, "DRUG")
        if not self.needs_drug or drug is None or "CLOT" in drug.hospital.abilities:
            return None
        first = self._visit(drug)
        transfer = fastest(trips_from(roads, hospitals, drug.hospital.city), "CLOT")
        second = Visit(transfer, first.arrives + TRANSFER_LEAVES)
        second.clot_at = second.arrives + CLOT_AFTER_TRANSFER
        return [first, second]

    def _choose(self):
        """If only one plan gives the drug in time, choose it. Otherwise choose the earlier clot removal."""
        a, b = self.plan_a, self.plan_b
        if b is None:
            return "A", ""
        if not self.case.clot_possible(b[-1].clot_at):
            return "A", "Plan B removes the clot too late."
        a_drug = a[0].drug_at is not None
        b_drug = b[0].drug_at is not None
        if a_drug != b_drug:
            return ("A" if a_drug else "B"), "Only this plan gives the drug in time."
        both = "Both plans give" if a_drug else "Neither plan gives"
        sooner = abs(a[-1].clot_at - b[-1].clot_at)
        chosen = "B" if b[-1].clot_at < a[-1].clot_at else "A"
        return chosen, f"{both} the drug in time, and this one removes the clot {sooner} min sooner."

    def to_dict(self):
        route = {"treatment": self.treatment}
        route.update(self.visits[0].to_dict())
        route["transfer"] = self.visits[1].to_dict() if len(self.visits) == 2 else None
        return route


class RouteBook(CaseBook):
    """The cases file of Mission 3, with the chosen route kept inside each case."""

    def __init__(self, path):
        super().__init__(path)
        self.routes = {}  # case id -> saved route
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                for item in json.load(file)["cases"]:
                    if "route" in item:
                        self.routes[str(item["id"])] = item["route"]

    def set_route(self, case, route):
        old_routes = dict(self.routes)
        self.routes[case.id] = route
        try:
            self.save()
        except OSError:
            self.routes = old_routes
            raise

    def save(self):
        data = {"nextNumber": self.next_number, "cases": []}
        for case in self.cases:
            item = case.to_dict()
            if case.id in self.routes:
                item["route"] = self.routes[case.id]
            data["cases"].append(item)
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        os.replace(temp_path, self.path)
