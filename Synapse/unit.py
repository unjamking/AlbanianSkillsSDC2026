"""The stroke unit: the patients of one morning, the scanner and the clot removal room, and the hospital times."""
from atlas import AtlasError
from route import clock_or_none
from triage import CLOT_MIN_SEVERITY, CLOT_WINDOW, DRUG_WINDOW, MINUTES_PER_DAY, clock, parse_time

UNIT = "Qendra Neuro Tirana"
SCAN_TIME = 15
DRUG_AFTER_SCAN = 15
ROOM_AFTER_SCAN = 45
ROOM_TIME = 60
SLOW = 60
HEAD_SCAN_LIMIT = 60
DEADLINE_AFTER_ARRIVAL = 60
MAX_SCANNERS = 10
ORDERS = {"arrival": "first come, first served", "deadline": "deadline first"}
DAYS = {"": 0, "yesterday": -1, "tomorrow": 1}
EVENT_ORDER = ("arrives", "scan", "drug", "clot")


class Patient:
    def __init__(self, patient_id, kind, arrives, severity=0, drug_until=None, clot_until=None, needs_clot=False):
        self.id = patient_id
        self.kind = kind  # "stroke" or "head"
        self.arrives = arrives
        self.severity = severity
        self.drug_until = drug_until  # None: never gets the drug here
        self.clot_until = clot_until
        self.needs_clot = needs_clot
        self.case = None  # the saved case, for a patient from the database
        self.note = ""

    def drug_in_time(self, scan_at):
        """True if a scan that starts at scan_at still gives the drug within the limit."""
        return self.drug_until is not None and scan_at + SCAN_TIME + DRUG_AFTER_SCAN <= self.drug_until


def read_time(text):
    try:
        return parse_time(text)
    except ValueError:
        return None


def parse_clock(text):
    """Reads a time written by clock(), such as "01:20 tomorrow"."""
    time, _, day = text.partition(" ")
    return parse_time(time) + DAYS[day] * MINUTES_PER_DAY


def stroke_patient(patient_id, arrives, severity, seen, big_pipe):
    if seen > arrives:
        seen -= MINUTES_PER_DAY  # seen well later in the day than the arrival: that was yesterday
    clot_until = seen + CLOT_WINDOW
    needs_clot = big_pipe and severity >= CLOT_MIN_SEVERITY and arrives <= clot_until
    return Patient(patient_id, "stroke", arrives, severity, seen + DRUG_WINDOW, clot_until, needs_clot)


def load_events(path):
    try:
        with open(path, encoding="utf-8-sig") as file:
            lines = [line.strip() for line in file]
    except FileNotFoundError:
        raise AtlasError([f"File not found: {path}"])
    except UnicodeDecodeError:
        raise AtlasError([f"Cannot read {path}: it is not a UTF-8 text file."])
    except OSError as error:
        raise AtlasError([f"Cannot read {path}: {error.strerror}"])
    patients = []
    first_line = {}
    errors = []
    for number, text in enumerate(lines, start=1):
        if not text or text.startswith("#"):
            continue
        fields = [field.strip() for field in text.split("|")]
        kind = fields[3].lower() if len(fields) == 7 else ""
        if fields[0] != "ARRIVAL":
            problem = f'unknown record type "{fields[0]}". Expected ARRIVAL.'
        elif len(fields) != 7:
            problem = f"ARRIVAL needs 7 fields, found {len(fields)}."
        elif read_time(fields[1]) is None:
            problem = f'invalid time "{fields[1]}". Use HH:MM.'
        elif not fields[2]:
            problem = "a patient id is missing."
        elif fields[2].upper() in first_line:
            problem = f"patient {fields[2]} is listed twice (first on line {first_line[fields[2].upper()]})."
        elif kind not in ("stroke", "head"):
            problem = f'unknown patient type "{fields[3]}". Expected stroke or head.'
        elif kind == "head" and fields[4:] != ["-", "-", "-"]:
            problem = 'a head injury has "-" for severity, last seen well and big pipe.'
        elif kind == "stroke" and not fields[4].isdecimal():
            problem = f'severity must be a whole number, found "{fields[4]}".'
        elif kind == "stroke" and read_time(fields[5]) is None:
            problem = f'invalid time "{fields[5]}". Use HH:MM.'
        elif kind == "stroke" and fields[6].lower() not in ("yes", "no"):
            problem = "big pipe must be yes or no."
        else:
            problem = None
            arrives = parse_time(fields[1])
            if kind == "head":
                patients.append(Patient(fields[2], "head", arrives))
            else:
                patients.append(stroke_patient(fields[2], arrives, int(fields[4]), parse_time(fields[5]),
                                               fields[6].lower() == "yes"))
            first_line[fields[2].upper()] = number
        if problem:
            errors.append(f"{path}, line {number}: {problem}")
    if errors:
        raise AtlasError(errors)
    return patients


