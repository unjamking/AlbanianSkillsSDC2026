"""Synapse stroke command center. Start with: python synapse.py"""
import os
import sys

from atlas import Atlas, AtlasError
from lesion import Lesion, risky_pipes

HELP = """Commands:
  atlas load <path>    load another atlas file (nothing changes if it has errors)
  atlas pipes          list every pipe with its size and where it comes from
  atlas areas          list every area with the pipes that feed it
  atlas show <name>    show one pipe or one area in full
  atlas find <word>    list areas whose name, symptoms or description contain the word
  atlas tree           draw the whole network, starting at the heart
  atlas path <area>    list every route the blood can take from the heart to an area
  lesion block <pipe>  block a pipe (or several: a, b, c) and show what stops working
  lesion risk <area>   list every pipe that would stop the area if it alone were blocked
  lesion tree <pipe>   draw the network and mark what a blocked pipe affects
  help                 show this list
  exit                 quit Synapse"""


def count(number, word):
    if number == 1:
        return f"1 {word}"
    return f"{number} {word}s"


def print_table(rows):
    widths = [max(len(row[i]) for row in rows) + 3 for i in range(len(rows[0]))]
    for row in rows:
        print("".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())


class Synapse:
    def __init__(self):
        self.atlas = None
        self.commands = {
            "atlas": {
                "load": (self.atlas_load, "<path>"),
                "pipes": (self.atlas_pipes, ""),
                "areas": (self.atlas_areas, ""),
                "show": (self.atlas_show, "<name>"),
                "find": (self.atlas_find, "<word>"),
                "tree": (self.atlas_tree, ""),
                "path": (self.atlas_path, "<area>"),
            },
            "lesion": {
                "block": (self.lesion_block, "<pipe>"),
                "risk": (self.lesion_risk, "<area>"),
                "tree": (self.lesion_tree, "<pipe>"),
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
        method, usage = commands[subcommand]
        if usage and not argument:
            print(f"ERROR: Missing {usage.strip('<>')}. Usage: {command} {subcommand} {usage}")
        elif argument and not usage:
            print(f"ERROR: {command} {subcommand} takes nothing after it. Usage: {command} {subcommand}")
        elif self.atlas is None and (command, subcommand) != ("atlas", "load"):
            print("ERROR: No atlas is loaded. Use: atlas load <path>")
        else:
            method(argument)

    def find_area(self, name, usage):
        area = self.atlas.areas.get(name.lower())
        if area:
            return area
        if name.lower() in self.atlas.pipes:
            print(f'ERROR: "{name}" is a pipe, not an area. Usage: {usage}')
        else:
            print(f'ERROR: No area called "{name}".')
        return None

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

    def atlas_load(self, path):
        path = path.strip("\"'")
        try:
            self.atlas = Atlas.load(path)
        except AtlasError as error:
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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    shell = Synapse()
    print('Synapse 1.0 · type "help" to see all commands')
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # so data/... paths work wherever it is started from
    shell.atlas_load(os.path.join("data", "atlas.txt"))
    while True:
        try:
            if not shell.run_command(input("\nsynapse> ")):
                break
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except Exception as error:
            print(f"ERROR: Unexpected problem: {error}")


if __name__ == "__main__":
    main()
