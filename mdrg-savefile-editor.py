#!/usr/bin/env python3
"""
mdrg-savefile-editor — inspect and edit My Dystopian Robot Girlfriend save files.

Two frontends over one parser:

  CLI     subcommands (scan, stats, inventory, color, additem, ...)
  TUI     `edit`  — full-screen curses editor

Handles both formats:
  - Current (0.97.x): save.mdrg (registry) + *.mdrgslot (game state) + PlayerPrefs.pp
  - Old (0.80 beta): save<timestamp>.mdrg with inline savedata

No external dependencies — stdlib only. (`windows-curses` is needed for the
TUI on Windows; everything else works without it.)

Usage examples:
  mdrg-savefile-editor.py scan ./Saves
  mdrg-savefile-editor.py slots ./Saves
  mdrg-savefile-editor.py inventory M20.mdrgslot
  mdrg-savefile-editor.py color M20.mdrgslot --list
  mdrg-savefile-editor.py diff A1.mdrgslot A10.mdrgslot
  mdrg-savefile-editor.py edit M20.mdrgslot
  mdrg-savefile-editor.py where
"""

import argparse
import base64
import json
import os
import sys
import uuid
import zlib
import datetime
from pathlib import Path
from collections import Counter


IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


def reconfigure_stdout():
    """Ask for UTF-8 output on Windows so the nice glyphs work when possible"""
    if not IS_WINDOWS:
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


reconfigure_stdout()


def _windows_console_utf8():
    """True when the Windows console is genuinely on the UTF-8 code page.

    sys.stdout.encoding cannot answer this. reconfigure_stdout() has already
    forced it to "utf-8", so asking the stream whether it can render the
    glyphs always returns yes - even on a CP437 console, where the bytes
    would show up as mojibake and the ASCII fallback would never trigger.

    Ask the console itself instead.
    """
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleOutputCP() == 65001
    except (AttributeError, OSError):
        # No console attached (redirected to a file, or an IDE output pane).
        # Prefer plain ASCII over risking mangled output.
        return False


def _console_is_unicode():
    """True when stdout can encode the box-drawing glyphs we like to use"""
    if os.environ.get("MDRG_ASCII"):
        return False
    if os.environ.get("MDRG_UNICODE"):
        return True
    if not _windows_console_utf8():
        return False
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    if not enc:
        return False
    try:
        "─►→—✓✗±".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


_UNI = _console_is_unicode()

H_LINE = BULLET = ARROW = DASH = CHECK = CROSS = UP = DN = LEFT = RIGHT = ""


def set_ascii_mode(force_ascii=False):
    """(Re)choose the output glyph set. Called again once args are parsed"""
    global _UNI, H_LINE, BULLET, ARROW, DASH, CHECK, CROSS, UP, DN, LEFT, RIGHT
    _UNI    = False if force_ascii else _console_is_unicode()
    H_LINE  = "─" if _UNI else "-"
    BULLET  = "►" if _UNI else ">"
    ARROW   = "→" if _UNI else "->"
    DASH    = "—" if _UNI else "-"
    CHECK   = "✓" if _UNI else "OK"
    CROSS   = "✗" if _UNI else "!"
    UP      = "↑" if _UNI else "^"
    DN      = "↓" if _UNI else "v"
    LEFT    = "←" if _UNI else "<"
    RIGHT   = "→" if _UNI else ">"



set_ascii_mode()


def safe_print(*args, **kwargs):
    """print() that degrades gracefully on a non-UTF-8 console"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        cleaned = [str(a).encode(enc, "replace").decode(enc, "replace")
                   for a in args]
        print(*cleaned, **kwargs)


LABELS = {
    "<AcceptBonusReward>k__BackingField":       "Accept bonus reward",
    "<AcceptedTime>k__BackingField":             "Accepted at",
    "<CocktractPartners>k__BackingField":        "Cocktract partners",
    "<CreatedTime>k__BackingField":              "Created at",
    "<Deliveries>k__BackingField":               "Deliveries",
    "<DeliveryDuration>k__BackingField":         "Duration",
    "<DeliveryItems>k__BackingField":            "Delivery items",
    "<EarliestHour>k__BackingField":             "Stream start hour",
    "<FailureReward>k__BackingField":            "Failure reward",
    "<FinishedTime>k__BackingField":             "Finished at",
    "<Followers>k__BackingField":                "Followers",
    "<Id>k__BackingField":                       "ID",
    "<Instability>k__BackingField":              "Price instability",
    "<IsGold>k__BackingField":                   "Is gold contract",
    "<ItemsBought>k__BackingField":              "Items bought",
    "<LatestHour>k__BackingField":               "Stream end hour",
    "<MinPrice>k__BackingField":                 "Min price",
    "<MoneySpent>k__BackingField":               "Money spent",
    "<Name>k__BackingField":                     "Name",
    "<PremiumDeliveryBought>k__BackingField":    "Premium delivery",
    "<Respect>k__BackingField":                  "Respect",
    "<Seen>k__BackingField":                     "Seen",
    "<Sender>k__BackingField":                   "Sender",
    "<SentTime>k__BackingField":                 "Sent at",
    "<Status>k__BackingField":                   "Status",
    "<StockCompanies>k__BackingField":           "Stock companies",
    "<SuccessReward>k__BackingField":            "Success reward",
    "<TargetPrice>k__BackingField":              "Target price",
    "<TimeLimitForAccepting>k__BackingField":    "Time to accept",
    "<TrackingNumber>k__BackingField":           "Tracking number",
    "<Type>k__BackingField":                     "Stream type",
    "<Unlocked>k__BackingField":                 "Unlocked",
    "<ignored>k__BackingField":                  "Ignored entries",
    "AdditionalDataSlots":                       "Additional data slots",
    "AvailableContracts":                        "Available contracts",
    "BackgroundColor":                           "Background color",
    "CumOutsideData":                            "Cum outside data",
    "CurrentContracts":                          "Active contracts",
    "DI":                                        "Dynamic int",
    "D_AlreadyInsertedOnce":                     "Already inserted once",
    "D_BotLeadStatus":                           "Bot lead status",
    "D_ContinueAfterCumming":                    "Continue after cumming",
    "D_CurrentOnCum":                            "Current on cum",
    "D_Edge":                                    "Edge",
    "D_EdgedForThrusts":                         "Edged for thrusts",
    "D_HadToSlowDown":                           "Had to slow down",
    "D_HadToStop":                               "Had to stop",
    "D_HasSaidStartFrickConversation":           "Said start frick convo",
    "D_TimesAnonCame":                           "Times anon came",
    "D_TimesBeggedToStop":                       "Times begged to stop",
    "D_TimesBotCame":                            "Times bot came",
    "D_UnzippedPantsAlready":                    "Unzipped pants already",
    "EquippedItems":                             "Equipped items",
    "F":                                         "Float list",
    "I":                                         "Int list",
    "IM":                                        "Item manager",
    "IsFavourite":                               "Favourite",
    "Key":                                       "Pref key",
    "Name":                                      "Set name",
    "OwnedStocksCost":                           "Owned stocks cost",
    "OwnedStocksCount":                          "Owned stocks count",
    "PastContracts":                             "Past contracts",
    "S":                                         "String list",
    "S_CurrentCumBarValue":                      "Current cum bar",
    "S_IsCockOut":                               "Cock out",
    "S_IsFlaccid":                               "Flaccid",
    "S_IsPantsAside":                            "Pants aside",
    "S_TargetCumBarValue":                       "Target cum bar",
    "SourceItemsUniqueGuids":                    "Source GUIDs",
    "TextColor":                                 "Text color",
    "UniqueItemGuid":                            "Unique GUID",
    "UsedMods":                                  "Used mods",
    "Value":                                     "Pref value",
    "_additionalData":                           "Additional data",
    "_allEmails":                                "All emails generated",
    "_blogSaves":                                "Blog saves",
    "_colors":                                   "Colors",
    "_consoleStyle":                             "Console style",
    "_cumInMouthPercent":                        "Cum in mouth %",
    "_cumInsideAnalPercent":                     "Cum inside anal %",
    "_cumInsideStomachPercent":                  "Cum inside stomach %",
    "_cumInsideVaginaPercent":                   "Cum inside vagina %",
    "_cumInsideWombPercent":                     "Cum inside womb %",
    "_currentHorniness":                         "Current horniness",
    "_equipedSlot":                              "Equipped slot",
    "_events":                                   "Active events list",
    "_fishingTipSeed":                           "Fishing tip seed",
    "_gameId":                                   "Game definition ID",
    "_health":                                   "Health",
    "_id":                                       "Template ID",
    "_longing":                                  "Longing",
    "_lust":                                     "Lust",
    "_maxCum":                                   "Max cum capacity",
    "_mentalHealth":                             "Mental health",
    "_mentalHealthTemporary":                    "Mental health (temporary)",
    "_mood":                                     "Mood",
    "_partnerId":                                "Partner ID",
    "_remainingCum":                             "Current cum amount",
    "_requirement":                              "Requirement",
    "_rngCompensationData":                      "RNG compensation",
    "_s":                                        "Save entries",
    "_satiation":                                "Satiation",
    "_saveType":                                 "Save type",
    "_serialized":                               "Serialized data",
    "_serializedSaves":                          "Fishing saves",
    "_shopItems":                                "Shop items",
    "_stamina":                                  "Stamina",
    "_streamers":                                "Twitch streamers",
    "_sympathy":                                 "Sympathy",
    "_time":                                     "Timestamp",
    "_uniqueConversationsLeft":                  "Unique conversations left",
    "achievements":                              "Achievements",
    "arguments":                                 "Arguments",
    "autoSaves":                                 "Auto-save slots",
    "bathroomLightOn":                           "Bathroom light on",
    "botLive2DCommonState":                      "Bot Live2D state",
    "botName":                                   "Bot name",
    "botStatusAppManager":                       "Bot status console",
    "casinoTokens":                              "Casino tokens",
    "clothierOrders":                            "Clothier orders",
    "cockTwitchManager":                         "Twitch streaming manager",
    "cocktractManager":                          "Contracts / dating manager",
    "cookingMinigameManager":                    "Cooking minigame",
    "count":                                     "Count",
    "customData":                                "Custom data",
    "data":                                      "PlayerPrefs data",
    "deathGripEffectEnd":                        "Death grip effect end",
    "deliveryManager":                           "Package deliveries",
    "description":                               "Description",
    "dialogueChainData":                         "Dialogue tracking",
    "emailId":                                   "Email ID",
    "emails":                                    "Inbox emails",
    "eventManager":                              "Active events",
    "firstTimeAdded":                            "First time added",
    "fishingMinigameManager":                    "Fishing minigame",
    "flags":                                     "Flags",
    "followerMemorySerialize":                   "Follower memory",
    "followers":                                 "Twitch followers",
    "frickData":                                 "Frick (sexual) state data",
    "gameId":                                    "Game ID",
    "gameVersion":                               "Game version",
    "globalRespect":                             "Global respect",
    "ignoredGameIds":                            "Ignored game IDs",
    "ingameTime":                                "In-game time",
    "inteligence":                               "Inteligence",
    "itemLocation":                              "Item location",
    "itemManager":                               "Inventory / shop manager",
    "items":                                     "Inventory items",
    "joinUsBlogManager":                         "Join Us blog",
    "lastAnonsShowerAt":                         "Last anon shower",
    "lastBotCameAt":                             "Last bot came",
    "lastBotStartedTalkAt":                      "Last bot talk start",
    "lastCuddledAt":                             "Last cuddle",
    "lastEquipmentAt":                           "Last equipment change",
    "lastFuckedAt":                              "Last fuck",
    "lastHeadpatedAt":                           "Last headpat",
    "lastHungerInfoAt":                          "Last hunger update",
    "lastInteractAt":                            "Last interact",
    "lastMentalHealthInfoAt":                    "Last mental health update",
    "lastOutsideWithBotAt":                      "Last walk w/ bot",
    "lastSleptWithBot":                          "Last slept with bot",
    "lastStreamedAt":                            "Last streamed",
    "lastTalkedAt":                              "Last talked",
    "lastWentToChurchAt":                        "Last church",
    "lastWokeUpAt":                              "Last woke up",
    "lastWorkedAtDay":                           "Last worked at day",
    "leastBotCleanAt":                           "Last bot clean",
    "lightSwitchOn":                             "Main light on",
    "longestStream":                             "Longest stream",
    "mainNews":                                  "Main news slot",
    "mlCameFromThighjob":                        "ml came thighjob",
    "mlCameInAss":                               "ml came anal",
    "mlCameInMouth":                             "ml came oral",
    "mlCameInVagina":                            "ml came vaginal",
    "mlCameOutside":                             "ml came outside",
    "mlOfCumWasted":                             "ml cum wasted",
    "money":                                     "Money",
    "moneyEarnedFromDonations":                  "Money earned from donations",
    "name":                                      "Flag name",
    "newsDataManager":                           "News system",
    "newsId":                                    "News ID",
    "newsSeed":                                  "News seed",
    "nextAutoSaveIndex":                         "Next auto-slot index",
    "notes":                                     "Player notes",
    "nunPoints":                                 "Nun interaction points",
    "nunRepairOrders":                           "Nun repair orders",
    "onReadEventHolder":                         "On-read event",
    "opinionNews":                               "Opinion news slot",
    "playerName":                                "Player name",
    "presetColors":                              "Preset colors",
    "priceMemorySerialize":                      "Price history",
    "priestBotPoints":                           "Priest-bot interaction points",
    "quality":                                   "Quality",
    "read":                                      "Read",
    "replacement":                               "Replacement",
    "savedata":                                  "Saved data",
    "saves":                                     "Manual save slots",
    "search":                                    "Search",
    "seed":                                      "Random seed",
    "serializedEmails":                          "Serialized emails",
    "sets":                                      "Outfit sets",
    "shopManager":                               "Shop data",
    "sideNews1":                                 "Side news slot 1",
    "sideNews2":                                 "Side news slot 2",
    "sideNews3":                                 "Side news slot 3",
    "slot":                                      "Slot",
    "specialData":                               "Special data",
    "specialValues":                             "Special values",
    "stage":                                     "Story stage",
    "statusText":                                "Status text",
    "stockManager":                              "Stock market manager",
    "storyTextIds_Comp":                         "Seen story text IDs",
    "streamCount":                               "Total streams done",
    "streamedFor":                               "Total seconds streamed",
    "subs":                                      "Subscribers",
    "time":                                      "In-game time",
    "timeAdded":                                 "Time added",
    "times":                                     "Times",
    "timesCameInMouth":                          "Times came",
    "timesCameInside":                           "Times came",
    "timesCameInsideAnal":                       "Times came",
    "timesCameOutside":                          "Times came",
    "timesCameThighjob":                         "Times came",
    "timesLostChess":                            "Chess losses",
    "timesLostOldMaid":                          "Old Maid losses",
    "timesLostWordChain":                        "Word Chain losses",
    "timesRanAwayOldMaid":                       "Old Maid — ran away",
    "timesWentToChurch":                         "Church visits",
    "timesWonChess":                             "Chess wins",
    "timesWonOldMaid":                           "Old Maid wins",
    "timesWonWordChain":                         "Word Chain wins",
    "vinegaraEffectEnd":                         "Vinegar effect end",
    "visibleAt":                                 "Visible at",
    "visitedWebsites":                           "Visited websites",
    "weeklyRent":                                "Weekly rent",
}


GAME_DIR_NAME = "My Dystopian Robot Girlfriend"
GAME_COMPANY = "IncontinentCell"


def candidate_game_dirs():
    """Every plausible game data directory on this platform, best first"""
    home = Path.home()
    out = []
    if IS_WINDOWS:
        for var in ("USERPROFILE", "LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(var)
            if not base:
                continue
            b = Path(base)
            if var == "USERPROFILE":
                out.append(b / "AppData" / "LocalLow")
            out.append(b)
        out = [p / GAME_COMPANY / GAME_DIR_NAME for p in out] + \
              [p / GAME_DIR_NAME for p in out]
    elif IS_MAC:
        sup = home / "Library" / "Application Support"
        out = [
            sup / f"unity.{GAME_COMPANY}.{GAME_DIR_NAME}",
            sup / f"{GAME_COMPANY} {GAME_DIR_NAME}",
            sup / GAME_COMPANY / GAME_DIR_NAME,
            sup / "unity3d" / GAME_COMPANY / GAME_DIR_NAME,
        ]
    else:
        out = [
            home / ".config" / "unity3d" / GAME_COMPANY / GAME_DIR_NAME,
            home / ".local" / "share" / "unity3d" / GAME_COMPANY / GAME_DIR_NAME,
        ]
    # explicit override always wins
    env = os.environ.get("MDRG_GAME_DIR")
    if env:
        out.insert(0, Path(env).expanduser())
    return out


def candidate_save_dirs():
    """Saves/ directories to try, best first."""
    return [d / "Saves" for d in candidate_game_dirs()]


def resolve_saves_dir(explicit=None, near=None):
    """Work out which saves directory to operate on

    Priority:
      1. `explicit` argument from the command line
      2. `near` - the directory of the file being edited. This guarantees the
         tool always operates on the SAME folder as the file you are working
         with, even if several installs exist
      3. the first existing platform candidate
      4. the first platform candidate, so the error message is actionable
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return p.parent
        return p
    env = os.environ.get("MDRG_SAVES_DIR")
    if env:
        return Path(env).expanduser()
    if near is not None:
        near = Path(near).expanduser()
        d = near if near.is_dir() else near.parent
        if d.is_dir():
            return d
    for cand in candidate_save_dirs():
        if cand.is_dir():
            return cand
    return candidate_save_dirs()[0]


