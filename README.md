# MDRG Save File Editor

A cross-platform command-line save editor for My Dystopian Robot Girlfriend (!Ω Factorial Omega)


Standard library only — no dependencies for editing. Works on Linux, Windows
and macOS. (hopefully)

## Quick start

```bash
python3 mdrg-savefile-editor.py where               # show platform + detected save dirs
python3 mdrg-savefile-editor.py slots               # list every save slot with progression
python3 mdrg-savefile-editor.py inventory           # rich inventory view of a save
python3 mdrg-savefile-editor.py edit M7.mdrgslot    # interactive TUI editor
```

On Windows use `mdrg-savefile-editor.cmd scan` instead, or `py mdrg-savefile-editor.py scan`.

No save directory argument is needed — the tool auto-detects it per platform
and, when you name a specific file, always operates on **that file's own
folder**.

## Commands

| Command | Purpose |
|---|---|
| `scan` | Scan a Saves directory |
| `slots` | List all save slots with progression |
| `inventory` | Rich inventory listing |
| `items` | List items in one save |
| `find` | Search saves for an item by name |
| `slotsdb` | Show which items can go in each slot |
| `color` | View or set item colours (0-255 display) |
| `additem` / `delitem` | Add or remove items |
| `dupe` | Duplicate items with fresh GUIDs |
| `equip` | Equip / unequip an item |
| `validate` | Sanity-check a save file |
| `backups` | List or restore `.bak` backups |
| `tree` | Dump with item names and colours resolved |
| `export` | Export a normalised JSON summary |
| `edit` | Interactive curses TUI editor |
| `where` | Platform info and Saves directories checked |

Run `python3 mdrg-savefile-editor.py --help` for the full list.

## Requirements

- Python 3.8+
- `pip install windows-curses` — **Windows only**, for the edit TUI.
  Everything else works without it.

## Safety

Every write takes a `.bak` backup **before** modifying anything. Just in case my script mangles anything or if a user mangles anything

`tests/test_roundtrip.py` enforces this on every run.

## Repo contents

Everything in this list is tracked and published:

```
mdrg-savefile-editor.py    the editor (CLI subcommands + curses TUI + tkinter GUI)
mdrg-savefile-editor.cmd   Windows launcher
item_ids.txt               gameID -> ItemEnum name  (required at runtime)
items_by_slot.json         slot -> allowed items    (optional; powers `slotsdb`)
docs/                      reverse-engineering notes on the save format
tests/                     round-trip and TUI test suites
README.md
.gitignore
```

Deliberately **not** published — kept locally only and git-ignored:

```
tools/    the scripts that regenerate item_ids.txt from the game assembly.
          Only needed if the game updates and adds or renames items.
          See tools/README.md (local) for the pipeline.
```

## Environment variables

| Variable | Effect |
|---|---|
| `MDRG_GAME_DIR` | Force the game data dir (parent of `Saves/`) |
| `MDRG_SAVES_DIR` | Force the `Saves` dir directly |
| `MDRG_ASCII=1` | Plain-ASCII output |
| `MDRG_UNICODE=1` | Force Unicode glyphs |

## Save locations

| OS | Path |
|---|---|
| Windows | `%USERPROFILE%\AppData\LocalLow\IncontinentCell\My Dystopian Robot Girlfriend\Saves\` |
| macOS | `~/Library/Application Support/unity3d/IncontinentCell/My Dystopian Robot Girlfriend/Saves/` |
| Linux | `~/.config/unity3d/IncontinentCell/My Dystopian Robot Girlfriend/Saves/` |
