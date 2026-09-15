# MDRG Save File Editor

A cross-platform save editor for My Dystopian Robot Girlfriend (!Ω Factorial Omega).
Three frontends over one parser: command-line subcommands, a full-screen curses
TUI, and a small tkinter GUI.

Standard library only — no dependencies for editing. Works on Linux, Windows
and macOS. (hopefully)

## Quick start

```bash
python3 mdrg-savefile-editor.py where            # platform + detected save dirs
python3 mdrg-savefile-editor.py slots            # all save slots + progression
python3 mdrg-savefile-editor.py inventory        # rich inventory view of a save
python3 mdrg-savefile-editor.py edit M7.mdrgslot # interactive TUI editor
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
| `gui` | Small tkinter analyzer window |
| `where` | Platform info and Saves directories checked |

Run `python3 mdrg-savefile-editor.py --help` for the full list.

## Requirements

- Python 3.8+
- `pip install windows-curses` — **Windows only**, for the edit TUI.
  Everything else works without it.

## Safety

Every write takes a `.bak` backup **before** anything is modified, in case the
tool or the user mangles something. List and restore them with:

```bash
python3 mdrg-savefile-editor.py backups M20.mdrgslot
python3 mdrg-savefile-editor.py backups M20.mdrgslot --restore
```

Save files use bare LF line endings and no BOM, and the tool preserves that
exactly — a save with no edits comes back byte-identical. `tests/test_roundtrip.py`
asserts this on every run.

## Tests

```bash
cd tests
python3 test_roundtrip.py    # colour round-trip + line-ending/BOM guard
python3 test_tui.py          # drives the TUI in a pty, ~43 key presses
```

Both need a save file to run against — **any slot works**, M20 is not special.
They auto-detect one in your platform's standard saves directory, or you can
point at a specific slot:

```bash
python3 test_roundtrip.py /path/to/A1.mdrgslot
MDRG_TEST_SAVE=/path/to/A1.mdrgslot python3 test_tui.py
```

Your real saves are never modified: each test copies the slot to a temporary
directory and works on the copy.

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