def patients_from_cases(book):
    """The cases whose saved route ends at the stroke unit, the ids of the others, and the skip messages."""
    patients = []
    elsewhere = []
    skipped = []
    for case in book.cases:
        route = book.routes.get(case.id)
        if route is None:
            skipped.append(f"Case {case.id} has no route yet. Run route {case.id} first. Skipped.")
            continue
        try:
            last = route if route["transfer"] is None else route["transfer"]
            hospital = last["hospital"]
            arrives = parse_clock(last["arrives"])
            note = ""
            if route["transfer"] is not None and route["drugAt"] is not None:
                note = f"drug given at {route['hospital']} ({route['drugAt']})"
        except (KeyError, TypeError, ValueError, AttributeError):
            skipped.append(f"Case {case.id} has a saved route that cannot be read. "
                           f"Run route {case.id} again. Skipped.")
            continue
        if hospital != UNIT:
            elsewhere.append(case.id)
            continue
        patient = Patient(case.id, "stroke", arrives, case.severity, case.drug_until, case.clot_until,
                          case.clot_possible(arrives))
        patient.case = case
        if note:
            patient.drug_until = None  # the drug was given before the transfer
            patient.note = note
        patients.append(patient)
    return patients, elsewhere, skipped


class Stay:
    """What happens to one patient in the hospital."""

    def __init__(self, patient):
        self.patient = patient
        self.scan_at = None
        self.drug_at = None
        self.ready_at = None  # ready for the clot removal room
        self.clot_at = None
        self.missed_clot = False

    @property
    def scan_wait(self):
        return self.scan_at - self.patient.arrives

    @property
    def door_to_drug(self):
        if self.drug_at is None:
            return None
        return self.drug_at - self.patient.arrives

    def to_dict(self):
        return {
            "hospital": UNIT,
            "arrives": clock(self.patient.arrives),
            "scanAt": clock(self.scan_at),
            "drugAt": clock_or_none(self.drug_at),
            "doorToDrugMinutes": self.door_to_drug,
            "clotRemovalAt": clock_or_none(self.clot_at),
        }


