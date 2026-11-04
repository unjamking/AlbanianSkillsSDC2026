"""The brain atlas: pipes, brain areas, bridges, and reading them from a file."""
import re

SIZES = ("big", "small")
FIELDS = {"PIPE": 4, "AREA": 5}
NAME = re.compile(r"[a-z0-9-]*[a-z0-9][a-z0-9-]*")
NAME_RULE = "Names use lowercase letters, digits and hyphens."


class Pipe:
    def __init__(self, name, size, parent_names, line):
        self.name = name
        self.size = size
        self.parent_names = parent_names
        self.line = line
        self.parents = []
        self.children = []
        self.areas = []
        self.bridges = []

    def __str__(self):
        return "\n".join([
            "Pipe: " + self.name,
            "  Size:          " + self.size,
            "  Comes from:    " + (", ".join(self.parent_names) or "- (this is the heart)"),
            "  Branches into: " + (", ".join(child.name for child in self.children) or "none"),
            "  Feeds areas:   " + (", ".join(area.name for area in self.areas) or "none directly"),
        ])


class Area:
    def __init__(self, name, pipe_names, symptoms, description, line):
        self.name = name
        self.pipe_names = pipe_names
        self.symptoms = symptoms
        self.description = description
        self.line = line
        self.pipes = []

    def __str__(self):
        return "\n".join([
            "Area: " + self.name,
            "  What it does:  " + self.description,
            "  Fed by:        " + ", ".join(self.pipe_names),
            "  If it stops:   " + ", ".join(self.symptoms),
        ])

    def matches(self, word):
        texts = [self.name, self.description] + self.symptoms
        return any(word.lower() in text.lower() for text in texts)


