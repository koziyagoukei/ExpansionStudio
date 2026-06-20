# Expansion Studio

⚠ Experimental Alpha

Always commit your changes before using this tool.
Back up your repository.

Desktop workbench for this Japanese `pokeemerald-expansion` localization project.

The application reads the repository source files directly. Source data remains
the authority; the tool makes conservative edits and creates a `.bak` backup
before it overwrites a source file.
This project is not affiliated with Nintendo, Game Freak, or The Pokémon Company.

This project is licensed under the MIT License.

<img width="2545" height="1434" alt="{5A24AF13-AB1D-4216-8E30-0B9EBB78C49B}" src="https://github.com/user-attachments/assets/ad4d4cf4-54a0-4483-876e-d56f53a5008e" />

<img width="2541" height="1425" alt="{8DB14912-9E99-47A4-B72B-628DC4303EBB}" src="https://github.com/user-attachments/assets/e3bd07eb-cf4e-4c7f-9fc2-87e3581f4d65" />

<img width="2543" height="1426" alt="{C0836482-31D0-47BA-89FB-E6E38F1751BC}" src="https://github.com/user-attachments/assets/ffc2dad8-a48f-43b5-a8f3-7a9c26f7e064" />

https://github.com/koziyagoukei/ExpansionStudio/releases

## Requirements

* Python 3.10 or later
* PySide6

Install the Python dependency from the repository root:

```powershell
python -m pip install -r "requirements.txt"
```

## Start

```powershell
python "ExpansionStudio.py"
```

Select the repository root when prompted, or set it in the toolbar. A valid
root contains both `src` and `include`.

## Available workspaces

* **Translation**: finds `_()` and `COMPOUND_STRING()` text in `src` and
  `include`; supports search, filename filtering, untranslated/changed filters,
  UTF-8 text edits, character count, CSV import/export, and backups. Its Event
  Browser recursively scans repository `.inc` files, listing each `.string`
  definition with its label, body, path, line, use count, and definition type.
  It displays `msgbox` / `message` text in an event tree, searches labels and
  text together, and lets you follow references in both directions. The
  terminal `$` is hidden during INC editing and restored when saved. Definitions
  are identified by type, relative path, and label; an INC/Poryscript name
  collision is deliberately left unresolved instead of guessing a target.
  Supported `.string` and existing C text can be edited and saved with backups.
* **Constants**: browses `#define` values and enum-style constants under
  `include/constants`.
* **File Search**: searches source, data, Makefile, and text files and copies a
  selected `path:line` location to the clipboard.
* **Pokemon**: uses a development-oriented detail view with Basic, Stats,
  Abilities, Evolutions, Moves, Pokedex, and Graphics tabs. It shows localized
  type names, total base stats, ability descriptions, evolution links,
  level-up moves, front graphics, and cry IDs. Double-click a move or evolution
  to jump to its detailed record. Level-up, egg, and teachable move lists can
  be selected from their actual source files, edited, diffed, and saved with a
  backup. The evolution expression can also be edited while retaining complex
  project-specific conditions.
* **Moves**: shows localized type/category labels, power, accuracy, PP, effect
  summary, critical-hit stage, and selectable flags such as contact, punching,
  sound, and wind. The Additional Effects tab supports effects such as a 10%
  paralysis chance, including chance and self-target settings. It also lists
  static source references for the selected move.
* **Assets**: shows PNG-backed image groups by default. A group includes the
  related `.gbapal`, `.pal`, `.bin`, and `.4bpp` files with the same base path.
  It shows static reference locations and labels zero-reference groups as
  **unused candidates**, with path, unused-first, and reference-count sorting.
  Candidate removal moves the whole group to `quarantine/assets/<timestamp>/`
  instead of deleting it. Enable the non-PNG filter for groups without a PNG.
* **Dependencies**: shows static textual references for a file path, constant,
  symbol, species ID, or move ID.
* **Glyph Table**: manages the selected font PNG as 8x16 glyph cells by Glyph
  ID. It lists mapped characters, image previews, measured widths, static use
  counts, and use locations; supports Glyph ID/character search and unused
  glyph filtering. Normal charmap mappings can be added, changed, or removed
  with a backup of `charmap.txt`. It does not use automatic language profiles:
  the selected Glyph ID is always the unit of inspection and editing.
* **Poryscript**: recursively searches `.pory` files, supports filename/body/
  label search, edits one file at a time with backups, marks unsaved files, and
  shows compile stdout/stderr. New files can start blank or from a managed
  template in `workspace/templates/poryscript`; template variables such as
  `{{SCRIPT_NAME}}` and `{{MESSAGE}}` are entered in a form and previewed
  before writing. An existing `.inc` can also be saved as a Poryscript `raw`
  block without changing the original assembly source. Editing and creation
  work without Poryscript installed.
* **Settings**: stores the external Poryscript executable, source directory,
  and output directory separately from the event editor.

The UI language can be switched between Japanese and English from the toolbar.
The same toolbar provides pending diff, save, build, ROM launch, and build/ROM
command configuration actions. Set the command once before running it; commands
are executed with the selected repository root as their working directory.

## Build a Windows executable

`em.png` is used as the window and executable icon. Install the build
requirements, then run the bundled builder from this directory:

```powershell
python -m pip install -r "workspace\requirements-build.txt"
python "workspace\build_exe.py"
```

The distributable application is created under
`workspace\dist\ExpansionStudio.exe`.
When the executable first opens Poryscript templates, it copies the bundled
defaults into `workspace\dist\templates\poryscript`; that folder is the
editable template location for the standalone application.

## Current limits

* The C parser is intentionally limited. Complex or unrecognized expressions
  are displayed but are not rewritten automatically.
* Static reference results do not prove that an asset has no dynamic or
  build-generated use. Confirm a clean build after deleting assets.
* Species and move deletion does not renumber or remove internal constants.
  This prevents accidental ABI/data-table corruption.
* Poryscript is currently a source editor. `.inc` import intentionally starts
  as a `raw` block, rather than attempting an unsafe automatic rewrite. Flowchart
  rendering and structured graphical editing are not yet implemented.
* Trainer, battle AI, and map editors are out of scope for the current version.
