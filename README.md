# MDRG Save File Editor

A cross-platform command-line save editor for **My Dystopian Robot Girlfriend**
(Factorial Omega, v0.97.x).

Standard library only — no dependencies for editing. Works on Linux, Windows
and macOS.

## Quick start

```bash
python3 mdrg-cli.py where          # show platform + detected save dirs
python3 mdrg-cli.py slots          # list every save slot with progression
python3 mdrg-cli.py inventory      # rich inventory view of a save
python3 mdrg-cli.py edit M7.mdrgslot   # interactive TUI editor
```

On Windows use `mdrg.cmd scan` instead, or `py mdrg-cli.py scan`.

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

Run `python3 mdrg-cli.py --help` for the full list.

## Requirements

- Python 3.8+
- `pip install windows-curses` — **Windows only**, for the `edit` TUI.
  Everything else works without it.

## Safety

Every write takes a `.bak` backup **before** modifying anything. Save files use
bare LF line endings with no BOM, and the tool preserves that exactly — a
round-trip with no edits is byte-identical.

`tests/test_roundtrip.py` enforces this on every run.

## Layout

```
mdrg-cli.py            the editor
item_ids.txt           gameID -> ItemEnum name   (required at runtime)
items_by_slot.json     slot -> allowed items     (optional, powers slotsdb)
mdrg.cmd               Windows launcher
docs/                  reverse-engineering notes on the save format
tests/                 round-trip and TUI test suites
```

## Tests

```bash
cd tests
python3 test_roundtrip.py     # colour round-trip + LF/BOM regression guard
python3 test_tui.py           # drives the TUI in a pty, ~43 key steps
```

Both need a save at `M20.mdrgslot` in the standard save directory.

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