class AtlasError(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


class Atlas:
    def __init__(self, path, pipes, areas, heart, bridges):
        self.path = path
        self.pipes = pipes
        self.areas = areas
        self.heart = heart
        self.bridges = bridges

    @staticmethod
    def load(path):
        return AtlasReader(path).read()

    def get(self, name):
        return self.pipes.get(name) or self.areas.get(name)

    def find(self, word):
        return [area for area in self.areas.values() if area.matches(word)]

    def tree_lines(self, status=None):
        rows = []
        drawn = set()

        def add(item, text):
            rows.append((text, status(item) if status else ""))

        def draw(pipe, indent):
            if pipe in drawn:
                add(pipe, indent + pipe.name + " (see above)")
                return
            drawn.add(pipe)
            add(pipe, indent + pipe.name)
            for child in pipe.children:
                draw(child, indent + "  ")
            for area in pipe.areas:
                label = indent + "  [" + area.name + "]"
                if area in drawn:
                    label += " (see above)"
                add(area, label)
                drawn.add(area)

        draw(self.heart, "")
        width = max(len(text) for text, _ in rows) + 3
        return [(text.ljust(width) + mark).rstrip() for text, mark in rows]

    def routes_to(self, area):
        known = {}

        def routes(pipe):
            if pipe not in known:
                if pipe is self.heart:
                    known[pipe] = [[pipe.name]]
                else:
                    known[pipe] = [route + [pipe.name] for parent in pipe.parents for route in routes(parent)]
            return known[pipe]

        return [route + [area.name] for pipe in area.pipes for route in routes(pipe)]


class AtlasReader:
    def __init__(self, path):
        self.path = path
        self.errors = []
        self.pipes = {}
        self.areas = {}
        self.hearts = []
        self.first_line = {}
        self.broken = set()
        self.bridge_lines = []
        self.bridges = []

    def read(self):
        lines = self._read_file()
        records = [(number, text) for number, text in enumerate(lines, start=1)
                   if text and not text.startswith("#")]
        if not records:
            raise AtlasError(["The file is empty."])
        for number, text in records:
            fields = [field.strip() for field in text.split("|")]
            self._record(number, fields)
        self._link()
        heart = self._check_heart()
        self._check_loops()
        if heart:
            self._check_reachable(heart)
        if self.errors:
            self.errors.sort(key=lambda error: error[0] or float("inf"))  # errors with no line go last
            raise AtlasError([message if line is None else f"{self.path}, line {line}: {message}"
                              for line, message in self.errors])
        return Atlas(self.path, self.pipes, self.areas, heart, self.bridges)

    def _read_file(self):
        try:
            with open(self.path, encoding="utf-8-sig") as file:
                return [line.strip() for line in file]
        except FileNotFoundError:
            raise AtlasError([f"File not found: {self.path}"])
        except UnicodeDecodeError:
            raise AtlasError([f"Cannot read {self.path}: it is not a UTF-8 text file."])
        except OSError as error:
            raise AtlasError([f"Cannot read {self.path}: {error.strerror}"])

    def _error(self, line, message):
        self.errors.append((line, message))

    def _skip(self, line, name, message):
        self._error(line, message)
        self.broken.add(name)

    def _record(self, line, fields):
        kind = fields[0]
        name = fields[1] if len(fields) > 1 else ""
        if kind == "BRIDGE":
            self._bridge(line, fields)
        elif kind not in FIELDS:
            self._skip(line, name, f'unknown record type "{kind}". Expected PIPE, AREA or BRIDGE.')
        elif len(fields) != FIELDS[kind]:
            self._skip(line, name, f"{kind} needs {FIELDS[kind]} fields, found {len(fields)}.")
        elif not NAME.fullmatch(name):
            self._skip(line, name, f'invalid name "{name}". {NAME_RULE}')
        elif name in self.first_line:
            self._error(line, f'"{name}" is defined twice (first on line {self.first_line[name]}).')
        else:
            self.first_line[name] = line
            if kind == "PIPE":
                self._pipe(line, *fields[1:])
            else:
                self._area(line, *fields[1:])

    def _pipe(self, line, name, size, comes_from):
        if size not in SIZES:
            self._error(line, f'size must be {" or ".join(SIZES)}, found "{size}".')
        if comes_from == "-":
            pipe = Pipe(name, size, [], line)
            self.hearts.append(pipe)
        else:
            pipe = Pipe(name, size, self._list(line, comes_from, f'pipe "{name}"', "comes from"), line)
        self.pipes[name] = pipe

    def _area(self, line, name, fed_by, symptoms, description):
        owner = f'area "{name}"'
        pipe_names = self._list(line, fed_by, owner, "fed by")
        symptom_list = self._list(line, symptoms, owner, "symptoms", are_names=False)
        if not description:
            self._error(line, f'{owner} is missing "what it does".')
        self.areas[name] = Area(name, pipe_names, symptom_list, description, line)

    def _bridge(self, line, fields):
        if len(fields) != 3:
            self._error(line, f"BRIDGE needs 3 fields, found {len(fields)}.")
            return
        for name in fields[1:]:
            if not NAME.fullmatch(name):
                self._error(line, f'bridge has invalid name "{name}". {NAME_RULE}')
        if fields[1] == fields[2]:
            self._error(line, f'bridge connects "{fields[1]}" to itself.')
        else:
            self.bridge_lines.append((line, fields[1], fields[2]))

    def _list(self, line, text, owner, field, are_names=True):
        if not text:
            hint = ' Use "-" only for the heart.' if field == "comes from" else ""
            self._error(line, f'{owner} has nothing in "{field}".{hint}')
            return []
        result = []
        for item in [item.strip() for item in text.split(",")]:
            if not item:
                self._error(line, f'{owner} has an empty item in "{field}".')
            elif item in result:
                self._error(line, f'{owner} lists "{item}" twice in "{field}".')
            else:
                if are_names and not NAME.fullmatch(item):
                    self._error(line, f'{owner} has invalid name "{item}" in "{field}". {NAME_RULE}')
                result.append(item)
        return result

    def _link(self):
        for pipe in self.pipes.values():
            for parent in self._find_pipes(pipe.line, f'pipe "{pipe.name}" comes from', pipe.parent_names):
                pipe.parents.append(parent)
                parent.children.append(pipe)
        for area in self.areas.values():
            for pipe in self._find_pipes(area.line, f'area "{area.name}" is fed by', area.pipe_names):
                area.pipes.append(pipe)
                pipe.areas.append(area)
        for line, name_a, name_b in self.bridge_lines:
            ends = self._find_pipes(line, "bridge connects", [name_a, name_b])
            if len(ends) < 2:
                continue
            pipe_a, pipe_b = ends
            if pipe_b in pipe_a.bridges:
                self._error(line, f'the bridge between "{pipe_a.name}" and "{pipe_b.name}" is listed twice.')
            else:
                pipe_a.bridges.append(pipe_b)
                pipe_b.bridges.append(pipe_a)
                self.bridges.append((pipe_a, pipe_b))

    def _find_pipes(self, line, subject, names):
        found = []
        for name in names:
            if name in self.pipes:
                found.append(self.pipes[name])
            elif name in self.broken or not NAME.fullmatch(name):
                pass  # already reported on its own line
            elif name in self.areas:
                self._error(line, f'{subject} "{name}", which is an area, not a pipe.')
            else:
                self._error(line, f'{subject} "{name}", which does not exist.')
        return found

    def _check_heart(self):
        hearts = self.hearts
        # no heart but a broken line: the heart may be on that line, which is already reported
        if len(hearts) > 1 or (not hearts and not self.broken):
            message = f'The atlas needs exactly one pipe that comes from "-" (the heart). Found {len(hearts)}'
            if hearts:
                message += ": " + ", ".join(f'"{pipe.name}" (line {pipe.line})' for pipe in hearts)
            self._error(None, message + ".")
        return hearts[0] if hearts else None

    def _check_loops(self):
        state = {}

        def visit(pipe, path):
            if state.get(pipe) == "open":
                loop = [p.name for p in reversed(path[path.index(pipe):])]
                loop.append(loop[0])
                message = f"Loop: {loop[0]} comes from " + ", which comes from ".join(loop[1:])
                self._error(path[-1].line, message + ".")
            elif pipe not in state:
                state[pipe] = "open"
                path.append(pipe)
                for child in pipe.children:
                    visit(child, path)
                path.pop()
                state[pipe] = "done"

        for pipe in self.pipes.values():
            visit(pipe, [])

    def _check_reachable(self, heart):
        # a pipe with a missing parent already has an error, so blood counts as reaching it
        todo = [heart] + [pipe for pipe in self.pipes.values() if len(pipe.parents) < len(pipe.parent_names)]
        reached = set()
        while todo:
            pipe = todo.pop()
            if pipe not in reached:
                reached.add(pipe)
                todo.extend(pipe.children + pipe.bridges)
        for pipe in self.pipes.values():
            if pipe not in reached:
                self._error(pipe.line, f'Pipe "{pipe.name}" can never receive blood from the heart.')