def cmd_where(args):
    """Show which save directories were checked and which one is in use"""
    print(f"platform : {'Windows' if IS_WINDOWS else 'macOS' if IS_MAC else 'Linux/other'}")
    print(f"python   : {sys.version.split()[0]}")
    print(f"unicode  : {'yes' if _UNI else 'no (ASCII fallback)'}")
    try:
        import curses  # noqa: F401
        have = "yes"
    except ImportError:
        have = "NO"
    print(f"curses   : {have}"
          + ("" if have == "yes" else
             "   -> 'pip install windows-curses' enables the interactive editor"))
    print(f"game dir : {os.environ.get('MDRG_GAME_DIR') or '(not set)'}")
    print(f"saves dir: {os.environ.get('MDRG_SAVES_DIR') or '(not set)'}")
    print("\ncandidate Saves directories:")
    for c in candidate_save_dirs():
        mark = "FOUND" if c.is_dir() else "     "
        n = ""
        if c.is_dir():
            try:
                n = f"  ({len(list(c.glob('*.mdrgslot')))} slot files)"
            except OSError:
                pass
        print(f"  [{mark}] {c}{n}")
    print(f"\nin use   : {resolve_saves_dir(args.directory)}")
    for var in ("MDRG_GAME_DIR", "MDRG_SAVES_DIR", "MDRG_ASCII", "MDRG_UNICODE"):
        if os.environ.get(var):
            print(f"  env {var}={os.environ[var]}")


SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60


def _is_likely_json(path):
    """Check if a file starts with a JSON opening bracket"""
    try:
        with open(path, "rb") as f:
            prefix = f.read(2)
        return prefix[:1] in (b"{", b"[")
    except Exception:
        return False


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)


