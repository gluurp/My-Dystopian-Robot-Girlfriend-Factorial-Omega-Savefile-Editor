# MDRG Save File Editor

A cross-platform save editor for My Dystopian Robot Girlfriend (!Ω Factorial Omega).
It has a CLI and a full-screen curses TUI.

Standard library only, so no dependencies for editing. Works on Linux, Windows
and macOS. (I ACTUALLY HAVENT TESTED IT ON WINDOWS OR MACOS... I was too lazy to spin up a VM so SOMEONE LMK IF ITS BROKEN I'll fix it super fast dw)

## Quick start

```bash
python3 mdrg-savefile-editor.py where            # platform + detected save dirs
python3 mdrg-savefile-editor.py slots            # all save slots + progression
python3 mdrg-savefile-editor.py inventory        # rich inventory view of a save
python3 mdrg-savefile-editor.py edit             # pick a save from a list
python3 mdrg-savefile-editor.py edit M7.mdrgslot # ...or name one directly
```

On Windows use `mdrg-savefile-editor.cmd scan` instead, or `py mdrg-savefile-editor.py scan`.

No save directory argument is needed — the tool auto-detects it per platform
and, when you name a specific file, always operates on **that file's own
folder**.

## Commands

### Inspection

| Command | Purpose |
|---|---|
| `scan` | Scan a Saves directory |
| `slots` | List all save slots with progression |
| `inventory` | Rich inventory listing |
| `items` | List items in one save |
| `find` | Search saves for an item by name |
| `slotsdb` | Show which items can go in each slot |
| `color` | View or set item colours (0-255 display) |
| `backups` | List or restore `.bak` backups |
| `tree` | Dump with item names and colours resolved |
| `export` | Export a normalised JSON summary |
| `where` | Platform info and Saves directories checked |

### Editing

`edit` is the interactive curses TUI editor. You can navigate, edit scalars,
add/delete items, rename, clone, and undo/redo.

Give it no file argument and it lists the saves it can find: `.mdrgslot`
and `.mdrg` files plus their `.bak` backups, so you can pick one:

```bash
python3 mdrg-savefile-editor.py edit
```

It starts with your **main save folder**. The last row scans every other save
folder it knows about, which is handy if you have a second install or a
backup copy somewhere else.

| Key | |
|---|---|
| `↑` `↓` / `j` `k` / `w` `s` | move |
| `Enter` | open the highlighted file |
| `/` | filter by filename |
| `S` | sort by date (default, newest first) or by name |
| `q` / `ESC` | cancel |

Each row shows the file's size and last-modified date so you can spot the save
you actually want. Backups are dimmed.

**Moving between saves.** The list and the editor are two levels of one
navigation model. Backing out of a file's root (`a` or `←`) returns you to the
list, so you can hop between saves without quitting and re-running the tool.
Back goes up exactly one level at a time, just like it does between sections
inside a file.

`ESC` deliberately does *not* go up a level. Arrow keys arrive as
`ESC` + `[` + letter, so a split read can deliver a bare `ESC` — if that
navigated, a stray arrow press would bounce you out of the file mid-edit.

**Backups.** Pressing `Enter` on a `.bak` asks what you want to do with it:

| Choice | What happens |
|---|---|
| **edit** | open the backup in the editor like any other save |
| **restore** | put it back as the live save and delete the `.bak` |
| **cancel** | back to the list |

A restore is not a one-way door: your current file is copied to
`.prerestore` first, so the state you had before is still on disk.

If no save directory exists at all, it prints the paths it checked instead of
failing silently, so you can see where it looked and point it somewhere with
`MDRG_SAVES_DIR`.

### Data manipulation

| Command | Purpose |
|---|---|
| `additem` / `delitem` | Add or remove items |
| `dupe` | Duplicate items with fresh GUIDs |
| `equip` | Equip / unequip an item |
| `validate` | Sanity-check a save file |

Run `python3 mdrg-savefile-editor.py --help` for the full list.

## Requirements

- Python 3.8+
- `pip install windows-curses` **Windows only**, for the edit TUI.
  Everything else works without it.

## Safety

Every write takes a `.bak` backup **before** anything is modified, in case the
tool or the user mangles something. List and restore them with:

```bash
python3 mdrg-savefile-editor.py backups M20.mdrgslot # replace M20 with whatever slot the name is btw ofc
python3 mdrg-savefile-editor.py backups M20.mdrgslot --restore
```

Save files use bare LF line endings and no BOM, and the tool preserves that
exactly — a save with no edits comes back byte-identical. `tests/test_roundtrip.py`
asserts this on every run.

Your save isn't written to until you save it. It's copied to a temp dir

## Environment variables

| Variable | Effect |
|---|---|
| `MDRG_GAME_DIR` | Force the game data dir (parent of `Saves/`) |
| `MDRG_SAVES_DIR` | Force the `Saves` dir directly |
| `MDRG_ASCII=1` | Plain-ASCII output |
| `MDRG_UNICODE=1` | Force Unicode glyphs |

## Save locations (usually idk)

| OS | Path |
|---|---|
| Windows | `%USERPROFILE%\AppData\LocalLow\IncontinentCell\My Dystopian Robot Girlfriend\Saves\` |
| macOS | `~/Library/Application Support/unity3d/IncontinentCell/My Dystopian Robot Girlfriend/Saves/` |
| Linux | `~/.config/unity3d/IncontinentCell/My Dystopian Robot Girlfriend/Saves/` |
