# Synapse · Mission 1: The Brain Map

Python 3.7+, standard library only, no installs needed.

```
cd Synapse/Mission-1-Brain-Map
python synapse.py
```

The program loads `data/atlas.txt` on start, then reads commands at the `synapse>` prompt:

| Command | What it does |
|---|---|
| `atlas load <path>` | Load another atlas. All or nothing: if the file has any error, the previous atlas stays in use |
| `atlas pipes` | Every pipe with its size and where it comes from |
| `atlas areas` | Every area with the pipes that feed it |
| `atlas show <name>` | One pipe (with its branches and the areas it feeds) or one area in full |
| `atlas find <word>` | Areas whose name, symptoms or description contain the word, ignoring case |
| `atlas tree` | Bonus 1: the network as an indented tree from the heart |
| `atlas path <area>` | Bonus 2: every route from the heart to an area |
| `help`, `exit` | |

Bonus 3: loading reports every error in a file at once, including loops and pipes that can never receive blood from the heart.

## Files

- `atlas.py`: the model (`Pipe`, `Area`, `Atlas`) and `AtlasReader`, which reads and checks a file
- `synapse.py`: the interactive shell
