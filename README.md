# Expansion Studio

[日本語版はこちら](./読んでね.md)

⚠ **Experimental Alpha**

Expansion Studio is a desktop workbench for Pokémon decompilation projects, with a focus on `pokeemerald-expansion`.

It provides project-wide browsing, text editing, asset management, Poryscript assistance, Battle Frontier editing, general trainer block editing, command launching, and source indexing.

Always commit your changes before using this tool.
Back up your repository.

This application edits repository source files directly. Source data remains the authority. Expansion Studio tries to make conservative edits and creates `.bak` backups before overwriting source files, but it is still an alpha tool.

This project is not affiliated with Nintendo, Game Freak, Creatures, or The Pokémon Company.

This project is licensed under the MIT License.

## Download

Latest releases are available here:

https://github.com/koziyagoukei/ExpansionStudio/releases

## Supported Projects

Current support is best for:

* `pokeemerald-expansion`
* `pokeemerald`

Partial or experimental support:

* `pokefirered`

Other Pokémon decompilation projects may open, but parsers and editors may not fully understand their layouts.

## Requirements

To run from source:

* Python 3.10 or later
* PySide6

Install dependencies from the repository root:

```powershell
python -m pip install -r "requirements.txt"
```

## Start

```powershell
python "ExpansionStudio.py"
```

When prompted, select the repository root.
A valid project root should contain at least `src` and `include`.

## Executable Build

`em.png` is used as the window and executable icon.

To build the Windows executable:

```powershell
python -m pip install -r "workspace\requirements-build.txt"
python "workspace\build_exe.py"
```

The executable is created under:

```text
workspace\dist\ExpansionStudio.exe
```

## UI Language

The UI language can be switched between Japanese and English from the toolbar.

A Japanese README is planned separately as:

```text
読んでね.md
```

## Main Workspaces

### Translation

The Translation workspace scans source text definitions such as:

* `_()`
* `COMPOUND_STRING()`
* `.string` definitions in event `.inc` files

Features include:

* Search
* Filename filtering
* Untranslated / changed filters
* UTF-8 text editing
* Character count
* CSV import / export
* Diff preview
* Backup creation
* Event browser
* Reference navigation
* Automatic text formatting

The automatic formatting tool can insert line breaks based on configurable width rules and shows a diff preview before applying changes.

### Constants

Browses constants from project headers, mainly under:

```text
include/constants
```

It is useful for checking species, moves, items, abilities, flags, vars, and related constants.

### File Search

Performs plain source-file text search.

Use this when you want raw text search rather than indexed symbol search.

### Index

The Index workspace builds a project-wide definition index.

Indexed entries include:

* Constants
* `gText_*`
* `COMPOUND_STRING`
* Script labels
* Macros
* Enums
* Structs

Features:

* Fast search by name, value, preview, or file path
* Type filter
* File path filter
* Source preview
* Open file
* Jump to line
* Copy name
* Copy relative path
* Find references
* Re-index button

The index is cached under:

```text
.expansionstudio/index.json
```

The `.expansionstudio/` directory should not be committed.

### Pokémon

The Pokémon workspace provides a development-oriented Pokémon data viewer and editor.

It includes tabs for:

* Basic data
* Stats
* Abilities
* Evolutions
* Moves
* Pokédex
* Graphics

Features include:

* Localized type display
* Base stat total
* Ability descriptions
* Evolution links
* Level-up moves
* Egg moves
* Teachable moves
* Front graphics preview
* Cry ID display
* Diff preview
* Backup creation

### Moves

The Moves workspace shows and edits move data.

Displayed information includes:

* Type
* Category
* Power
* Accuracy
* PP
* Effect summary
* Critical-hit stage
* Flags such as contact, punching, sound, wind, and more
* Additional effects

Move lists can be filtered by type and category.

### ROM Layout

The ROM Layout workspace connects build outputs back to source-level symbols.

It reads `pokeemerald.map` and `pokeemerald.gba` from the project root, then displays where symbols are placed in the compiled ROM.

Features:

- Automatic detection of `pokeemerald.map`, `pokeemerald.gba`, and `pokeemerald.elf`
- Symbol name, GBA address, ROM offset, estimated size, section, and object file display
- Hex preview for symbols located inside the ROM file
- Safe handling for RAM symbols such as `0x02000000` / `0x03000000`
- Warning when `.map` and `.gba` timestamps appear to come from different builds
- Related source candidate display
- Jump to definition
- Copy symbol name, GBA address, and ROM offset

This is a read-only inspection feature. It does not decompile ROMs and does not edit ROM files.

### Assets

The Assets workspace helps browse, add, and replace graphics-related files.

It can group related files such as:

* `.png`
* `.gbapal`
* `.pal`
* `.bin`
* `.4bpp`

Features:

* Asset grouping
* Reference display
* Unused candidate display
* Sorting by path, unused state, and reference count
* Add assets under `graphics`
* Replace selected assets
* `.bak` backup before overwrite
* Basic replacement checks

Replacement checks include:

* Extension mismatch
* PNG readability
* 16-color warning for 4bpp targets
* 8px tile-size warning
* Odd-size warning for `.gbapal`
* 32-byte alignment warning for raw `.4bpp`

Expansion Studio does not directly convert PNG to 4bpp or LZ77.
It replaces source assets safely and lets the existing build system handle `INCGFX_*` / `INCBIN_*` conversion.

### Glyph Table

The Glyph Table workspace manages font PNG glyph cells by Glyph ID.

Features:

* 8x16 glyph cell preview
* Character mapping display
* Measured width display
* Static use count
* Use locations
* Glyph ID search
* Character search
* Unused glyph filtering
* `charmap.txt` editing with backups

The selected Glyph ID is always the inspection and editing unit.

### Poryscript

The Poryscript workspace searches and edits `.pory` files.

Features:

* Recursive `.pory` search
* Filename / body / label search
* One-file-at-a-time editing
* Unsaved marker
* Backup creation
* Compile stdout / stderr display
* Poryscript folder setting
* Auto-detection of `poryscript.exe` / `poryscript`
* Helper insert dropdowns

Helper insert categories include:

* `look`
* `text / msgbox`
* `text / yes-no`
* `movement`
* `flow`
* `giveitem`
* `trainerbattle`
* `warp`

Editing and file creation work even when Poryscript is not installed. Compilation requires a valid Poryscript folder.

### Battle Frontier

The Battle Frontier workspace edits Battle Frontier-related data.

Supported editing includes:

* `gBattleFrontierMons`
* Species
* Held item
* Ability
* Nature
* Ball
* Gender
* Moves
* EVs
* IVs
* Tera type
* Dynamax settings
* Gigantamax flag
* Shiny flag
* Tags

Move selection prioritizes species learnsets while still allowing all `MOVE_*` constants, so existing special sets are not accidentally destroyed.

The Pokémon list also displays overview columns:

* Mega
* Z
* DMax
* Tera
* Shiny
* Unused

Unused status is based on Battle Frontier trainer pool references.
It does not prove that the entry is unused everywhere in the project.

Battle Factory-related tables are also partially supported, including rental ranges and fixed IV tables.

### General Trainers

The General Trainers workspace edits trainer source blocks from:

```text
src/data/trainers.party
```

It intentionally does not edit:

```text
src/data/trainers.h
```

because `trainers.h` is an auto-generated file.

Features:

* TRAINER block listing
* Trainer name display
* Trainer class display
* Party size display
* Basic flag display
* Block text editing
* Diff preview
* Save
* `.bak` backup creation

This workspace currently focuses on safe block editing rather than fully structured trainer-party editing.

### Command Launcher

The toolbar provides terminal and script launcher features.

Features:

* Open terminal
* Registered scripts 1-5
* Per-script confirmation toggle
* Last executed script marker
* Execution log dialog
* stdout / stderr display
* Exit code display
* Terminal type presets

Supported terminal types include:

* PowerShell
* cmd
* WSL
* Windows Terminal

Template variables include:

* `{ROOT}`: current repository root
* `{WSL_ROOT}`: WSL-style `/mnt/c/...` root path
* `{SCRIPT}`: registered script body

Terminal and script behavior may require adjustment depending on your environment.

## Safety Notes

Expansion Studio is designed to avoid destructive edits where possible, but it is still an alpha tool.

Before using it:

1. Commit your current work.
2. Back up your repository.
3. Review diffs before saving.
4. Run a clean build after major edits.

The tool may create `.bak` files before overwriting source files.

## Current Limits

* The C parser is intentionally lightweight.
* Complex or unrecognized expressions may be displayed but not safely rewritten.
* Static reference results do not prove that an asset or symbol has no dynamic use.
* Asset deletion or quarantine should always be followed by a clean build.
* Species and move deletion does not renumber constants.
* Poryscript `.inc` import starts as a raw block rather than attempting unsafe automatic conversion.
* General Trainers currently edits source blocks, not every trainer field through structured GUI controls.
* Some features are optimized for `pokeemerald-expansion` and may not fully work on other projects.

## Legal Notice

This repository does not include ROM files.

Users are responsible for using their own legally obtained materials and for following the laws of their region.

Expansion Studio is an unofficial development utility and is not affiliated with Nintendo, Game Freak, Creatures, or The Pokémon Company.
