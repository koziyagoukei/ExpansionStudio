# Expansion Studio

[Japanese README](./読んでね.md)

Expansion Studio is a local desktop workbench for Pokemon decompilation projects, focused on `pokeemerald-expansion`.

It is an experimental alpha tool. It edits source files directly, so keep your project under Git and review diffs before committing.

## Main Features

- Translation and text management for `_()`, `COMPOUND_STRING()`, `gText_*`, event `.string`, and `msgbox` references
- Event script browser and editor for `data/maps/*/map.json`, `scripts.inc`, and `text.inc`
- New event script/text label creation with templates
- Event script search and script label rename support
- Project-wide code index for constants, gText, COMPOUND_STRING, script labels, macros, enums, and structs
- Pokemon data browser/editor
- Move data browser/editor
- Battle Frontier Pokemon pool editor
- General trainer and trainer party editor, including Mugshot cut-in and team transition helper fields
- Map encounter editor
- Asset browser, image/palette replacement helper, PNG analysis, indexed PNG conversion, and JASC-PAL generation
- Glyph Table editor for charmap/glyph inspection
- Font management helper
- Info Viewer editor
- ROM Layout / Build Map viewer
- Read-only ROM Binary Viewer with hex/ASCII view
- Patch helper for BPS/PPF workflows
- Command launcher for PowerShell, cmd, WSL, and Windows Terminal
- Poryscript file browser/editor and template creation helper
- CLI tools for external automation
- Local stdio MCP server for ChatGPT Desktop / Codex integration

- <img width="981" height="364" alt="{D04066D6-BA70-45E4-B208-DC1AAB794D2B}" src="https://github.com/user-attachments/assets/a14d9faf-5963-4189-8d9e-295f3d0a87e8" />

<img width="983" height="565" alt="{6533CA58-BC2F-4699-BFDF-C1476F23DC89}" src="https://github.com/user-attachments/assets/02e4b8d3-c584-41b1-963a-23df4ffaa186" />

<img width="986" height="591" alt="{EA65C494-2621-4D05-B96D-361BF01734EB}" src="https://github.com/user-attachments/assets/dff95886-f906-4005-92db-b1e7458914b0" />


## Supported Projects

Best supported:

- `pokeemerald-expansion`

Partial or experimental:

- `pokeemerald`
- `pokefirered`-style layouts

Other decomp projects may open, but parsers and editors may not understand every file layout.

## Requirements

To run from source:

- Python 3.10 or later
- PySide6

Install runtime dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install build dependencies only when creating an executable:

```powershell
python -m pip install -r requirements-build.txt
```

## Start From Source

```powershell
python ExpansionStudio.py
```

Select the target decomp repository root from the toolbar. A valid root should contain at least `src` and `include`.

## Build Executable

`em.png` is used as the application icon. To build the Windows executable:

```powershell
python build_exe.py
```

The executable is generated under:

```text
dist/ExpansionStudio.exe
```

`build/` and `dist/` are generated outputs and should not be committed.

## CLI

Expansion Studio also exposes a Qt-free CLI package:

```powershell
python -m expansionstudio validate-project --root "C:\path\to\pokeemerald-expansion" --pretty
python -m expansionstudio scan-texts --root "C:\path\to\pokeemerald-expansion" --query CONTINUE --pretty
python -m expansionstudio search-map-scripts --root "C:\path\to\pokeemerald-expansion" --query msgbox --pretty
```

Write-capable CLI commands create backups where the underlying editor supports it. Review diffs before committing.

## MCP Server

A local stdio MCP wrapper is included so ChatGPT Desktop, Codex, or another MCP client can call the Expansion Studio CLI safely.

```powershell
python -m expansionstudio.mcp_server --root "C:\path\to\pokeemerald-expansion"
```

See [ExpansionStudio_MCP.md](./ExpansionStudio_MCP.md) for MCP client configuration examples, safety rules, and smoke tests.

## Safety Notes

- Always commit or stash your project before editing with this tool.
- The source repository remains the authority.
- The editor tries to make conservative, targeted edits.
- `.bak` files are created before many save operations.
- Generated files such as `build/`, `dist/`, `__pycache__/`, and `.expansionstudio/` should not be committed.
- The tool does not create Git commits, pushes, or pull requests by itself.

## License

MIT License. This project is not affiliated with Nintendo, Game Freak, Creatures, or The Pokemon Company.
