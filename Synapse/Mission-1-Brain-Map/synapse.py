"""Synapse stroke command center. Start with: python synapse.py"""
import os
import sys

from atlas import Atlas, AtlasError

HELP = """Commands:
  atlas load <path>   load another atlas file (nothing changes if it has errors)
  atlas pipes         list every pipe with its size and where it comes from
  atlas areas         list every area with the pipes that feed it
  atlas show <name>   show one pipe or one area in full
  atlas find <word>   list areas whose name, symptoms or description contain the word
  atlas tree          draw the whole network, starting at the heart
  atlas path <area>   list every route the blood can take from the heart to an area
  help                show this list
  exit                quit Synapse"""


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
            "load": (self.atlas_load, "<path>"),
            "pipes": (self.atlas_pipes, ""),
            "areas": (self.atlas_areas, ""),
            "show": (self.atlas_show, "<name>"),
            "find": (self.atlas_find, "<word>"),
            "tree": (self.atlas_tree, ""),
            "path": (self.atlas_path, "<area>"),
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
        elif command == "atlas":
            subcommand = words[1].lower() if len(words) > 1 else ""
            argument = words[2].strip() if len(words) > 2 else ""
            self.run_atlas(subcommand, argument)
        else:
            print(f'ERROR: Unknown command "{words[0]}". Type "help" to see all commands.')
        return True

    def run_atlas(self, subcommand, argument):
        if subcommand not in self.commands:
            problem = f'Unknown atlas command "{subcommand}"' if subcommand else "Missing atlas command"
            print(f"ERROR: {problem}. Use one of: atlas " + ", atlas ".join(self.commands))
            return
        method, usage = self.commands[subcommand]
        if usage and not argument:
            print(f"ERROR: Missing {usage.strip('<>')}. Usage: atlas {subcommand} {usage}")
        elif argument and not usage:
            print(f"ERROR: atlas {subcommand} takes nothing after it. Usage: atlas {subcommand}")
        elif self.atlas is None and subcommand != "load":
            print("ERROR: No atlas loaded. Usage: atlas load <path>")
        else:
            method(argument)

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
            pipes = count(len(self.atlas.pipes), "pipe")
            areas = count(len(self.atlas.areas), "area")
            print(f"SUCCESS: Atlas loaded from {path}: {pipes}, {areas}.")

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
        area = self.atlas.areas.get(name.lower())
        if area:
            routes = self.atlas.routes_to(area)
            print(f"{count(len(routes), 'route')} from the heart to {area.name}:")
            for route in routes:
                print("  " + " > ".join(route))
        elif name.lower() in self.atlas.pipes:
            print(f'ERROR: "{name}" is a pipe, not an area. Usage: atlas path <area>')
        else:
            print(f'ERROR: No area called "{name}".')


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    shell = Synapse()
    print('Synapse 1.0 · type "help" to see all commands')
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join("data", "atlas.txt")
    if os.getcwd() != here:
        path = os.path.join(here, path)
    shell.atlas_load(path)
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