class Morning:
    """One morning at the stroke unit. Like Lesion and Route, everything is worked out at once."""

    def __init__(self, patients, scanners=1, order="arrival"):
        self.patients = sorted(patients, key=lambda patient: (patient.arrives, patient.id))
        self.scanners = scanners
        self.order = order
        self.stays = {patient: Stay(patient) for patient in self.patients}
        self.events = [(patient.arrives, "arrives", patient, "arrives") for patient in self.patients]
        self._scan_everyone()
        self._clot_room()
        self.events.sort(key=lambda event: (event[0], EVENT_ORDER.index(event[1])))

    def _scan_everyone(self):
        coming = list(self.patients)
        if not coming:
            return
        waiting = []
        now = coming[0].arrives
        free_at = [now] * self.scanners
        while coming or waiting:
            scanner = free_at.index(min(free_at))
            now = max(now, free_at[scanner])  # time only moves forward, a scanner free earlier has been waiting
            if not waiting and coming[0].arrives > now:
                now = coming[0].arrives  # nobody is waiting: the scanner waits for the next arrival
            while coming and coming[0].arrives <= now:
                waiting.append(coming.pop(0))
            patient = min(waiting, key=lambda patient: self._priority(patient, now))
            waiting.remove(patient)
            self._scan(patient, now)
            free_at[scanner] = now + SCAN_TIME

    def _priority(self, patient, now):
        if self.order == "arrival":
            return patient.arrives, patient.id
        # Bonus 1: the last minute the scan can start and still give the drug, otherwise arrival + 60 min
        if patient.drug_in_time(now):
            deadline = patient.drug_until - SCAN_TIME - DRUG_AFTER_SCAN
        else:
            deadline = patient.arrives + DEADLINE_AFTER_ARRIVAL
        return deadline, -patient.severity, patient.arrives, patient.id

    def _scan(self, patient, now):
        stay = self.stays[patient]
        stay.scan_at = now
        text = "scan starts"
        if patient.kind == "head" and stay.scan_wait > HEAD_SCAN_LIMIT:
            text += f" ({stay.scan_wait} min after arrival, too late for a head injury)"
        self.events.append((now, "scan", patient, text))
        scan_end = now + SCAN_TIME
        if patient.drug_in_time(now):
            stay.drug_at = scan_end + DRUG_AFTER_SCAN
            text = f"drug given ({stay.door_to_drug} min after arrival)"
            self.events.append((stay.drug_at, "drug", patient, text))
        elif patient.drug_in_time(patient.arrives):
            text = "drug limit passed before the drug could be given"
            self.events.append((patient.drug_until, "drug", patient, text))
        if patient.needs_clot:
            stay.ready_at = scan_end + ROOM_AFTER_SCAN

    def _clot_room(self):
        """The room takes the patient who was ready first, as soon as it is free."""
        ready = [stay for stay in self.stays.values() if stay.ready_at is not None]
        ready.sort(key=lambda stay: (stay.ready_at, stay.patient.arrives, stay.patient.id))
        room_free = None
        for stay in ready:
            start = stay.ready_at
            if room_free is not None:
                start = max(start, room_free)
            if start > stay.patient.clot_until:
                stay.missed_clot = True
                self.events.append((stay.patient.clot_until, "clot", stay.patient,
                                    "clot removal limit passed before it could start"))
                continue
            stay.clot_at = start
            room_free = start + ROOM_TIME
            self.events.append((start, "clot", stay.patient, "clot removal starts"))

    def could_get_drug(self):
        return [stay for stay in self.stays.values() if stay.patient.drug_in_time(stay.patient.arrives)]

    def given_drug(self):
        return [stay for stay in self.stays.values() if stay.drug_at is not None]

    def missed_drug(self):
        return [stay for stay in self.could_get_drug() if stay.drug_at is None]

    def slow(self):
        return [stay for stay in self.given_drug() if stay.door_to_drug > SLOW]

    def heads(self):
        return [stay for stay in self.stays.values() if stay.patient.kind == "head"]

    def late_heads(self):
        return [stay for stay in self.heads() if stay.scan_wait > HEAD_SCAN_LIMIT]

    def average_door_to_drug(self):
        given = self.given_drug()
        if not given:
            return None
        return int(sum(stay.door_to_drug for stay in given) / len(given) + 0.5)


def save_stays(book, morning):
    """Saves the hospital times inside the route that brought each case here. Running again replaces them."""
    stays = [stay for stay in morning.stays.values() if stay.patient.case]
    old_routes = {stay.patient.case.id: dict(book.routes[stay.patient.case.id]) for stay in stays}
    for stay in stays:
        book.routes[stay.patient.case.id]["hospitalStay"] = stay.to_dict()
    try:
        book.save()
    except OSError:
        book.routes.update(old_routes)
        raise
