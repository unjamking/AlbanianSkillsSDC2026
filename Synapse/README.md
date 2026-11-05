# Synapse

Python 3.7+, standard library only, no installs needed. One program for every mission:

```
python3 Synapse/main.py
```

It works from any folder. It loads `data/atlas.txt`, `data/symptoms.txt` and the saved cases in `data/cases.json` on start, then reads commands at the `synapse>` prompt. Type `help` to see them all.

## Mission 1: The Brain Map

| Command | What it does |
|---|---|
| `atlas load <path>` | Load another atlas. All or nothing: if the file has any error, the previous atlas stays in use |
| `atlas pipes` | Every pipe with its size and where it comes from |
| `atlas areas` | Every area with the pipes that feed it |
| `atlas show <name>` | One pipe (with its branches and the areas it feeds) or one area in full |
| `atlas find <word>` | Areas whose name, symptoms or description contain the word, ignoring case |
| `atlas tree` | Bonus 1: the network as an indented tree from the heart |
| `atlas path <area>` | Bonus 2: every route from the heart to an area |

Bonus 3: loading reports every error in a file at once, including loops and pipes that can never receive blood from the heart.

## Mission 2: The Lesion Engine

| Command | What it does |
|---|---|
| `lesion block <pipe>` | Block a pipe: the pipes left without blood, the areas that stop working and the expected symptoms |
| `lesion block a, b, c` | Bonus 1: several clots at once |
| `lesion risk <area>` | Every pipe that, blocked on its own, stops the area |
| `lesion tree <pipe>` | Bonus 3: the tree with BLOCKED, no blood and stops working marked |

Bonus 2: `atlas load data/atlas-bridges.txt` loads an atlas with `BRIDGE | pipe | pipe` records. Blood crosses a bridge in both directions, and `lesion block` says which pipes a bridge saved.

## Mission 3: Triage

| Command | What it does |
|---|---|
| `triage symptoms` | Every symptom code with its points and what the crew sees |
| `triage load <path>` | Load another symptom list, all or nothing |
| `triage new` | Create a case: asks for the patient's details one by one, then shows the severity, the likely blocked pipe and the time limits |
| `triage list` | Every case with its id, name, age, city, severity and likely pipe |
| `triage show <id>` | One case in full |
| `triage update <id>` | Bonus 2: add new symptoms and compute everything again; the case keeps a history |
| `triage urgent` | Bonus 3: the cases that can still be treated, shortest time left first |

Bonus 1: when no pipe matches the symptoms exactly, `triage new` shows the 3 closest pipes, and the best one counts if it matches 60% or more.

## Files

- `main.py`: the program you start; the `synapse.py` shell with the triage commands added
- `synapse.py`: the shell for the atlas and lesion commands
- `atlas.py`: the model (`Pipe`, `Area`, `Atlas`) and `AtlasReader`, which reads and checks a file
- `lesion.py`: the lesion engine (`Lesion`, `risky_pipes`); the four blood rules are written here and nowhere else
- `triage.py`: the symptom list, the cases and their time limits, and `CaseBook`, which saves them
- `data/`: the atlases (`atlas.txt`, `atlas-bridges.txt`), `symptoms.txt`, and `cases.json` once a case is saved