def load_data(path):
    """Load JSON and normalize embedded savedata strings into objects"""
    data = load_json(path)
    ft = file_type(path.name)
    if ft in ("registry", "old_save"):
        entries = []
        if ft == "registry":
            entries = data.get("saves", []) + data.get("autoSaves", [])
        elif isinstance(data, dict):
            entries = data.get("saves", [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            savedata = entry.get("savedata")
            if isinstance(savedata, str):
                try:
                    entry["savedata"] = json.loads(savedata)
                except json.JSONDecodeError:
                    pass
    return data


def analysis_records(path, data=None):
    """Return gameplay records, including records embedded in old save files"""
    path = Path(path)
    data = data if data is not None else load_data(path)
    ft = file_type(path.name)
    if ft == "old_save":
        return [entry.get("savedata") for entry in data.get("saves", [])
                if isinstance(entry, dict) and isinstance(entry.get("savedata"), dict)]
    if ft in ("registry", "auto_slot", "manual_slot"):
        return [data]
    return []


def format_analysis(path, record):
    """Build a concise, human-readable summary for the analyze/report views"""
    path = Path(path)
    lines = [f"=== {path.name} ==="]
    if not record:
        return "\n".join(lines + ["No gameplay data found."])
    lines.extend([
        f"Game version: {record.get('gameVersion', '?')}",
        f"Player / bot: {record.get('playerName', '?')} / {record.get('botName', '?')}",
        f"Story stage: {record.get('stage', '?')}",
        f"In-game time: {record.get('time', '?')} ({ingame_time_str(record.get('time'))})",
        f"Money: {num(record.get('money')):,}",
        f"Subscribers / followers: {num(record.get('subs')):,} / {num(record.get('followers')):,}",
        f"Flags: {len(record.get('flags', []))}",
        f"Inventory items: {len(record.get('itemManager', {}).get('items', []))}",
        f"Emails: {len(record.get('_allEmails', []))}",
        f"Streams: {num(record.get('streamCount'))} ({num(record.get('streamedFor'))} seconds)",
        f"Health / mental health: {record.get('_health', '?')} / "
        f"{record.get('_mentalHealth', '?')}",
    ])
    return "\n".join(lines)


def save_data(path, data):
    """Save JSON, serializing savedata objects back to strings in registry files

    Order matters: the .bak is taken BEFORE anything is mutated or normalized,
    so it always contains the exact bytes that were on disk
    """
    bak = backup_file(path)
    # 2. normalise ITEM colours only (see normalize_colors for why)
    fixes = normalize_colors(data)
    # 3. re-serialise embedded savedata for registry / old formats
    ft = file_type(path.name)
    if ft in ("registry", "old_save"):
        keys = ("saves", "autoSaves") if ft == "registry" else ("saves",)
        for key in keys:
            for entry in data.get(key, []):
                if isinstance(entry, dict) and isinstance(entry.get("savedata"), (dict, list)):
                    entry["savedata"] = json.dumps(entry["savedata"], ensure_ascii=False)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if fixes:
        print(f"  (normalised {len(fixes)} item colour channel(s) to float 0..1)")
    return bak


def file_type(path):
    """Classify a file in the Saves directory"""
    p = Path(path).name
    if p == "save.mdrg":
        return "registry"
    if p.startswith("save") and p.endswith(".mdrg"):
        return "old_save"
    if p == "PlayerPrefs.pp":
        return "playerprefs"
    if p.endswith(".mdrgslot"):
        if p.startswith("A"):
            return "auto_slot"
        elif p.startswith("M"):
            return "manual_slot"
        return "slot"
    if p.startswith("!") or p.startswith("Ω"):
        return "sentinel"
    if p.startswith("save") and ".mdrg" in p:
        return "old_save"
    return "unknown"


def ft_to_str(v):
    """Convert FILETIME ticks to datetime"""
    try:
        return str(datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=int(v) // 10))
    except Exception:
        return str(v)


def ingame_time_str(seconds):
    """Convert in-game seconds to a rough time string."""
    if seconds is None:
        return "?"
    s = int(seconds)
    days = s // SECONDS_PER_DAY
    hours = (s % SECONDS_PER_DAY) // SECONDS_PER_HOUR
    mins = (s % SECONDS_PER_HOUR) // SECONDS_PER_MINUTE
    if days > 0:
        return f"Day {days+1} {hours:02d}:{mins:02d}"
    return f"{hours:02d}:{mins:02d}"


def label_for(key):
    return LABELS.get(key, key)


def is_scalar(v):
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def is_bool(v):
    return isinstance(v, bool)


def num(v, default=0):
    """Return v if not None, else default."""
    return v if v is not None else default


def cmd_scan(args):
    """Scan a Saves directory and list all files"""
    directory = resolve_saves_dir(getattr(args, "directory", None))
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        print("       run 'mdrg-savefile-editor where' to see the directories checked,",
              file=sys.stderr)
        print("       or set MDRG_GAME_DIR to your game data folder.", file=sys.stderr)
        sys.exit(1)

    files = sorted(directory.iterdir(), key=lambda p: p.name)
    print(f"{'File':<60} {'Type':<14} {'Size':>10} {'Summary'}")
    print(H_LINE * 120)
    for f in files:
        if f.is_dir():
            print(f"{f.name:<60} {'dir':<14} {'':>10} {sum(1 for _ in f.iterdir())} entries")
            continue
        ft = file_type(f.name)
        size = f.stat().st_size
        summary = ""
        if size == 0:
            summary = "(empty sentinel)"
        elif not _is_likely_json(f):
            summary = f"({ft})"
        else:
            try:
                data = load_data(f)
                if ft == "registry":
                    summary = f"keys={list(data.keys())}"
                    if "saves" in data:
                        summary += (
                            f" | saves={len(data['saves'])} "
                            f"autoSaves={len(data.get('autoSaves',[]))}"
                        )
                        if data["saves"]:
                            first_sd = data["saves"][0].get("savedata")
                            if isinstance(first_sd, dict):
                                summary += f" | savedata_keys={list(first_sd.keys())[:8]}"
                            elif isinstance(first_sd, str):
                                summary += " | savedata=(unparsed)"
                    if "visitedWebsites" in data:
                        summary += f" | websites={len(data['visitedWebsites'])}"
                    if "achievements" in data:
                        summary += f" | achievements={data['achievements'].get('values',[])}"
                elif ft in ("auto_slot", "manual_slot"):
                    summary = (
                        f"v{data.get('gameVersion','?')} | "
                        f"time={data.get('time','?')} | "
                        f"flags={len(data.get('flags',[]))} | "
                        f"items={len(data.get('itemManager',{}).get('items',[]))}"
                    )
                    if "subs" in data:
                        summary += (
                            f" | subs={data.get('subs')} "
                            f"followers={data.get('followers')} "
                            f"money={data.get('money')}"
                        )
                elif ft == "old_save":
                    summary = f"keys={list(data.keys())}"
                    if "saves" in data:
                        for s in data["saves"]:
                            summary += f" | slot{s.get('slot','?')}: {s.get('description','')}"
                elif ft == "playerprefs":
                    summary = "; ".join(f"{e['Key']}={e['Value']}" for e in data.get("data", []))
            except Exception as e:
                summary = f"parse error: {e}"
        print(f"{f.name:<60} {ft:<14} {size:>10} {summary}")


def cmd_info(args):
    """Show structure/keys of a file"""
    path = Path(args.file)
    data = load_data(path)
    ft = file_type(path.name)

    print(f"File: {path.name}  (type: {ft})")
    print(f"Size: {path.stat().st_size} bytes")
    print()

    if ft == "registry":
        print("Top-level keys:")
        for k, v in data.items():
            t = type(v).__name__
            extra = ""
            if isinstance(v, list):
                extra = f" len={len(v)}"
                if v and isinstance(v[0], dict):
                    extra += f" keys={list(v[0].keys())}"
            elif isinstance(v, dict):
                extra = f" keys={list(v.keys())[:10]}"
            elif isinstance(v, str) and len(v) > 80:
                extra = f" (str len={len(v)})"
            print(f"  {k}: {t}{extra}")
        print()
        if "saves" in data:
            print("Manual saves:")
            for s in data["saves"]:
                sd = s.get("savedata")
                sd_info = ""
                if isinstance(sd, dict):
                    sd_info = f" | savedata_keys={list(sd.keys())[:10]}"
                elif isinstance(sd, str):
                    sd_info = " | savedata=(unparsed)"
                print(f"  slot {s.get('slot')}: "
                      f"_time={ft_to_str(s.get('_time'))} "
                      f"ingame={s.get('ingameTime')} "
                      f"type={s.get('_saveType')}{sd_info}")
        if "autoSaves" in data:
            print("Auto-saves:")
            for s in data["autoSaves"]:
                sd = s.get("savedata")
                sd_info = ""
                if isinstance(sd, dict):
                    sd_info = f" | savedata_keys={list(sd.keys())[:10]}"
                elif isinstance(sd, str):
                    sd_info = " | savedata=(unparsed)"
                print(f"  slot {s.get('slot')}: "
                      f"_time={ft_to_str(s.get('_time'))} "
                      f"ingame={s.get('ingameTime')} "
                      f"type={s.get('_saveType')}{sd_info}")

    elif ft in ("auto_slot", "manual_slot"):
        print("Top-level keys (scalar values shown):")
        for k, v in data.items():
            if is_scalar(v) or is_bool(v):
                print(f"  {k}: {v}")
            elif isinstance(v, list):
                print(f"  {k}: list[{len(v)}]")
            elif isinstance(v, dict):
                print(f"  {k}: dict keys={list(v.keys())[:12]}")
        print()
        print("Managers present:")
        for k in data:
            EXCLUDED = (
                "_allEmails", "newsDataManager", "dialogueChainData",
                "shopManager", "botLive2DCommonState",
            )
            if isinstance(data[k], dict) and k not in EXCLUDED:
                print(f"  {k}")

    elif ft == "old_save":
        print("Top-level keys:")
        for k, v in data.items():
            t = type(v).__name__
            extra = ""
            if isinstance(v, list):
                extra = f" len={len(v)}"
                if v and isinstance(v[0], dict):
                    extra += f" keys={list(v[0].keys())}"
            elif isinstance(v, dict):
                extra = f" keys={list(v.keys())[:10]}"
            elif isinstance(v, str) and len(v) > 80:
                extra = f" (str len={len(v)})"
            print(f"  {k}: {t}{extra}")
        records = analysis_records(path, data)
        print(f"\nEmbedded gameplay records: {len(records)}")
        for i, record in enumerate(records, 1):
            print(f"  {i}: {format_analysis(path, record).splitlines()[1]}")

    elif ft == "playerprefs":
        print("PlayerPrefs:")
        for e in data.get("data", []):
            print(f"  {e['Key']}: {e['Value']}")


def cmd_stats(args):
    """Show key stats from a slot file"""
    path = Path(args.file)
    data = load_data(path)
    ft = file_type(path.name)
    records = analysis_records(path, data)
    if not records:
        print(f"Error: {path.name} has no analyzable gameplay data", file=sys.stderr)
        sys.exit(1)

    d = records[0]
    print(f"=== {path.name} ===")
    print(f"  Game version:    {d.get('gameVersion')}")
    print(f"  Player:          {d.get('playerName')}")
    print(f"  Bot:             {d.get('botName')}")
    print(f"  Story stage:     {d.get('stage')}")
    print(f"  In-game time:    {d.get('time')} "
          f"({ingame_time_str(d.get('time'))})")
    print(f"  Money:           {num(d.get('money')):,}")
    print(f"  Subs:            {d.get('subs')}")
    print(f"  Followers:       {d.get('followers')}")
    print(f"  Flags triggered: {len(d.get('flags',[]))}")
    print(f"  Inventory items: {len(d.get('itemManager',{}).get('items',[]))}")
    print(f"  Outfit sets:     {len(d.get('itemManager',{}).get('sets',[]))}")
    print(f"  Emails total:    {len(d.get('_allEmails',[]))}")
    print(f"  Stream count:    {d.get('streamCount')} ({d.get('streamedFor')}s)")
    print(f"  Donations earned:{num(d.get('moneyEarnedFromDonations')):,}")
    print(f"  Casino tokens:   {num(d.get('casinoTokens'))}")
    print(f"  Priest bot pts:  {num(d.get('priestBotPoints'))}")
    print(f"  Nun points:      {num(d.get('nunPoints'))}")
    print()
    print("--- Core Stats ---")
    CORE_STATS = [
        "_stamina", "_satiation", "_health", "_mentalHealth",
        "_mentalHealthTemporary", "_lust", "_longing",
        "_currentHorniness", "_sympathy", "_mood", "_maxCum",
        "_remainingCum", "inteligence", "search",
    ]
    for k in CORE_STATS:
        v = d.get(k)
        if v is not None:
            print(f"  {label_for(k):<30} {v}")
    print()
    print("--- Timestamps (in-game) ---")
    TIMESTAMP_KEYS = [
        "lastWokeUpAt", "lastFuckedAt", "lastBotCameAt",
        "lastInteractAt", "lastEquipmentAt", "lastOutsideWithBotAt",
        "lastStreamedAt", "lastTalkedAt", "lastBotStartedTalkAt",
        "lastHeadpatedAt", "lastAnonsShowerAt", "leastBotCleanAt",
        "lastHungerInfoAt", "lastMentalHealthInfoAt",
        "lastWentToChurchAt", "lastCuddledAt", "lastWorkedAtDay",
    ]
    for k in TIMESTAMP_KEYS:
        v = d.get(k)
        if v is not None and v != 0:
            print(f"  {label_for(k):<30} {v} ({ingame_time_str(v)})")
    print()
    print("--- Sexual Stats ---")
    SEXUAL_KEYS = [
        "timesCameInside", "timesCameInsideAnal", "timesCameThighjob",
        "timesCameOutside", "timesCameInMouth", "mlCameInMouth",
        "mlCameInVagina", "mlCameInAss", "mlCameFromThighjob",
        "mlCameOutside", "mlOfCumWasted",
    ]
    for k in SEXUAL_KEYS:
        v = d.get(k)
        if v is not None and v != 0:
            print(f"  {label_for(k):<30} {v}")


def cmd_analyze(args):
    """Analyze one or more save files using the shared normalized format"""
    results = []
    for name in args.files:
        path = Path(name)
        try:
            data = load_data(path)
            records = analysis_records(path, data)
            if not records:
                results.append(f"=== {path.name} ===\nNo gameplay data found.")
            else:
                results.extend(format_analysis(path, record) for record in records)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"Error: {path}: {exc}", file=sys.stderr)
            continue
    print("\n\n".join(results))


def cmd_flags(args):
    """List all flags from a slot file"""
    path = Path(args.file)
    data = load_json(path)
    flags = data.get("flags", [])
    if not flags:
        print(f"No flags in {path.name}")
        return
    print(f"=== {path.name} {DASH} {len(flags)} flags ===")
    print(f"{'#':>4} {'Name':<40} {'Added':>10} {'First':>10} {'x':>4}")
    print(H_LINE * 72)
    for i, f in enumerate(flags):
        t = ingame_time_str(f.get("timeAdded"))
        t0 = ingame_time_str(f.get("firstTimeAdded"))
        print(f"{i+1:>4} {f.get('name', '?'):<40} {t:>10} {t0:>10} {f.get('times',1):>4}")


def cmd_emails(args):
    """List emails from a slot file"""
    path = Path(args.file)
    data = load_json(path)
    emails = data.get("_allEmails", [])
    if not emails:
        print(f"No emails in {path.name}")
        return
    print(f"=== {path.name} {DASH} {len(emails)} emails ===")
    ids = Counter(e.get("emailId") for e in emails)
    print(f"\nEmail types:")
    for eid, count in ids.most_common():
        print(f"  {eid}: {count}")
    print(f"\nUnread: {sum(1 for e in emails if not e.get('read'))}")
    print(f"Read:   {sum(1 for e in emails if e.get('read'))}")
    if args.detail:
        print("\nAll emails:")
        for i, e in enumerate(emails):
            print(
                f"\n  [{i}] {e.get('emailId')} "
                f"read={e.get('read')} "
                f"visibleAt={e.get('visibleAt')}"
            )
            if e.get("specialValues"):
                print(f"      specialValues: {e['specialValues']}")
            eh = e.get("onReadEventHolder", {})
            if eh.get("data") or eh.get("eventEnum"):
                print(f"      onRead: enum={eh.get('eventEnum')} data={eh.get('data','')[:80]}")


def cmd_items(args):
    """List items from a slot file, resolving names via the ItemEnum table"""
    path = Path(args.file)
    data = load_json(path)
    im = data.get("itemManager", {})
    items = im.get("items", [])
    if not items:
        print(f"No items in {path.name}")
        return

    load_item_names()
    mods = mod_names(data)
    print(f"=== {path.name} {DASH} {len(items)} items ===")

    # group by the full (modGuid, id) key, NOT by id alone
    groups = {}
    for it in items:
        gj = it.get("_gameId") or {}
        guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
        key = (guid, gj.get("_id"))
        groups.setdefault(key, []).append(it)

    print(f"\n{'Item':<38} {'Recs':>5} {'Qty':>5} {'Colors':>7}  Slots")
    print(H_LINE * 88)
    for key in sorted(groups, key=lambda k: (bool(k[0]), str(k[1]))):
        guid, gid = key
        lst = groups[key]
        slots = [i.get("_equipedSlot", "") for i in lst if i.get("_equipedSlot", "")]
        qty = sum(i.get("_count", 0) for i in lst)
        ncol = sum(len(i.get("_colors") or []) for i in lst)
        slot_str = ", ".join(sorted(set(slots))) if slots else DASH
        print(f"{gameid_label(guid, gid, mods):<38} {len(lst):>5} {qty:>5} "
              f"{ncol:>7}  {slot_str}")

    if args.equipped:
        print("\nEquipped items:")
        for it in items:
            slot = it.get("_equipedSlot", "")
            if not slot:
                continue
            gj = it.get("_gameId") or {}
            guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
            label = gameid_label(guid, gj.get("_id"), mods)
            q = it.get("_count", 0)
            ql = it.get("_quality", 1.0)
            cols = it.get("_colors") or []
            hexes = " ".join(color_hex(c) for c in cols if is_color_dict(c))
            print(f"  {slot:<18} {label:<38} count={q} quality={ql:.3f}"
                  + (f"  {hexes}" if hexes else ""))


def cmd_diff(args):
    """Diff two slot files"""
    p1 = Path(args.file1)
    p2 = Path(args.file2)
    d1 = load_json(p1)
    d2 = load_json(p2)
    print(f"=== Diff: {p1.name} vs {p2.name} ===")
    print()
    scalar_keys = set()
    for d in (d1, d2):
        for k, v in d.items():
            if is_scalar(v) or is_bool(v):
                scalar_keys.add(k)
    added = []
    removed = []
    changed = []
    for k in sorted(scalar_keys):
        v1 = d1.get(k)
        v2 = d2.get(k)
        k1 = k in d1
        k2 = k in d2
        if k1 and not k2:
            removed.append((k, v1))
        elif k2 and not k1:
            added.append((k, v2))
        elif v1 != v2:
            changed.append((k, v1, v2))
    if added:
        print("Added fields:")
        for k, v in added:
            print(f"  + {label_for(k):<30} {v!r}")
    if removed:
        print("Removed fields:")
        for k, v in removed:
            print(f"  - {label_for(k):<30} {v!r}")
    if changed:
        print("Scalar changes:")
        for k, v1, v2 in changed:
            print(f"  {label_for(k):<30} {v1!r:>20} {ARROW} {v2!r}")
    if not added and not removed and not changed:
        print("No scalar changes.")
    print()
    # flags
    f1 = {f.get("name", "?"): f for f in d1.get("flags", [])}
    f2 = {f.get("name", "?"): f for f in d2.get("flags", [])}
    new_flags = sorted(set(f2) - set(f1))
    gone_flags = sorted(set(f1) - set(f2))
    if new_flags:
        print(f"New flags ({len(new_flags)}):")
        for n in new_flags:
            print(f"  + {n} (at {ingame_time_str(f2[n]['timeAdded'])})")
    if gone_flags:
        print(f"Removed flags ({len(gone_flags)}):")
        for n in gone_flags:
            print(f"  - {n}")
    print()
    print("Key stats comparison:")
    for k in ["money","subs","followers","moneyEarnedFromDonations","streamCount","streamedFor"]:
        v1 = d1.get(k)
        v2 = d2.get(k)
        if v1 != v2:
            v1n = v1 if v1 is not None else 0
            v2n = v2 if v2 is not None else 0
            delta = v2n - v1n
            print(
                f"  {label_for(k):<30} {v1n:>12,} {ARROW} {v2n:>12,}  "
                f"({'+' if delta>=0 else ''}{delta:,})"
            )


def cmd_story(args):
    """Analyze storyTextIds_Comp from save.mdrg"""
    path = Path(args.file)
    data = load_json(path)
    raw = data.get("storyTextIds_Comp", "")
    if not raw:
        print("No storyTextIds_Comp found (or empty)")
        return
    print(f"=== storyTextIds_Comp ===")
    print(f"  Base64 length:  {len(raw)} chars")
    try:
        dec = base64.b64decode(raw)
        print(f"  Decoded length: {len(dec)} bytes")
        print(f"  Distinct bytes: {len(set(dec))} of {len(dec)}")
        # try deflate
        try:
            out = zlib.decompress(dec, -15)
            print(f"  Raw-deflate OK: {len(out)} bytes")
            # check for repeating patterns in decoded
            tail = dec[-30:]
            print(f"  Tail bytes hex: {tail.hex()}")
            # check if tail is repeating
            for blen in [4, 6, 8, 12, 16, 21]:
                if len(dec) >= blen * 4:
                    b = dec[-blen*3:]
                    pat = b[:blen]
                    reps = 0
                    i = len(b) - blen
                    while i >= 0 and b[i:i+blen] == pat:
                        reps += 1; i -= blen
                    if reps >= 3:
                        print(f"  Repeating block at tail: {pat.hex()} (len {blen}, {reps+1} reps)")
                        print(
                            f"  {ARROW} Likely XOR-encrypted with "
                            f"{blen}-byte key, tail is padding"
                        )
        except Exception as e:
            print(f"  Raw-deflate FAIL: {e}")
    except Exception as e:
        print(f"  Base64 FAIL: {e}")
    print()
    print(f"  Interpretation: base64 {ARROW} raw-deflate {ARROW} custom binary serialization")
    print("  Tracks which story text IDs have already been shown.")


def cmd_slots(args):
    """List all save slots from a directory with progression"""
    directory = resolve_saves_dir(getattr(args, "directory", None))
    if not directory.is_dir():
        print(f"Error: {directory} is not a directory", file=sys.stderr)
        print("       run 'mdrg-savefile-editor where' to see the directories checked.",
              file=sys.stderr)
        sys.exit(1)

    auto_slots = []
    manual_slots = []
    for f in sorted(directory.iterdir()):
        if not f.is_file():
            continue
        ft = file_type(f.name)
        if ft == "auto_slot":
            try:
                auto_slots.append(load_json(f))
            except Exception as e:
                print(f"Warning: skipping {f.name}: {e}", file=sys.stderr)
        elif ft == "manual_slot":
            try:
                manual_slots.append(load_json(f))
            except Exception as e:
                print(f"Warning: skipping {f.name}: {e}", file=sys.stderr)

    if auto_slots:
        print("=== Auto-Saves (A*.mdrgslot) ===")
        print(
            f"{'File':<20} {'Time':>8} {'Stage':>5} "
            f"{'Money':>12} {'Subs':>5} {'Fol':>5} "
            f"{'Flags':>5} {'Streams':>7}"
        )
        print(H_LINE * 75)
        for d in auto_slots:
            row = (
                f"{(d.get('botName','')+'-'+str(d.get('time','')))[:19]:<20} "
                f"{d.get('time',''):>8} {d.get('stage','') or '':>5} "
                f"{num(d.get('money')):>12,} {num(d.get('subs')):>5} "
                f"{num(d.get('followers')):>5} {len(d.get('flags',[])):>5} "
                f"{d.get('streamCount','') or '':>7}"
            )
            print(row)
        print()

    if manual_slots:
        print("=== Manual Saves (M*.mdrgslot) ===")
        print(
            f"{'File':<20} {'Time':>8} {'Stage':>5} "
            f"{'Money':>12} {'Subs':>5} {'Fol':>5} "
            f"{'Flags':>5} {'Streams':>7}"
        )
        print(H_LINE * 75)
        for d in manual_slots:
            row = (
                f"{(d.get('botName','')+'-'+str(d.get('time','')))[:19]:<20} "
                f"{d.get('time',''):>8} {d.get('stage','') or '':>5} "
                f"{num(d.get('money')):>12,} {num(d.get('subs')):>5} "
                f"{num(d.get('followers')):>5} {len(d.get('flags',[])):>5} "
                f"{d.get('streamCount','') or '':>7}"
            )
            print(row)
        print()

    if manual_slots:
        print("=== Manual Save Progression ===")
        for i, d in enumerate(manual_slots):
            t = d.get("time", 0)
            print(
                f"  M{i+1}: in-game {t} ({ingame_time_str(t)}), "
                f"money={num(d.get('money')):,}, "
                f"subs={num(d.get('subs'))}, "
                f"flags={len(d.get('flags',[]))}"
            )


def cmd_dump(args):
    """Pretty-print a file (with depth control)"""
    path = Path(args.file)
    data = load_data(path)
    ft = file_type(path.name)
    depth = args.depth

    def truncate(v, d):
        if d <= 0:
            if isinstance(v, (dict, list)):
                return f"<{type(v).__name__} depth={depth}>"
            return v
        if isinstance(v, dict):
            out = {}
            for k, val in v.items():
                if isinstance(val, str) and len(val) > 200:
                    out[k] = val[:200] + f"...(+{len(val)-200})"
                else:
                    out[k] = truncate(val, d - 1)
            return out
        elif isinstance(v, list):
            if len(v) > 50 and depth <= 1:
                return f"<list len={len(v)}>"
            return [truncate(x, d - 1) for x in v]
        return v

    if ft == "registry":
        print(json.dumps(truncate(data, depth), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(truncate(data, depth), indent=2, ensure_ascii=False))


def cmd_extract(args):
    """Extract a specific field from a file"""
    path = Path(args.file)
    data = load_json(path)
    field = args.field

    def find(obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                r = find(v, key)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = find(item, key)
                if r is not None:
                    return r
        return None

    result = find(data, field)
    if result is not None:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Field '{field}' not found in {path.name}", file=sys.stderr)
        sys.exit(1)


def cmd_playerprefs(args):
    """Parse PlayerPrefs.pp"""
    path = Path(args.file)
    data = load_json(path)
    print(f"=== PlayerPrefs: {path.name} ===")
    for e in data.get("data", []):
        val = e.get("Value", "")
        if val.isdigit():
            ival = int(val)
            if e["Key"] == "millisSpentPlaying":
                hrs = ival / 3600000
                mins = ival / 60000
                print(f"  {e['Key']}: {ival:,} ms  ({hrs:.1f} hours, {mins:.0f} minutes)")
            elif e["Key"] in ("lastLoadingSucceded", "shownModsDanger", "cumFlashbangEnabled"):
                print(f"  {e['Key']}: {bool(ival)}")
            else:
                print(f"  {e['Key']}: {ival}")
        else:
            print(f"  {e['Key']}: {val}")



def backup_file(path):
    """Create a .bak backup of a file"""
    bak = path.with_suffix(path.suffix + ".bak")
    with open(path, "rb") as f_in, open(bak, "wb") as f_out:
        f_out.write(f_in.read())
    return bak


def parse_value(s):
    """Parse a string into the appropriate Python type"""
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() == "null":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if len(s) >= 2 and s[0] in '"\'' and s[-1] == s[0]:
        return s[1:-1]
    return s


def parse_path(path_str):
    """Parse 'itemManager.items[0]._count' into [(type,key), ...]"""
    parts = []
    current = ""
    i = 0
    while i < len(path_str):
        ch = path_str[i]
        if ch == ".":
            if current:
                parts.append(("dict", current))
                current = ""
        elif ch == "[":
            if current:
                parts.append(("dict", current))
                current = ""
            if "]" not in path_str[i:]:
                raise ValueError(f"Unmatched '[' in path at position {i}")
            j = path_str.index("]", i)
            idx = int(path_str[i + 1 : j])
            parts.append(("list", idx))
            i = j
        else:
            current += ch
        i += 1
    if current:
        parts.append(("dict", current))
    return parts


def set_path(data, path_str, value):
    """Set a value at the given path"""
    parts = parse_path(path_str)
    if not parts:
        raise ValueError("Empty path")
    current = data
    for pt, pv in parts[:-1]:
        current = current[pv]
    pt, pv = parts[-1]
    current[pv] = value


def format_value(v):
    """Format a value for display"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return f"{'T' if v else 'F'} ({v})"
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, str):
        if len(v) > 80:
            return f'"{v[:80]}..."'
        return f'"{v}"'
    if isinstance(v, list):
        return f"[list {len(v)}]"
    if isinstance(v, dict):
        return f"{{dict {len(v)}}}"
    return str(v)


# Item id -> name table (Il2CppGameItems.ItemEnum)
#
# `_gameId` is a PAIR (modGuid, id):
#   empty guid -> VANILLA item; _id indexes Il2CppGameItems.ItemEnum
#   mod guid   -> id is in that MOD's own namespace, NOT the ItemEnum entry
#
# Names come from item_ids.txt (id<TAB>name), generated by fix_enum.py from the
# decompiled assembly. Mod names come from sets[].UsedMods[].

# The ai was just saying shi so I figured I should put it here ig..?


ITEM_NAMES = {}
_COLOR_KEYS = ("r", "g", "b", "a")


def _data_file(name):
    """Locate a shipped data file, first hit wins

    Checked in order:
      <script dir>/<name>        the documented location
      <script dir>/data/<name>   data kept out of the repo root
      <script dir>/docs/<name>   also accepted, for convenience

    These are runtime dependencies, not documentation - without item_ids.txt
    every item renders as a bare #id and `find` by name matches nothing.
    """
    here = Path(__file__).resolve().parent
    for cand in (here / name, here / "data" / name, here / "docs" / name):
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def load_item_names():
    """Load id -> name from item_ids.txt (see _data_file for search order)"""
    if ITEM_NAMES:
        return ITEM_NAMES
    cand = _data_file("item_ids.txt")
    if cand is None:
        return ITEM_NAMES
    try:
        with open(cand, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) != 2:
                    parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                try:
                    ITEM_NAMES[int(parts[0])] = parts[1].strip()
                except ValueError:
                    continue
    except OSError:
        pass
    return ITEM_NAMES


def mod_names(data):
    """Map mod GUID -> mod name, harvested from sets[].UsedMods[]"""
    out = {}
    for st in ((data or {}).get("itemManager") or {}).get("sets") or []:
        for m in st.get("UsedMods") or []:
            g = (m.get("ModGuid") or {}).get("serializedGuid")
            n = m.get("ModName")
            if g and n:
                out[g] = n
    return out


def gameid_label(guid, gid, mods=None):
    """Human label for a (_gameId._guid, _gameId._id) pair"""
    if guid:
        who = (mods or {}).get(guid) or f"mod {guid[:8]}"
        return f"[mod] {who} #{gid}"
    name = load_item_names().get(gid)
    return f"{name} (#{gid})" if name else f"#{gid}"


def find_item_id(text):
    """Resolve an item id from a number or a fuzzy internal name"""
    names = load_item_names()
    t = text.strip()
    if t.lstrip("-").isdigit():
        return int(t)
    low = t.lower().replace(" ", "").replace("_", "")
    exact = {n.lower(): i for i, n in names.items()}
    if low in exact:
        return exact[low]
    hits = [(i, n) for i, n in sorted(names.items()) if low in n.lower()]
    if len(hits) == 1:
        return hits[0][0]
    if not hits:
        raise SystemExit(f"No item matches {text!r}")
    listing = "\n".join(f"  {i:>9}  {n}" for i, n in hits[:25])
    raise SystemExit(f"{len(hits)} items match {text!r}:\n{listing}"
                     + ("\n  ..." if len(hits) > 25 else ""))


SLOT_DB = {}


def load_slot_db():
    """slot -> [(id, name)] from items_by_slot.json (optional)

    See _data_file for the search order.
    """
    if SLOT_DB:
        return SLOT_DB
    cand = _data_file("items_by_slot.json")
    if cand is None:
        return SLOT_DB
    try:
        raw = json.loads(cand.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SLOT_DB
    for slot, lst in raw.items():
        SLOT_DB[slot] = [(e["id"], e["name"]) for e in lst]
    return SLOT_DB


# Item record construction
#
# Key order matches what the game writes, so a record created here is
# byte-comparable with a native one.


ITEM_KEY_ORDER = [
    "I", "F", "S", "_count", "_quality", "IsFavourite", "_id", "_gameId",
    "_additionalData", "AdditionalDataSlots", "UniqueItemGuid",
    "SourceItemsUniqueGuids", "_equipedSlot", "itemLocation", "_colors",
    "DI", "IM",
]


def qkeyorder(rec):
    return {k: rec[k] for k in ITEM_KEY_ORDER if k in rec} | {
        k: v for k, v in rec.items() if k not in ITEM_KEY_ORDER}


def new_item(gid, mod_guid="", count=1, quality=1.0, slot="", colors=1,
             favourite=False):
    """Build a fresh item record in the game's own schema."""
    cols = [{"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0} for _ in range(max(0, colors))]
    rec = {
        "I": [], "F": [], "S": [],
        "_count": int(count), "_quality": float(quality),
        "IsFavourite": bool(favourite), "_id": -1,
        "_gameId": {"_guid": {"serializedGuid": mod_guid}, "_id": int(gid)},
        "_additionalData": "", "AdditionalDataSlots": [],
        "UniqueItemGuid": {"serializedGuid": str(uuid.uuid4())},
        "SourceItemsUniqueGuids": [], "_equipedSlot": slot, "itemLocation": 0,
        "_colors": cols, "DI": [], "IM": [],
    }
    return qkeyorder(rec)


def item_summary(it, mods=None):
    """One-line description of an item record"""
    gj = it.get("_gameId") or {}
    guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
    label = gameid_label(guid, gj.get("_id"), mods)
    cols = [c for c in (it.get("_colors") or []) if is_color_dict(c)]
    hexes = " ".join(color_hex(c) for c in cols[:4])
    slot = (it.get("_equipedSlot") or "").strip()
    bits = [f"q={float(it.get('_quality') or 0):.3f}"]
    if it.get("_count"):
        bits.append(f"n={it['_count']}")
    if slot:
        bits.append(f"slot={slot}")
    if hexes:
        bits.append(hexes)
    return f"{label:<40} " + " ".join(bits)


def iter_all_items(paths):
    """Yield (path, index, item, data) for every item in the given files"""
    for p in paths:
        p = Path(p)
        try:
            data = load_data(p)
        except SystemExit:
            continue
        for i, it in enumerate((data.get("itemManager") or {}).get("items") or []):
            yield p, i, it, data


def find_guids(data):
    """All item GUIDs in a save, plus duplicates"""
    seen, dups = Counter(), []
    for it in (data.get("itemManager") or {}).get("items") or []:
        g = (it.get("UniqueItemGuid") or {}).get("serializedGuid")
        if not g:
            continue
        seen[g] += 1
    dups = [g for g, n in seen.items() if n > 1]
    return seen, dups


def is_color_dict(d):
    """True if d looks exactly like a colour entry {r,g,b[,a]} of numbers"""
    if not isinstance(d, dict) or not d:
        return False
    if not set(d.keys()) <= set(_COLOR_KEYS):
        return False
    if not all(k in d for k in ("r", "g", "b")):
        return False
    return all(isinstance(d[k], (int, float)) and not isinstance(d[k], bool)
               for k in d)


def to255(v):
    """float 0..1 -> int 0..255 (for display)"""
    try:
        return max(0, min(255, int(round(float(v) * 255))))
    except (TypeError, ValueError):
        return 0


def from255(n):
    """int 0..255 -> float 0..1 (for storage)"""
    return max(0.0, min(1.0, float(n) / 255.0))


def color_hex(d):
    """#RRGGBB preview for a colour dict"""
    return "#{:02X}{:02X}{:02X}".format(
        to255(d.get("r", 0)), to255(d.get("g", 0)), to255(d.get("b", 0)))


def coerce_color(text, old):
    """Interpret user input for one colour channel

    > 1   -> treated as 0..255 and divided by 255
    0..1  -> literal float (legacy/float entry)
    junk  -> unchanged
    """
    s = text.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1]
    try:
        f = float(s)
    except ValueError:
        return old
    return from255(f) if f > 1.0 else max(0.0, min(1.0, f))


def normalize_colors(data):
    """Force ITEM colour entries (`_colors[]`) to float 0..1

    *** Only dicts reached through a key named `_colors` are touched ***

    The game uses TWO different colour encodings:
        itemManager.items[]._colors[]           -> FLOATS 0..1
        botStatusAppManager._consoleStyle.*     -> INTS   0..255
    A blanket sweep over every {r,g,b,a} dict would silently divide the UI-style
    colors by 255 and destroy them. Verified against a real save

    Returns the list of channels that were changed
    """
    fixes = []

    def walk(node, path, in_colors):
        if isinstance(node, dict):
            if in_colors and is_color_dict(node):
                for k in list(node.keys()):
                    v = node[k]
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        continue
                    fv = float(v)
                    nv = from255(fv) if fv > 1.0 else max(0.0, min(1.0, fv))
                    if not isinstance(v, float) or nv != v:
                        node[k] = nv
                        fixes.append(f"{path}.{k}")
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}", in_colors or k == "_colors")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", in_colors)

    walk(data, "root", False)
    return fixes


def cmd_set(args):
    """Set a value at a given path (non-interactive)"""
    path = Path(args.file)
    data = load_data(path)
    value = parse_value(args.value)

    try:
        parts = parse_path(args.path)
        parent = data
        for _pt, pv in parts[:-1]:
            parent = parent[pv]
        leaf = parts[-1][1] if parts else None
        if parent is not None and leaf in _COLOR_KEYS and is_color_dict(parent):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                print(f"Error: colour channel '{leaf}' needs a number (0-255 or 0.0-1.0)",
                      file=sys.stderr)
                sys.exit(1)
            value = coerce_color(str(value), parent.get(leaf, 0.0))
    except (KeyError, IndexError, TypeError, ValueError):
        pass

    try:
        set_path(data, args.path, value)
    except (KeyError, IndexError, TypeError) as e:
        print(f"Error: path not found: {e}", file=sys.stderr)
        sys.exit(1)
    bak = save_data(path, data)
    print(f"Set {args.path} = {repr(value)}")
    print(f"Saved: {path}")
    print(f"Backup: {bak}")


def item_context_lines(node, mods=None):
    """Header lines describing an item record (label, slot, colour swatches)"""
    if not isinstance(node, dict) or "_gameId" not in node:
        return []
    gj = node.get("_gameId") or {}
    guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
    out = [f" Item: {gameid_label(guid, gj.get('_id'), mods)}"]
    slot = (node.get("_equipedSlot") or "").strip()
    out.append(f" Slot: {slot}" if slot else " Slot: (not equipped)")
    cols = [c for c in (node.get("_colors") or []) if is_color_dict(c)]
    if cols:
        out.append(" Colors: " + "  ".join(
            f"{color_hex(c)} a={to255(c.get('a', 1.0))}" for c in cols))
    return out


def item_label_of(v, mods=None):
    """Item name for a record dict, or "" if `v` is not an item record

    `_gameId` is the marker (the same test item_context_lines uses), so this
    also names the entries inside sets[].EquippedItems[].
    """
    if not isinstance(v, dict) or "_gameId" not in v:
        return ""
    gj = v.get("_gameId") or {}
    guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
    return gameid_label(guid, gj.get("_id"), mods)


def editor_child_value(v, mods=None):
    """Value string for a child row

    Colour dicts show a hex swatch. Item records show their item name, which
    beats the "{dict 17}" placeholder - the type column already carries the
    dict/N size, so the placeholder was redundant. Putting the name in this
    column also makes `/Manicure` filter the item list by name.
    """
    if is_color_dict(v):
        return f"{color_hex(v)}  {len(v)} ch"
    label = item_label_of(v, mods)
    if label:
        return label
    return format_value(v)


def editor_scalar_value(parent, key, v):
    """Value string for a scalar row (colour channels shown as 0..255)"""
    if key in _COLOR_KEYS and is_color_dict(parent) and isinstance(v, (int, float)):
        return f"{to255(v):>3}/255   {float(v):.6g}"
    return format_value(v)


def edit_prefill(parent, key, value):
    """Initial edit buffer: colour channels start as 0..255 integers"""
    if key in _COLOR_KEYS and is_color_dict(parent) and isinstance(value, (int, float)):
        return str(to255(value))
    return repr(value)


def _human_size(n):
    """Compact file size for the picker: 812B / 24K / 1.2M"""
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f}K"
    return f"{n / (1024 * 1024):.1f}M"


def _save_dir_candidates():
    """Every directory the editor would consider, in priority order

    Mirrors resolve_saves_dir(): MDRG_SAVES_DIR wins outright, otherwise the
    platform candidates apply. candidate_save_dirs() alone does NOT include
    the env override, so it cannot be used directly here
    """
    env = os.environ.get("MDRG_SAVES_DIR")
    if env:
        return [Path(env).expanduser()]
    return candidate_save_dirs()


def _candidate_dirs():
    """Save directories that actually exist, best first, de-duplicated"""
    seen, out = set(), []
    for d in _save_dir_candidates():
        try:
            if d.is_dir() and d not in seen:
                seen.add(d)
                out.append(d)
        except OSError:
            continue
    return out


def _shorten_path(p, width):
    """Trim a path to `width`, keeping the informative tail visible"""
    s = str(p)
    home = str(Path.home())
    if s.startswith(home):
        s = "~" + s[len(home):]
    if len(s) <= width:
        return s
    if width <= 1:
        return s[-width:] if width else ""
    return "\u2026" + s[-(width - 1):]


def _scan_dir(d):
    """[(path, size, mtime), ...] for the file kinds the editor can open"""
    rows, seen = [], set()
    for pat in ("*.mdrgslot", "*.mdrgslot.bak", "*.mdrg", "*.mdrg.bak"):
        for p in sorted(d.glob(pat)):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            try:
                st = p.stat()
            except OSError:
                continue
            rows.append((p, st.st_size, st.st_mtime))
    return rows


def _report_no_save_dir():
    """Explain which directories were checked, in the style of `where`"""
    print("Error: no save directory found.", file=sys.stderr)
    print("\nChecked:", file=sys.stderr)
    for c in _save_dir_candidates():
        try:
            mark = "FOUND" if c.is_dir() else "     "
        except OSError:
            mark = "     "
        print(f"  [{mark}] {c}", file=sys.stderr)
    print("\nPoint it at yours with MDRG_SAVES_DIR, or name a file directly:",
          file=sys.stderr)
    print("  mdrg-savefile-editor.py edit /path/to/M7.mdrgslot", file=sys.stderr)


_BAK = ".bak"


def _is_bak(p):
    return p.name.endswith(_BAK)


def _live_of(bak):
    """M20.mdrgslot.bak -> M20.mdrgslot"""
    return bak.with_name(bak.name[: -len(_BAK)])


def _restore_bak(bak):
    """Put a .bak back as the live save, then remove the .bak

    The live file is copied to .prerestore first, matching `backups --restore`,
    so a restore is never a one-way door.
    """
    live = _live_of(bak)
    if not live.name:
        return False, "cannot work out which file this backs up"
    try:
        if live.exists():
            keep = live.with_name(live.name + ".prerestore")
            keep.write_bytes(live.read_bytes())
        live.write_bytes(bak.read_bytes())
        bak.unlink()
    except OSError as exc:
        return False, f"restore failed: {exc}"
    return True, f"restored {live.name}  (previous kept as .prerestore)"


def _kaomoji(text):
    """Only return `text` if this console can actually render it"""
    if not _UNI:
        return ""
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    if not enc:
        return ""
    try:
        text.encode(enc)
    except (UnicodeEncodeError, LookupError):
        return ""
    return text


def _confirm_bak(stdscr, bak):
    """Modal for a .bak file. Returns 'edit', 'restore' or None

    cancel is listed first so it is the default selection: Enter on an
    untouched menu backs out rather than opening or overwriting anything.
    """
    import curses

    opts = [
        ("cancel",  "back to the list"),
        ("edit",    "open this backup in the editor"),
        ("restore", "put it back as the live save, then delete the .bak"),
    ]
    sel = 0
    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        box_h = len(opts) + 4
        top = max(0, (h - box_h) // 2)
        try:
            stdscr.addstr(top, 0, f" {bak.name} ".center(w - 1),
                          curses.A_BOLD | curses.A_REVERSE)
            stdscr.addstr(top + 1, 0,
                          f" this is a backup of {_live_of(bak).name}"[: w - 1],
                          curses.color_pair(1))
        except curses.error:
            pass
        for i, (name, desc) in enumerate(opts):
            line = f"  {'>' if i == sel else ' '} {name:<9} {desc}"
            attr = (curses.color_pair(6) | curses.A_BOLD) if i == sel else 0
            try:
                stdscr.addstr(top + 3 + i, 0, line[: w - 1], attr)
            except curses.error:
                pass
        try:
            stdscr.addstr(min(h - 1, top + box_h), 0,
                          " ↑↓:choose  Enter:confirm  a / ← / ESC:back "[: w - 1],
                          curses.color_pair(7))
        except curses.error:
            pass
        stdscr.refresh()

        k = stdscr.getch()
        # same back keys as everywhere else: a, left arrow, ESC
        if k in (27, ord("q"), ord("a"), curses.KEY_LEFT):
            return None
        elif k in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(opts)
        elif k in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(opts)
        elif k in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            return opts[sel][0]


# Returned by the editor when the user presses "back" at the file root.
# The file list is just the level above an open file, so backing out of the
# root means "show me the list again", not "there is nowhere to go".
_BACK_TO_LIST = object()


def _pick_save(stdscr, state=None):
    """Curses file picker. Shows the main save dir first; the last row scans
    every candidate folder. Returns a Path, or None if cancelled.

    `state` is a dict carried across visits so returning here from a file
    lands on the same row instead of resetting to the top.
    """
    import curses

    dirs = _candidate_dirs()
    if not dirs:
        return None
    primary = dirs[0]

    try:
        curses.set_escdelay(25)
    except AttributeError:
        pass
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(False)

    for cp, fg, bg in [
        (1, curses.COLOR_CYAN,    curses.COLOR_BLACK),
        (2, curses.COLOR_YELLOW,  curses.COLOR_BLACK),
        (6, curses.COLOR_BLACK,   curses.COLOR_WHITE),
        (7, curses.COLOR_BLUE,    curses.COLOR_BLACK),
    ]:
        try:
            curses.init_pair(cp, fg, bg)
        except Exception:
            pass

    state = state if state is not None else {}
    selected = state.get("selected", 0)
    scroll = state.get("scroll", 0)
    by_name = state.get("by_name", False)
    scope_all = state.get("scope_all", False)
    filter_text = ""
    filter_prompt = False
    filter_buffer = ""
    status = ""

    def files():
        src = dirs if scope_all else [primary]
        rows, seen = [], set()
        for d in src:
            for r in _scan_dir(d):
                if r[0] in seen:
                    continue
                seen.add(r[0])
                rows.append(r)
        rows.sort(key=(lambda r: r[0].name.lower()) if by_name
                  else (lambda r: -r[2]))
        if filter_text:
            f = filter_text.lower()
            rows = [r for r in rows if f in r[0].name.lower()]
        return rows

    def action_label():
        if scope_all:
            return "←  Back to just the main save folder"
        extra = len(dirs) - 1
        if extra <= 0:
            return "⌕  Scan again"
        return f"⌕  Scan all save folders  ({extra} more)"

    while True:
        rows = files()
        total = len(rows) + 1                     # +1 for the action row
        if selected > total - 1:
            selected = total - 1
        if selected < 0:
            selected = 0
        if selected < scroll:
            scroll = selected

        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 7 or w < 34:
            try:
                stdscr.addstr(0, 0, "Terminal too small")
                stdscr.refresh()
            except curses.error:
                pass
            stdscr.getch()
            continue

        # --- header -------------------------------------------------
        try:
            stdscr.addstr(0, 0, " open a save ".center(w - 1),
                          curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass
        where = "every save folder" if scope_all else _shorten_path(primary, w - 26)
        loc = f" {where}"
        if by_name:
            loc += "   [name]"
        if filter_text:
            loc += f"   /{filter_text}"
        try:
            stdscr.addstr(1, 0, loc[: w - 1], curses.color_pair(1))
        except curses.error:
            pass
        if status:
            try:
                stdscr.addstr(2, 0, f" {status}"[: w - 1], curses.color_pair(2))
            except curses.error:
                pass

        list_top = 3
        visible = max(1, h - list_top - 2)
        if selected >= scroll + visible:
            scroll = selected - visible + 1

        # --- rows ----------------------------------------------------
        if not rows:
            if scope_all:
                msg = "couldn't find any save files anywhere"
                ka = _kaomoji("｡:ﾟ(｡ﹷ ‸ ﹷ ✿)")
                if ka:
                    msg += f"   {ka}"
            else:
                msg = "nothing in the main save folder — try the scan below"
            try:
                stdscr.addstr(list_top, 0, f"  {msg}"[: w - 1],
                              curses.color_pair(2))
            except curses.error:
                pass

        end = min(scroll + visible, len(rows))
        for i in range(scroll, end):
            p, size, mtime = rows[i]
            when = datetime.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
            folder = "" if not scope_all else f"{p.parent.name}/"
            name = f"{folder}{p.name}"
            line = f" {name:<40} {_human_size(size):>7}  {when}"
            if i == selected:
                attr = curses.color_pair(6) | curses.A_BOLD
            elif _is_bak(p):
                attr = curses.A_DIM
            else:
                attr = curses.color_pair(2)
            try:
                stdscr.addstr(list_top + i - scroll, 0, line[: w - 1], attr)
            except curses.error:
                pass

        # --- action row (always last) --------------------------------
        act_i = len(rows)
        if scroll <= act_i < scroll + visible:
            attr = (curses.color_pair(6) | curses.A_BOLD) if selected == act_i \
                else curses.color_pair(1)
            try:
                stdscr.addstr(list_top + act_i - scroll, 0,
                              f" {action_label()}"[: w - 1], attr)
            except curses.error:
                pass

        if total > visible:
            sb = f" {selected + 1}/{total} "
            try:
                stdscr.addstr(list_top, w - len(sb) - 1, sb, curses.color_pair(7))
            except curses.error:
                pass

        # --- prompt / footer ------------------------------------------
        if filter_prompt:
            try:
                stdscr.addstr(h - 2, 0, f" filter: {filter_buffer}_"[: w - 1],
                              curses.color_pair(2) | curses.A_BOLD)
                stdscr.addstr(h - 1, 0, " Enter:apply  ESC:clear"[: w - 1],
                              curses.color_pair(7))
            except curses.error:
                pass
        else:
            try:
                stdscr.addstr(h - 1, 0,
                              " ↑↓:move  Enter:open  /:filter  S:sort  q:quit "[: w - 1],
                              curses.color_pair(7))
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()
        if key == curses.KEY_RESIZE:
            continue

        # --- filter prompt swallows keys ------------------------------
        if filter_prompt:
            if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                filter_text = filter_buffer
                filter_prompt = False
                selected = scroll = 0
            elif key == 27:
                filter_buffer = ""
                filter_prompt = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                filter_buffer = filter_buffer[:-1]
            elif 32 <= key < 127:
                filter_buffer += chr(key)
            continue

        if key == ord("/"):
            filter_prompt = True
            filter_buffer = filter_text
        elif key in (ord("q"), 27):
            return None
        elif key in (curses.KEY_UP, ord("k"), ord("w")) and selected > 0:
            selected -= 1
        elif (key in (curses.KEY_DOWN, ord("j"), ord("s"))
              and selected < total - 1):
            selected += 1
        elif key in (curses.KEY_PPAGE,):
            selected = max(0, selected - visible)
        elif key in (curses.KEY_NPAGE,):
            selected = min(total - 1, selected + visible)
        elif key == curses.KEY_HOME or key == ord("g"):
            selected = 0
        elif key == curses.KEY_END or key == ord("G"):
            selected = total - 1
        elif key == ord("S"):
            by_name = not by_name
            selected = scroll = 0
        elif key == 9 and len(dirs) > 1:            # TAB jumps to the scan row
            selected = len(rows)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r"), curses.KEY_RIGHT):
            if selected == act_i:
                # the action row
                scope_all = not scope_all
                selected = scroll = 0
                status = "scanned every folder" if scope_all else "main folder"
                continue
            if not rows:
                continue
            chosen = rows[selected][0]
            if _is_bak(chosen):
                action = _confirm_bak(stdscr, chosen)
                if action == "edit":
                    state.update(selected=selected, scroll=scroll,
                                 by_name=by_name, scope_all=scope_all)
                    return chosen
                if action == "restore":
                    ok, msg = _restore_bak(chosen)
                    status = msg
                continue
            state.update(selected=selected, scroll=scroll,
                         by_name=by_name, scope_all=scope_all)
            return chosen


def cmd_edit(args):
    """Interactive TUI editor (curses). With no file, opens the file picker

    The list and the editor are two levels of one navigation model: backing
    out of a file's root returns to the list, so you can move between saves
    without quitting. The two curses.wrapper calls stay separate so that a
    file which fails to load reports an ordinary error rather than leaving a
    half-initialised screen behind.
    """
    try:
        import curses
    except ImportError:
        print("Error: the interactive editor needs the 'curses' module.", file=sys.stderr)
        if IS_WINDOWS:
            print("  Windows:  pip install windows-curses", file=sys.stderr)
            print("  (everything except 'edit' works without it)", file=sys.stderr)
        else:
            print("  Linux:   sudo apt install python3-curses  (usually preinstalled)",
                  file=sys.stderr)
        sys.exit(1)

    chosen = Path(args.file) if args.file else None
    picker_state = {}          # survives a round trip through the editor

    while True:
        if chosen is None:
            # Level 0: choose a file.
            if not _candidate_dirs():
                _report_no_save_dir()
                sys.exit(1)
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                print("Error: the file picker needs an interactive terminal.",
                      file=sys.stderr)
                print("       name a file instead:  edit /path/to/M7.mdrgslot",
                      file=sys.stderr)
                sys.exit(1)
            chosen = curses.wrapper(_pick_save, picker_state)
            if chosen is None:
                sys.exit(0)        # cancelled at the list

        # Level 1 and deeper: the file itself.
        data = load_data(chosen)
        edit_data = data
        if file_type(chosen.name) == "old_save":
            records = analysis_records(chosen, data)
            if not records:
                print(f"Error: {chosen.name} has no embedded gameplay data",
                      file=sys.stderr)
                sys.exit(1)
            if len(records) > 1:
                print(f"Error: {chosen.name} contains multiple saves; edit is "
                      f"not ambiguous-safe", file=sys.stderr)
                sys.exit(1)
            edit_data = records[0]

        try:
            result = curses.wrapper(_interactive_edit, edit_data, chosen, data)
        except KeyboardInterrupt:
            return

        if result is _BACK_TO_LIST:
            chosen = None          # up one level: back to the list
            continue
        return


def _interactive_edit(stdscr, data, path, save_root=None):
    """Curses-based interactive editor"""
    import curses
    try:
        curses.set_escdelay(25)
    except AttributeError:
        pass
    if save_root is None:
        save_root = data
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(False)

    # Color pairs
    for cp, fg, bg in [
        (1, curses.COLOR_CYAN,      curses.COLOR_BLACK),
        (2, curses.COLOR_YELLOW,    curses.COLOR_BLACK),
        (3, curses.COLOR_GREEN,     curses.COLOR_BLACK),
        (4, curses.COLOR_RED,       curses.COLOR_BLACK),
        (5, curses.COLOR_WHITE,     curses.COLOR_BLUE),
        (6, curses.COLOR_BLACK,     curses.COLOR_WHITE),
        (7, curses.COLOR_BLUE,      curses.COLOR_BLACK),
        (8, curses.COLOR_MAGENTA,   curses.COLOR_BLACK),
    ]:
        try:
            curses.init_pair(cp, fg, bg)
        except Exception:
            pass

    stack = []
    current = data
    current_path_str = "root"
    selected = 0
    scroll = 0
    edit_mode = False
    edit_buffer = ""
    edit_key = ""
    edit_parent = None
    edit_dirty = False
    saved_flag = False
    mods = mod_names(data)
    load_item_names()
    load_slot_db()

    filter_text = ""
    filter_prompt = False
    filter_buffer = ""
    help_mode = False
    jump_prompt = False
    jump_buffer = ""
    rename_prompt = False
    rename_buffer = ""
    rename_target = None
    undo_stack = []
    redo_stack = []
    yank_buf = [None]          # [value] or [None] when empty
    status_msg = ""
    last_was_nudge = False
    quit_confirm = False

    def snapshot():
        """Push the current state for undo."""
        undo_stack.append(json.dumps(data, ensure_ascii=False))
        if len(undo_stack) > 100:
            undo_stack.pop(0)
        redo_stack.clear()

    def restore(snap):
        new = json.loads(snap)
        if isinstance(data, dict):
            data.clear()
            data.update(new)

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 5:
            stdscr.addstr(0, 0, "Terminal too small (need 5+ rows)")
            stdscr.refresh()
            stdscr.getch()
            continue

        children = []
        if isinstance(current, dict):
            for k, v in current.items():
                if isinstance(v, (dict, list)):
                    type_str = f"dict/{len(v)}" if isinstance(v, dict) else f"list/{len(v)}"
                    children.append((k, BULLET, type_str,
                                     editor_child_value(v, mods), "container"))
                else:
                    children.append((
                        k, " ", "scalar",
                        editor_scalar_value(current, k, v), "scalar"
                    ))
        elif isinstance(current, list):
            for i, v in enumerate(current):
                if isinstance(v, (dict, list)):
                    type_str = f"dict/{len(v)}" if isinstance(v, dict) else f"list/{len(v)}"
                    children.append((
                        f"[{i}]", BULLET, type_str,
                        editor_child_value(v, mods), "container"
                    ))
                else:
                    children.append((f"[{i}]", " ", "scalar", format_value(v), "scalar"))

        total_children = len(children)
        if filter_text:
            ft = filter_text.lower()
            children = [c for c in children
                        if ft in str(c[0]).lower() or ft in str(c[3]).lower()]
            if selected >= len(children):
                selected = max(0, len(children) - 1)
                scroll = 0

        if filter_text:
            pos = f" [{selected + 1}/{len(children)}/{total_children}]" if children else f" [0/{total_children}]"
        else:
            pos = f" [{selected + 1}/{total_children}]" if children else " [0/0]"
        filt = f"  /{filter_text}" if filter_text else ""
        try:
            hdr = f" mdrg-savefile-editor edit {DASH} {path.name}{pos}{filt} "
            stdscr.addstr(0, 0, hdr[: w - 1].ljust(w - 1), curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass

        try:
            stdscr.addstr(1, 0, f" Path: {current_path_str}"[: w - 1], curses.color_pair(1))
        except curses.error:
            pass

        HELP_SECTIONS = [
            {
                "title": "Navigation",
                "entries": [
                    (f"{UP}{DN}  W S", "move selection"),
                    (f"{LEFT}  A  ESC", "go up one level / clear filter"),
                    (f"{RIGHT}  D  Enter", "descend / edit scalar"),
                    ("g / G", "jump to first / last entry"),
                    ("Ctrl+U / Ctrl+D", "page up / page down"),
                    ("Home / End", "first / last"),
                    ("/", "filter entries (ESC clears)"),
                    (":", "jump to a path, e.g. itemManager.items[0]._count"),
                ],
            },
            {
                "title": "Editing",
                "entries": [
                    ("e", "edit the selected scalar"),
                    ("Tab", "cycle value type (bool/int/float/str)"),
                    ("+ -  [ ]", "adjust (colour mode: +/-1 / +/-8)"),
                    ("H", "colour: enter #RRGGBB"),
                    ("n", "add a key (dict) or append a value (list)"),
                    ("r", "rename the selected key"),
                    ("x", "delete the selected key / list entry"),
                    ("c", "clone entry (fresh guid for items)"),
                    ("y / p", "yank value / paste into the selection"),
                    ("u / Ctrl+R", "undo / redo"),
                ],
            },
            {
                "title": "Files",
                "entries": [
                    ("o  Ctrl+S", "save (makes a .bak first)"),
                    ("q", "quit (asks again if there are unsaved changes)"),
                    ("?", "close this help"),
                ],
            },
            {
                "title": "Note",
                "entries": [
                    ("ESC", "never quits — arrow keys send ESC and a split read;"),
                    ("",     "otherwise the editor would close mid-navigation."),
                ],
            },
        ]

        if help_mode:
            y = 2
            for section in HELP_SECTIONS:
                if y < h - 1 and section["title"]:
                    try:
                        stdscr.addstr(y, 1, section["title"], curses.color_pair(2) | curses.A_BOLD)
                    except curses.error:
                        pass
                    y += 1

                for key, desc in section["entries"]:
                    if y >= h - 1:
                        break
                    if not key and not desc:
                        continue
                    try:
                        if desc:
                            stdscr.addstr(y, 1, f" {key:<18}", curses.color_pair(3) | curses.A_BOLD)
                            stdscr.addstr(y, 20, desc[: w - 22])
                        else:
                            stdscr.addstr(y, 1, key, curses.color_pair(2) | curses.A_BOLD)
                    except curses.error:
                        pass
                    y += 1

                if y < h - 1:
                    y += 1

                if y >= h - 1:
                    break

            stdscr.refresh()
            stdscr.getch()
            help_mode = False
            continue

        if isinstance(current, dict):
            type_line = f" Type: dict ({len(current)} keys)"
        elif isinstance(current, list):
            type_line = f" Type: list ({len(current)} items)"
        else:
            type_line = f" Type: {type(current).__name__}"
        if status_msg:
            type_line += f"    {status_msg}"
        try:
            stdscr.addstr(2, 0, type_line[: w - 1],
                          curses.color_pair(3) if status_msg else 0)
        except curses.error:
            pass

        row = 3
        for extra in item_context_lines(current, mods):
            try:
                stdscr.addstr(row, 0, extra[: w - 1], curses.color_pair(2))
            except curses.error:
                pass
            row += 1

        start_row = row

        if filter_prompt or jump_prompt or rename_prompt:
            if filter_prompt:
                label, buf = " filter ", filter_buffer
            elif jump_prompt:
                label, buf = " jump to ", jump_buffer
            else:
                label, buf = " rename to ", rename_buffer
            try:
                stdscr.addstr(row, 0, f"{label}{buf}_"[: w - 1],
                              curses.color_pair(3) | curses.A_BOLD)
                stdscr.addstr(row + 1, 0, " Enter:confirm  ESC:cancel"[: w - 1],
                              curses.color_pair(7))
            except curses.error:
                pass
            start_row = row + 3

        if edit_mode:
            try:
                stdscr.addstr(
                    row, 0,
                    f" Edit {edit_key}: {edit_buffer}_"[: w - 1],
                    curses.color_pair(3) | curses.A_BOLD
                )
            except curses.error:
                pass
            if edit_parent is not None:
                try:
                    current_val = editor_scalar_value(
                        edit_parent, edit_key, edit_parent[edit_key]
                    )
                    stdscr.addstr(
                        row + 1, 0,
                        f" Current: {current_val}"[: w - 1],
                        curses.color_pair(2),
                    )
                except Exception:
                    pass
            try:
                hint = (" Enter:confirm  ESC:cancel  "
                        "channel input accepts 0-255 or 0.0-1.0"
                        if (edit_key in _COLOR_KEYS and is_color_dict(edit_parent or {}))
                        else " Enter:confirm  ESC:cancel  Tab:toggle type")
                stdscr.addstr(row + 2, 0, hint[: w - 1], curses.color_pair(7))
            except curses.error:
                pass
            start_row = row + 4

        visible = max(1, h - start_row - 2)
        end = min(scroll + visible, len(children))
        for i in range(scroll, end):
            if i < 0 or i >= len(children):
                continue
            name, icon, type_str, val_str, kind = children[i]
            line = f" {icon} {name:<28} {type_str:>12}  {val_str}"
            line = line[: w - 1]
            attr = 0
            if i == selected:
                attr |= curses.color_pair(6) | curses.A_BOLD
            elif kind == "scalar":
                attr |= curses.color_pair(3)
            else:
                attr |= curses.color_pair(8)
            try:
                stdscr.addstr(start_row + i - scroll, 0, line, attr)
            except curses.error:
                pass

        footer = (
            " ↑↓←→:nav  /:filter  ::jump  e:edit  r:rename  x:del  "
            "c:clone  y/p  n:add  u:undo  ?:help  o:save  q:quit "
        )
        if is_color_dict(current):
            footer = (" colour: ↑↓:channel  +/-:±1  [ ]:±8  H:hex  e/→:type 0-255  "
                      "u:undo  ?:help  o:save  q:quit ")
        try:
            stdscr.addstr(h - 1, 0, footer[: w - 1], curses.color_pair(7))
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()
        if key == curses.KEY_RESIZE:
            continue
        if key not in (ord("+"), ord("="), ord("-"), ord("["), ord("]")):
            last_was_nudge = False

        if edit_mode:
            if key == 27:  # ESC
                edit_mode = False
                edit_buffer = ""
                edit_key = ""
                edit_parent = None
                edit_dirty = False
            elif key in (10, 13):  # Enter
                if edit_parent is not None and edit_key is not None:
                    is_chan = (edit_key in _COLOR_KEYS and is_color_dict(edit_parent))
                    if is_chan and not edit_dirty:
                        new_val = edit_parent[edit_key]
                    elif is_chan:
                        new_val = coerce_color(edit_buffer, edit_parent[edit_key])
                    else:
                        new_val = parse_value(edit_buffer)
                    try:
                        snapshot()
                        edit_parent[edit_key] = new_val
                        saved_flag = True
                    except Exception as e:
                        try:
                            stdscr.addstr(h - 2, 0, f" Error: {e}"[: w - 1], curses.color_pair(4))
                            stdscr.refresh()
                            curses.napms(1000)
                        except Exception as e2:
                            print(f"Error: {e2}", file=sys.stderr)
                edit_mode = False
                edit_buffer = ""
                edit_key = ""
                edit_parent = None
                edit_dirty = False
            elif key in (9,):  # Tab for toggle type / colour representation
                if edit_parent is not None and edit_key is not None:
                    cur = edit_parent.get(edit_key) if isinstance(edit_parent, dict) else None
                    is_colour_channel = (
                        edit_key in _COLOR_KEYS
                        and is_color_dict(edit_parent)
                        and isinstance(cur, (int, float))
                    )
                    if is_colour_channel:
                        # flip between the 0..255 view and the stored 0..1 float
                        edit_buffer = (f"{float(cur):.6g}" if edit_buffer.strip() == str(to255(cur))
                                       else str(to255(cur)))
                    elif isinstance(cur, bool):
                        edit_buffer = "false" if cur else "true"
                    elif isinstance(cur, int):
                        edit_buffer = str(float(cur))
                    elif isinstance(cur, float):
                        edit_buffer = str(int(cur))
                    elif isinstance(cur, str):
                        edit_buffer = repr(cur)
            elif key in ( curses.KEY_BACKSPACE, 127, 8):
                edit_buffer = edit_buffer[:-1]
                edit_dirty = True
            elif key >= 32 and key < 127:
                edit_buffer += chr(key)
                edit_dirty = True
            continue

        # prompt modes (filter / jump / rename)
        if filter_prompt or jump_prompt or rename_prompt:
            if key == 27:
                filter_prompt = jump_prompt = rename_prompt = False
                filter_buffer = jump_buffer = rename_buffer = ""
            elif key in (10, 13):
                if filter_prompt:
                    filter_text = filter_buffer
                    selected = scroll = 0
                    status_msg = f"filter: {filter_text or '(none)'}"
                elif jump_prompt:
                    target = jump_buffer.strip()
                    node, ok = data, True
                    try:
                        for part in parse_path(target):
                            node = node[part[1]]
                    except Exception:
                        ok = False
                    if ok:
                        # rebuild the breadcrumb for the current path
                        stack.clear()
                        current, current_path_str = node, target
                        selected = scroll = 0
                        status_msg = f"jumped to {target}"
                    else:
                        status_msg = f"no such path: {target}"
                else:
                    new_key = rename_buffer
                    if rename_target and new_key and new_key != rename_target[1]:
                        holder, old = rename_target
                        snapshot()
                        if isinstance(holder, dict):
                            rebuilt = {}
                            for k, v in holder.items():
                                rebuilt[new_key if k == old else k] = v
                            holder.clear()
                            holder.update(rebuilt)
                        else:
                            holder.append(new_key)
                            holder.pop(holder.index(old))
                        saved_flag = True
                        status_msg = f"renamed {old} -> {new_key}"
                filter_prompt = jump_prompt = rename_prompt = False
                filter_buffer = jump_buffer = rename_buffer = ""
                rename_target = None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if filter_prompt:
                    filter_buffer = filter_buffer[:-1]
                elif jump_prompt:
                    jump_buffer = jump_buffer[:-1]
                else:
                    rename_buffer = rename_buffer[:-1]
            elif key >= 32 and key < 127:
                if filter_prompt:
                    filter_buffer += chr(key)
                elif jump_prompt:
                    jump_buffer += chr(key)
                else:
                    rename_buffer += chr(key)
            continue

        if (key == curses.KEY_UP or key in (ord("w"), ord("W"))) and selected > 0:
            selected -= 1
            if selected < scroll:
                scroll = selected
        elif (
            key == curses.KEY_DOWN or key in (ord("s"), ord("S"))
        ) and selected < len(children) - 1:
            selected += 1
            if selected >= scroll + visible:
                scroll = selected - visible + 1
        elif key in (curses.KEY_HOME,) or key == ord("g"):
            selected = 0
            scroll = 0
        elif key in (curses.KEY_END,) or key == ord("G"):
            selected = max(0, len(children) - 1)
            scroll = max(0, selected - visible + 1)
        elif key == 21:  # Ctrl+U
            selected = max(0, selected - visible)
            scroll = max(0, scroll - visible)
        elif key == 4:   # Ctrl+D
            selected = min(max(0, len(children) - 1), selected + visible)
            scroll = max(0, min(max(0, len(children) - visible), scroll + visible))
        elif key == ord("/"):
            filter_prompt = True
            filter_buffer = filter_text
            status_msg = ""
        elif key == ord(":"):
            jump_prompt = True
            jump_buffer = ""
            status_msg = ""
        elif key == ord("?"):
            help_mode = True
        elif key == ord("u"):  # undo
            if undo_stack:
                redo_stack.append(json.dumps(data, ensure_ascii=False))
                restore(undo_stack.pop())
                stack.clear()
                current = data
                current_path_str = "root"
                selected = scroll = 0
                saved_flag = True
                status_msg = f"undo ({len(undo_stack)} left)"
            else:
                status_msg = "nothing to undo"
        elif key == 18:  # Ctrl+R — redo
            if redo_stack:
                undo_stack.append(json.dumps(data, ensure_ascii=False))
                restore(redo_stack.pop())
                stack.clear()
                current = data
                current_path_str = "root"
                selected = scroll = 0
                saved_flag = True
                status_msg = "redo"
            else:
                status_msg = "nothing to redo"
        elif key == ord("y"):  # yank
            if selected < len(children):
                name = children[selected][0]
                try:
                    val = current[name] if isinstance(current, dict) else current[int(name[1:-1])]
                    yank_buf[0] = json.loads(json.dumps(val))
                    status_msg = f"yanked {name}"
                except Exception as e:
                    status_msg = f"yank failed: {e}"
        elif key == ord("p"):  # paste
            if yank_buf[0] is None:
                status_msg = "clipboard empty"
            elif selected < len(children):
                name = children[selected][0]
                try:
                    snapshot()
                    if isinstance(current, dict):
                        current[name] = json.loads(json.dumps(yank_buf[0]))
                    else:
                        current[int(name[1:-1])] = json.loads(json.dumps(yank_buf[0]))
                    saved_flag = True
                    status_msg = f"pasted into {name}"
                except Exception as e:
                    status_msg = f"paste failed: {e}"
        elif key == ord("x"):  # delete
            if selected < len(children):
                name = children[selected][0]
                try:
                    snapshot()
                    if isinstance(current, dict):
                        del current[name]
                    else:
                        current.pop(int(name[1:-1]))
                    saved_flag = True
                    selected = max(0, selected - 1)
                    status_msg = f"deleted {name}"
                except Exception as e:
                    status_msg = f"delete failed: {e}"
        elif key == ord("r"):  # rename
            if selected < len(children) and isinstance(current, dict):
                rename_prompt = True
                rename_buffer = children[selected][0]
                rename_target = (current, children[selected][0])
                status_msg = ""
        elif key == ord("c"):  # clone
            if selected < len(children):
                name = children[selected][0]
                try:
                    snapshot()
                    if isinstance(current, list):
                        idx = int(name[1:-1])
                        clone = json.loads(json.dumps(current[idx]))
                        if isinstance(clone, dict) and "_gameId" in clone:
                            clone["UniqueItemGuid"] = {"serializedGuid": str(uuid.uuid4())}
                            if isinstance(clone.get("_gameId"), dict):
                                g = clone["_gameId"].setdefault("_guid", {})
                                if not isinstance(g, dict):
                                    g = {}
                                    clone["_gameId"]["_guid"] = g
                            clone["_equipedSlot"] = ""
                        current.insert(idx + 1, clone)
                        saved_flag = True
                        status_msg = f"cloned {name}"
                    elif isinstance(current, dict):
                        val = json.loads(json.dumps(current[name]))
                        k2 = f"{name} copy"
                        n = 2
                        while k2 in current:
                            k2 = f"{name} copy {n}"
                            n += 1
                        current[k2] = val
                        saved_flag = True
                        status_msg = f"cloned {name} -> {k2}"
                except Exception as e:
                    status_msg = f"clone failed: {e}"
        elif key in (10, 13, curses.KEY_RIGHT, ord("d"), ord("D")):  # Enter
            if selected < len(children):
                name, icon, type_str, val_str, kind = children[selected]
                if kind == "container":
                    if isinstance(current, dict):
                        child = current[name]
                    else:
                        idx = int(name[1:-1])
                        child = current[idx]
                    stack.append((current, name, child, current_path_str, selected))
                    if isinstance(current, dict):
                        current_path_str = f"{current_path_str}.{name}"
                    else:
                        current_path_str = f"{current_path_str}{name}"
                    current = child
                    selected = 0
                    scroll = 0
                elif kind == "scalar":
                    if isinstance(current, dict):
                        edit_parent = current
                        edit_key = name
                    else:
                        idx = int(name[1:-1])
                        edit_parent = current
                        edit_key = str(idx)
                    edit_target = (
                        current[name] if isinstance(current, dict)
                        else current[idx]
                    )
                    edit_buffer = edit_prefill(
                        edit_parent, edit_key, edit_target
                    )
                    edit_mode = True
                    edit_dirty = False
        elif key == ord("e") or key == ord("E"):
            if selected < len(children):
                name, icon, type_str, val_str, kind = children[selected]
                if kind == "scalar":
                    if isinstance(current, dict):
                        edit_parent = current
                        edit_key = name
                    else:
                        idx = int(name[1:-1])
                        edit_parent = current
                        edit_key = str(idx)
                    edit_mode = True
                    edit_target = (
                        current[name] if isinstance(current, dict)
                        else current[idx]
                    )
                    edit_buffer = edit_prefill(
                        edit_parent, edit_key, edit_target
                    )
                    edit_dirty = False
        elif (
            key in (ord("+"), ord("="), ord("-"), ord("["), ord("]"))
            and is_color_dict(current)
            and selected < len(children)
        ):
            # color adjuster: nudge the selected channel without typing.
            name = children[selected][0]
            if name in _COLOR_KEYS:
                step = 8 if key in (ord("["), ord("]")) else 1
                if key in (ord("-"), ord("[")):
                    step = -step
                cur = current[name]
                newv = from255(max(0, min(255, to255(cur) + step)))
                if not last_was_nudge:
                    snapshot()
                current[name] = newv
                saved_flag = True
                last_was_nudge = True
        elif key in (ord("h"), ord("H")) and is_color_dict(current):
            # hex entry #rrggbb applied to r,g,b
            try:
                stdscr.addstr(h - 2, 0, " Hex (RRGGBB): "[: w - 1], curses.color_pair(5))
                stdscr.refresh()
                curses.echo()
                txt = stdscr.getstr(h - 2, 15, 10).decode("utf-8", errors="replace").strip()
                curses.noecho()
                txt = txt.lstrip("#")
                if len(txt) == 6:
                    snapshot()
                    current["r"] = from255(int(txt[0:2], 16))
                    current["g"] = from255(int(txt[2:4], 16))
                    current["b"] = from255(int(txt[4:6], 16))
                    saved_flag = True
            except Exception:
                try:
                    curses.noecho()
                except Exception:
                    pass
        elif key == ord("n") or key == ord("N"):
            # add item
            if isinstance(current, dict):
                # prompt for key
                try:
                    stdscr.addstr(h - 2, 0, " New key: "[: w - 1], curses.color_pair(5))
                    stdscr.refresh()
                    curses.echo()
                    new_key = stdscr.getstr(h - 2, 11, w - 12).decode("utf-8", errors="replace")
                    curses.noecho()
                    if new_key:
                        stdscr.addstr(h - 2, 0, " New value: "[: w - 1], curses.color_pair(5))
                        stdscr.refresh()
                        curses.echo()
                        new_val_str = stdscr.getstr(
                            h - 2, 13, w - 14
                        ).decode("utf-8", errors="replace")
                        curses.noecho()
                        snapshot()
                        current[new_key] = parse_value(new_val_str)
                        saved_flag = True
                except Exception as e:
                    try:
                        stdscr.addstr(h - 1, 0, f" Error: {e}"[: w - 1], curses.color_pair(4))
                        stdscr.refresh()
                        curses.napms(1000)
                    except Exception as e2:
                        print(f"Error: {e2}", file=sys.stderr)
            elif isinstance(current, list):
                try:
                    stdscr.addstr(h - 2, 0, " New value: "[: w - 1], curses.color_pair(5))
                    stdscr.refresh()
                    curses.echo()
                    new_val_str = stdscr.getstr(h - 2, 13, w - 14).decode("utf-8", errors="replace")
                    curses.noecho()
                    current.append(parse_value(new_val_str))
                    saved_flag = True
                except Exception as e:
                    try:
                        stdscr.addstr(h - 1, 0, f" Error: {e}"[: w - 1], curses.color_pair(4))
                        stdscr.refresh()
                        curses.napms(1000)
                    except Exception as e2:
                        print(f"Error: {e2}", file=sys.stderr)
        elif key in (ord("o"), ord("O"), 19):  # 19 = Ctrl+S
            bak = save_data(path, save_root)
            saved_flag = False
            quit_confirm = False
            try:
                msg = f" {CHECK} Saved (backup: {bak.name})"
                stdscr.addstr(h - 2, 0, msg[: w - 1], curses.color_pair(3) | curses.A_BOLD)
                stdscr.refresh()
                curses.napms(1200)
            except Exception as e:
                try:
                    stdscr.addstr(h - 1, 0, f" Error: {e}"[: w - 1], curses.color_pair(4))
                    stdscr.refresh()
                except Exception as e2:
                    print(f"Error: {e2}", file=sys.stderr)
        elif key in (curses.KEY_LEFT, ord("a")):
            if edit_mode:
                edit_mode = False
                edit_buffer = ""
                edit_key = ""
                edit_parent = None
                edit_dirty = False
            elif stack:
                parent, key, child, path_str, sel = stack.pop()
                current = parent
                current_path_str = path_str
                selected = sel
                scroll = max(0, selected - 3)
            elif saved_flag and not quit_confirm:
                quit_confirm = True
                status_msg = ("UNSAVED CHANGES - back again to leave anyway, "
                              "o to save")
            else:
                return _BACK_TO_LIST
        elif key in (ord("q"), ord("Q")):
            if edit_mode:
                edit_mode = False
                edit_buffer = ""
                edit_key = ""
                edit_parent = None
                edit_dirty = False
                status_msg = "edit cancelled"
            elif saved_flag and not quit_confirm:
                # don't lose edits by accident
                quit_confirm = True
                status_msg = "UNSAVED CHANGES - press q again to discard, or o to save"
            else:
                break
        elif key == 27:
            if edit_mode:
                edit_mode = False
                edit_buffer = ""
                edit_key = ""
                edit_parent = None
                edit_dirty = False
            elif filter_text:
                filter_text = ""
                selected = scroll = 0
                status_msg = "filter cleared"
            elif stack:
                parent, key, child, path_str, sel = stack.pop()
                current = parent
                current_path_str = path_str
                selected = sel
                scroll = max(0, selected - 3)
            else:
                # Deliberately does NOT go up a level. Arrow keys arrive as
                # ESC + '[' + letter, so a split read yields a bare ESC; if
                # that navigated, a stray arrow press would bounce you out of
                # the file. Use `a` or the left arrow to go back.
                status_msg = "at root - 'a' or left arrow goes back, q quits"


def select_items(data, selector):
    """Resolve a selector to [(index, item), ...]

    Accepted forms:
        @3            index into items[]
        guid:ab12cd   UniqueItemGuid prefix
        =Name         exact internal name
        Name          substring match on the internal name
        mod:Name      matches items from a mod namespace
    """
    items = (data.get("itemManager") or {}).get("items") or []
    mods = mod_names(data)
    s = selector.strip()
    out = []
    if s.startswith("@"):
        i = int(s[1:])
        return [(i, items[i])] if 0 <= i < len(items) else []
    if s.startswith("guid:"):
        pre = s[5:].lower()
        for i, it in enumerate(items):
            g = ((it.get("UniqueItemGuid") or {}).get("serializedGuid") or "")
            if g.lower().startswith(pre):
                out.append((i, it))
        return out
    if s.startswith("="):
        want = s[1:].lower()
        for i, it in enumerate(items):
            gj = it.get("_gameId") or {}
            guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
            if guid:
                continue
            if load_item_names().get(gj.get("_id"), "").lower() == want:
                out.append((i, it))
        return out
    if s.startswith("mod:"):
        want = s[4:].lower()
        for i, it in enumerate(items):
            gj = it.get("_gameId") or {}
            guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
            if guid and want in mods.get(guid, "").lower():
                out.append((i, it))
        return out
    low = s.lower()
    for i, it in enumerate(items):
        gj = it.get("_gameId") or {}
        guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
        if low in gameid_label(guid, gj.get("_id"), mods).lower():
            out.append((i, it))
    return out


def cmd_inventory(args):
    """Rich inventory listing with names, slots, colours and filtering"""
    load_item_names()
    paths = collect_files(args.files)
    total = 0
    for path in paths:
        try:
            data = load_data(path)
        except SystemExit:
            continue
        im = data.get("itemManager") or {}
        items = im.get("items") or []
        if not items:
            continue
        mods = mod_names(data)
        rows = []
        for i, it in enumerate(items):
            gj = it.get("_gameId") or {}
            guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
            name = load_item_names().get(gj.get("_id"), "") if not guid else ""
            slot = (it.get("_equipedSlot") or "").strip()
            if args.equipped and not slot:
                continue
            if args.slot and slot.lower() != args.slot.lower():
                continue
            if args.name and args.name.lower() not in name.lower():
                continue
            if args.mod and not guid:
                continue
            if args.vanilla and guid:
                continue
            if args.colors is not None and len(it.get("_colors") or []) != args.colors:
                continue
            rows.append((i, it, guid, name, slot))
        if not rows:
            continue
        print(f"=== {path.name} {DASH} {len(rows)}/{len(items)} items ===")
        print(f"{'idx':>5}  {'item':<40} {'cnt':>4} {'qual':>7} {'slot':<16} colors")
        print("-" * 96)
        for i, it, guid, name, slot in rows:
            cols = [c for c in (it.get("_colors") or []) if is_color_dict(c)]
            hexes = " ".join(color_hex(c) for c in cols[:5])
            print(f"{i:>5}  {gameid_label(guid, (it.get('_gameId') or {}).get('_id'), mods):<40} "
                  f"{it.get('_count', 0):>4} {float(it.get('_quality') or 0):>7.3f} "
                  f"{slot:<16} {hexes}")
        total += len(rows)
        print()
    if len(paths) > 1:
        print(f"total items matched: {total}")


def cmd_slotsdb(args):
    """Show which items can go in each slot (from items_by_slot.json)"""
    db = load_slot_db()
    if not db:
        print("items_by_slot.json not found next to the script", file=sys.stderr)
        sys.exit(1)
    want = (args.slot or "").lower()
    for slot in sorted(db):
        if want and want not in slot.lower():
            continue
        print(f"\n=== {slot}  ({len(db[slot])} items) ===")
        for i, n in sorted(db[slot]):
            print(f"  {i:>9}  {n}")


def cmd_find(args):
    """Search saves for item names, keys, or values"""
    needle = args.text.lower()
    paths = collect_files(args.targets)
    load_item_names()
    hits = 0
    for path in paths:
        try:
            data = load_data(path)
        except SystemExit:
            continue
        mods = mod_names(data)
        for i, it in enumerate((data.get("itemManager") or {}).get("items") or []):
            gj = it.get("_gameId") or {}
            guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
            label = gameid_label(guid, gj.get("_id"), mods)
            blob = json.dumps(it).lower()
            if needle in label.lower() or (args.deep and needle in blob):
                print(f"{path.name:<20} @{i:<5} {label}")
                hits += 1
    print(f"\n{hits} match(es)")


def cmd_color(args):
    """View or set an item's colours (0..255 in, float 0..1 out)"""
    path = Path(args.file)
    data = load_data(path)
    load_item_names()
    matches = select_items(data, args.item)
    if not matches:
        print(f"No item matches {args.item!r}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1 and not args.all:
        print(f"{len(matches)} items match; use --all or a narrower selector:")
        for i, it in matches[:20]:
            print(f"  @{i:<5} {item_summary(it, mod_names(data))}")
        return
    changed = 0
    for i, it in matches:
        cols = [c for c in (it.get("_colors") or []) if is_color_dict(c)]
        print(f"@{i}  {item_summary(it, mod_names(data))}")
        for j, c in enumerate(cols):
            print(f"   [{j}] {color_hex(c)}  "
                  f"r={to255(c['r']):>3} g={to255(c['g']):>3} b={to255(c['b']):>3} "
                  f"a={to255(c.get('a', 1.0)):>3}")
            if args.set:
                for pair in args.set.split(","):
                    if "=" not in pair:
                        continue
                    k, v = pair.split("=", 1)
                    k = k.strip().lower()
                    if k in ("r", "g", "b", "a") and k in c:
                        c[k] = coerce_color(v.strip(), c[k])
                        changed += 1
    if changed:
        bak = save_data(path, data)
        print(f"\nupdated {changed} channel(s)  (backup: {bak.name})")


def cmd_additem(args):
    """Add an item to a save's inventory"""
    path = Path(args.file)
    data = load_data(path)
    im = data.setdefault("itemManager", {})
    items = im.setdefault("items", [])
    gid = find_item_id(args.item)
    mod_guid = ""
    if args.mod:
        for st in im.get("sets") or []:
            for m in st.get("UsedMods") or []:
                n = (m.get("ModName") or "").lower()
                if args.mod.lower() in n:
                    mod_guid = (m.get("ModGuid") or {}).get("serializedGuid") or ""
    rec = new_item(gid, mod_guid, count=args.count, quality=args.quality,
                   slot=args.slot, colors=args.colors)
    items.append(rec)
    bak = save_data(path, data)
    print(f"Added {gameid_label(mod_guid, gid, mod_names(data))} "
          f"(count={args.count}, quality={args.quality}, colors={args.colors})")
    print(f"items[] is now {len(items)} records")
    print(f"Saved: {path}\nBackup: {bak}")


def cmd_delitem(args):
    """Remove item(s) from a save's inventory"""
    path = Path(args.file)
    data = load_data(path)
    mods = mod_names(data)
    matches = select_items(data, args.item)
    if not matches:
        print(f"No item matches {args.item!r}", file=sys.stderr)
        sys.exit(1)
    print(f"removing {len(matches)} item(s):")
    for i, it in matches[:30]:
        print(f"  @{i:<5} {item_summary(it, mods)}")
    idxs = sorted((i for i, _ in matches), reverse=True)
    if args.dry_run:
        print("(dry run - nothing written)")
        return
    if not args.yes:
        try:
            if input("confirm? [y/N] ").strip().lower() not in ("y", "yes"):
                print("aborted")
                return
        except EOFError:
            print("aborted (no tty; pass --yes)")
            return
    items = (data.get("itemManager") or {}).get("items") or []
    for i in idxs:
        items.pop(i)
    bak = save_data(path, data)
    print(f"items[] is now {len(items)} records\nSaved: {path}\nBackup: {bak}")


def cmd_dupe(args):
    """Duplicate item(s) N times (new GUIDs, independent copies)"""
    path = Path(args.file)
    data = load_data(path)
    mods = mod_names(data)
    items = (data.get("itemManager") or {}).get("items") or []
    matches = select_items(data, args.item)
    if not matches:
        print(f"No item matches {args.item!r}", file=sys.stderr)
        sys.exit(1)
    added = 0
    for i, it in matches:
        for _ in range(args.times):
            clone = json.loads(json.dumps(it))
            clone["UniqueItemGuid"] = {"serializedGuid": str(uuid.uuid4())}
            clone["_equipedSlot"] = ""
            items.append(clone)
            added += 1
    bak = save_data(path, data)
    print(f"duplicated {len(matches)} item(s) x{args.times} = +{added} records")
    print(f"items[] is now {len(items)} records\nSaved: {path}\nBackup: {bak}")


def cmd_equip(args):
    """Equip or unequip an item"""
    path = Path(args.file)
    data = load_data(path)
    items = (data.get("itemManager") or {}).get("items") or []
    matches = select_items(data, args.item)
    if not matches:
        print(f"No item matches {args.item!r}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1 and not args.all:
        print(f"{len(matches)} items match; use --all:")
        for i, it in matches[:20]:
            print(f"  @{i:<5} {item_summary(it, mod_names(data))}")
        return
    db = load_slot_db()
    names = load_item_names()
    LAYERED = {"EyeMakeup"}
    for i, it in matches:
        if args.slot is None:
            it["_equipedSlot"] = ""
            print(f"@{i} unequipped")
        else:
            gj = it.get("_gameId") or {}
            guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
            if not guid and db:
                gid = gj.get("_id")
                homes = [s for s, lst in db.items()
                         if any(x[0] == gid for x in lst)]
                if homes and args.slot not in homes:
                    print(
                        f"  ! warning: {names.get(gid, gid)} normally lives in "
                        f"{', '.join(sorted(homes))}, not {args.slot}"
                    )
            if args.slot not in LAYERED:
                for j, other in enumerate(items):
                    if j != i and (other.get("_equipedSlot") or "") == args.slot:
                        other["_equipedSlot"] = ""
                        print(f"@{j} displaced from {args.slot}")
            it["_equipedSlot"] = args.slot
            print(f"@{i} equipped in {args.slot}")
    bak = save_data(path, data)
    print(f"Saved: {path}\nBackup: {bak}")


def cmd_validate(args):
    """Sanity-check a save (colours, ids, guids, slots, counts)"""
    path = Path(args.file)
    data = load_data(path)
    items = (data.get("itemManager") or {}).get("items") or []
    problems, warns = [], []

    _, dups = find_guids(data)
    if dups:
        problems.append(f"{len(dups)} duplicate UniqueItemGuid value(s): {dups[:3]}")

    names = load_item_names()
    unknown = Counter()
    bad_colors = 0
    slot_counts = Counter()
    for i, it in enumerate(items):
        gj = it.get("_gameId") or {}
        guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
        gid = gj.get("_id")
        if not guid and gid not in names:
            unknown[gid] += 1
        if (it.get("UniqueItemGuid") or {}).get("serializedGuid") in (None, ""):
            problems.append(f"@{i} has an empty UniqueItemGuid")
        for c in it.get("_colors") or []:
            if not is_color_dict(c):
                warns.append(f"@{i} _colors entry is not an r/g/b/a dict: {c}")
                continue
            for k, v in c.items():
                if isinstance(v, bool) or not isinstance(v, float) or not (0.0 <= v <= 1.0):
                    bad_colors += 1
        s = (it.get("_equipedSlot") or "").strip()
        if s:
            slot_counts[s] += 1

    if bad_colors:
        problems.append(f"{bad_colors} colour channel(s) not float 0..1")
    if unknown:
        warns.append(f"unknown vanilla ids: {dict(unknown.most_common(8))}")
    multi = {s: n for s, n in slot_counts.items() if n > 1}
    if multi:
        warns.append(f"slots holding more than one item: {multi}")

    print(f"=== {path.name} ===")
    print(f"  items[]            : {len(items)}")
    n_guids = len({
        (i.get("UniqueItemGuid") or {}).get("serializedGuid")
        for i in items
    })
    print(f"  distinct guids     : {n_guids}")
    print(f"  equipped slots     : {len(slot_counts)}")
    print(f"  outfit sets        : {len((data.get('itemManager') or {}).get('sets') or [])}")
    print(f"  problems           : {len(problems)}")
    for p in problems:
        print(f"    {CROSS} {p}")
    print(f"  warnings           : {len(warns)}")
    for wn in warns:
        print(f"    ! {wn}")
    if not problems:
        print("  OK - no blocking problems found")
    return 1 if problems else 0


def cmd_backups(args):
    """List or restore .bak files"""
    path = Path(args.file)
    cands = sorted(path.parent.glob(path.name + "*.bak"))
    if args.restore is None:
        if not cands:
            print("no backups found")
            return
        for c in cands:
            st = c.stat()
            print(f"  {c.name:<40} {st.st_size:>10} bytes  "
                  f"{datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}")
        return
    if not cands:
        print("no backups found", file=sys.stderr)
        sys.exit(1)
    src = cands[0] if args.restore == "latest" else Path(args.restore)
    if not src.is_absolute():
        src = path.parent / src
    if not src.exists():
        print(f"backup not found: {src}", file=sys.stderr)
        sys.exit(1)
    cur = path.with_suffix(path.suffix + ".prerestore")
    if path.exists():
        cur.write_bytes(path.read_bytes())
    path.write_bytes(src.read_bytes())
    print(f"restored {path.name} from {src.name}")
    print(f"previous state kept as {cur.name}")


def cmd_tree(args):
    """Dump a file with item names resolved and colours as hex"""
    path = Path(args.file)
    data = load_data(path)
    mods = mod_names(data)
    load_item_names()
    out = []

    def walk(node, name, depth):
        pad = "  " * depth
        if isinstance(node, dict):
            if is_color_dict(node):
                out.append(f"{pad}{name}: #{color_hex(node)} "
                           f"({to255(node['r'])},{to255(node['g'])},{to255(node['b'])},"
                           f"{to255(node.get('a', 1.0))})")
                return
            if "_gameId" in node:
                out.append(f"{pad}{name}: ITEM {item_summary(node, mods)}")
                return
            out.append(f"{pad}{name}: {{}}")
            if depth >= args.depth:
                return
            for k, v in node.items():
                walk(v, k, depth + 1)
        elif isinstance(node, list):
            out.append(f"{pad}{name}: [{len(node)}]")
            if depth >= args.depth:
                return
            for i, v in enumerate(node):
                walk(v, f"[{i}]", depth + 1)
        else:
            out.append(f"{pad}{name}: {format_value(node)}")

    for k, v in data.items():
        walk(v, k, 0)
    text = "\n".join(out)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"wrote {args.out} ({len(out)} lines)")
    else:
        print(text)


def cmd_export(args):
    """Export a save to a normalised JSON with item names resolved"""
    path = Path(args.file)
    data = load_data(path)
    mods = mod_names(data)
    load_item_names()
    out = {"source": path.name, "items": [], "sets": []}
    for i, it in enumerate((data.get("itemManager") or {}).get("items") or []):
        gj = it.get("_gameId") or {}
        guid = ((gj.get("_guid") or {}).get("serializedGuid") or "").strip()
        out["items"].append({
            "index": i,
            "label": gameid_label(guid, gj.get("_id"), mods),
            id: gj.get("_id"), "modGuid": guid,
            "count": it.get("_count"), "quality": it.get("_quality"),
            "slot": it.get("_equipedSlot"),
            "colors": [color_hex(c) for c in (it.get("_colors") or []) if is_color_dict(c)],
            guid: (it.get("UniqueItemGuid") or {}).get("serializedGuid"),
        })
    for s in (data.get("itemManager") or {}).get("sets") or []:
        out["sets"].append({"name": s.get("Name"), "items": len(s.get("EquippedItems") or [])})
    dst = Path(args.out) if args.out else path.with_suffix(path.suffix + ".export.json")
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"wrote {dst}  ({len(out['items'])} items, {len(out['sets'])} sets)")


def collect_files(inputs):
    """Expand a mix of files, directories, or nothing into save files.

    With no arguments the auto-detected Saves directory is used, so the tool
    always operates on the same folder as the install it found.
    """
    out = []
    if not inputs:
        inputs = [str(resolve_saves_dir())]
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            out.extend(sorted(p.glob("*.mdrgslot")))
            out.extend(sorted(p.glob("save.mdrg")))
        elif p.exists():
            out.append(p)
        else:
            print(f"skip (not found): {raw}", file=sys.stderr)
    return out


def main():
    parser = argparse.ArgumentParser(
        prog="mdrg-savefile-editor",
        description="Inspect / rip apart My Dystopian Robot Girlfriend save files",
        epilog=(
            "See https://github.com/ for updates. "
            "No external dependencies required."
        ),
    )
    parser.add_argument("--ascii", action="store_true",
                        help="force plain ASCII output (auto-enabled on a "
                             "non-UTF8 console; also MDRG_ASCII=1)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Scan a Saves directory")
    p_scan.add_argument("directory", nargs="?",
                        help="Path to Saves directory (default: auto-detected)")

    p_info = sub.add_parser("info", help="Show file structure")
    p_info.add_argument("file", help="Path to save file")

    p_stats = sub.add_parser("stats", help="Show key stats from a slot file")
    p_stats.add_argument("file", help="Path to .mdrg or .mdrgslot file")

    p_analyze = sub.add_parser("analyze", help="Analyze one or more save files")
    p_analyze.add_argument("files", nargs="+", help="Paths to .mdrg or .mdrgslot files")

    p_flags = sub.add_parser("flags", help="List all flags from a slot file")
    p_flags.add_argument("file", help="Path to .mdrgslot file")

    p_emails = sub.add_parser("emails", help="List emails from a slot file")
    p_emails.add_argument("file", help="Path to .mdrgslot file")
    p_emails.add_argument("-d", "--detail", action="store_true", help="Show all email details")

    p_items = sub.add_parser("items", help="List items from a slot file")
    p_items.add_argument("file", help="Path to .mdrgslot file")
    p_items.add_argument("-e", "--equipped", action="store_true", help="Show equipped items only")

    p_diff = sub.add_parser("diff", help="Diff two slot files")
    p_diff.add_argument("file1", help="First .mdrgslot")
    p_diff.add_argument("file2", help="Second .mdrgslot")

    p_story = sub.add_parser("story", help="Analyze storyTextIds_Comp")
    p_story.add_argument("file", help="Path to save.mdrg")

    p_slots = sub.add_parser("slots", help="List all save slots with progression")
    p_slots.add_argument("directory", nargs="?",
                         help="Path to Saves directory (default: auto-detected)")

    p_dump = sub.add_parser("dump", help="Pretty-print a file")
    p_dump.add_argument("file", help="Path to save file")
    p_dump.add_argument("--depth", type=int, default=3, help="Dump depth (default: 3)")

    p_extract = sub.add_parser("extract", help="Extract a field by name (recursive search)")
    p_extract.add_argument("file", help="Path to save file")
    p_extract.add_argument("field", help="Field name to extract")

    p_pp = sub.add_parser("playerprefs", help="Parse PlayerPrefs.pp")
    p_pp.add_argument("file", help="Path to PlayerPrefs.pp")

    p_set = sub.add_parser("set", help="Set a value at a path (non-interactive)")
    p_set.add_argument("file", help="Path to save file")
    p_set.add_argument(
        "path",
        help="JSON path (e.g. money, flags[0].name, "
             "itemManager.items[0]._count)",
    )
    p_set.add_argument("value", help="New value (auto-detected: int/float/bool/string/null)")

    p_edit = sub.add_parser("edit", help="Interactive TUI editor (curses)")
    p_edit.add_argument("file", nargs="?",
                        help="Path to save file (omit to pick from the save dir)")

    p_inv = sub.add_parser("inventory", help="Rich inventory listing (files or dirs)")
    p_inv.add_argument("files", nargs="*", help="Save file(s) or Saves directory"
                                             " (default: auto-detected)")
    p_inv.add_argument("-s", "--slot", help="Only this equip slot")
    p_inv.add_argument("-n", "--name", help="Filter by item name substring")
    p_inv.add_argument("-e", "--equipped", action="store_true", help="Only equipped items")
    p_inv.add_argument("--mod", action="store_true", help="Only mod items")
    p_inv.add_argument("--vanilla", action="store_true", help="Only vanilla items")
    p_inv.add_argument("-c", "--colors", type=int, help="Only items with N colour channels")

    p_sdb = sub.add_parser("slotsdb", help="Show which items can go in each slot")
    p_sdb.add_argument("slot", nargs="?", help="Filter by slot name substring")

    p_find = sub.add_parser("find", help="Search saves for an item name")
    p_find.add_argument("text", help="Text to search for")
    p_find.add_argument("targets", nargs="*", help="Save file(s) or Saves directory"
                                                " (default: auto-detected)")
    p_find.add_argument("--deep", action="store_true",
                        help="Also match anywhere in the raw item JSON")

    p_col = sub.add_parser("color", help="View or set item colours (0-255)")
    p_col.add_argument("file", help="Path to .mdrgslot file")
    p_col.add_argument("item", help="Selector: @index, guid:xxxx, =Name, or a name substring")
    p_col.add_argument("--set", metavar="r=200,g=128,b=0",
                       help="Set channels (0-255, or 0.0-1.0)")
    p_col.add_argument("--all", action="store_true", help="Apply to every match")

    p_add = sub.add_parser("additem", help="Add an item to the inventory")
    p_add.add_argument("file", help="Path to .mdrgslot file")
    p_add.add_argument("item", help="Item name (fuzzy) or id")
    p_add.add_argument("-n", "--count", type=int, default=1)
    p_add.add_argument("-q", "--quality", type=float, default=1.0)
    p_add.add_argument("-s", "--slot", default="")
    p_add.add_argument("-c", "--colors", type=int, default=1, help="Number of colour channels")
    p_add.add_argument("--mod", help="Mod name to place it in that mod's namespace")

    p_del = sub.add_parser("delitem", help="Remove item(s) from the inventory")
    p_del.add_argument("file", help="Path to .mdrgslot file")
    p_del.add_argument("item", help="Selector: @index, guid:xxxx, =Name, or a name substring")
    p_del.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    p_del.add_argument("--dry-run", action="store_true", help="Show what would be removed")

    p_dup = sub.add_parser("dupe", help="Duplicate item(s) with fresh GUIDs")
    p_dup.add_argument("file", help="Path to .mdrgslot file")
    p_dup.add_argument("item", help="Selector: @index, guid:xxxx, =Name, or a name substring")
    p_dup.add_argument("-n", "--times", type=int, default=1)

    p_eq = sub.add_parser("equip", help="Equip / unequip an item")
    p_eq.add_argument("file", help="Path to .mdrgslot file")
    p_eq.add_argument("item", help="Selector: @index, guid:xxxx, =Name, or a name substring")
    p_eq.add_argument("-s", "--slot", default=None,
                      help="Slot to equip into (omit to unequip)")
    p_eq.add_argument("--all", action="store_true", help="Apply to every match")

    p_val = sub.add_parser("validate", help="Sanity-check a save file")
    p_val.add_argument("file", help="Path to .mdrgslot file")

    p_bak = sub.add_parser("backups", help="List or restore .bak backups")
    p_bak.add_argument("file", help="Path to the save file the backups belong to")
    p_bak.add_argument("--restore", nargs="?", const="latest",
                       help="Restore a backup (default: latest)")

    p_tree = sub.add_parser("tree", help="Dump with item names and colours resolved")
    p_tree.add_argument("file", help="Path to save file")
    p_tree.add_argument("--depth", type=int, default=2, help="Depth to descend (default: 2)")
    p_tree.add_argument("-o", "--out", help="Write to a file instead of stdout")

    p_exp = sub.add_parser("export", help="Export a normalised JSON summary")
    p_exp.add_argument("file", help="Path to .mdrgslot file")
    p_exp.add_argument("-o", "--out", help="Output path")

    p_where = sub.add_parser("where", help="Show platform info and the Saves dirs checked")
    p_where.add_argument("directory", nargs="?", help="Override directory to resolve")

    args = parser.parse_args()
    if getattr(args, "ascii", False):
        set_ascii_mode(True)

    cmds = {
        "scan":         cmd_scan,
        "info":         cmd_info,
        "stats":        cmd_stats,
        "analyze":      cmd_analyze,
        "flags":        cmd_flags,
        "emails":       cmd_emails,
        "items":        cmd_items,
        "diff":         cmd_diff,
        "story":        cmd_story,
        "slots":        cmd_slots,
        "dump":         cmd_dump,
        "extract":      cmd_extract,
        "playerprefs":  cmd_playerprefs,
        "set":          cmd_set,
        "edit":         cmd_edit,
        "inventory":    cmd_inventory,
        "slotsdb":      cmd_slotsdb,
        "find":         cmd_find,
        "color":        cmd_color,
        "additem":      cmd_additem,
        "delitem":      cmd_delitem,
        "dupe":         cmd_dupe,
        "equip":        cmd_equip,
        "validate":     cmd_validate,
        "backups":      cmd_backups,
        "tree":         cmd_tree,
        "export":       cmd_export,
        "where":        cmd_where,
    }

    handler = cmds.get(args.command)
    if handler is None:
        parser.error(f"Unknown command: {args.command}")
    sys.exit(handler(args) or 0)

if __name__ == "__main__":
    main()
