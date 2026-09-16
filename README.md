# MDRG Save File Editor

A cross-platform save editor for My Dystopian Robot Girlfriend (!Ω Factorial Omega).
It has a CLI and a full-screen curses TUI.

Standard library only, so no dependencies for editing. Works on Linux, Windows
and macOS. (I ACTUALLY HAVENT TESTED IT ON WINDOWS OR MACOS... I was too lazy to spin up a VM so SOMEONE LMK IF ITS BROKEN I'll fix it super fast dw)

## Quick start

```bash
python3 mdrg-savefile-editor.py where                           # platform + detected save dirs
python3 mdrg-savefile-editor.py slots                           # all save slots + progression
python3 mdrg-savefile-editor.py inventory                       # rich inventory view of a save
python3 mdrg-savefile-editor.py edit                            # pick a save from a list
python3 mdrg-savefile-editor.py edit full/path/to/slot.mdrgslot # ...or name one directly
```

On Windows use   
```bash
mdrg-savefile-editor.cmd scan
```  
instead, or  
```bash
py mdrg-savefile-editor.py scan
```

No save directory argument is forcibly necessary, rather the tool automatically detects it per platform.  
But when you name a specific file, always operates on that file's own folder.

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

| Key | Does |
|---|---|
| `↑` `↓` / `j` `k` / `w` `s` | move |
| `Enter` | open the highlighted file |
| `/` | filter by filename |
| `S` | sort by date (default, newest first) or by name |
| `q` / `ESC` | cancel |

Each row shows the file's size and last-modified date so you can spot the save
you actually want. Backups are dimmed.

**Mouse.** The wheel scrolls one row per notch

The buttons match the keys: **left click is forward** (like `d`) and **right
click is back** (like `a`). A click acts on the current selection, not on the row
you pointed at.

The one cost: with mouse reporting on, the terminal hands clicks and drags to
the tool instead of selecting text itself, so drag-to-select needs **Shift**
held. Most terminals still honour that.

**Filtering.** `/` filters whatever section you're looking at. Plain text
matches a row's name or its value, and whatever you type sticks to that
section. Come back to it from above or below and the filter is still there.
`ESC` clears it. (ESC is slightly different than a or arrow)

For items you can compare numbers as well, which plain text can't reach since
they aren't columns:

| Filter | Matches |
|---|---|
| `%q<1` | quality below 1 |
| `%q>=1.2` | quality at least 1.2 |
| `%c>2` | more than 2 owned |
| `%c=1` | exactly 1 owned |

`%q` is quality, `%c` is how many you own — the same number the row shows, so a
filter never disagrees with what you can see. `%quality` and `%count` spell it
out if you'd rather. `<` `<=` `>` `>=` `=` `==` `!=` all work.

A `%` filter replaces the text match instead of combining with it, so it's one
or the other, not both at once.

**Item rows** show the name, the slot if it's equipped, the colour swatches,
and how many you own:

```text
BikiniBra (#14002)  slot=Bra  #111B1F #4D717F  x1
```

Left to right is most important to least, because on a narrow terminal the end
of the row gets cut off. So `x1` means one — the save stores a 0 for that, the
row just does the plus one for you.

Quality isn't in the row at all. It sits at a flat 1.0 on clothes and modules,
so it was a column of identical numbers saying nothing. Use `%q` when you
actually want to find something by it.

**Moving between saves**   
The list and the editor are two levels of one
navigation model. Backing out of a file's root (`a` or `←`) returns you to the
list, so you can hop between saves without quitting and re-running the tool.  
Back goes up exactly one level at a time, just like it does between sections
inside a file.

`ESC` deliberately does *not* go up a level. Arrow keys arrive as
`ESC` + `[` + letter, so a split read can deliver a bare `ESC`. If that
navigated, a stray arrow press would bounce you out of the file mid-edit.

**Backups.** Pressing `Enter` on a `.bak` asks what you want to do with it:

| Choice | What happens |
|---|---|
| **cancel** | back to the list |
| **edit** | open the backup in the editor like any other save |
| **restore** | put it back as the live save and delete the `.bak` |

A restore will create another backup `.prerestore` so the edited file still exists.

If no save directory exists at all, it prints the paths it checked instead of
failing silently, so you can see where it looked and point it somewhere with
`MDRG_SAVES_DIR`.

So say you edit `M1.mdrgslot` and brick it.  
You'll have `M1.mdrgslot` (modified) and `M1.mdrgslot.bak`.  
Then you restore `M1.mdrgslot.bak`.  
You'll have `M1.mdrgslot` (original) and `M1.mdrgslot.prerestore`.  
-- I also havent really tested this lmk if its broken pls (~_~;).

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
exactly, so a save with no edits comes back byte-identical. `tests/test_roundtrip.py`
asserts this on every run.

Your save isn't written to until you save it, it's copied to a temp dir

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
| Windows | `%AppData%\LocalLow\IncontinentCell\My Dystopian Robot Girlfriend\Saves\` |
| macOS | `~/Library/Application Support/unity3d/IncontinentCell/My Dystopian Robot Girlfriend/Saves/` |
| Linux | `~/.config/unity3d/IncontinentCell/My Dystopian Robot Girlfriend/Saves/` |

# Extra notes to be aware of

Item count starts at 0, so if you have a single slip dress thats unique in color, itll still have count 0  
Items with unique stats (colors/wear/damage/etc) are counted separately
