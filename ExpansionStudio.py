#!/usr/bin/env python3
"""Pokemon Emerald Expansion workbench.

This desktop utility reads the project sources directly.  It intentionally keeps
the C source as the source of truth: fields it cannot parse are displayed but
are not rewritten automatically.
"""

from __future__ import annotations

import csv
import difflib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

try:
    from PySide6.QtCore import QProcess, QProcessEnvironment, QSettings, QTimer, Qt, Signal
    from PySide6.QtGui import QAction, QFont, QIcon, QImage, QKeySequence, QPixmap, QShortcut, QTextCursor
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
        QFileDialog, QFormLayout, QFrame, QGraphicsScene, QGraphicsView,
        QGroupBox, QHBoxLayout, QLabel, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
        QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
        QSplitter, QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
        QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - depends on local installation
    print("PySide6 is required. Install dependencies with:")
    print('  python -m pip install -r "デコンプデータ作業用ツール/requirements.txt"')
    raise SystemExit(1) from exc


APP_NAME = "Pokemon Decomp Workbench"
UI_FONT_POINT_SIZE = 11
TABLE_VISIBLE_ROWS = 15
TABLE_ROW_HEIGHT = 26
COMBO_MIN_CONTENTS = 28
DETAIL_PANEL_MIN_WIDTH = 520
LIST_PANEL_MIN_WIDTH = 460
DEFAULT_TERMINAL_COMMAND = 'powershell.exe -NoExit -Command "$env:PATH = \'{ROOT};\' + $env:PATH; Set-Location -LiteralPath \'{ROOT}\'"'
DEFAULT_SCRIPT_RUN_TEMPLATE = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:PATH = \'{ROOT};\' + $env:PATH; Set-Location -LiteralPath \'{ROOT}\'; {SCRIPT}"'
DEFAULT_TERMINAL_TYPE = "powershell"
TERMINAL_TYPES = [
    ("PowerShell", "powershell"),
    ("cmd", "cmd"),
    ("WSL", "wsl"),
    ("Windows Terminal", "windows_terminal"),
]
TERMINAL_TEMPLATES = {
    "powershell": (
        DEFAULT_TERMINAL_COMMAND,
        DEFAULT_SCRIPT_RUN_TEMPLATE,
    ),
    "cmd": (
        'cmd.exe /K "set PATH={ROOT};%PATH% && cd /d {ROOT}"',
        'cmd.exe /C "set PATH={ROOT};%PATH% && cd /d {ROOT} && {SCRIPT}"',
    ),
    "wsl": (
        'wsl.exe --cd "{WSL_ROOT}"',
        'wsl.exe --cd "{WSL_ROOT}" bash -lc "export PATH=\\"{WSL_ROOT}:$PATH\\"; {SCRIPT}"',
    ),
    "windows_terminal": (
        'wt.exe -d "{ROOT}" powershell.exe -NoExit -Command "$env:PATH = \'{ROOT};\' + $env:PATH"',
        'wt.exe -d "{ROOT}" powershell.exe -NoExit -Command "$env:PATH = \'{ROOT};\' + $env:PATH; {SCRIPT}; Write-Host \'\'; Read-Host \'Press Enter to close\'"',
    ),
}
DEFAULT_COMMAND_SCRIPTS = [
    ("make clean", "make clean"),
    ("make", "make"),
    ("clean + make", "make clean; make"),
    ("", ""),
    ("", ""),
]
SOURCE_EXTENSIONS = {".c", ".h", ".inc", ".s", ".mk", ".json", ".txt"}
TEXT_EXTENSIONS = {".c", ".h", ".inc"}
LANG = {
    "ja": {
        "window": "ポケモン デコンプ作業ツール", "root": "リポジトリ", "browse": "参照",
        "reload": "再読込", "save": "保存", "search": "検索", "clear": "クリア",
        "translation": "翻訳", "constants": "定数", "files": "ファイル検索",
        "species": "ポケモン", "moves": "わざ", "frontier": "バトルフロンティア", "assets": "アセット",
        "dependencies": "依存関係", "fonts": "Glyph Table", "poryscript": "Poryscript", "settings": "設定",
        "language": "言語", "results": "件", "original": "原文", "edited": "編集後",
        "untranslated": "未翻訳のみ", "dirty": "変更済みのみ", "file": "ファイル",
        "export": "CSV 出力", "import": "CSV 読込", "add_template": "雛形を作成",
        "copy": "追加", "delete": "削除", "references": "参照", "configure": "設定",
        "not_configured": "Poryscript は未設定です。外部ツールの場所を設定してください。",
        "diff": "差分", "terminal": "端末起動", "command_settings": "コマンド設定",
    },
    "en": {
        "window": "Pokemon Decomp Workbench", "root": "Repository", "browse": "Browse",
        "reload": "Reload", "save": "Save", "search": "Search", "clear": "Clear",
        "translation": "Translation", "constants": "Constants", "files": "File Search", "index": "Index",
        "species": "Pokemon", "moves": "Moves", "frontier": "Battle Frontier", "assets": "Assets",
        "dependencies": "Dependencies", "fonts": "Glyph Table", "poryscript": "Poryscript", "settings": "Settings",
        "language": "Language", "results": "results", "original": "Original", "edited": "Edited",
        "untranslated": "Untranslated only", "dirty": "Changed only", "file": "File",
        "export": "Export CSV", "import": "Import CSV", "add_template": "Create template",
        "copy": "Add", "delete": "Delete", "references": "References", "configure": "Configure",
        "not_configured": "Poryscript is not configured. Set the external tool location.",
        "diff": "Diff", "terminal": "Open terminal", "command_settings": "Command settings",
    },
}
LANG["ja"]["index"] = "インデックス"


def tr(key: str, lang: str) -> str:
    return LANG[lang].get(key, key)


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def resource_path(name: str) -> Path:
    """Resolve a bundled resource when running from a PyInstaller executable."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def writable_tool_dir() -> Path:
    """Keep user-managed data beside the executable, never in PyInstaller's temp dir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def pory_template_root(tool_dir: Path) -> Path:
    """Seed editable templates from the bundle without overwriting user changes."""
    target = tool_dir / "templates" / "poryscript"; target.mkdir(parents=True, exist_ok=True)
    bundled = resource_path("templates/poryscript")
    if bundled.exists():
        for source in bundled.glob("*.pory"):
            destination = target / source.name
            if not destination.exists(): shutil.copy2(source, destination)
    return target


def read_utf8(path: Path) -> str:
    # newline="" keeps CRLF/LF exactly as stored so narrow edits do not reformat a file.
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def prune_backups(path: Path) -> None:
    """Keep only the most recent single .bak file for a source file."""
    for old_backup in path.parent.glob(path.name + ".bak.*"):
        try:
            old_backup.unlink()
        except OSError:
            pass


def backup_path(path: Path) -> Path:
    prune_backups(path)
    return path.with_name(path.name + ".bak")


def write_with_backup(path: Path, content: str) -> None:
    shutil.copy2(path, backup_path(path))
    path.write_text(content, encoding="utf-8", newline="")


def copy_with_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, backup_path(target))
    shutil.copy2(source, target)


def configure_table(table: QTableWidget, rows: int = TABLE_VISIBLE_ROWS) -> None:
    """Make large result tables readable while keeping the visible height stable."""
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
    table.verticalHeader().setMinimumSectionSize(TABLE_ROW_HEIGHT)
    fixed_height = 30 + (TABLE_ROW_HEIGHT * rows) + (table.frameWidth() * 2)
    table.setMinimumHeight(fixed_height)
    table.setMaximumHeight(fixed_height)


def stabilize_combo(combo: QComboBox, min_contents: int = COMBO_MIN_CONTENTS) -> None:
    """Prevent dynamic option lists from changing the surrounding layout width."""
    combo.setMinimumContentsLength(min_contents)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumWidth(260)


def stabilize_splitter(splitter: QSplitter, first: int = 1, second: int = 1) -> None:
    splitter.setChildrenCollapsible(False)
    splitter.setStretchFactor(0, first)
    splitter.setStretchFactor(1, second)


def skip_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def skip_string(text: str, pos: int, quote: str) -> int:
    pos += 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
        elif text[pos] == quote:
            return pos + 1
        else:
            pos += 1
    return pos


def balanced_end(text: str, open_pos: int, opener: str = "{", closer: str = "}") -> int | None:
    """Return the position after a balanced C block, ignoring comments/strings."""
    depth, pos = 0, open_pos
    while pos < len(text):
        if text.startswith("//", pos):
            end = text.find("\n", pos + 2)
            pos = len(text) if end < 0 else end + 1
            continue
        if text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            pos = len(text) if end < 0 else end + 2
            continue
        if text[pos] in "\"'":
            pos = skip_string(text, pos, text[pos])
            continue
        if text[pos] == opener:
            depth += 1
        elif text[pos] == closer:
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None


def parse_c_strings(text: str, pos: int) -> tuple[int, int, str] | None:
    pos = skip_space(text, pos)
    start = None
    parts: list[str] = []
    end = pos
    while pos < len(text) and text[pos] == '"':
        if start is None:
            start = pos
        pos += 1
        buf: list[str] = []
        while pos < len(text):
            char = text[pos]
            if char == "\\" and pos + 1 < len(text):
                buf.append(text[pos:pos + 2])
                pos += 2
            elif char == '"':
                pos += 1
                break
            else:
                buf.append(char)
                pos += 1
        parts.append("".join(buf))
        end = pos
        pos = skip_space(text, pos)
    return None if start is None else (start, end, "".join(parts))


def quote_c_text(value: str) -> str:
    # Existing escapes are retained because text strings contain charmap controls.
    out = ['"']
    for char in value:
        if char == "\n":
            out.append(r"\n")
        elif char == '"':
            out.append(r"\"")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def read_define_int(root: Path, name: str, default: int) -> int:
    constants = root / "include/constants/global.h"
    if not constants.exists():
        return default
    match = re.search(rf"(?m)^\s*#define\s+{re.escape(name)}\s+(\d+)\b", read_utf8(constants))
    return int(match.group(1)) if match else default


def extract_c_text_symbol(source: str, symbol: str) -> str | None:
    match = re.search(rf"\b{re.escape(symbol)}\s*(?:\[[^\]]*\])?\s*=\s*(?:_\s*\(|COMPOUND_STRING\s*\()", source)
    if not match:
        return None
    parsed = parse_c_strings(source, match.end())
    return parsed[2] if parsed else None


def extract_c_text_symbol_span(source: str, symbol: str) -> tuple[int, int, str] | None:
    match = re.search(rf"\b{re.escape(symbol)}\s*(?:\[[^\]]*\])?\s*=\s*(?:_\s*\(|COMPOUND_STRING\s*\()", source)
    if not match:
        return None
    parsed = parse_c_strings(source, match.end())
    if not parsed:
        return None
    start, end, text = parsed
    return start, end, text


@dataclass
class AutoFormatSettings:
    scope: str
    font_id: str
    max_width: int
    range_start: int
    range_end: int
    skip_existing_breaks: bool
    halfwidth_ascii: bool
    safe_placeholders: bool
    placeholder_max_chars: int = 20


@dataclass
class AutoFormatChange:
    label: str
    before: str
    after: str
    target: object | None = None
    selection: tuple[int, int] | None = None


class TextWidthModel:
    ZERO_WIDTH_CONTROLS = {
        "JPN", "ENG", "AUTO", "COLOR", "SHADOW", "HIGHLIGHT", "PALETTE", "PAUSE",
        "PAUSE_MUSIC", "RESUME_MUSIC", "PLAY_SE", "PLAY_BGM", "WAIT_SE", "FILL_WINDOW",
        "FONT", "RESET_FONT", "MIN_LETTER_SPACING", "SPEAKER", "ACCENT", "BACKGROUND",
        "COLOR_HIGHLIGHT_SHADOW", "TEXT_COLORS", "ESCAPE", "SHIFT_RIGHT", "SHIFT_DOWN",
    }
    WIDTH_CONTROLS = {"CLEAR", "SKIP", "CLEAR_TO"}
    FONT_JPN_WIDTHS = {"FONT_NORMAL": 7, "FONT_SMALL": 7, "FONT_NARROW": 7, "FONT_NARROWER": 7}
    STATIC_PLACEHOLDER_SYMBOLS = {
        "KUN": ("gText_ExpandedPlaceholder_Kun", "gText_ExpandedPlaceholder_Chan"),
        "RIVAL": ("gText_ExpandedPlaceholder_May", "gText_ExpandedPlaceholder_Brendan", "gText_ExpandedPlaceholder_Red", "gText_ExpandedPlaceholder_Green"),
        "VERSION": ("gText_ExpandedPlaceholder_Emerald",),
        "AQUA": ("gText_ExpandedPlaceholder_Aqua",),
        "MAGMA": ("gText_ExpandedPlaceholder_Magma",),
        "ARCHIE": ("gText_ExpandedPlaceholder_Archie",),
        "MAXIE": ("gText_ExpandedPlaceholder_Maxie",),
        "KYOGRE": ("gText_ExpandedPlaceholder_Kyogre",),
        "GROUDON": ("gText_ExpandedPlaceholder_Groudon",),
        "REGION": ("gText_Hoenn", "gText_Kanto"),
    }

    def __init__(self, root: Path) -> None:
        self.root = root
        self.constants = {
            "PLAYER_NAME_LENGTH": read_define_int(root, "PLAYER_NAME_LENGTH", 7),
            "TRAINER_NAME_LENGTH": read_define_int(root, "TRAINER_NAME_LENGTH", 10),
            "POKEMON_NAME_LENGTH": read_define_int(root, "POKEMON_NAME_LENGTH", 12),
            "MOVE_NAME_LENGTH": read_define_int(root, "MOVE_NAME_LENGTH", 16),
            "ITEM_NAME_LENGTH": read_define_int(root, "ITEM_NAME_LENGTH", 20),
        }
        self.static_placeholders = self.load_static_placeholders()

    def load_static_placeholders(self) -> dict[str, list[str]]:
        strings_path = self.root / "src/strings.c"
        if not strings_path.exists():
            return {}
        source = read_utf8(strings_path)
        result: dict[str, list[str]] = {}
        for placeholder, symbols in self.STATIC_PLACEHOLDER_SYMBOLS.items():
            values = [text for symbol in symbols if (text := extract_c_text_symbol(source, symbol)) is not None]
            if values:
                result[placeholder] = values
        return result

    def japanese_width(self, settings: AutoFormatSettings) -> int:
        return self.FONT_JPN_WIDTHS.get(settings.font_id, 7)

    @staticmethod
    def is_japanese_like(char: str) -> bool:
        code = ord(char)
        return code >= 0x80 or 0x3040 <= code <= 0x30FF or 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF

    @staticmethod
    def ascii_width(char: str) -> int:
        if char == " ":
            return 4
        if char in "ilI.,'!|":
            return 2
        if char in "fjrt()[]{}":
            return 4
        if char in "MW@#%&":
            return 7
        return 5

    def dynamic_placeholder_chars(self, name: str, settings: AutoFormatSettings) -> int:
        limit = max(1, settings.placeholder_max_chars)
        if name in {"PLAYER", "RIVAL", "B_PLAYER_NAME", "B_LINK_PLAYER_NAME"}:
            return min(self.constants["PLAYER_NAME_LENGTH"], limit)
        if "TRAINER" in name:
            return min(self.constants["TRAINER_NAME_LENGTH"], limit)
        if "MON" in name or "PKMN" in name or "POKEMON" in name:
            return min(self.constants["POKEMON_NAME_LENGTH"], limit)
        if "MOVE" in name:
            return min(self.constants["MOVE_NAME_LENGTH"], limit)
        if "ITEM" in name:
            return min(self.constants["ITEM_NAME_LENGTH"], limit)
        if name.startswith("STR_VAR") or name.startswith("B_BUFF") or name.startswith("B_COPY_VAR"):
            return limit
        if name == "KUN":
            return min(2, limit)
        if name in {"VERSION", "AQUA", "MAGMA", "ARCHIE", "MAXIE", "KYOGRE", "GROUDON", "REGION"}:
            return min(10, limit)
        if name.startswith("B_"):
            return limit
        return 0

    def placeholder_width(self, name: str, settings: AutoFormatSettings) -> int:
        if not settings.safe_placeholders:
            return 0
        static_values = self.static_placeholders.get(name)
        if static_values:
            return max(self.measure(value, settings) for value in static_values)
        chars = self.dynamic_placeholder_chars(name, settings)
        return chars * self.japanese_width(settings) if chars else 0

    def placeholder_units(self, name: str, settings: AutoFormatSettings) -> int:
        if not settings.safe_placeholders:
            return 0
        static_values = self.static_placeholders.get(name)
        if static_values:
            return max(self.visible_units(value, settings) for value in static_values)
        return self.dynamic_placeholder_chars(name, settings)

    @staticmethod
    def control_number(body: str) -> int:
        match = re.search(r"[-+]?\d+", body)
        return max(0, int(match.group(0))) if match else 0

    def brace_width(self, token: str, settings: AutoFormatSettings) -> int:
        body = token[1:-1].strip()
        name = body.split()[0] if body else ""
        if name in self.ZERO_WIDTH_CONTROLS:
            return 0
        if name in self.WIDTH_CONTROLS:
            return self.control_number(body)
        return self.placeholder_width(name, settings)

    def token_width(self, token: str, settings: AutoFormatSettings) -> int:
        if token in {"\n", r"\n"}:
            return 0
        if token.startswith("{") and token.endswith("}"):
            return self.brace_width(token, settings)
        if len(token) == 2 and token.startswith("\\"):
            return self.japanese_width(settings)
        char = token[0]
        if ord(char) < 0x80:
            return self.ascii_width(char) if settings.halfwidth_ascii else self.japanese_width(settings)
        return self.japanese_width(settings)

    def iter_tokens(self, text: str) -> Iterable[tuple[str, int, int]]:
        pos = 0
        while pos < len(text):
            if text.startswith(r"\n", pos):
                yield r"\n", pos, pos + 2
                pos += 2
                continue
            char = text[pos]
            if char == "\n":
                yield "\n", pos, pos + 1
                pos += 1
                continue
            if char == "\\" and pos + 1 < len(text):
                yield text[pos:pos + 2], pos, pos + 2
                pos += 2
                continue
            if char == "{":
                end = text.find("}", pos + 1)
                if end > pos:
                    yield text[pos:end + 1], pos, end + 1
                    pos = end + 1
                    continue
            yield char, pos, pos + 1
            pos += 1

    def measure(self, text: str, settings: AutoFormatSettings) -> int:
        width = 0
        max_width = 0
        for token, _start, _end in self.iter_tokens(text):
            if token in {"\n", r"\n"}:
                max_width = max(max_width, width)
                width = 0
            else:
                width += self.token_width(token, settings)
        return max(max_width, width)

    def visible_units(self, text: str, settings: AutoFormatSettings) -> int:
        total = 0
        for token, _start, _end in self.iter_tokens(text):
            if token in {"\n", r"\n"}:
                continue
            if token.startswith("{") and token.endswith("}"):
                name = token[1:-1].strip().split()[0] if token[1:-1].strip() else ""
                total += self.placeholder_units(name, settings)
            elif not (token.startswith("\\") and len(token) == 2):
                total += 1
        return total


class TextAutoFormatter:
    def __init__(self, root: Path) -> None:
        self.model = TextWidthModel(root)

    @staticmethod
    def has_existing_break(text: str) -> bool:
        return "\n" in text or r"\n" in text

    def format_text(self, text: str, settings: AutoFormatSettings) -> str:
        if settings.skip_existing_breaks and self.has_existing_break(text):
            return text
        pieces = re.split(r"(\\n|\n)", text)
        changed = False
        for index in range(0, len(pieces), 2):
            formatted = self.format_segment(pieces[index], settings)
            changed = changed or formatted != pieces[index]
            pieces[index] = formatted
        return "".join(pieces) if changed else text

    def format_segment(self, text: str, settings: AutoFormatSettings) -> str:
        if not text.strip() or self.model.measure(text, settings) <= settings.max_width:
            return text
        lines: list[str] = []
        remaining = text
        guard = 0
        while remaining and self.model.measure(remaining, settings) > settings.max_width and guard < 16:
            guard += 1
            candidates = []
            for index, char in enumerate(remaining):
                if char not in {" ", "　"}:
                    continue
                visible = self.model.visible_units(remaining[:index], settings)
                if settings.range_start <= visible <= settings.range_end:
                    candidates.append(index)
            if not candidates:
                break
            fitting = [index for index in candidates if self.model.measure(remaining[:index], settings) <= settings.max_width]
            break_at = fitting[-1] if fitting else candidates[0]
            head = remaining[:break_at].rstrip()
            tail = remaining[break_at + 1:].lstrip()
            if not head or not tail:
                break
            lines.append(head)
            remaining = tail
        if not lines:
            return text
        lines.append(remaining)
        return "\n".join(lines)


class AutoFormatDialog(QDialog):
    PRESETS = [
        ("Default 14-20 / 208px", {"max_width": 208, "range_start": 14, "range_end": 20, "halfwidth_ascii": True, "skip_existing_breaks": True, "placeholder_max_chars": 20}),
        ("Short 10-16 / 160px", {"max_width": 160, "range_start": 10, "range_end": 16, "halfwidth_ascii": True, "skip_existing_breaks": True, "placeholder_max_chars": 16}),
        ("Dialog 12-18 / 184px", {"max_width": 184, "range_start": 12, "range_end": 18, "halfwidth_ascii": True, "skip_existing_breaks": True, "placeholder_max_chars": 18}),
        ("Wide 18-26 / 224px", {"max_width": 224, "range_start": 18, "range_end": 26, "halfwidth_ascii": True, "skip_existing_breaks": True, "placeholder_max_chars": 20}),
        ("Reflow existing breaks", {"max_width": 208, "range_start": 14, "range_end": 20, "halfwidth_ascii": True, "skip_existing_breaks": False, "placeholder_max_chars": 20}),
        ("Full-width ASCII", {"max_width": 208, "range_start": 14, "range_end": 20, "halfwidth_ascii": False, "skip_existing_breaks": True, "placeholder_max_chars": 20}),
    ]

    def __init__(self, parent: QWidget, owner: object, title: str) -> None:
        super().__init__(parent)
        self.owner = owner
        self.changes: list[AutoFormatChange] = []
        self.setWindowTitle(title); self.resize(980, 720)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem("Custom", None)
        for label, values in self.PRESETS:
            self.preset.addItem(label, values)
        self.scope = QComboBox()
        self.scope.addItem("現在選択中の文字列", "current")
        self.scope.addItem("現在開いているファイル", "file")
        self.scope.addItem("検索結果に一致した文字列", "search")
        self.scope.addItem("選択範囲のみ", "selection")
        self.font = QComboBox()
        for font in ("FONT_NORMAL", "FONT_SMALL", "FONT_NARROW", "FONT_NARROWER"):
            self.font.addItem(font, font)
        self.max_width = QSpinBox(); self.max_width.setRange(16, 240); self.max_width.setValue(208); self.max_width.setSuffix(" px")
        self.range_start = QSpinBox(); self.range_start.setRange(1, 999); self.range_start.setValue(14)
        self.range_end = QSpinBox(); self.range_end.setRange(1, 999); self.range_end.setValue(20)
        self.placeholder_max_chars = QSpinBox(); self.placeholder_max_chars.setRange(1, 99); self.placeholder_max_chars.setValue(20)
        self.skip_breaks = QCheckBox("既に \\n がある文字列は処理しない"); self.skip_breaks.setChecked(True)
        self.halfwidth_ascii = QCheckBox("英数字・記号を半角幅で扱う"); self.halfwidth_ascii.setChecked(True)
        self.safe_placeholders = QCheckBox("{PLAYER} などの制御変数を最大幅で見積もる"); self.safe_placeholders.setChecked(True)
        form.addRow("対象", self.scope); form.addRow("フォント", self.font); form.addRow("最大幅", self.max_width)
        form.addRow("空白探索 開始文字目", self.range_start); form.addRow("空白探索 終了文字目", self.range_end)
        form.addRow(self.skip_breaks); form.addRow(self.halfwidth_ascii); form.addRow(self.safe_placeholders)
        form.insertRow(0, "Preset", self.preset)
        form.addRow("Placeholder max chars", self.placeholder_max_chars)
        layout.addLayout(form)
        preview_button = QPushButton("差分プレビュー"); preview_button.clicked.connect(self.preview_changes); layout.addWidget(preview_button)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); layout.addWidget(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("適用")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.preset.currentIndexChanged.connect(self.apply_preset)
        for control in (self.scope, self.font):
            control.currentIndexChanged.connect(self.preview_changes)
        for control in (self.max_width, self.range_start, self.range_end, self.placeholder_max_chars):
            control.valueChanged.connect(self.preview_changes)
        for control in (self.skip_breaks, self.halfwidth_ascii, self.safe_placeholders):
            control.stateChanged.connect(self.preview_changes)
        self.preview_changes()

    def apply_preset(self) -> None:
        values = self.preset.currentData()
        if not isinstance(values, dict):
            self.preview_changes()
            return
        self.max_width.setValue(int(values.get("max_width", self.max_width.value())))
        self.range_start.setValue(int(values.get("range_start", self.range_start.value())))
        self.range_end.setValue(int(values.get("range_end", self.range_end.value())))
        self.placeholder_max_chars.setValue(int(values.get("placeholder_max_chars", self.placeholder_max_chars.value())))
        self.halfwidth_ascii.setChecked(bool(values.get("halfwidth_ascii", self.halfwidth_ascii.isChecked())))
        self.skip_breaks.setChecked(bool(values.get("skip_existing_breaks", self.skip_breaks.isChecked())))
        self.preview_changes()

    def settings(self) -> AutoFormatSettings:
        start = min(self.range_start.value(), self.range_end.value())
        end = max(self.range_start.value(), self.range_end.value())
        return AutoFormatSettings(
            self.scope.currentData(), self.font.currentData(), self.max_width.value(),
            start, end, self.skip_breaks.isChecked(), self.halfwidth_ascii.isChecked(), self.safe_placeholders.isChecked(),
            self.placeholder_max_chars.value(),
        )

    def preview_changes(self) -> None:
        self.changes = self.owner.preview_auto_format(self.settings())  # type: ignore[attr-defined]
        if not self.changes:
            self.preview.setPlainText("No changes.")
            return
        chunks = []
        for change in self.changes:
            diff = difflib.unified_diff(change.before.splitlines(), change.after.splitlines(), fromfile=change.label + " before", tofile=change.label + " after", lineterm="")
            chunks.append("\n".join(diff))
        self.preview.setPlainText("\n\n".join(chunks))

    def accept(self) -> None:
        self.preview_changes()
        if self.changes:
            self.owner.apply_auto_format(self.changes)  # type: ignore[attr-defined]
        super().accept()


@dataclass
class TextEntry:
    path: Path
    file_name: str
    line: int
    macro: str
    symbol: str
    start: int
    end: int
    original: str
    current: str

    @property
    def dirty(self) -> bool:
        return self.original != self.current


@dataclass
class TextVariableEntry:
    placeholder: str
    variant: str
    symbol: str
    description: str
    path: Path | None
    file_name: str
    line: int
    start: int
    end: int
    original: str
    current: str
    editable: bool

    @property
    def dirty(self) -> bool:
        return self.editable and self.current != self.original


def infer_symbol(text: str, macro_pos: int) -> str:
    context = text[max(0, macro_pos - 700):macro_pos]
    found = list(re.finditer(r"\b(gText_[A-Za-z0-9_]+)\b", context))
    if found:
        return found[-1].group(1)
    field = list(re.finditer(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*$", context))
    if field:
        return "." + field[-1].group(1)
    return "(anonymous)"


def find_text_entries(root: Path) -> tuple[list[TextEntry], dict[Path, str]]:
    entries: list[TextEntry] = []
    contents: dict[Path, str] = {}
    macro_re = re.compile(r"(?<![A-Za-z0-9_])(COMPOUND_STRING|_)\s*\(")
    for base_name in ("src", "include"):
        base = root / base_name
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.suffix in TEXT_EXTENSIONS and p.is_file()):
            try:
                source = read_utf8(path)
            except UnicodeDecodeError:
                continue
            if "COMPOUND_STRING" not in source and "_(" not in source and "_ (" not in source:
                continue
            contents[path] = source
            used: set[tuple[int, int]] = set()
            for match in macro_re.finditer(source):
                parsed = parse_c_strings(source, match.end())
                if not parsed:
                    continue
                start, end, value = parsed
                if (start, end) in used:
                    continue
                used.add((start, end))
                entries.append(TextEntry(
                    path, rel(root, path), source.count("\n", 0, start) + 1,
                    match.group(1), infer_symbol(source, match.start()), start, end, value, value,
                ))
    return entries, contents


class TranslationTextPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__()
        self.window = window
        self.entries: list[TextEntry] = []
        self.contents: dict[Path, str] = {}
        self.current: TextEntry | None = None
        self.loading = False
        self.search = QLineEdit()
        self.file_filter = QLineEdit()
        self.untranslated = QCheckBox()
        self.changed = QCheckBox()
        self.count = QLabel()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["*", "Symbol", "Kind", "Text", "File", "Line"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.select_entry)
        self.original = QPlainTextEdit(); self.original.setReadOnly(True)
        self.editor = QPlainTextEdit(); self.editor.textChanged.connect(self.edit_changed)
        self.char_count = QLabel("0")
        self.build()

    def build(self) -> None:
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search.setPlaceholderText("Search")
        self.file_filter.setPlaceholderText("File name")
        for control in (self.search, self.file_filter):
            control.textChanged.connect(self.refresh)
            filters.addWidget(control)
        self.untranslated.stateChanged.connect(self.refresh)
        self.changed.stateChanged.connect(self.refresh)
        filters.addWidget(self.untranslated); filters.addWidget(self.changed)
        clear = QPushButton(); clear.clicked.connect(self.clear_filters); filters.addWidget(clear)
        self._clear_button = clear
        layout.addLayout(filters)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        detail = QWidget(); detail_layout = QVBoxLayout(detail)
        self.detail = QLabel(); self.detail.setWordWrap(True); detail_layout.addWidget(self.detail)
        self.original_label = QLabel(); detail_layout.addWidget(self.original_label)
        detail_layout.addWidget(self.original)
        self.edited_label = QLabel(); detail_layout.addWidget(self.edited_label)
        detail_layout.addWidget(self.editor)
        controls = QHBoxLayout()
        revert = QPushButton("Revert"); revert.clicked.connect(self.revert); controls.addWidget(revert)
        copy_path = QPushButton("Copy path"); copy_path.clicked.connect(self.copy_path); controls.addWidget(copy_path)
        controls.addStretch(); controls.addWidget(QLabel("Chars:")); controls.addWidget(self.char_count)
        detail_layout.addLayout(controls)
        split.addWidget(detail); split.setSizes([800, 500]); layout.addWidget(split)
        buttons = QHBoxLayout()
        export = QPushButton(); export.clicked.connect(self.export_csv); self._export = export
        import_button = QPushButton(); import_button.clicked.connect(self.import_csv); self._import = import_button
        format_button = QPushButton("自動整形"); format_button.clicked.connect(self.open_auto_format); self._format = format_button
        save = QPushButton(); save.clicked.connect(self.save); self._save = save
        buttons.addWidget(export); buttons.addWidget(import_button); buttons.addWidget(format_button); buttons.addStretch(); buttons.addWidget(save)
        layout.addLayout(buttons)
        self.retranslate()

    def retranslate(self) -> None:
        lang = self.window.lang
        self.untranslated.setText(tr("untranslated", lang)); self.changed.setText(tr("dirty", lang))
        self._clear_button.setText(tr("clear", lang)); self.original_label.setText(tr("original", lang))
        self.edited_label.setText(tr("edited", lang)); self._export.setText(tr("export", lang))
        self._import.setText(tr("import", lang)); self._format.setText("自動整形" if lang == "ja" else "Auto Format"); self._save.setText(tr("save", lang))

    def load(self) -> None:
        if not self.window.root_valid():
            return
        self.entries, self.contents = find_text_entries(self.window.root)
        self.current = None; self.original.clear(); self.editor.clear(); self.refresh()
        self.window.status(f"Scanned {len(self.entries)} text entries")

    def filtered(self) -> list[TextEntry]:
        query = self.search.text().casefold().strip(); file_name = self.file_filter.text().casefold().strip()
        result = []
        for entry in self.entries:
            haystack = "\n".join((entry.symbol, entry.macro, entry.current, entry.file_name)).casefold()
            untranslated = entry.current == entry.original and bool(re.search(r"[A-Za-z]", entry.current))
            if query and query not in haystack: continue
            if file_name and file_name not in entry.file_name.casefold(): continue
            if self.untranslated.isChecked() and not untranslated: continue
            if self.changed.isChecked() and not entry.dirty: continue
            result.append(entry)
        return result

    def refresh(self) -> None:
        visible = self.filtered(); selected = self.current
        self.table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            values = ["*" if entry.dirty else "", entry.symbol, entry.macro,
                      entry.current.replace("\n", r"\n")[:180], entry.file_name, str(entry.line)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, entry); self.table.setItem(row, column, item)
            if entry is selected:
                self.table.selectRow(row)
        dirty = sum(item.dirty for item in self.entries)
        self.count.setText(f"{len(visible)} / {len(self.entries)} {tr('results', self.window.lang)} | Dirty: {dirty}")
        self.window.status(self.count.text())

    def clear_filters(self) -> None:
        self.search.clear(); self.file_filter.clear(); self.untranslated.setChecked(False); self.changed.setChecked(False)

    def select_entry(self) -> None:
        selected = self.table.selectedItems()
        if not selected: return
        entry = selected[0].data(Qt.ItemDataRole.UserRole)
        if entry is self.current: return
        self.current = entry; self.loading = True
        self.detail.setText(f"{entry.file_name}:{entry.line}\n{entry.symbol} [{entry.macro}]")
        self.original.setPlainText(entry.original); self.editor.setPlainText(entry.current); self.loading = False
        self.char_count.setText(str(len(entry.current)))

    def edit_changed(self) -> None:
        if self.loading or not self.current: return
        self.current.current = self.editor.toPlainText(); self.char_count.setText(str(len(self.current.current))); self.refresh()

    def revert(self) -> None:
        if self.current:
            self.current.current = self.current.original; self.loading = True; self.editor.setPlainText(self.current.current); self.loading = False; self.refresh()

    def copy_path(self) -> None:
        if self.current:
            QApplication.clipboard().setText(str(self.current.path)); self.window.status(str(self.current.path))

    def save(self) -> None:
        dirty = [entry for entry in self.entries if entry.dirty]
        if not dirty: return self.window.status("No translation changes")
        by_path: dict[Path, list[TextEntry]] = {}
        for entry in dirty: by_path.setdefault(entry.path, []).append(entry)
        try:
            for path, entries in by_path.items():
                disk = read_utf8(path)
                if disk != self.contents[path]:
                    raise RuntimeError(f"{rel(self.window.root, path)} changed on disk; reload first.")
                new = disk
                for entry in sorted(entries, key=lambda item: item.start, reverse=True):
                    new = new[:entry.start] + quote_c_text(entry.current) + new[entry.end:]
                write_with_backup(path, new)
        except Exception as error:
            QMessageBox.critical(self, "Save failed", str(error)); return
        self.load(); self.window.status(f"Saved {len(dirty)} translations with backups")

    def show_diff(self) -> None:
        if not self.current:
            return
        DiffDialog(self, f"Diff: {self.current.symbol}", self.current.original, self.current.current).exec()

    def open_auto_format(self) -> None:
        AutoFormatDialog(self, self, "テキスト自動整形").exec()

    def selected_text_range(self) -> tuple[int, int, str] | None:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return None
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        return start, end, cursor.selectedText().replace("\u2029", "\n")

    def format_entries_for_scope(self, scope: str) -> list[TextEntry]:
        if scope == "current":
            return [self.current] if self.current else []
        if scope == "file":
            return [entry for entry in self.entries if self.current and entry.path == self.current.path]
        if scope == "search":
            if not self.search.text().strip() and not self.file_filter.text().strip() and not self.untranslated.isChecked() and not self.changed.isChecked():
                return []
            return self.filtered()
        return []

    def preview_auto_format(self, settings: AutoFormatSettings) -> list[AutoFormatChange]:
        formatter = TextAutoFormatter(self.window.root)
        changes: list[AutoFormatChange] = []
        if settings.scope == "selection":
            selected = self.selected_text_range()
            if not self.current or not selected:
                return []
            start, end, before = selected
            after = formatter.format_text(before, settings)
            return [AutoFormatChange(f"{self.current.symbol} selection", before, after, self.current, (start, end))] if after != before else []
        for entry in self.format_entries_for_scope(settings.scope):
            after = formatter.format_text(entry.current, settings)
            if after != entry.current:
                changes.append(AutoFormatChange(f"{entry.symbol} ({entry.file_name}:{entry.line})", entry.current, after, entry))
        return changes

    def apply_auto_format(self, changes: list[AutoFormatChange]) -> None:
        for change in changes:
            if change.selection and change.target is self.current:
                start, end = change.selection
                cursor = self.editor.textCursor()
                cursor.setPosition(start); cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor); cursor.insertText(change.after)
            elif isinstance(change.target, TextEntry):
                change.target.current = change.after
        if self.current:
            self.loading = True; self.editor.setPlainText(self.current.current); self.loading = False
        self.refresh(); self.window.status(f"Auto formatted {len(changes)} text item(s)")

    def export_csv(self) -> None:
        if not self.entries: return
        name, _ = QFileDialog.getSaveFileName(self, "Export CSV", "translations.csv", "CSV (*.csv)")
        if not name: return
        with open(name, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["file", "line", "macro", "symbol", "original", "current"])
            writer.writeheader()
            for entry in self.filtered(): writer.writerow({"file": entry.file_name, "line": entry.line, "macro": entry.macro, "symbol": entry.symbol, "original": entry.original, "current": entry.current})
        self.window.status(f"Exported CSV: {name}")

    def import_csv(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV (*.csv)")
        if not name: return
        index = {(e.file_name, e.line, e.macro, e.symbol, e.original): e for e in self.entries}; imported = 0
        try:
            with open(name, encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    key = (row["file"], int(row["line"]), row["macro"], row["symbol"], row["original"])
                    if key in index: index[key].current = row["current"]; imported += 1
        except (OSError, KeyError, ValueError) as error:
            QMessageBox.critical(self, "Import failed", str(error)); return
        self.refresh(); self.window.status(f"Imported {imported} translations")


@dataclass
class EventStringPart:
    start: int
    end: int


TextIdentity = tuple[str, str, str]


@dataclass
class EventTextEntry:
    path: Path
    file_name: str
    line: int
    symbol: str
    parts: list[EventStringPart]
    has_terminator: bool
    supported: bool
    unsupported_reason: str
    original: str
    current: str

    @property
    def dirty(self) -> bool:
        return self.original != self.current

    @property
    def identity(self) -> TextIdentity:
        return ("INC", self.file_name, self.symbol)


@dataclass
class PoryTextEntry:
    path: Path
    file_name: str
    line: int
    symbol: str
    original: str
    current: str

    @property
    def dirty(self) -> bool:
        return False

    @property
    def identity(self) -> TextIdentity:
        return ("PORY", self.file_name, self.symbol)


@dataclass
class EventScript:
    path: Path
    file_name: str
    label: str
    line: int
    body: str
    uses: list["EventTextUse"] = field(default_factory=list)


@dataclass
class EventTextUse:
    script: EventScript
    command: str
    symbol: str
    line: int
    target_id: TextIdentity | None = None
    resolution: str = ""


EVENT_LABEL_RE = re.compile(r"(?m)^([A-Za-z_][A-Za-z0-9_]*):(?::)?\s*(?:@.*)?$")
EVENT_STRING_RE = re.compile(r"(?m)^(?P<indent>[ \t]*)\.string\b")
EVENT_TEXT_COMMAND_RE = re.compile(r"(?m)^[ \t]*(msgbox|message|yesnobox)\s+([A-Za-z_][A-Za-z0-9_]*)")


def event_source_paths(root: Path) -> list[Path]:
    excluded = {".git", "workspace", "build", "dist"}
    return sorted(
        (path for path in root.rglob("*.inc") if path.is_file() and not excluded.intersection(path.relative_to(root).parts)),
        key=lambda path: path.as_posix().casefold(),
    )


PORY_TEXT_RE = re.compile(r"(?m)^\s*text(?:\([^)]*\))?\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{")


def find_pory_text_records(root: Path) -> list[PoryTextEntry]:
    """Index Poryscript text labels so INC/PORY name collisions remain visible."""
    excluded = {".git", "workspace", "build", "dist"}; records: list[PoryTextEntry] = []
    for path in sorted((item for item in root.rglob("*.pory") if item.is_file() and not excluded.intersection(item.relative_to(root).parts)), key=lambda item: item.as_posix().casefold()):
        try: source = read_utf8(path)
        except UnicodeDecodeError: continue
        for match in PORY_TEXT_RE.finditer(source):
            block_end = balanced_end(source, source.find("{", match.start(), match.end()))
            if block_end is None: continue
            block = source[match.end():block_end - 1]; values: list[str] = []; position = 0
            while position < len(block):
                quote = block.find('"', position)
                if quote < 0: break
                parsed = parse_c_strings(block, quote)
                if not parsed: break
                values.append(parsed[2]); position = parsed[1]
            text = "".join(values)
            records.append(PoryTextEntry(path, rel(root, path), source.count("\n", 0, match.start()) + 1, match.group(1), text, text))
    return records


def find_event_records(root: Path) -> tuple[list[EventScript], list[EventTextEntry], dict[Path, str]]:
    """Collect event labels, message commands, and data-side .string labels."""
    scripts: list[EventScript] = []; texts: list[EventTextEntry] = []; contents: dict[Path, str] = {}
    for path in event_source_paths(root):
        try: source = read_utf8(path)
        except UnicodeDecodeError: continue
        contents[path] = source; labels = list(EVENT_LABEL_RE.finditer(source))
        for index, label_match in enumerate(labels):
            label = label_match.group(1); block_start = label_match.end(); block_end = labels[index + 1].start() if index + 1 < len(labels) else len(source)
            directives = list(EVENT_STRING_RE.finditer(source, block_start, block_end)); string_parts: list[EventStringPart] = []; values: list[str] = []
            for directive in directives:
                parsed = parse_c_strings(source, directive.end())
                if parsed and parsed[1] <= block_end:
                    start, end, value = parsed; string_parts.append(EventStringPart(start, end)); values.append(value)
            if directives:
                raw_text = "".join(values); supported = len(directives) == len(string_parts); reason = "" if supported else "複雑な .string 定義"
                has_terminator = raw_text.endswith("$")
                display_text = raw_text[:-1] if has_terminator else raw_text
                texts.append(EventTextEntry(
                    path, rel(root, path), source.count("\n", 0, label_match.start()) + 1, label, string_parts,
                    has_terminator, supported, reason, display_text, display_text,
                ))
            commands = list(EVENT_TEXT_COMMAND_RE.finditer(source, block_start, block_end))
            if "EventScript" not in label and not label.startswith("EventScript_") and not commands:
                continue
            script_line = source.count("\n", 0, label_match.start()) + 1
            script = EventScript(path, rel(root, path), label, script_line, source[block_start:block_end]); scripts.append(script)
            for command in commands:
                script.uses.append(EventTextUse(
                    script, command.group(1), command.group(2), source.count("\n", 0, command.start()) + 1,
                ))
    return scripts, texts, contents


class LegacyEventBrowserPanel(QWidget):
    """Translation-oriented browser for event script labels and their text."""
    def __init__(self, window: "Workbench", translation: TranslationTextPanel) -> None:
        super().__init__(); self.window = window; self.translation = translation; self.scripts: list[EventScript] = []; self.data_texts: list[EventTextEntry] = []; self.data_contents: dict[Path, str] = {}; self.texts: dict[str, TextEntry | EventTextEntry] = {}; self.current_target: TextEntry | EventTextEntry | None = None; self.loading = False
        layout = QVBoxLayout(self); filters = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("スクリプトラベル・テキスト・ファイルを検索"); self.search.textChanged.connect(self.refresh_tree); clear = QPushButton("クリア"); clear.clicked.connect(self.search.clear); self.count = QLabel(); filters.addWidget(self.search); filters.addWidget(clear); filters.addWidget(self.count); filters.addStretch(); layout.addLayout(filters)
        split = QSplitter(Qt.Orientation.Horizontal); self.tree = QTreeWidget(); self.tree.setHeaderLabels(["イベント構造", "種類"]); self.tree.itemSelectionChanged.connect(self.select_tree_item); split.addWidget(self.tree)
        detail = QWidget(); detail_layout = QVBoxLayout(detail); self.detail = QLabel("イベントまたはテキストを選択してください。"); self.detail.setWordWrap(True); detail_layout.addWidget(self.detail); detail_layout.addWidget(QLabel("イベント本文 / 相互参照")); self.context = QPlainTextEdit(); self.context.setReadOnly(True); self.context.setMaximumHeight(180); detail_layout.addWidget(self.context); detail_layout.addWidget(QLabel("元のテキスト")); self.original = QPlainTextEdit(); self.original.setReadOnly(True); self.original.setMaximumHeight(120); detail_layout.addWidget(self.original); detail_layout.addWidget(QLabel("翻訳テキスト")); self.editor = QPlainTextEdit(); self.editor.setEnabled(False); self.editor.textChanged.connect(self.edit_changed); detail_layout.addWidget(self.editor); references_label = QLabel("参照イベント / 使用テキスト"); detail_layout.addWidget(references_label); self.references = QListWidget(); self.references.itemDoubleClicked.connect(self.open_reference); detail_layout.addWidget(self.references); controls = QHBoxLayout(); self.revert_button = QPushButton("元に戻す"); self.revert_button.clicked.connect(self.revert); self.save_button = QPushButton("保存"); self.save_button.clicked.connect(self.save); self.diff_button = QPushButton("差分"); self.diff_button.clicked.connect(self.show_diff); controls.addWidget(self.revert_button); controls.addWidget(self.diff_button); controls.addStretch(); controls.addWidget(self.save_button); detail_layout.addLayout(controls); split.addWidget(detail); split.setSizes([760, 650]); layout.addWidget(split)

    def retranslate(self) -> None:
        # Labels are intentionally explicit because this is a translation workflow view.
        self.save_button.setText(tr("save", self.window.lang))

    def load(self) -> None:
        if not self.window.root_valid(): return
        self.scripts, self.data_texts, self.data_contents = find_event_records(self.window.root)
        self.texts = {entry.symbol: entry for entry in self.data_texts}
        for entry in self.translation.entries:
            if entry.symbol != "(anonymous)": self.texts.setdefault(entry.symbol, entry)
        self.current_target = None; self.original.clear(); self.editor.clear(); self.editor.setEnabled(False); self.references.clear(); self.refresh_tree(); self.window.status(f"イベント: {len(self.scripts)} scripts, {len(self.data_texts)} data text labels")

    def target(self, use: EventTextUse) -> TextEntry | EventTextEntry | None:
        return self.texts.get(use.symbol)

    def script_matches(self, script: EventScript, query: str) -> bool:
        if not query: return True
        values = [script.label, script.file_name]
        for use in script.uses:
            text = self.target(use); values.extend((use.command, use.symbol, text.current if text else ""))
        return query in "\n".join(values).casefold()

    def refresh_tree(self) -> None:
        query = self.search.text().casefold().strip(); selected_target = self.current_target.symbol if self.current_target else ""; self.tree.blockSignals(True); self.tree.clear(); files: dict[str, QTreeWidgetItem] = {}; visible = 0
        for script in self.scripts:
            if not self.script_matches(script, query): continue
            visible += 1; file_item = files.get(script.file_name)
            if file_item is None:
                file_item = QTreeWidgetItem([script.file_name, "file"]); files[script.file_name] = file_item; self.tree.addTopLevelItem(file_item)
            script_item = QTreeWidgetItem([script.label, f"label ({len(script.uses)})"]); script_item.setData(0, Qt.ItemDataRole.UserRole, ("script", script)); file_item.addChild(script_item)
            for use in script.uses:
                text = self.target(use); preview = text.current.replace("\n", r"\n")[:92] if text else "<テキスト未解決>"; child = QTreeWidgetItem([f"{use.command}: {use.symbol}  {preview}", "text"]); child.setData(0, Qt.ItemDataRole.UserRole, ("use", use)); script_item.addChild(child)
                if selected_target and use.symbol == selected_target: self.tree.setCurrentItem(child)
            file_item.setExpanded(True)
        self.tree.blockSignals(False); self.count.setText(f"{visible} scripts / {len(self.data_texts)} data texts")

    def select_tree_item(self) -> None:
        selected = self.tree.selectedItems()
        if not selected: return
        payload = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not payload: return
        kind, value = payload
        if kind == "script": self.show_script(value)
        elif kind == "use": self.show_use(value)

    def show_script(self, script: EventScript) -> None:
        self.current_target = None; self.loading = True; self.detail.setText(f"{script.file_name}:{script.line}\n{script.label}"); self.context.setPlainText(script.body.strip()); self.original.clear(); self.editor.clear(); self.editor.setEnabled(False); self.loading = False; self.references.clear()
        for use in script.uses:
            text = self.target(use); preview = text.current.replace("\n", r"\n")[:110] if text else "<テキスト未解決>"; item = QListWidgetItem(f"{use.command}: {use.symbol}  {preview}"); item.setData(Qt.ItemDataRole.UserRole, use); self.references.addItem(item)

    def show_use(self, use: EventTextUse) -> None:
        target = self.target(use)
        if target is None:
            self.current_target = None; self.detail.setText(f"{use.script.label}:{use.line}\n{use.command} {use.symbol} (テキスト定義を見つけられません)"); self.context.setPlainText(use.script.body.strip()); self.original.clear(); self.editor.clear(); self.editor.setEnabled(False); self.references.clear(); return
        self.current_target = target; self.loading = True; self.detail.setText(f"{target.file_name}:{target.line}\n{use.command} {target.symbol}"); self.context.setPlainText(use.script.body.strip()); self.original.setPlainText(target.original); self.editor.setEnabled(True); self.editor.setPlainText(target.current); self.loading = False; self.references.clear()
        for related in (candidate for script in self.scripts for candidate in script.uses if candidate.symbol == target.symbol):
            item = QListWidgetItem(f"{related.script.file_name}:{related.line}  {related.script.label} ({related.command})"); item.setData(Qt.ItemDataRole.UserRole, related.script); self.references.addItem(item)

    def open_reference(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, EventTextUse): self.show_use(value)
        elif isinstance(value, EventScript): self.show_script(value)

    def edit_changed(self) -> None:
        if self.loading or not self.current_target: return
        self.current_target.current = self.editor.toPlainText(); self.refresh_tree(); self.window.status(f"Edited event text: {self.current_target.symbol}")

    def revert(self) -> None:
        if not self.current_target: return
        self.current_target.current = self.current_target.original; self.loading = True; self.editor.setPlainText(self.current_target.current); self.loading = False; self.refresh_tree()

    def save_data_texts(self) -> int:
        dirty = [entry for entry in self.data_texts if entry.dirty]
        if not dirty: return 0
        grouped: dict[Path, list[EventTextEntry]] = {}
        for entry in dirty: grouped.setdefault(entry.path, []).append(entry)
        for path, entries in grouped.items():
            disk = read_utf8(path)
            if disk != self.data_contents[path]: raise RuntimeError(f"{rel(self.window.root, path)} changed on disk; reload first.")
            updated = disk
            for entry in sorted(entries, key=lambda item: item.start, reverse=True):
                updated = updated[:entry.start] + f"{entry.indent}.string {quote_c_text(entry.current)}" + updated[entry.end:]
            write_with_backup(path, updated)
        return len(dirty)

    def save(self) -> None:
        try: data_count = self.save_data_texts()
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Event text save failed", str(error)); return
        source_count = sum(entry.dirty for entry in self.translation.entries)
        if source_count: self.translation.save()
        self.load(); self.window.status(f"Saved {data_count} event texts and {source_count} source texts with backups")

    def show_diff(self) -> None:
        if self.current_target: DiffDialog(self, f"Diff: {self.current_target.symbol}", self.current_target.original, self.current_target.current).exec()


TextTarget = TextEntry | EventTextEntry | PoryTextEntry


class EventBrowserPanel(QWidget):
    """INC text manager plus event/text cross references for translation work."""
    def __init__(self, window: "Workbench", translation: TranslationTextPanel) -> None:
        super().__init__(); self.window = window; self.translation = translation; self.scripts: list[EventScript] = []; self.inc_texts: list[EventTextEntry] = []; self.pory_texts: list[PoryTextEntry] = []; self.inc_contents: dict[Path, str] = {}; self.definitions: dict[TextIdentity, TextTarget] = {}; self.symbol_index: dict[str, list[TextIdentity]] = {}; self.uses_by_target: dict[TextIdentity, list[EventTextUse]] = {}; self.text_rows: list[TextIdentity] = []; self.current_id: TextIdentity | None = None; self.loading = False; self.edited_source_ids: set[TextIdentity] = set()
        layout = QVBoxLayout(self); filters = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("ラベル名・本文・ファイル・イベントを検索"); self.search.textChanged.connect(self.refresh); clear = QPushButton("クリア"); clear.clicked.connect(self.search.clear); self.count = QLabel(); filters.addWidget(self.search); filters.addWidget(clear); filters.addWidget(self.count); filters.addStretch(); layout.addLayout(filters)
        split = QSplitter(Qt.Orientation.Horizontal); left = QSplitter(Qt.Orientation.Vertical); self.text_table = QTableWidget(0, 7); self.text_table.setHorizontalHeaderLabels(["種別", "ラベル", "本文", "ファイル", "行", "使用", "状態"]); self.text_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.text_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.text_table.itemSelectionChanged.connect(self.select_text_row); left.addWidget(self.text_table); self.tree = QTreeWidget(); self.tree.setHeaderLabels(["イベント構造", "種類"]); self.tree.itemSelectionChanged.connect(self.select_tree_item); left.addWidget(self.tree); left.setSizes([460, 420]); split.addWidget(left)
        detail = QWidget(); detail_layout = QVBoxLayout(detail); self.detail = QLabel("テキストまたはイベントを選択してください。"); self.detail.setWordWrap(True); detail_layout.addWidget(self.detail); detail_layout.addWidget(QLabel("イベント本文 / 相互参照")); self.context = QPlainTextEdit(); self.context.setReadOnly(True); self.context.setMaximumHeight(160); detail_layout.addWidget(self.context); detail_layout.addWidget(QLabel("元のテキスト（INC の末尾 $ は非表示）")); self.original = QPlainTextEdit(); self.original.setReadOnly(True); self.original.setMaximumHeight(110); detail_layout.addWidget(self.original); detail_layout.addWidget(QLabel("翻訳テキスト")); self.editor = QPlainTextEdit(); self.editor.setEnabled(False); self.editor.textChanged.connect(self.edit_changed); detail_layout.addWidget(self.editor); detail_layout.addWidget(QLabel("使用箇所 / 使用テキスト")); self.references = QListWidget(); self.references.itemDoubleClicked.connect(self.open_reference); detail_layout.addWidget(self.references); controls = QHBoxLayout(); revert = QPushButton("元に戻す"); revert.clicked.connect(self.revert); self.diff_button = QPushButton("差分"); self.diff_button.clicked.connect(self.show_diff); self.format_button = QPushButton("自動整形"); self.format_button.clicked.connect(self.open_auto_format); self.save_button = QPushButton("保存"); self.save_button.clicked.connect(self.save); controls.addWidget(revert); controls.addWidget(self.diff_button); controls.addWidget(self.format_button); controls.addStretch(); controls.addWidget(self.save_button); detail_layout.addLayout(controls); split.addWidget(detail); split.setSizes([850, 650]); layout.addWidget(split)

    @staticmethod
    def target_kind(target: TextTarget) -> str:
        if isinstance(target, EventTextEntry): return "INC"
        if isinstance(target, PoryTextEntry): return "PORY"
        return "COMPOUND_STRING" if target.macro == "COMPOUND_STRING" else "GTEXT"

    def target_id(self, target: TextTarget) -> TextIdentity:
        if isinstance(target, (EventTextEntry, PoryTextEntry)): return target.identity
        return (self.target_kind(target), target.file_name, target.symbol)

    @staticmethod
    def target_editable(target: TextTarget) -> bool:
        return not isinstance(target, PoryTextEntry) and (not isinstance(target, EventTextEntry) or target.supported)

    def retranslate(self) -> None:
        self.format_button.setText("自動整形" if self.window.lang == "ja" else "Auto Format"); self.save_button.setText(tr("save", self.window.lang))

    def add_definition(self, target: TextTarget) -> None:
        key = self.target_id(target); self.definitions[key] = target; self.symbol_index.setdefault(target.symbol, []).append(key)

    def resolve_use(self, use: EventTextUse) -> None:
        candidates = self.symbol_index.get(use.symbol, []); same_file = [key for key in candidates if key[1] == use.script.file_name]
        if len(same_file) == 1: use.target_id = same_file[0]; return
        if len(same_file) > 1: use.resolution = "同一ファイル内で定義が重複"; return
        if len(candidates) == 1: use.target_id = candidates[0]; return
        use.resolution = "テキスト定義が見つかりません" if not candidates else "同名の定義が複数あり未解決"

    def load(self) -> None:
        if not self.window.root_valid(): return
        self.scripts, self.inc_texts, self.inc_contents = find_event_records(self.window.root); self.pory_texts = find_pory_text_records(self.window.root); self.definitions.clear(); self.symbol_index.clear(); self.uses_by_target.clear()
        for target in [*self.inc_texts, *self.pory_texts, *[entry for entry in self.translation.entries if entry.symbol != "(anonymous)"]]: self.add_definition(target)
        for script in self.scripts:
            for use in script.uses:
                self.resolve_use(use)
                if use.target_id: self.uses_by_target.setdefault(use.target_id, []).append(use)
        self.text_rows = [target.identity for target in self.inc_texts] + [target.identity for target in self.pory_texts]
        self.text_rows.extend(key for key in self.uses_by_target if key not in self.text_rows); self.text_rows.sort(key=lambda key: (key[0], key[1].casefold(), key[2].casefold()))
        self.current_id = None; self.edited_source_ids.clear(); self.original.clear(); self.editor.clear(); self.editor.setEnabled(False); self.references.clear(); self.refresh(); self.window.status(f"INC text: {len(self.inc_texts)} definitions, {sum(len(script.uses) for script in self.scripts)} msgbox/message uses")

    def target_for_use(self, use: EventTextUse) -> TextTarget | None:
        return self.definitions.get(use.target_id) if use.target_id else None

    def target_matches(self, target: TextTarget, query: str) -> bool:
        return not query or query in "\n".join((self.target_kind(target), target.symbol, target.current, target.file_name)).casefold()

    def script_matches(self, script: EventScript, query: str) -> bool:
        if not query: return True
        values = [script.label, script.file_name]
        for use in script.uses:
            target = self.target_for_use(use); values.extend((use.command, use.symbol, target.current if target else use.resolution))
        return query in "\n".join(values).casefold()

    def refresh(self) -> None:
        self.refresh_text_table(); self.refresh_tree()

    def refresh_text_table(self) -> None:
        query = self.search.text().casefold().strip(); visible = [key for key in self.text_rows if key in self.definitions and self.target_matches(self.definitions[key], query)]; self.text_table.blockSignals(True); self.text_table.setRowCount(len(visible))
        for row, key in enumerate(visible):
            target = self.definitions[key]; uses = len(self.uses_by_target.get(key, [])); status = "対応" if self.target_editable(target) else (target.unsupported_reason if isinstance(target, EventTextEntry) else "参照のみ")
            values = [key[0], target.symbol, target.current.replace("\n", r"\n")[:180], target.file_name, str(target.line), str(uses), status]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, key); self.text_table.setItem(row, column, item)
            if key == self.current_id: self.text_table.selectRow(row)
        self.text_table.blockSignals(False)

    def refresh_tree(self) -> None:
        query = self.search.text().casefold().strip(); current = self.current_id; self.tree.blockSignals(True); self.tree.clear(); files: dict[str, QTreeWidgetItem] = {}; visible = 0
        for script in self.scripts:
            if not self.script_matches(script, query): continue
            visible += 1; file_item = files.get(script.file_name)
            if file_item is None:
                file_item = QTreeWidgetItem([script.file_name, "file"]); files[script.file_name] = file_item; self.tree.addTopLevelItem(file_item)
            script_item = QTreeWidgetItem([script.label, f"label ({len(script.uses)})"]); script_item.setData(0, Qt.ItemDataRole.UserRole, ("script", script)); file_item.addChild(script_item)
            for use in script.uses:
                target = self.target_for_use(use); preview = target.current.replace("\n", r"\n")[:92] if target else f"<{use.resolution}>"; child = QTreeWidgetItem([f"{use.command}: {use.symbol}  {preview}", "text"]); child.setData(0, Qt.ItemDataRole.UserRole, ("use", use)); script_item.addChild(child)
                if current and use.target_id == current: self.tree.setCurrentItem(child)
            file_item.setExpanded(True)
        self.tree.blockSignals(False); self.count.setText(f"{len(self.text_rows)} texts / {visible} scripts")

    def select_text_row(self) -> None:
        selected = self.text_table.selectedItems()
        if selected: self.show_target(selected[0].data(Qt.ItemDataRole.UserRole))

    def select_tree_item(self) -> None:
        selected = self.tree.selectedItems()
        if not selected: return
        payload = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if payload:
            kind, value = payload
            if kind == "script": self.show_script(value)
            elif kind == "use": self.show_use(value)

    def show_script(self, script: EventScript) -> None:
        self.current_id = None; self.loading = True; self.detail.setText(f"INC | {script.file_name}:{script.line}\n{script.label}"); self.context.setPlainText(script.body.strip()); self.original.clear(); self.editor.clear(); self.editor.setEnabled(False); self.loading = False; self.references.clear()
        for use in script.uses:
            target = self.target_for_use(use); preview = target.current.replace("\n", r"\n")[:110] if target else f"<{use.resolution}>"; item = QListWidgetItem(f"{use.command}: {use.symbol}  {preview}"); item.setData(Qt.ItemDataRole.UserRole, use); self.references.addItem(item)

    def show_use(self, use: EventTextUse) -> None:
        if not use.target_id:
            self.current_id = None; self.detail.setText(f"INC | {use.script.file_name}:{use.line}\n{use.command} {use.symbol} ({use.resolution})"); self.context.setPlainText(use.script.body.strip()); self.original.clear(); self.editor.clear(); self.editor.setEnabled(False); self.references.clear(); return
        self.show_target(use.target_id, use.script)

    def show_target(self, key: TextIdentity, context_script: EventScript | None = None) -> None:
        target = self.definitions.get(key)
        if target is None: return
        self.current_id = key; self.loading = True; suffix = "  ($ は保存時に維持)" if isinstance(target, EventTextEntry) and target.has_terminator else ""; self.detail.setText(f"{key[0]} | {target.file_name}:{target.line}\n{target.symbol}{suffix}"); self.context.setPlainText(context_script.body.strip() if context_script else ""); self.original.setPlainText(target.original); self.editor.setEnabled(self.target_editable(target)); self.editor.setPlainText(target.current); self.loading = False; self.references.clear()
        for use in self.uses_by_target.get(key, []):
            item = QListWidgetItem(f"{use.script.file_name}:{use.line}  {use.script.label} ({use.command})"); item.setData(Qt.ItemDataRole.UserRole, use.script); self.references.addItem(item)

    def open_reference(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, EventTextUse): self.show_use(value)
        elif isinstance(value, EventScript): self.show_script(value)

    def edit_changed(self) -> None:
        if self.loading or not self.current_id: return
        target = self.definitions.get(self.current_id)
        if not target or not self.target_editable(target): return
        target.current = self.editor.toPlainText()
        if isinstance(target, TextEntry): self.edited_source_ids.add(self.current_id)
        self.refresh(); self.window.status(f"Edited {self.current_id[0]} text: {target.symbol}")

    def revert(self) -> None:
        if not self.current_id: return
        target = self.definitions.get(self.current_id)
        if not target: return
        target.current = target.original; self.edited_source_ids.discard(self.current_id); self.loading = True; self.editor.setPlainText(target.current); self.loading = False; self.refresh()

    def open_auto_format(self) -> None:
        AutoFormatDialog(self, self, "イベントテキスト自動整形").exec()

    def selected_text_range(self) -> tuple[int, int, str] | None:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return None
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        return start, end, cursor.selectedText().replace("\u2029", "\n")

    def editable_keys_for_scope(self, scope: str) -> list[TextIdentity]:
        if scope == "current":
            return [self.current_id] if self.current_id and self.current_id in self.definitions and self.target_editable(self.definitions[self.current_id]) else []
        if scope == "file":
            if not self.current_id or self.current_id not in self.definitions:
                return []
            current_path = self.definitions[self.current_id].path
            return [key for key, target in self.definitions.items() if self.target_editable(target) and target.path == current_path]
        if scope == "search":
            query = self.search.text().casefold().strip()
            if not query:
                return []
            return [key for key in self.text_rows if key in self.definitions and self.target_editable(self.definitions[key]) and self.target_matches(self.definitions[key], query)]
        return []

    def preview_auto_format(self, settings: AutoFormatSettings) -> list[AutoFormatChange]:
        formatter = TextAutoFormatter(self.window.root)
        if settings.scope == "selection":
            selected = self.selected_text_range()
            if not self.current_id or self.current_id not in self.definitions or not selected:
                return []
            target = self.definitions[self.current_id]
            if not self.target_editable(target):
                return []
            start, end, before = selected
            after = formatter.format_text(before, settings)
            return [AutoFormatChange(f"{target.symbol} selection", before, after, target, (start, end))] if after != before else []
        changes: list[AutoFormatChange] = []
        for key in self.editable_keys_for_scope(settings.scope):
            target = self.definitions[key]
            after = formatter.format_text(target.current, settings)
            if after != target.current:
                changes.append(AutoFormatChange(f"{target.symbol} ({target.file_name}:{target.line})", target.current, after, target))
        return changes

    def apply_auto_format(self, changes: list[AutoFormatChange]) -> None:
        for change in changes:
            target = change.target
            if not isinstance(target, (TextEntry, EventTextEntry)):
                continue
            if change.selection:
                start, end = change.selection
                target.current = target.current[:start] + change.after + target.current[end:]
            else:
                target.current = change.after
            if isinstance(target, TextEntry):
                self.edited_source_ids.add(self.target_id(target))
        if self.current_id and self.current_id in self.definitions:
            current = self.definitions[self.current_id]
            self.loading = True; self.editor.setPlainText(current.current); self.loading = False
        self.refresh(); self.window.status(f"Auto formatted {len(changes)} event text item(s)")

    def save_inc_texts(self) -> int:
        dirty = [entry for entry in self.inc_texts if entry.dirty]
        grouped: dict[Path, list[EventTextEntry]] = {}
        for entry in dirty:
            if not entry.supported: raise RuntimeError(f"{entry.file_name}:{entry.line} is unsupported and cannot be saved.")
            grouped.setdefault(entry.path, []).append(entry)
        for path, entries in grouped.items():
            disk = read_utf8(path)
            if disk != self.inc_contents[path]: raise RuntimeError(f"{rel(self.window.root, path)} changed on disk; reload first.")
            updated = disk
            for entry in sorted(entries, key=lambda item: item.parts[0].start, reverse=True):
                value = entry.current[:-1] if entry.has_terminator and entry.current.endswith("$") else entry.current
                replacement_values = [value] + [""] * (len(entry.parts) - 1)
                if entry.has_terminator: replacement_values[-1] += "$"
                for part, replacement in reversed(list(zip(entry.parts, replacement_values))): updated = updated[:part.start] + quote_c_text(replacement) + updated[part.end:]
            write_with_backup(path, updated)
        return len(dirty)

    def save_source_texts(self) -> int:
        entries = [self.definitions[key] for key in self.edited_source_ids if key in self.definitions and isinstance(self.definitions[key], TextEntry) and self.definitions[key].dirty]
        unmanaged = [entry for entry in self.translation.entries if entry.dirty and self.target_id(entry) not in self.edited_source_ids]
        if unmanaged: raise RuntimeError("別の『文字列』タブの未保存変更があります。先にそちらを保存または戻してください。")
        grouped: dict[Path, list[TextEntry]] = {}
        for entry in entries: grouped.setdefault(entry.path, []).append(entry)
        for path, items in grouped.items():
            disk = read_utf8(path)
            if disk != self.translation.contents[path]: raise RuntimeError(f"{rel(self.window.root, path)} changed on disk; reload first.")
            updated = disk
            for entry in sorted(items, key=lambda item: item.start, reverse=True): updated = updated[:entry.start] + quote_c_text(entry.current) + updated[entry.end:]
            write_with_backup(path, updated)
        return len(entries)

    def save(self) -> None:
        try: inc_count = self.save_inc_texts(); source_count = self.save_source_texts()
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Text save failed", str(error)); return
        if source_count: self.translation.load()
        self.load(); self.window.status(f"Saved {inc_count} INC texts and {source_count} source texts with backups")

    def show_diff(self) -> None:
        if self.current_id and (target := self.definitions.get(self.current_id)): DiffDialog(self, f"Diff: {target.symbol}", target.original, target.current).exec()


TEXT_VARIABLE_DEFS = [
    ("KUN", "Male player", "gText_ExpandedPlaceholder_Kun", "Used when the saved player gender is male."),
    ("KUN", "Female player", "gText_ExpandedPlaceholder_Chan", "Used when the saved player gender is not male."),
    ("RIVAL", "Emerald / male player", "gText_ExpandedPlaceholder_May", "Fallback rival name for Emerald when the player is male."),
    ("RIVAL", "Emerald / female player", "gText_ExpandedPlaceholder_Brendan", "Fallback rival name for Emerald when the player is female."),
    ("RIVAL", "FRLG / male player", "gText_ExpandedPlaceholder_Green", "FRLG fallback rival name when no rival save name exists."),
    ("RIVAL", "FRLG / female player", "gText_ExpandedPlaceholder_Red", "FRLG fallback rival name when no rival save name exists."),
    ("VERSION", "Emerald", "gText_ExpandedPlaceholder_Emerald", "Version placeholder currently returned by ExpandPlaceholder_Version."),
    ("AQUA", "Team Aqua", "gText_ExpandedPlaceholder_Aqua", "Fixed team name placeholder."),
    ("MAGMA", "Team Magma", "gText_ExpandedPlaceholder_Magma", "Fixed team name placeholder."),
    ("ARCHIE", "Archie", "gText_ExpandedPlaceholder_Archie", "Fixed character name placeholder."),
    ("MAXIE", "Maxie", "gText_ExpandedPlaceholder_Maxie", "Fixed character name placeholder."),
    ("KYOGRE", "Kyogre", "gText_ExpandedPlaceholder_Kyogre", "Fixed Pokemon name placeholder."),
    ("GROUDON", "Groudon", "gText_ExpandedPlaceholder_Groudon", "Fixed Pokemon name placeholder."),
    ("REGION", "Hoenn", "gText_Hoenn", "Returned by {REGION} in Emerald mode."),
    ("REGION", "Kanto", "gText_Kanto", "Returned by {REGION} in FRLG mode."),
]

RUNTIME_PLACEHOLDER_DESCRIPTIONS = {
    "PLAYER": "Runtime value: player name from save data.",
    "STR_VAR_1": "Runtime value: gStringVar1.",
    "STR_VAR_2": "Runtime value: gStringVar2.",
    "STR_VAR_3": "Runtime value: gStringVar3.",
    "B_BUFF1": "Battle runtime buffer.",
    "B_BUFF2": "Battle runtime buffer.",
    "B_BUFF3": "Battle runtime buffer.",
    "B_CURRENT_MOVE": "Battle runtime value: current move name.",
    "B_LAST_MOVE": "Battle runtime value: previous move name.",
    "B_LAST_ITEM": "Battle runtime value: item name.",
    "B_LAST_ABILITY": "Battle runtime value: ability name.",
    "B_PLAYER_NAME": "Battle runtime value: player trainer name.",
}

CHARMAP_PLACEHOLDER_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*FD\b")


def find_charmap_placeholders(root: Path) -> list[tuple[str, str, int]]:
    path = root / "charmap.txt"
    if not path.exists():
        return []
    result: list[tuple[str, str, int]] = []
    try:
        lines = read_utf8(path).splitlines()
    except UnicodeDecodeError:
        return []
    for line_no, line in enumerate(lines, 1):
        match = CHARMAP_PLACEHOLDER_RE.match(line)
        if match:
            result.append((match.group(1), line.strip(), line_no))
    return result


class TextVariablePanel(QWidget):
    """Browse and edit text placeholders that expand into visible strings."""
    def __init__(self, window: "Workbench", translation: TranslationTextPanel) -> None:
        super().__init__()
        self.window = window
        self.translation = translation
        self.entries: list[TextVariableEntry] = []
        self.contents: dict[Path, str] = {}
        self.current: TextVariableEntry | None = None
        self.loading = False
        self.search = QLineEdit()
        self.changed = QCheckBox("Changed only")
        self.count = QLabel()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["*", "Variable", "Case", "Symbol", "Value", "File", "Line"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.select_entry)
        self.detail = QLabel("Select a text variable.")
        self.detail.setWordWrap(True)
        self.original = QPlainTextEdit(); self.original.setReadOnly(True); self.original.setMaximumHeight(105)
        self.editor = QPlainTextEdit(); self.editor.textChanged.connect(self.edit_changed)
        self.usage = QListWidget()
        self.char_count = QLabel("0")
        self.build()

    def build(self) -> None:
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search.setPlaceholderText("Search variable / symbol / value")
        self.search.textChanged.connect(self.refresh)
        self.changed.stateChanged.connect(self.refresh)
        filters.addWidget(self.search); filters.addWidget(self.changed); filters.addStretch(); filters.addWidget(self.count)
        layout.addLayout(filters)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        detail = QWidget(); detail_layout = QVBoxLayout(detail)
        detail_layout.addWidget(self.detail)
        detail_layout.addWidget(QLabel("Current expanded text"))
        detail_layout.addWidget(self.original)
        detail_layout.addWidget(QLabel("Edited text"))
        detail_layout.addWidget(self.editor)
        controls = QHBoxLayout()
        self.revert_button = QPushButton("Revert"); self.revert_button.clicked.connect(self.revert)
        self.diff_button = QPushButton("Diff"); self.diff_button.clicked.connect(self.show_diff)
        self.save_button = QPushButton("Save"); self.save_button.clicked.connect(self.save)
        controls.addWidget(self.revert_button); controls.addWidget(self.diff_button); controls.addStretch(); controls.addWidget(QLabel("Chars:")); controls.addWidget(self.char_count); controls.addWidget(self.save_button)
        detail_layout.addLayout(controls)
        detail_layout.addWidget(QLabel("Usage in scanned text entries"))
        detail_layout.addWidget(self.usage)
        split.addWidget(detail); split.setSizes([860, 620])
        layout.addWidget(split)
        self.retranslate()

    def retranslate(self) -> None:
        if self.window.lang == "ja":
            self.changed.setText("変更済みのみ")
            self.detail.setText("テキスト内変数を選択してください。")
            self.revert_button.setText("元に戻す")
            self.diff_button.setText("差分")
            self.save_button.setText("保存")
        else:
            self.changed.setText("Changed only")
            self.detail.setText("Select a text variable.")
            self.revert_button.setText("Revert")
            self.diff_button.setText("Diff")
            self.save_button.setText("Save")

    def load(self) -> None:
        if not self.window.root_valid():
            return
        if not self.translation.entries:
            self.translation.load()
        self.entries = []
        self.contents = {}
        strings_path = self.window.root / "src/strings.c"
        strings_source = read_utf8(strings_path) if strings_path.exists() else ""
        if strings_source:
            self.contents[strings_path] = strings_source
        for placeholder, variant, symbol, description in TEXT_VARIABLE_DEFS:
            found = extract_c_text_symbol_span(strings_source, symbol) if strings_source else None
            if found:
                start, end, value = found
                line = strings_source.count("\n", 0, start) + 1
                self.entries.append(TextVariableEntry(placeholder, variant, symbol, description, strings_path, rel(self.window.root, strings_path), line, start, end, value, value, True))
            else:
                self.entries.append(TextVariableEntry(placeholder, variant, symbol, description + " Source symbol was not found.", None, "(missing)", 0, 0, 0, "", "", False))
        static_names = {placeholder for placeholder, _variant, _symbol, _description in TEXT_VARIABLE_DEFS}
        for name, raw, line in find_charmap_placeholders(self.window.root):
            if name in static_names:
                continue
            description = RUNTIME_PLACEHOLDER_DESCRIPTIONS.get(name, "Runtime value. Source text is decided by game code at display time.")
            self.entries.append(TextVariableEntry(name, "runtime", raw, description, None, "charmap.txt", line, 0, 0, f"<{description}>", f"<{description}>", False))
        self.current = None; self.original.clear(); self.editor.clear(); self.usage.clear(); self.refresh()
        self.window.status(f"Scanned {len(self.entries)} text variables")

    def filtered(self) -> list[TextVariableEntry]:
        query = self.search.text().casefold().strip()
        result: list[TextVariableEntry] = []
        for entry in self.entries:
            haystack = "\n".join((entry.placeholder, entry.variant, entry.symbol, entry.current, entry.description, entry.file_name)).casefold()
            if query and query not in haystack:
                continue
            if self.changed.isChecked() and not entry.dirty:
                continue
            result.append(entry)
        return result

    def refresh(self) -> None:
        visible = self.filtered()
        selected = self.current
        self.table.blockSignals(True)
        self.table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            values = [
                "*" if entry.dirty else "",
                "{" + entry.placeholder + "}",
                entry.variant,
                entry.symbol,
                entry.current.replace("\n", r"\n")[:160],
                entry.file_name,
                str(entry.line) if entry.line else "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, entry); self.table.setItem(row, column, item)
            if entry is selected:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        dirty = sum(entry.dirty for entry in self.entries)
        self.count.setText(f"{len(visible)} / {len(self.entries)} results | Dirty: {dirty}")

    def select_entry(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        entry = selected[0].data(Qt.ItemDataRole.UserRole)
        if entry is self.current:
            return
        self.current = entry
        self.loading = True
        editable = "editable" if entry.editable else "read-only"
        self.detail.setText(f"{entry.placeholder} [{entry.variant}] - {editable}\n{entry.symbol}\n{entry.description}")
        self.original.setPlainText(entry.original)
        self.editor.setPlainText(entry.current if entry.editable else entry.original)
        self.editor.setReadOnly(not entry.editable)
        self.loading = False
        self.char_count.setText(str(len(entry.current)))
        self.refresh_usage(entry)

    def refresh_usage(self, entry: TextVariableEntry) -> None:
        self.usage.clear()
        token = "{" + entry.placeholder + "}"
        count = 0
        for text_entry in self.translation.entries:
            if token not in text_entry.current and token not in text_entry.original:
                continue
            preview = text_entry.current.replace("\n", r"\n")[:150]
            item = QListWidgetItem(f"{text_entry.file_name}:{text_entry.line}  {text_entry.symbol}  {preview}")
            item.setData(Qt.ItemDataRole.UserRole, text_entry)
            self.usage.addItem(item)
            count += 1
        if count == 0:
            self.usage.addItem("No scanned source text entry uses this placeholder.")

    def edit_changed(self) -> None:
        if self.loading or not self.current or not self.current.editable:
            return
        self.current.current = self.editor.toPlainText()
        self.char_count.setText(str(len(self.current.current)))
        self.refresh()

    def revert(self) -> None:
        if not self.current or not self.current.editable:
            return
        self.current.current = self.current.original
        self.loading = True; self.editor.setPlainText(self.current.current); self.loading = False
        self.refresh()

    def save(self) -> None:
        dirty = [entry for entry in self.entries if entry.dirty and entry.path is not None]
        if not dirty:
            return self.window.status("No text variable changes")
        grouped: dict[Path, list[TextVariableEntry]] = {}
        for entry in dirty:
            grouped.setdefault(entry.path, []).append(entry)
        try:
            for path, entries in grouped.items():
                disk = read_utf8(path)
                if disk != self.contents.get(path, ""):
                    raise RuntimeError(f"{rel(self.window.root, path)} changed on disk; reload first.")
                updated = disk
                for entry in sorted(entries, key=lambda item: item.start, reverse=True):
                    updated = updated[:entry.start] + quote_c_text(entry.current) + updated[entry.end:]
                write_with_backup(path, updated)
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Variable save failed", str(error)); return
        if self.translation.entries:
            self.translation.load()
        self.load()
        self.window.status(f"Saved {len(dirty)} text variable value(s) with backups")

    def show_diff(self) -> None:
        if self.current:
            DiffDialog(self, f"Diff: {self.current.placeholder} / {self.current.variant}", self.current.original, self.current.current).exec()


class LegacyTranslationPanel(QWidget):
    """Legacy translation panel kept for compatibility; TranslationPanel below is active."""
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.loaded_sections: set[str] = set(); self.text = TranslationTextPanel(window); self.events = EventBrowserPanel(window, self.text); layout = QVBoxLayout(self); self.tabs = QTabWidget(); self.tabs.addTab(self.text, "文字列"); self.tabs.addTab(self.events, "イベントブラウザ"); self.tabs.currentChanged.connect(lambda _index: self.load_current()); layout.addWidget(self.tabs)

    def retranslate(self) -> None:
        self.text.retranslate(); self.events.retranslate(); self.tabs.setTabText(0, "文字列" if self.window.lang == "ja" else "Strings"); self.tabs.setTabText(1, "イベントブラウザ" if self.window.lang == "ja" else "Event Browser")

    def reset_loaded(self) -> None:
        self.loaded_sections.clear()

    def load_current(self, force: bool = False) -> None:
        section = "events" if self.tabs.currentWidget() is self.events else "text"
        if section in self.loaded_sections and not force:
            return
        self.window.begin_loading(f"読み込み中: {'イベントブラウザ' if section == 'events' else '文字列'}")
        try:
            if section == "events" and ("text" not in self.loaded_sections or not self.text.entries or force):
                self.text.load()
                self.loaded_sections.add("text")
            (self.events if section == "events" else self.text).load()
            self.loaded_sections.add(section)
        finally:
            self.window.end_loading()

    def load(self) -> None:
        self.load_current(force=True)

    def save(self) -> None:
        (self.events if self.tabs.currentWidget() is self.events else self.text).save()

    def show_diff(self) -> None:
        (self.events if self.tabs.currentWidget() is self.events else self.text).show_diff()


class TranslationPanel(QWidget):
    """Translation workspace with source strings, event text, and placeholders."""
    def __init__(self, window: "Workbench") -> None:
        super().__init__()
        self.window = window
        self.loaded_sections: set[str] = set()
        self.text = TranslationTextPanel(window)
        self.events = EventBrowserPanel(window, self.text)
        self.variables = TextVariablePanel(window, self.text)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.text, "Strings")
        self.tabs.addTab(self.events, "Event Browser")
        self.tabs.addTab(self.variables, "Variables")
        self.tabs.currentChanged.connect(lambda _index: self.load_current())
        layout.addWidget(self.tabs)
        self.retranslate()

    def retranslate(self) -> None:
        self.text.retranslate()
        self.events.retranslate()
        self.variables.retranslate()
        self.tabs.setTabText(0, "文字列" if self.window.lang == "ja" else "Strings")
        self.tabs.setTabText(1, "イベントブラウザ" if self.window.lang == "ja" else "Event Browser")
        self.tabs.setTabText(2, "変数" if self.window.lang == "ja" else "Variables")

    def reset_loaded(self) -> None:
        self.loaded_sections.clear()

    def load_current(self, force: bool = False) -> None:
        current = self.tabs.currentWidget()
        section = "events" if current is self.events else ("variables" if current is self.variables else "text")
        if section in self.loaded_sections and not force:
            return
        self.window.begin_loading(f"読み込み中: {section}" if self.window.lang == "ja" else f"Loading: {section}")
        try:
            if section in {"events", "variables"} and ("text" not in self.loaded_sections or not self.text.entries or force):
                self.text.load()
                self.loaded_sections.add("text")
            if section == "events":
                self.events.load()
            elif section == "variables":
                self.variables.load()
            else:
                self.text.load()
            self.loaded_sections.add(section)
        finally:
            self.window.end_loading()

    def load(self) -> None:
        self.load_current(force=True)

    def save(self) -> None:
        panel = self.tabs.currentWidget()
        if hasattr(panel, "save"):
            panel.save()

    def show_diff(self) -> None:
        panel = self.tabs.currentWidget()
        if hasattr(panel, "show_diff"):
            panel.show_diff()


@dataclass
class SourceRecord:
    path: Path
    key: str
    start: int
    end: int
    block: str
    values: dict[str, str] = field(default_factory=dict)


DESIGNATED_FIELD_RE = re.compile(r"\.[A-Za-z_][A-Za-z0-9_]*\s*=\s*")
CONCATENATED_DESIGNATORS_RE = re.compile(r"\.[A-Za-z_][A-Za-z0-9_]*\s*=.*\.[A-Za-z_][A-Za-z0-9_]*\s*=")


def ensure_designated_initializer_commas(block: str) -> str:
    """Ensure every designated initializer field in one record ends with a comma."""
    insertions: list[int] = []
    pos = 0
    while True:
        match = DESIGNATED_FIELD_RE.search(block, pos)
        if not match:
            break
        scan = match.end()
        depth = 0
        value_end = scan
        while scan < len(block):
            if block.startswith("//", scan) or block.startswith("/*", scan):
                insertions.append(value_end)
                break
            char = block[scan]
            if char in "\"'":
                scan = skip_string(block, scan, char)
                value_end = scan
                continue
            if char in "({[":
                depth += 1
                value_end = scan + 1
            elif char in ")}]":
                if depth == 0:
                    insertions.append(value_end)
                    break
                depth -= 1
                value_end = scan + 1
            elif char == "," and depth == 0:
                scan += 1
                break
            elif depth == 0 and char == "." and DESIGNATED_FIELD_RE.match(block, scan):
                insertions.append(value_end)
                break
            elif not char.isspace():
                value_end = scan + 1
            scan += 1
        pos = max(scan, match.end())
    updated = block
    for index in sorted(set(insertions), reverse=True):
        updated = updated[:index] + "," + updated[index:]
    return updated


def concatenated_designator_lines(source: str) -> list[tuple[int, str]]:
    return [(index, line.strip()) for index, line in enumerate(source.splitlines(), 1) if CONCATENATED_DESIGNATORS_RE.search(line)]


def assert_no_concatenated_designators(path: Path, source: str, root: Path | None = None) -> None:
    bad_lines = concatenated_designator_lines(source)
    if bad_lines:
        base = root if root is not None else Path.cwd()
        sample = "\n".join(f"{rel(base, path)}:{line_no}: {line[:160]}" for line_no, line in bad_lines[:8])
        raise RuntimeError("Multiple designated initializers were found on one line; save was aborted.\n" + sample)


def raw_field(block: str, name: str) -> tuple[int, int, str] | None:
    match = re.search(rf"\.{re.escape(name)}\s*=\s*", block)
    if not match: return None
    start = match.end(); pos = start; depth = 0
    while pos < len(block):
        char = block[pos]
        if char in "\"'": pos = skip_string(block, pos, char); continue
        if char in "({[": depth += 1
        elif char in ")}]":
            if depth == 0:
                return start, pos, block[start:pos].strip()
            depth -= 1
        elif char == "," and depth == 0: return start, pos, block[start:pos].strip()
        pos += 1
    return (start, pos, block[start:pos].strip()) if start < pos else None


def string_field(block: str, name: str) -> tuple[int, int, str, str] | None:
    raw = raw_field(block, name)
    if not raw: return None
    start, end, value = raw
    macro = "COMPOUND_STRING" if "COMPOUND_STRING" in value else "_"
    open_pos = value.find("(")
    if open_pos < 0: return None
    parsed = parse_c_strings(value, open_pos + 1)
    if not parsed: return None
    local_start, local_end, text = parsed
    return start + local_start, start + local_end, text, macro


def indexed_records(root: Path, paths: Iterable[Path], prefix: str, wanted: list[str]) -> tuple[list[SourceRecord], dict[Path, str]]:
    records: list[SourceRecord] = []; contents: dict[Path, str] = {}
    matcher = re.compile(rf"\[({re.escape(prefix)}[A-Za-z0-9_]+)\]\s*=\s*\{{")
    for path in paths:
        source = read_utf8(path); contents[path] = source
        for match in matcher.finditer(source):
            block_start = source.find("{", match.start(), match.end())
            block_end = balanced_end(source, block_start)
            if block_end is None: continue
            block = source[block_start:block_end]
            values = {field_name: raw_field(block, field_name)[2] for field_name in wanted if raw_field(block, field_name)}
            records.append(SourceRecord(path, match.group(1), match.start(), block_end, source[match.start():block_end], values))
    return records, contents


class DatabasePanel(QWidget):
    """Conservative field editor for species and move records."""
    def __init__(self, window: "Workbench", kind: str) -> None:
        super().__init__(); self.window = window; self.kind = kind; self.records: list[SourceRecord] = []; self.contents: dict[Path, str] = {}; self.current: SourceRecord | None = None
        self.table = QTableWidget(0, 4); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.itemSelectionChanged.connect(self.select)
        self.find = QLineEdit(); self.find.textChanged.connect(self.refresh)
        self.fields: dict[str, QWidget] = {}; self.build()

    @property
    def is_species(self) -> bool: return self.kind == "species"

    def names(self) -> list[str]:
        return (["speciesName", "categoryName", "description", "baseHP", "baseAttack", "baseDefense", "baseSpAttack", "baseSpDefense", "baseSpeed", "types"] if self.is_species else ["name", "description", "power", "type", "accuracy", "pp", "priority", "category", "effect", "target", "makesContact", "punchingMove"])

    def build(self) -> None:
        layout = QVBoxLayout(self); top = QHBoxLayout(); self.find.setPlaceholderText("Filter identifier or text"); top.addWidget(self.find); create = QPushButton(); create.clicked.connect(self.template); self._create = create; top.addWidget(create); layout.addLayout(top)
        split = QSplitter(Qt.Orientation.Horizontal); split.addWidget(self.table)
        editor = QWidget(); form = QFormLayout(editor)
        for name in self.names():
            if name in {"description"}: control: QWidget = QPlainTextEdit(); control.setMaximumHeight(95); control.textChanged.connect(self.changed)
            elif name in {"baseHP", "baseAttack", "baseDefense", "baseSpAttack", "baseSpDefense", "baseSpeed", "power", "accuracy", "pp", "priority"}:
                spin = QSpinBox(); spin.setRange(-99, 999); spin.valueChanged.connect(self.changed); control = spin
            elif name in {"makesContact", "punchingMove"}:
                check = QCheckBox(); check.stateChanged.connect(self.changed); control = check
            else:
                line = QLineEdit(); line.textChanged.connect(self.changed); control = line
            self.fields[name] = control; form.addRow(name, control)
        save = QPushButton(); save.clicked.connect(self.save); self._save = save; form.addRow(save)
        split.addWidget(editor); split.setSizes([720, 480]); layout.addWidget(split); self.retranslate()

    def retranslate(self) -> None:
        self._create.setText(tr("add_template", self.window.lang)); self._save.setText(tr("save", self.window.lang))

    def load(self) -> None:
        if not self.window.root_valid(): return
        if self.is_species:
            paths = list((self.window.root / "src/data/pokemon/species_info").glob("*_families.h")) + [self.window.root / "src/data/pokemon/species_info.h"]
            self.records, self.contents = indexed_records(self.window.root, [p for p in paths if p.exists()], "SPECIES_", self.names())
            headers = ["Species", "Name", "Type", "Source"]
        else:
            path = self.window.root / "src/data/moves_info.h"; self.records, self.contents = indexed_records(self.window.root, [path], "MOVE_", self.names()) if path.exists() else ([], {})
            headers = ["Move", "Name", "Power", "Source"]
        self.table.setColumnCount(4); self.table.setHorizontalHeaderLabels(headers); self.current = None; self.refresh()

    def visible(self) -> list[SourceRecord]:
        query = self.find.text().casefold(); return [record for record in self.records if not query or query in (record.key + " " + " ".join(record.values.values())).casefold()]

    def refresh(self) -> None:
        items = self.visible(); self.table.setRowCount(len(items))
        for row, record in enumerate(items):
            if self.is_species: values = [record.key, self.display_text(record, "speciesName"), record.values.get("types", ""), rel(self.window.root, record.path)]
            else: values = [record.key, self.display_text(record, "name"), record.values.get("power", ""), rel(self.window.root, record.path)]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, record); self.table.setItem(row, col, item)

    @staticmethod
    def display_text(record: SourceRecord, name: str) -> str:
        parsed = string_field(record.block, name); return parsed[2] if parsed else record.values.get(name, "")

    def select(self) -> None:
        selected = self.table.selectedItems()
        if not selected: return
        self.current = selected[0].data(Qt.ItemDataRole.UserRole)
        for name, control in self.fields.items():
            field_value = self.current.values.get(name, "")
            parsed = string_field(self.current.block, name)
            if parsed: field_value = parsed[2]
            control.blockSignals(True)
            if isinstance(control, QPlainTextEdit): control.setPlainText(field_value)
            elif isinstance(control, QSpinBox): control.setValue(int(field_value) if re.fullmatch(r"-?\d+", field_value) else 0)
            elif isinstance(control, QCheckBox): control.setChecked(field_value == "TRUE")
            else: control.setText(field_value)
            control.blockSignals(False)

    def changed(self) -> None:
        if self.current: self.window.status(f"Editing {self.current.key}; save to write source")

    def control_value(self, control: QWidget) -> str:
        if isinstance(control, QPlainTextEdit): return control.toPlainText()
        if isinstance(control, QSpinBox): return str(control.value())
        if isinstance(control, QCheckBox): return "TRUE" if control.isChecked() else "FALSE"
        return control.text()  # type: ignore[union-attr]

    def save(self) -> None:
        if not self.current: return
        record = self.current; source = self.contents[record.path]; block = record.block
        replacements: list[tuple[int, int, str]] = []
        for name, control in self.fields.items():
            desired = self.control_value(control); parsed = string_field(block, name); raw = raw_field(block, name)
            if parsed:
                start, end, old, _macro = parsed
                if desired != old: replacements.append((start, end, quote_c_text(desired)))
            elif raw and desired != raw[2]: replacements.append((raw[0], raw[1], desired))
        if not replacements: return self.window.status("No database changes")
        new_block = block
        for start, end, value in sorted(replacements, reverse=True): new_block = new_block[:start] + value + new_block[end:]
        new_source = source[:record.start] + new_block + source[record.end:]
        try: write_with_backup(record.path, new_source)
        except OSError as error: QMessageBox.critical(self, "Save failed", str(error)); return
        self.load(); self.window.status(f"Saved {record.key} with backup")

    def template(self) -> None:
        kind = "species" if self.is_species else "move"; target = self.window.tool_dir / "templates"; target.mkdir(exist_ok=True)
        path = target / f"new_{kind}_template.h"
        if not path.exists():
            key = "SPECIES_NEW" if self.is_species else "MOVE_NEW"
            content = f"// Copy this record into the appropriate source after defining {key}.\n[{key}] =\n{{\n    .{'speciesName' if self.is_species else 'name'} = COMPOUND_STRING(\"New\"),\n}},\n"
            path.write_text(content, encoding="utf-8")
        QApplication.clipboard().setText(str(path)); self.window.status(f"Template created: {path}")


class ConstantsPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.find = QLineEdit(); self.find.textChanged.connect(self.refresh); self.items: list[tuple[str, str, str]] = []
        layout = QVBoxLayout(self); layout.addWidget(self.find); self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["Name", "Value", "File"]); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); layout.addWidget(self.table)

    def load(self) -> None:
        self.items.clear(); base = self.window.root / "include/constants"
        if not base.exists(): return
        for path in base.rglob("*.h"):
            try: source = read_utf8(path)
            except UnicodeDecodeError: continue
            for match in re.finditer(r"^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)\s*$", source, re.M): self.items.append((match.group(1), match.group(2), rel(self.window.root, path)))
            for match in re.finditer(r"^\s*([A-Z][A-Z0-9_]+)\s*(?:=\s*([^,]+))?,", source, re.M): self.items.append((match.group(1), match.group(2) or "", rel(self.window.root, path)))
        self.refresh()

    def refresh(self) -> None:
        query = self.find.text().casefold(); rows = [item for item in self.items if not query or query in " ".join(item).casefold()]; self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values): self.table.setItem(row, col, QTableWidgetItem(value))
        self.window.status(f"{len(rows)} constants")


class FileSearchPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window
        layout = QVBoxLayout(self); bar = QHBoxLayout(); self.query = QLineEdit(); self.query.returnPressed.connect(self.search); self.query.setPlaceholderText("Identifier, text, or asset path")
        run = QPushButton(); run.clicked.connect(self.search); self._run = run; bar.addWidget(self.query); bar.addWidget(run); layout.addLayout(bar)
        self.results = QTreeWidget(); self.results.setHeaderLabels(["File", "Line", "Text"]); self.results.itemActivated.connect(self.copy_result); layout.addWidget(self.results); self.retranslate()

    def retranslate(self) -> None: self._run.setText(tr("search", self.window.lang))

    def search(self) -> None:
        query = self.query.text()
        if not query or not self.window.root_valid(): return
        self.results.clear(); found = 0
        for path in self.window.root.rglob("*"):
            if path.suffix not in SOURCE_EXTENSIONS or not path.is_file() or ".git" in path.parts: continue
            try: lines = read_utf8(path).splitlines()
            except UnicodeDecodeError: continue
            for number, line in enumerate(lines, 1):
                if query.casefold() in line.casefold():
                    item = QTreeWidgetItem([rel(self.window.root, path), str(number), line.strip()[:220]]); item.setData(0, Qt.ItemDataRole.UserRole, path); self.results.addTopLevelItem(item); found += 1
        self.window.status(f"{found} search results")

    def copy_result(self, item: QTreeWidgetItem) -> None:
        QApplication.clipboard().setText(f"{item.data(0, Qt.ItemDataRole.UserRole)}:{item.text(1)}")


CODE_INDEX_VERSION = 1
CODE_INDEX_DIRS = ("src", "include", "data", "asm", "constants")
CODE_INDEX_SUFFIXES = {".c", ".h", ".inc", ".s", ".pory"}
CODE_INDEX_EXCLUDE_DIRS = {".git", "build", "dist", "workspace", "_pyinstaller", "__pycache__", ".venv", "venv", "node_modules", ".expansionstudio"}
CODE_INDEX_EXCLUDE_SUFFIXES = {".o", ".d", ".elf", ".gba", ".sav"}
CODE_INDEX_KINDS = ("constant", "gText", "COMPOUND_STRING", "script", "macro", "enum", "struct")
DEFINE_RE = re.compile(r"(?m)^[ \t]*#define[ \t]+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?[ \t]*(.*)$")
ASM_CONST_RE = re.compile(r"(?m)^[ \t]*\.(?:set|equiv)[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*,[ \t]*(.+)$")
ASM_MACRO_RE = re.compile(r"(?m)^[ \t]*\.macro[ \t]+([A-Za-z_][A-Za-z0-9_]*)(.*)$")
GTEXT_RE = re.compile(r"\b(gText_[A-Za-z0-9_]+)\s*(?:\[[^\]]*\])?\s*=\s*_\s*\(")
COMPOUND_RE = re.compile(r"\b(COMPOUND_STRING)\s*\(")
INC_LABEL_RE = re.compile(r"(?m)^([A-Za-z_][A-Za-z0-9_]*):(?::)?\s*(?:@.*)?$")
PORY_BLOCK_RE = re.compile(r"(?m)^\s*(script|text|movement|mart|mapscripts|object|warp|coord|bg|callback)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
ENUM_RE = re.compile(r"\b(?:typedef\s+)?enum\b([^{;]*)\{")
STRUCT_RE = re.compile(r"\b(?:typedef\s+)?struct\b([^{;]*)\{")
TYPEDEF_STRUCT_TAIL_RE = re.compile(r"\}\s*([A-Za-z_][A-Za-z0-9_]*)\s*;")
ENUM_MEMBER_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*(?:=\s*([^,/{]+))?\s*,?", re.M)
CODE_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class CodeIndexEntry:
    kind: str
    name: str
    value_or_signature: str
    file: str
    line: int
    preview: str
    search_text: str


def code_index_search_text(name: str, value: str, file_name: str, preview: str) -> str:
    return " ".join((name, value, file_name, preview)).casefold()


def make_code_index_entry(kind: str, name: str, value: str, file_name: str, line: int, preview: str) -> CodeIndexEntry:
    clean_preview = " ".join(preview.strip().split())[:260]
    return CodeIndexEntry(kind, name, value.strip(), file_name, line, clean_preview, code_index_search_text(name, value, file_name, clean_preview))


def c_tag_name(head: str) -> str:
    names = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", head)
    ignored = {"__attribute__", "packed", "aligned", "unused"}
    useful = [name for name in names if name not in ignored]
    return useful[-1] if useful else ""


def code_index_cache_path(root: Path) -> Path:
    return root / ".expansionstudio" / "index.json"


def code_index_excluded(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    parts = set(relative.parts)
    if parts.intersection(CODE_INDEX_EXCLUDE_DIRS):
        return True
    if any(part.startswith("rollback_") for part in relative.parts):
        return True
    name = path.name
    if name.endswith(".bak") or ".bak." in name:
        return True
    if path.suffix.lower() in CODE_INDEX_EXCLUDE_SUFFIXES:
        return True
    return False


def code_index_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for dirname in CODE_INDEX_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in CODE_INDEX_SUFFIXES:
                continue
            if not code_index_excluded(path, root):
                paths.append(path)
    return sorted(paths, key=lambda item: item.as_posix().casefold())


def append_enum_members(entries: list[CodeIndexEntry], root: Path, path: Path, source: str, body_start: int, body_end: int) -> None:
    file_name = rel(root, path)
    body = source[body_start:body_end]
    for member in ENUM_MEMBER_RE.finditer(body):
        name = member.group(1)
        value = member.group(2) or ""
        line = source.count("\n", 0, body_start + member.start()) + 1
        entries.append(make_code_index_entry("constant", name, value, file_name, line, source.splitlines()[line - 1] if line else ""))


def build_code_index(root: Path) -> list[CodeIndexEntry]:
    entries: list[CodeIndexEntry] = []
    for path in code_index_paths(root):
        try:
            source = read_utf8(path)
        except UnicodeDecodeError:
            continue
        file_name = rel(root, path)
        lines = source.splitlines()
        for match in DEFINE_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            name, args, value = match.group(1), match.group(2) or "", match.group(3).strip()
            kind = "macro" if args else "constant"
            entries.append(make_code_index_entry(kind, name, (args + " " + value).strip(), file_name, line, lines[line - 1] if line <= len(lines) else ""))
        for match in ASM_CONST_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            entries.append(make_code_index_entry("constant", match.group(1), match.group(2), file_name, line, lines[line - 1] if line <= len(lines) else ""))
        for match in ASM_MACRO_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            entries.append(make_code_index_entry("macro", match.group(1), match.group(2), file_name, line, lines[line - 1] if line <= len(lines) else ""))
        for match in GTEXT_RE.finditer(source):
            parsed = parse_c_strings(source, match.end())
            value = parsed[2] if parsed else ""
            line = source.count("\n", 0, match.start()) + 1
            entries.append(make_code_index_entry("gText", match.group(1), value, file_name, line, lines[line - 1] if line <= len(lines) else ""))
        for match in COMPOUND_RE.finditer(source):
            parsed = parse_c_strings(source, match.end())
            if not parsed:
                continue
            line = source.count("\n", 0, match.start()) + 1
            symbol = infer_symbol(source, match.start())
            entries.append(make_code_index_entry("COMPOUND_STRING", symbol, parsed[2], file_name, line, lines[line - 1] if line <= len(lines) else ""))
        if path.suffix == ".inc":
            for match in INC_LABEL_RE.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                entries.append(make_code_index_entry("script", match.group(1), "inc label", file_name, line, lines[line - 1] if line <= len(lines) else ""))
        if path.suffix == ".pory":
            for match in PORY_BLOCK_RE.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                entries.append(make_code_index_entry("script", match.group(2), match.group(1), file_name, line, lines[line - 1] if line <= len(lines) else ""))
        for match in ENUM_RE.finditer(source):
            open_pos = source.find("{", match.start())
            end = balanced_end(source, open_pos)
            if end is None:
                continue
            line = source.count("\n", 0, match.start()) + 1
            name = c_tag_name(match.group(1)) or f"enum @ {file_name}:{line}"
            entries.append(make_code_index_entry("enum", name, "", file_name, line, lines[line - 1] if line <= len(lines) else ""))
            append_enum_members(entries, root, path, source, open_pos + 1, end - 1)
        for match in STRUCT_RE.finditer(source):
            open_pos = source.find("{", match.start())
            end = balanced_end(source, open_pos)
            if end is None:
                continue
            line = source.count("\n", 0, match.start()) + 1
            tail = TYPEDEF_STRUCT_TAIL_RE.search(source, end - 1, min(len(source), end + 120))
            name = c_tag_name(match.group(1)) or (tail.group(1) if tail else f"struct @ {file_name}:{line}")
            entries.append(make_code_index_entry("struct", name, "", file_name, line, lines[line - 1] if line <= len(lines) else ""))
    return entries


def save_code_index_cache(root: Path, entries: list[CodeIndexEntry]) -> None:
    path = code_index_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CODE_INDEX_VERSION,
        "root": str(root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "entries": [entry.__dict__ for entry in entries],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_code_index_cache(root: Path) -> list[CodeIndexEntry] | None:
    path = code_index_cache_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(read_utf8(path))
        if payload.get("version") != CODE_INDEX_VERSION:
            return None
        entries = payload.get("entries", [])
        return [CodeIndexEntry(**entry) for entry in entries]
    except (OSError, TypeError, ValueError):
        return None


class CodeIndexPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.entries: list[CodeIndexEntry] = []; self.name_index: dict[str, list[CodeIndexEntry]] = {}; self.current: CodeIndexEntry | None = None
        layout = QVBoxLayout(self); bar = QHBoxLayout(); self.query = QLineEdit(); self.query.setPlaceholderText("Search definitions"); self.query.textChanged.connect(self.refresh); self.kind = QComboBox(); self.kind.addItem("All kinds", ""); [self.kind.addItem(kind, kind) for kind in CODE_INDEX_KINDS]; self.kind.currentIndexChanged.connect(self.refresh); self.path_filter = QLineEdit(); self.path_filter.setPlaceholderText("Filter path"); self.path_filter.textChanged.connect(self.refresh); self.reindex_button = QPushButton("Re-index"); self.reindex_button.clicked.connect(lambda: self.load(force=True)); bar.addWidget(self.query); bar.addWidget(self.kind); bar.addWidget(self.path_filter); bar.addWidget(self.reindex_button); layout.addLayout(bar)
        split = QSplitter(Qt.Orientation.Horizontal); self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["Kind", "Name", "Value / Signature", "File", "Line", "Preview"]); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.itemSelectionChanged.connect(self.select_entry); self.table.itemDoubleClicked.connect(lambda _item: self.goto_definition()); split.addWidget(self.table)
        detail = QWidget(); detail_layout = QVBoxLayout(detail); self.detail = QLabel("Select an index entry."); self.detail.setWordWrap(True); detail_layout.addWidget(self.detail); self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); detail_layout.addWidget(self.preview); buttons = QHBoxLayout(); self.goto_button = QPushButton("Go to definition"); self.goto_button.clicked.connect(self.goto_definition); self.open_button = QPushButton("Open file"); self.open_button.clicked.connect(self.open_file); self.jump_button = QPushButton("Copy line jump"); self.jump_button.clicked.connect(self.copy_line_jump); self.copy_name_button = QPushButton("Copy name"); self.copy_name_button.clicked.connect(self.copy_name); self.copy_path_button = QPushButton("Copy path"); self.copy_path_button.clicked.connect(self.copy_path); self.refs_button = QPushButton("Reference search"); self.refs_button.clicked.connect(self.reference_search); [buttons.addWidget(button) for button in (self.goto_button, self.open_button, self.jump_button, self.copy_name_button, self.copy_path_button, self.refs_button)]; detail_layout.addLayout(buttons); split.addWidget(detail); split.setSizes([980, 520]); layout.addWidget(split); self.goto_shortcut = QShortcut(QKeySequence("F12"), self); self.goto_shortcut.activated.connect(self.goto_definition); self.reference_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self); self.reference_shortcut.activated.connect(self.reference_search)

    def retranslate(self) -> None:
        self.goto_button.setText("定義へジャンプ" if self.window.lang == "ja" else "Go to definition")
        self.reindex_button.setText("再インデックス" if self.window.lang == "ja" else "Re-index")
        self.open_button.setText("ファイルを開く" if self.window.lang == "ja" else "Open file")
        self.jump_button.setText("行へジャンプ" if self.window.lang == "ja" else "Copy line jump")
        self.copy_name_button.setText("名前をコピー" if self.window.lang == "ja" else "Copy name")
        self.copy_path_button.setText("パスをコピー" if self.window.lang == "ja" else "Copy path")
        self.refs_button.setText("参照検索" if self.window.lang == "ja" else "Reference search")

    def load(self, force: bool = False) -> None:
        if not self.window.root_valid():
            return
        self.window.begin_loading("インデックス作成中..." if self.window.lang == "ja" else "Building index...")
        try:
            cached = None if force else load_code_index_cache(self.window.root)
            if cached is None:
                self.entries = build_code_index(self.window.root)
                save_code_index_cache(self.window.root, self.entries)
                self.window.status(f"Indexed {len(self.entries)} definitions")
            else:
                self.entries = cached
                self.window.status(f"Loaded {len(self.entries)} index entries")
            self.current = None; self.preview.clear(); self.rebuild_name_index(); self.refresh()
        finally:
            self.window.end_loading()

    def rebuild_name_index(self) -> None:
        self.name_index.clear()
        for entry in self.entries:
            self.name_index.setdefault(entry.name, []).append(entry)

    def selected_identifier(self) -> str:
        cursor = self.preview.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n").strip()
        if CODE_IDENTIFIER_RE.fullmatch(selected):
            return selected
        text = self.preview.toPlainText()
        pos = cursor.position()
        for match in CODE_IDENTIFIER_RE.finditer(text):
            if match.start() <= pos <= match.end():
                return match.group(0)
        return self.current.name if self.current else self.query.text().strip()

    def definition_candidates(self, name: str) -> list[CodeIndexEntry]:
        if not name:
            return []
        exact = self.name_index.get(name, [])
        if exact:
            return exact
        folded = name.casefold()
        return [entry for entry in self.entries if entry.name.casefold().startswith(folded)]

    def choose_definition(self, name: str, candidates: list[CodeIndexEntry]) -> CodeIndexEntry | None:
        if not candidates:
            QMessageBox.information(self, "Definition not found", f"No definition candidate for: {name}")
            return None
        if len(candidates) == 1:
            return candidates[0]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Definition candidates: {name}")
        dialog.resize(1000, 560)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(candidates), 5)
        table.setHorizontalHeaderLabels(["Kind", "Name", "File", "Line", "Preview"])
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, entry in enumerate(candidates):
            for column, value in enumerate((entry.kind, entry.name, entry.file, str(entry.line), entry.preview)):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                table.setItem(row, column, item)
        table.selectRow(0)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        table.itemDoubleClicked.connect(lambda _item: dialog.accept())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected = table.selectedItems()
        return selected[0].data(Qt.ItemDataRole.UserRole) if selected else candidates[0]

    def show_entry(self, target: CodeIndexEntry) -> None:
        self.query.setText(target.name)
        self.kind.setCurrentIndex(0)
        self.path_filter.clear()
        rows = self.filtered()
        self.refresh()
        for row, entry in enumerate(rows):
            if entry.file == target.file and entry.line == target.line and entry.kind == target.kind and entry.name == target.name:
                self.table.selectRow(row)
                break
        self.current = target
        self.detail.setText(f"{target.kind} | {target.name}\n{target.file}:{target.line}")
        self.preview.setPlainText(f"{target.preview}\n\n{target.value_or_signature}")
        QApplication.clipboard().setText(f"{target.file}:{target.line}")
        self.window.status(f"Definition: {target.name} -> {target.file}:{target.line}")

    def goto_definition(self) -> None:
        name = self.selected_identifier()
        target = self.choose_definition(name, self.definition_candidates(name))
        if target:
            self.show_entry(target)

    def filtered(self) -> list[CodeIndexEntry]:
        query = self.query.text().casefold().strip(); kind = self.kind.currentData(); path_query = self.path_filter.text().casefold().strip()
        result = []
        for entry in self.entries:
            if kind and entry.kind != kind: continue
            if query and query not in entry.search_text: continue
            if path_query and path_query not in entry.file.casefold(): continue
            result.append(entry)
        return result

    def refresh(self) -> None:
        rows = self.filtered(); self.table.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            values = [entry.kind, entry.name, entry.value_or_signature[:160], entry.file, str(entry.line), entry.preview]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, entry); self.table.setItem(row, column, item)
        self.window.status(f"{len(rows)} / {len(self.entries)} index entries")

    def select_entry(self) -> None:
        selected = self.table.selectedItems()
        if not selected: return
        self.current = selected[0].data(Qt.ItemDataRole.UserRole)
        entry = self.current
        self.detail.setText(f"{entry.kind} | {entry.name}\n{entry.file}:{entry.line}")
        self.preview.setPlainText(f"{entry.preview}\n\n{entry.value_or_signature}")

    def current_location(self) -> str:
        return f"{self.current.file}:{self.current.line}" if self.current else ""

    def open_file(self) -> None:
        if not self.current: return
        path = self.window.root / self.current.file
        QApplication.clipboard().setText(self.current_location())
        if sys.platform.startswith("win"):
            try: os.startfile(path)  # type: ignore[attr-defined]
            except OSError: pass
        self.window.status(f"Copied/opened {self.current_location()}")

    def copy_line_jump(self) -> None:
        if self.current:
            QApplication.clipboard().setText(self.current_location()); self.window.status(self.current_location())

    def copy_name(self) -> None:
        if self.current:
            QApplication.clipboard().setText(self.current.name); self.window.status(self.current.name)

    def copy_path(self) -> None:
        if self.current:
            QApplication.clipboard().setText(self.current.file); self.window.status(self.current.file)

    def reference_search(self) -> None:
        if not self.current: return
        self.window.files.query.setText(self.current.name)
        self.window.tabs.setCurrentWidget(self.window.files)
        self.window.files.search()


@dataclass
class AssetGroup:
    key: str
    members: list[Path]

    @property
    def primary_image(self) -> Path | None:
        return next((path for path in self.members if path.suffix.lower() == ".png"), None)


@dataclass
class AssetReference:
    source_file: str
    line: int
    macro: str
    asset_path: str
    mode: str

    def label(self) -> str:
        suffix = f" -> {self.mode}" if self.mode else ""
        return f"{self.source_file}:{self.line} {self.macro}{suffix}"


class AssetPanel(QWidget):
    """Static reference based image-group browser with reversible quarantine moves."""
    ASSET_SUFFIXES = {".png", ".pal", ".bin", ".4bpp", ".gbapal"}
    PALETTE_SUFFIXES = {".pal", ".gbapal"}
    RAW_SUFFIXES = {".bin", ".4bpp"}
    SOURCE_SUFFIXES = {".c", ".h", ".inc", ".mk", ".s"}
    ASSET_PATH_RE = re.compile(r"(?:graphics|data)/[A-Za-z0-9_./-]+\.(?:png|pal|bin|4bpp|gbapal)(?:\.[A-Za-z0-9_]+)?")
    INCGFX_RE = re.compile(r'\b(INCGFX(?:_[A-Z0-9]+)?)\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"')
    INCBIN_RE = re.compile(r'\b(INCBIN(?:_[A-Z0-9]+)?)\s*\(\s*"([^"]+)"')
    COPY_FILTER = "Supported assets (*.png *.pal *.gbapal *.bin *.4bpp);;PNG (*.png);;Palette (*.pal *.gbapal);;Raw GBA (*.bin *.4bpp);;All files (*)"

    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.assets: list[Path] = []; self.groups: list[AssetGroup] = []; self.reference_index: dict[Path, set[str]] = {}; self.mode_index: dict[Path, list[AssetReference]] = {}; self.references_loaded = False
        layout = QVBoxLayout(self); bar = QHBoxLayout(); self.filter = QLineEdit(); self.filter.textChanged.connect(self.refresh); self.filter.setPlaceholderText("Filter path"); self.include_non_png = QCheckBox("PNG以外のみのグループも表示"); self.include_non_png.stateChanged.connect(self.refresh); self.sort = QComboBox(); self.sort.addItem("パス順", "path"); self.sort.addItem("未使用候補を先頭", "unused"); self.sort.addItem("参照数順", "references"); self.sort.currentIndexChanged.connect(self.refresh)
        analyze = QPushButton("参照解析"); analyze.clicked.connect(self.load_references); self._analyze = analyze; add = QPushButton(); add.clicked.connect(self.add_asset); self._add = add; replace = QPushButton("選択ファイルを差し替え"); replace.clicked.connect(self.replace_asset); self._replace = replace; quarantine = QPushButton("quarantineへ移動"); quarantine.clicked.connect(self.quarantine_group); self._quarantine = quarantine
        bar.addWidget(self.filter); bar.addWidget(self.include_non_png); bar.addWidget(QLabel("並び順")); bar.addWidget(self.sort); bar.addWidget(analyze); bar.addWidget(add); bar.addWidget(replace); bar.addWidget(quarantine); layout.addLayout(bar)
        split = QSplitter(Qt.Orientation.Horizontal); self.list = QListWidget(); self.list.currentItemChanged.connect(self.select); split.addWidget(self.list)
        detail = QWidget(); box = QVBoxLayout(detail); self.preview = QLabel("No asset selected"); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(560, 380); box.addWidget(self.preview)
        self.asset_path = QLabel(); self.asset_path.setWordWrap(True); box.addWidget(self.asset_path); self.usage = QLabel(); self.usage.setWordWrap(True); box.addWidget(self.usage); self.mode_info = QLabel(); self.mode_info.setWordWrap(True); box.addWidget(self.mode_info); self.members = QListWidget(); self.members.currentItemChanged.connect(lambda _current, _previous: self.select_member()); box.addWidget(QLabel("画像グループ (.png / .gbapal / .pal / .bin / .4bpp)")); box.addWidget(self.members); self.refs = QListWidget(); box.addWidget(QLabel("静的参照箇所 / 変換指定")); box.addWidget(self.refs); split.addWidget(detail); split.setSizes([520, 760]); layout.addWidget(split); self.retranslate()

    def retranslate(self) -> None:
        self._analyze.setText("参照解析"); self._add.setText("追加"); self._replace.setText("選択ファイルを差し替え"); self._quarantine.setText("quarantineへ移動")

    def group_key(self, asset: Path) -> str:
        return rel(self.window.root, asset.with_suffix(""))

    def referenced_asset(self, by_name: dict[str, Path], asset_name: str) -> Path | None:
        if asset_name in by_name:
            return by_name[asset_name]
        for suffix in (".fastSmolTM", ".smolTM", ".fastSmol", ".smol", ".lz", ".rl"):
            if asset_name.endswith(suffix):
                stripped = asset_name[:-len(suffix)]
                if stripped in by_name:
                    return by_name[stripped]
        return None

    def source_files(self) -> Iterable[Path]:
        roots = [self.window.root / name for name in ("src", "include", "data", "asm")]
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in self.SOURCE_SUFFIXES:
                    yield path
        for path in self.window.root.glob("*"):
            if path.is_file() and path.suffix.lower() in {".mk", ".s"}:
                yield path

    def build_reference_index(self) -> None:
        self.reference_index = {asset: set() for asset in self.assets}; self.mode_index = {asset: [] for asset in self.assets}; by_name = {rel(self.window.root, asset): asset for asset in self.assets}
        excluded = {".git", "workspace", "build", "dist", "quarantine"}
        for path in self.source_files():
            try:
                if excluded.intersection(path.relative_to(self.window.root).parts): continue
                source = read_utf8(path)
            except (UnicodeDecodeError, OSError): continue
            source_file = rel(self.window.root, path)
            for line_no, line in enumerate(source.splitlines(), 1):
                for match in self.INCGFX_RE.finditer(line):
                    macro, asset_name, mode = match.groups()
                    asset = self.referenced_asset(by_name, asset_name)
                    if asset:
                        self.reference_index[asset].add(source_file)
                        self.mode_index.setdefault(asset, []).append(AssetReference(source_file, line_no, macro, asset_name, mode))
                for match in self.INCBIN_RE.finditer(line):
                    macro, asset_name = match.groups()
                    asset = self.referenced_asset(by_name, asset_name)
                    if asset:
                        self.reference_index[asset].add(source_file)
                        self.mode_index.setdefault(asset, []).append(AssetReference(source_file, line_no, macro, asset_name, "raw/include"))
                for match in self.ASSET_PATH_RE.finditer(line):
                    asset = self.referenced_asset(by_name, match.group(0))
                    if asset: self.reference_index[asset].add(source_file)

    def group_references(self, group: AssetGroup) -> list[str]:
        return sorted({reference for member in group.members for reference in self.reference_index.get(member, set())})

    def group_asset_references(self, group: AssetGroup) -> list[AssetReference]:
        refs = [reference for member in group.members for reference in self.mode_index.get(member, [])]
        return sorted(refs, key=lambda reference: (reference.source_file, reference.line, reference.asset_path, reference.mode))

    def load(self) -> None:
        base = self.window.root / "graphics"; self.assets = sorted((path for path in base.rglob("*") if path.is_file() and path.suffix.lower() in self.ASSET_SUFFIXES), key=lambda path: path.as_posix().casefold()) if base.exists() else []
        grouped: dict[str, list[Path]] = {}
        for asset in self.assets: grouped.setdefault(self.group_key(asset), []).append(asset)
        self.groups = [AssetGroup(key, members) for key, members in grouped.items()]
        self.reference_index = {asset: set() for asset in self.assets}; self.mode_index = {asset: [] for asset in self.assets}; self.references_loaded = False
        self.refresh()

    def load_references(self) -> None:
        if not self.assets:
            self.load()
        self.window.begin_loading("読み込み中: アセット参照解析")
        try:
            self.build_reference_index(); self.references_loaded = True; self.refresh(); self.select()
            self.window.status(f"Asset references: {sum(len(refs) for refs in self.mode_index.values())} conversion refs")
        finally:
            self.window.end_loading()

    def visible_groups(self) -> list[AssetGroup]:
        query = self.filter.text().casefold().strip(); groups = [group for group in self.groups if (self.include_non_png.isChecked() or group.primary_image) and (not query or query in group.key.casefold() or any(query in path.name.casefold() for path in group.members))]
        sort_mode = self.sort.currentData()
        if not self.references_loaded and sort_mode in {"unused", "references"}: return sorted(groups, key=lambda group: group.key.casefold())
        if sort_mode == "unused": return sorted(groups, key=lambda group: (bool(self.group_references(group)), group.key.casefold()))
        if sort_mode == "references": return sorted(groups, key=lambda group: (-len(self.group_references(group)), group.key.casefold()))
        return sorted(groups, key=lambda group: group.key.casefold())

    def refresh(self) -> None:
        current = self.list.currentItem().data(Qt.ItemDataRole.UserRole) if self.list.currentItem() else None; self.list.blockSignals(True); self.list.clear()
        for group in self.visible_groups():
            references = self.group_references(group); prefix = "[未使用候補] " if self.references_loaded and not references else ""; ref_text = str(len(references)) if self.references_loaded else "?"; label = f"{prefix}{group.key}  ({len(group.members)} files / {ref_text} refs)"; row = QListWidgetItem(label); row.setData(Qt.ItemDataRole.UserRole, group); self.list.addItem(row)
            if current and current.key == group.key: self.list.setCurrentItem(row)
        self.list.blockSignals(False)
        if self.references_loaded:
            self.window.status(f"{self.list.count()} image groups | 未使用候補: {sum(not self.group_references(group) for group in self.groups)}")
        else:
            self.window.status(f"{self.list.count()} image groups | 参照未解析")

    def select(self) -> None:
        item = self.list.currentItem(); self.refs.clear(); self.members.clear(); self.preview.clear(); self.asset_path.clear(); self.usage.clear(); self.mode_info.clear()
        if not item: return
        group: AssetGroup = item.data(Qt.ItemDataRole.UserRole); references = self.group_references(group); self.asset_path.setText(group.key)
        self.usage.setText(("参照未解析: 必要なら「参照解析」を押してください。" if not self.references_loaded else (f"使用中: {len(references)} ファイル" if references else "未使用候補: 静的参照は見つかりません（動的・生成時参照は確認してください）")))
        primary_row = 0
        for index, path in enumerate(group.members):
            row = QListWidgetItem(rel(self.window.root, path)); row.setData(Qt.ItemDataRole.UserRole, path); self.members.addItem(row)
            if path == group.primary_image: primary_row = index
        mode_refs = self.group_asset_references(group)
        if not self.references_loaded:
            self.refs.addItem("参照解析ボタンで使用箇所と変換指定を読み込みます。")
        else:
            self.refs.addItems([reference.label() for reference in mode_refs] if mode_refs else references)
        if self.members.count(): self.members.setCurrentRow(primary_row)

    def selected_group(self) -> AssetGroup | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected_asset(self) -> Path | None:
        item = self.members.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        group = self.selected_group()
        if not group:
            return None
        return group.primary_image or (group.members[0] if group.members else None)

    def select_member(self) -> None:
        asset = self.selected_asset(); group = self.selected_group()
        if not asset: return
        self.asset_path.setText(rel(self.window.root, asset)); self.mode_info.setText(self.asset_mode_summary(asset))
        preview_image = asset if asset.suffix.lower() == ".png" else (group.primary_image if group else None)
        if preview_image and preview_image.exists():
            pixmap = QPixmap(str(preview_image))
            if not pixmap.isNull():
                self.preview.setPixmap(pixmap.scaled(620, 460, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
                return
        self.preview.setText("PNG画像なしの関連アセットグループ")

    def asset_mode_summary(self, asset: Path) -> str:
        if not self.references_loaded:
            return "変換指定: 未解析。4bpp / gbapal / 圧縮指定を確認する場合は「参照解析」を押してください。"
        references = self.mode_index.get(asset, [])
        if not references:
            return "変換指定: INCGFX/INCBIN参照なし。追加後は呼び出し元の定義を別途確認してください。"
        modes = sorted({reference.mode for reference in references})
        lowered = " ".join(modes).lower()
        flags = []
        if "4bpp" in lowered: flags.append("4bpp")
        if "8bpp" in lowered: flags.append("8bpp")
        if "gbapal" in lowered: flags.append("gbapal")
        if any(token in lowered for token in ("lz", "smol", "rl")): flags.append("圧縮指定あり")
        return f"変換指定: {', '.join(modes)}" + (f" / {', '.join(flags)}" if flags else "")

    def is_under_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.window.root.resolve())
            return True
        except (OSError, ValueError):
            return False

    def image_color_count(self, image: QImage, limit: int = 257) -> int:
        if image.colorCount() > 0:
            return image.colorCount()
        converted = image.convertToFormat(QImage.Format.Format_ARGB32)
        colors: set[int] = set()
        for y in range(converted.height()):
            for x in range(converted.width()):
                colors.add(converted.pixel(x, y))
                if len(colors) >= limit:
                    return len(colors)
        return len(colors)

    def inspect_copy(self, source: Path, target: Path) -> tuple[list[str], list[str], list[str]]:
        errors: list[str] = []; warnings: list[str] = []; details: list[str] = []
        source_suffix = source.suffix.lower(); target_suffix = target.suffix.lower()
        if not source.exists() or not source.is_file():
            errors.append("コピー元ファイルが存在しません。")
            return errors, warnings, details
        if source_suffix != target_suffix:
            errors.append(f"拡張子が一致しません: source={source_suffix or '(なし)'} target={target_suffix or '(なし)'}。このGUIは変換せずにコピーします。")
        if target_suffix not in self.ASSET_SUFFIXES:
            errors.append(f"対応していない置換先拡張子です: {target_suffix}")
        try:
            size = source.stat().st_size
        except OSError as error:
            errors.append(str(error)); return errors, warnings, details
        if size == 0:
            errors.append("コピー元ファイルが空です。")

        references = self.mode_index.get(target, [])
        modes = [reference.mode for reference in references]
        lowered = " ".join(modes).lower()
        details.append("参照変換: " + ("未解析" if not self.references_loaded else (", ".join(sorted(set(modes))) if modes else "未検出")))

        if target_suffix == ".png":
            image = QImage(str(source))
            if image.isNull():
                errors.append("PNGとして読み込めません。")
            else:
                colors = self.image_color_count(image, 257)
                details.append(f"PNG: {image.width()}x{image.height()} / colors={colors if colors < 257 else '257+'}")
                if "4bpp" in lowered and colors > 16:
                    warnings.append("4bpp想定の可能性がありますが、PNGの色数が16色を超えています。GBA 4bpp変換で失敗または意図しない減色になる可能性があります。")
                elif not self.references_loaded:
                    warnings.append("参照未解析のため、4bpp / gbapal / 圧縮指定との整合性は未確認です。必要なら先に「参照解析」を実行してください。")
                if "8bpp" in lowered and colors > 256:
                    warnings.append("8bpp参照ですが、PNGの色数が256色を超えています。")
                if "4bpp" in lowered and (image.width() % 8 or image.height() % 8):
                    warnings.append("4bppタイル画像として参照されていますが、幅または高さが8px単位ではありません。")
                if "gbapal" in lowered and colors > 256:
                    warnings.append("gbapal抽出元として参照されていますが、色数が256色を超えています。")
        elif target_suffix in self.PALETTE_SUFFIXES:
            details.append(f"Palette/raw size: {size} bytes")
            if target_suffix == ".gbapal" and size % 2:
                warnings.append(".gbapal はGBA 15bit palette相当のため、通常は2バイト単位です。ファイルサイズが奇数です。")
        elif target_suffix in self.RAW_SUFFIXES:
            details.append(f"Raw size: {size} bytes")
            if target_suffix == ".4bpp" and size % 32:
                warnings.append(".4bpp raw tilesは通常1タイル32バイト単位です。ファイルサイズが32の倍数ではありません。")
        if any(token in lowered for token in ("lz", "smol", "rl")):
            details.append("圧縮指定は参照側にあります。GUIは元ファイルだけを置き換え、圧縮はビルド時の既存変換に任せます。")
        return errors, warnings, details

    def confirm_copy(self, source: Path, target: Path, action: str) -> bool:
        errors, warnings, details = self.inspect_copy(source, target)
        if errors:
            QMessageBox.critical(self, "Asset check failed", "\n".join(errors + details))
            return False
        message = [f"{action}: {rel(self.window.root, target)}", f"source: {source}", ""]
        if target.exists():
            message.append("既存ファイルは .bak に退避してから上書きします。")
        message.extend(details)
        if warnings:
            message.extend(["", "警告:"] + warnings)
        return QMessageBox.question(self, "Asset copy check", "\n".join(message)) == QMessageBox.StandardButton.Yes

    def add_asset(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, "追加するアセットを選択", str(self.window.root), self.COPY_FILTER)
        if not source: return
        group = self.selected_group()
        default_dir = Path(group.members[0]).parent if group and group.members else self.window.root / "graphics"
        target_name, _ = QFileDialog.getSaveFileName(self, "保存先を選択", str(default_dir / Path(source).name), self.COPY_FILTER)
        if not target_name: return
        target = Path(target_name)
        if not self.is_under_root(target) or "graphics" not in target.parts:
            QMessageBox.warning(self, "Invalid target", "保存先はリポジトリ内の graphics 配下にしてください。")
            return
        if target.exists() and QMessageBox.question(self, "Asset exists", "既存ファイルをバックアップして上書きしますか？") != QMessageBox.StandardButton.Yes:
            return
        if not self.confirm_copy(Path(source), target, "追加"): return
        try:
            copy_with_backup(Path(source), target)
        except OSError as error:
            QMessageBox.critical(self, "Asset add failed", str(error)); return
        self.load(); self.window.status(f"Added {rel(self.window.root, target)}")

    def replace_asset(self) -> None:
        target = self.selected_asset()
        if not target:
            QMessageBox.information(self, "No asset selected", "差し替えるファイルを画像グループから選択してください。")
            return
        if not self.references_loaded:
            answer = QMessageBox.question(self, "参照未解析", "4bpp / gbapal / 圧縮指定が未解析です。差し替え前に参照解析しますか？")
            if answer == QMessageBox.StandardButton.Yes:
                self.load_references()
        source, _ = QFileDialog.getOpenFileName(self, "差し替え元を選択", str(target.parent), self.COPY_FILTER)
        if not source: return
        source_path = Path(source)
        try:
            if source_path.resolve() == target.resolve():
                QMessageBox.information(self, "Same file", "同じファイルは差し替えできません。")
                return
        except OSError:
            pass
        if not self.confirm_copy(source_path, target, "差し替え"): return
        try:
            copy_with_backup(source_path, target)
        except OSError as error:
            QMessageBox.critical(self, "Asset replace failed", str(error)); return
        self.load(); self.window.status(f"Replaced {rel(self.window.root, target)}")

    def quarantine_group(self) -> None:
        item = self.list.currentItem()
        if not item: return
        if not self.references_loaded:
            QMessageBox.warning(self, "参照未解析", "quarantine移動は安全のため参照解析後に実行してください。")
            return
        group: AssetGroup = item.data(Qt.ItemDataRole.UserRole); references = self.group_references(group)
        if references:
            QMessageBox.warning(self, "参照中のアセット", "静的参照があるグループは quarantine へ移動できません。\n" + "\n".join(references[:20])); return
        if QMessageBox.question(self, "未使用候補を quarantine へ移動", f"{group.key} の {len(group.members)} ファイルを quarantine フォルダへ移動しますか？") != QMessageBox.StandardButton.Yes: return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S"); destination_root = self.window.root / "quarantine" / "assets" / stamp
        try:
            for asset in group.members:
                relative = asset.relative_to(self.window.root); destination = destination_root / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(asset), str(destination))
        except OSError as error:
            QMessageBox.critical(self, "Quarantine move failed", str(error)); return
        self.load(); self.window.status(f"Moved unused candidate group to {rel(self.window.root, destination_root)}")


@dataclass
class CharmapEntry:
    line: int
    input_text: str
    code: int | None
    kind: str
    raw_name: str


def parse_charmap(source: str) -> list[CharmapEntry]:
    entries: list[CharmapEntry] = []
    for line_no, line in enumerate(source.splitlines(), 1):
        char = re.match(r"^\s*'((?:\\.|[^'])*)'\s*=\s*([0-9A-Fa-f]{2})(?:\s|$)", line)
        if char:
            entries.append(CharmapEntry(line_no, char.group(1), int(char.group(2), 16), "文字", char.group(1)))
            continue
        named = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([0-9A-Fa-f]{2})(?:\s|$)", line)
        if named:
            kind = "EMOJI" if named.group(1).startswith("EMOJI_") else "制御コード"
            entries.append(CharmapEntry(line_no, named.group(1), int(named.group(2), 16), kind, named.group(1)))
    return entries


class GlyphProfilePanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.source = ""; self.entries: list[CharmapEntry] = []; self.fonts: list[Path] = []; self.all_fonts: list[Path] = []; self.current_entry: CharmapEntry | None = None
        layout = QVBoxLayout(self); top = QHBoxLayout(); top.addWidget(QLabel("表示モード")); self.mode = QComboBox(); self.mode.addItem("自動", "auto"); self.mode.addItem("日本語", "jpn"); self.mode.addItem("英語", "eng"); self.mode.currentIndexChanged.connect(self.change_mode); top.addWidget(self.mode); top.addWidget(QLabel("フォント")); self.font = QComboBox(); self.font.currentIndexChanged.connect(self.refresh); top.addWidget(self.font); top.addWidget(QLabel("文字 / 定義名")); self.search = QLineEdit(); self.search.textChanged.connect(self.refresh); top.addWidget(self.search); layout.addLayout(top)
        split = QSplitter(Qt.Orientation.Horizontal); self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["入力", "バイト", "glyph", "セル", "分類", "行"]); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.itemSelectionChanged.connect(self.select); split.addWidget(self.table)
        detail = QWidget(); form = QFormLayout(detail); self.preview = QLabel("glyph を選択"); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(180, 180); form.addRow("プレビュー", self.preview); self.input = QLineEdit(); self.input.setMaxLength(1); self.byte = QLineEdit(); self.byte.setPlaceholderText("01"); self.position = QLabel(); form.addRow("入力する文字", self.input); form.addRow("割り当てバイト (16進)", self.byte); form.addRow("glyph / セル", self.position); buttons = QHBoxLayout(); update = QPushButton("追加 / 更新"); update.clicked.connect(self.update_mapping); remove = QPushButton("文字定義を削除"); remove.clicked.connect(self.delete_mapping); buttons.addWidget(update); buttons.addWidget(remove); form.addRow(buttons); note = QLabel("通常文字は 1 バイトと glyph index が同じです。EMOJI と制御コードは通常文字 glyph として編集しません。"); note.setWordWrap(True); form.addRow(note); split.addWidget(detail); split.setSizes([860, 430]); layout.addWidget(split)

    def current_font(self) -> Path | None:
        return self.font.currentData()

    @staticmethod
    def is_japanese_input(text: str) -> bool:
        return any(("\u3040" <= char <= "\u30ff") or ("\u3000" <= char <= "\u303f") or ("\uff00" <= char <= "\uffef") for char in text)

    def refresh_font_options(self, preferred: Path | None = None) -> None:
        mode = self.mode.currentData(); current = preferred or self.current_font()
        if mode == "jpn": self.fonts = [path for path in self.all_fonts if path.name.startswith("japanese_")]
        elif mode == "eng": self.fonts = [path for path in self.all_fonts if path.name.startswith("latin_")]
        else: self.fonts = list(self.all_fonts)
        self.font.blockSignals(True); self.font.clear()
        for font in self.fonts: self.font.addItem(font.name, font)
        index = self.font.findData(current) if current else -1
        if index < 0 and self.fonts:
            normal = next((path for path in self.fonts if path.stem in {"japanese_normal", "latin_normal"}), self.fonts[0]); index = self.font.findData(normal)
        self.font.setCurrentIndex(index); self.font.blockSignals(False)

    def change_mode(self) -> None:
        if self.all_fonts:
            self.refresh_font_options(); self.refresh()

    def choose_font_for_entry(self, entry: CharmapEntry) -> None:
        if self.mode.currentData() != "auto" or entry.kind != "文字":
            return
        prefix = "japanese_" if self.is_japanese_input(entry.input_text) else "latin_"
        preferred = next((path for path in self.all_fonts if path.stem == prefix + "normal"), None)
        if preferred and self.current_font() != preferred:
            self.refresh_font_options(preferred)

    def cells(self) -> int:
        path = self.current_font()
        if not path: return 0
        image = QImage(str(path)); return (image.width() // 8) * (image.height() // 16)

    def load(self) -> None:
        path = self.window.root / "charmap.txt"
        if not path.exists(): return
        self.source = read_utf8(path); self.entries = parse_charmap(self.source); self.all_fonts = sorted((self.window.root / "graphics/fonts").glob("japanese_*.png")) + sorted((self.window.root / "graphics/fonts").glob("latin_*.png"))
        self.refresh_font_options(); self.refresh()

    def refresh(self) -> None:
        query = self.search.text().casefold(); cells = self.cells(); visible = [entry for entry in self.entries if not query or query in entry.input_text.casefold()]
        self.table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            glyph = str(entry.code) if entry.kind == "文字" and entry.code is not None else "-"; cell = f"{entry.code % 16}, {entry.code // 16}" if entry.kind == "文字" and entry.code is not None else "-"
            values = [entry.input_text, f"0x{entry.code:02X}" if entry.code is not None else "-", glyph, cell, entry.kind, str(entry.line)]
            for column, value in enumerate(values): item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, entry); self.table.setItem(row, column, item)
        used = sum(1 for entry in self.entries if entry.kind == "文字" and entry.code is not None and entry.code < cells); self.window.status(f"Charmap: {len(visible)} entries | glyph cells: {cells} | mapped: {used} | free: {max(0, cells - used)}")

    def select(self) -> None:
        selected = self.table.selectedItems()
        if not selected: return
        entry: CharmapEntry = selected[0].data(Qt.ItemDataRole.UserRole); self.current_entry = entry
        self.choose_font_for_entry(entry)
        editable = entry.kind == "文字"; self.input.setEnabled(editable); self.byte.setEnabled(editable); self.input.setText(entry.input_text if editable else ""); self.byte.setText(f"{entry.code:02X}" if editable and entry.code is not None else "")
        if not editable or entry.code is None: self.position.setText("通常文字の glyph はありません"); self.preview.setText(entry.kind); self.preview.setPixmap(QPixmap()); return
        self.position.setText(f"glyph {entry.code} / cell ({entry.code % 16}, {entry.code // 16})"); path = self.current_font(); image = QPixmap(str(path)) if path else QPixmap()
        x, y = (entry.code % 16) * 8, (entry.code // 16) * 16
        self.preview.setPixmap(image.copy(x, y, 8, 16).scaled(160, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation) if not image.isNull() else QPixmap())

    def update_mapping(self) -> None:
        character = self.input.text(); raw_code = self.byte.text().strip()
        if len(character) != 1 or not re.fullmatch(r"[0-9A-Fa-f]{1,2}", raw_code): QMessageBox.warning(self, "Invalid mapping", "入力する文字は 1 文字、バイトは 00-FF の16進数で指定してください。"); return
        code = int(raw_code, 16)
        if code >= self.cells(): QMessageBox.warning(self, "Glyph outside font", f"0x{code:02X} は選択中フォントの glyph 範囲外です。"); return
        existing = next((entry for entry in self.entries if entry.kind == "文字" and entry.input_text == character), None)
        conflict = next((entry for entry in self.entries if entry.kind == "文字" and entry.code == code and entry.input_text != character), None)
        if conflict and QMessageBox.question(self, "Byte already mapped", f"0x{code:02X} は {conflict.input_text!r} に割り当て済みです。続行しますか？") != QMessageBox.StandardButton.Yes: return
        lines = self.source.splitlines(keepends=True); target = existing or (self.current_entry if self.current_entry and self.current_entry.kind == "文字" else None)
        definition = f"'{character}' = {code:02X}\n"
        if target: lines[target.line - 1] = definition
        else: lines.append(definition)
        write_with_backup(self.window.root / "charmap.txt", "".join(lines)); self.load(); self.window.status(f"Saved charmap: {character} = 0x{code:02X}")

    def delete_mapping(self) -> None:
        entry = self.current_entry
        if not entry or entry.kind != "文字": return
        if QMessageBox.question(self, "Delete charmap entry", f"{entry.input_text!r} = 0x{entry.code:02X}") != QMessageBox.StandardButton.Yes: return
        lines = self.source.splitlines(keepends=True); del lines[entry.line - 1]; write_with_backup(self.window.root / "charmap.txt", "".join(lines)); self.load(); self.window.status("Deleted charmap entry")


class FontPanel(QWidget):
    """Glyph Table Editor: a glyph-ID view over charmap and font image cells."""
    SOURCE_SUFFIXES = {".c", ".h", ".inc", ".pory", ".s"}

    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.source = ""; self.entries: list[CharmapEntry] = []; self.fonts: list[Path] = []; self.image = QImage(); self.glyph_pixmap = QPixmap(); self.width_cache: dict[int, int] = {}; self.usage_count: dict[int, int] = {}; self.usage_paths: dict[int, set[str]] = {}; self.selected_id: int | None = None
        layout = QVBoxLayout(self); top = QHBoxLayout(); top.addWidget(QLabel("Glyph画像")); self.font = QComboBox(); self.font.currentIndexChanged.connect(self.change_font); top.addWidget(self.font); top.addWidget(QLabel("Glyph ID検索")); self.id_search = QLineEdit(); self.id_search.setPlaceholderText("例: 0x51 / 81"); self.id_search.textChanged.connect(self.refresh); top.addWidget(self.id_search); top.addWidget(QLabel("文字検索")); self.char_search = QLineEdit(); self.char_search.textChanged.connect(self.refresh); top.addWidget(self.char_search); self.unused_only = QCheckBox("未使用Glyphのみ"); self.unused_only.stateChanged.connect(self.refresh); top.addWidget(self.unused_only); layout.addLayout(top)
        split = QSplitter(Qt.Orientation.Horizontal); self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(["Glyph ID", "表示文字", "Glyph", "幅", "使用回数", "使用箇所数"]); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.itemSelectionChanged.connect(self.select); split.addWidget(self.table)
        detail = QWidget(); form = QFormLayout(detail); self.preview = QLabel("Glyph IDを選択"); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(200, 200); form.addRow("Glyph画像プレビュー", self.preview); self.position = QLabel(); form.addRow("セル / 幅", self.position); self.glyph_id = QSpinBox(); self.glyph_id.setRange(0, 255); self.glyph_id.valueChanged.connect(self.select_glyph_id); self.input = QLineEdit(); self.input.setMaxLength(1); form.addRow("Glyph ID", self.glyph_id); form.addRow("表示文字", self.input); buttons = QHBoxLayout(); update = QPushButton("文字割り当てを追加 / 更新"); update.clicked.connect(self.update_mapping); remove = QPushButton("文字割り当てを削除"); remove.clicked.connect(self.delete_mapping); buttons.addWidget(update); buttons.addWidget(remove); form.addRow(buttons); self.usage_label = QLabel(); self.usage_label.setWordWrap(True); form.addRow("使用状況", self.usage_label); self.refs = QListWidget(); form.addRow("使用箇所", self.refs); note = QLabel("Glyph ID はフォント PNG の 8x16 セル位置です。charmap の通常文字だけを編集します。EMOJI・制御コードは表示対象ですが、ここでは書き換えません。"); note.setWordWrap(True); form.addRow(note); split.addWidget(detail); split.setSizes([900, 460]); layout.addWidget(split)

    def retranslate(self) -> None:
        pass

    def current_font(self) -> Path | None:
        return self.font.currentData()

    def cells(self) -> int:
        return (self.image.width() // 8) * (self.image.height() // 16) if not self.image.isNull() else 0

    def mappings(self) -> dict[int, list[CharmapEntry]]:
        result: dict[int, list[CharmapEntry]] = {}
        for entry in self.entries:
            if entry.kind == "文字" and entry.code is not None: result.setdefault(entry.code, []).append(entry)
        return result

    def build_usage_index(self) -> None:
        self.usage_count.clear(); self.usage_paths.clear(); char_to_code = {entry.input_text: entry.code for entry in self.entries if entry.kind == "文字" and entry.code is not None and len(entry.input_text) == 1}
        if not char_to_code: return
        excluded = {".git", "workspace", "build", "dist", "quarantine"}
        for path in self.window.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.SOURCE_SUFFIXES: continue
            try:
                if excluded.intersection(path.relative_to(self.window.root).parts): continue
                source = read_utf8(path)
            except (UnicodeDecodeError, OSError): continue
            seen: set[int] = set()
            for character in source:
                code = char_to_code.get(character)
                if code is not None: self.usage_count[code] = self.usage_count.get(code, 0) + 1; seen.add(code)
            location = rel(self.window.root, path)
            for code in seen: self.usage_paths.setdefault(code, set()).add(location)

    def load(self) -> None:
        charmap = self.window.root / "charmap.txt"
        if not charmap.exists(): return
        self.source = read_utf8(charmap); self.entries = parse_charmap(self.source); fonts_dir = self.window.root / "graphics/fonts"; self.fonts = sorted((path for path in fonts_dir.glob("*.png") if path.stem.startswith(("japanese_", "latin_"))), key=lambda path: path.name.casefold()) if fonts_dir.exists() else []
        self.font.blockSignals(True); self.font.clear()
        for path in self.fonts: self.font.addItem(path.name, path)
        preferred = next((path for path in self.fonts if path.name == "japanese_normal.png"), self.fonts[0] if self.fonts else None)
        if preferred: self.font.setCurrentIndex(self.font.findData(preferred))
        self.font.blockSignals(False); self.change_font(); self.build_usage_index(); self.refresh()

    def change_font(self) -> None:
        path = self.current_font(); self.image = QImage(str(path)) if path else QImage(); self.glyph_pixmap = QPixmap(str(path)) if path else QPixmap(); self.width_cache.clear(); self.selected_id = None; self.refresh()

    def glyph_width(self, glyph_id: int) -> int:
        if glyph_id in self.width_cache: return self.width_cache[glyph_id]
        if glyph_id >= self.cells(): return 0
        x0, y0 = (glyph_id % (self.image.width() // 8)) * 8, (glyph_id // (self.image.width() // 8)) * 16; background = self.image.pixelColor(x0, y0); width = 0
        for x in range(8):
            for y in range(16):
                color = self.image.pixelColor(x0 + x, y0 + y)
                if color.alpha() and color.rgba() != background.rgba(): width = max(width, x + 1)
        self.width_cache[glyph_id] = width; return width

    def glyph_preview(self, glyph_id: int, scale: int = 1) -> QPixmap:
        if self.glyph_pixmap.isNull() or glyph_id >= self.cells(): return QPixmap()
        columns = self.image.width() // 8; image = self.glyph_pixmap.copy((glyph_id % columns) * 8, (glyph_id // columns) * 16, 8, 16)
        return image.scaled(8 * scale, 16 * scale, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation) if scale > 1 else image

    def matching_ids(self) -> list[int]:
        mappings = self.mappings(); raw_id = self.id_search.text().casefold().strip(); char_query = self.char_search.text().casefold()
        result = []
        for glyph_id in range(self.cells()):
            chars = "".join(entry.input_text for entry in mappings.get(glyph_id, [])); id_text = f"{glyph_id} 0x{glyph_id:02x}"
            if raw_id and raw_id not in id_text: continue
            if char_query and char_query not in chars.casefold(): continue
            if self.unused_only.isChecked() and self.usage_count.get(glyph_id, 0) != 0: continue
            result.append(glyph_id)
        return result

    def refresh(self) -> None:
        mappings = self.mappings(); visible = self.matching_ids(); selected = self.selected_id; self.table.blockSignals(True); self.table.setRowCount(len(visible))
        for row, glyph_id in enumerate(visible):
            chars = " ".join(entry.input_text for entry in mappings.get(glyph_id, [])); preview = self.glyph_preview(glyph_id, 2); values = [f"0x{glyph_id:02X}", chars or "-", "", f"{self.glyph_width(glyph_id)} px", str(self.usage_count.get(glyph_id, 0)), str(len(self.usage_paths.get(glyph_id, set())))]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, glyph_id)
                if column == 2 and not preview.isNull(): item.setIcon(QIcon(preview))
                self.table.setItem(row, column, item)
            if glyph_id == selected: self.table.selectRow(row)
        self.table.blockSignals(False); self.window.status(f"Glyph Table: {len(visible)} / {self.cells()} glyphs | 未使用: {sum(self.usage_count.get(glyph_id, 0) == 0 for glyph_id in range(self.cells()))}")

    def select(self) -> None:
        selected = self.table.selectedItems()
        if selected: self.show_glyph(selected[0].data(Qt.ItemDataRole.UserRole))

    def select_glyph_id(self, glyph_id: int) -> None:
        if glyph_id < self.cells() and glyph_id != self.selected_id: self.show_glyph(glyph_id)

    def show_glyph(self, glyph_id: int) -> None:
        if glyph_id >= self.cells(): return
        self.selected_id = glyph_id; mappings = self.mappings().get(glyph_id, []); self.glyph_id.blockSignals(True); self.glyph_id.setValue(glyph_id); self.glyph_id.blockSignals(False); self.input.setText(mappings[0].input_text if mappings else ""); self.position.setText(f"cell ({glyph_id % (self.image.width() // 8)}, {glyph_id // (self.image.width() // 8)}) / 幅 {self.glyph_width(glyph_id)} px"); self.preview.setPixmap(self.glyph_preview(glyph_id, 12)); self.usage_label.setText(f"使用回数: {self.usage_count.get(glyph_id, 0)} / 使用箇所数: {len(self.usage_paths.get(glyph_id, set()))}"); self.refs.clear(); self.refs.addItems(sorted(self.usage_paths.get(glyph_id, set()))); self.refresh()

    def update_mapping(self) -> None:
        character = self.input.text(); glyph_id = self.glyph_id.value()
        if len(character) != 1: QMessageBox.warning(self, "文字が無効です", "表示文字は 1 文字で指定してください。"); return
        if glyph_id >= self.cells(): QMessageBox.warning(self, "Glyph ID が無効です", "選択中の Glyph画像に存在する ID を指定してください。"); return
        existing = next((entry for entry in self.entries if entry.kind == "文字" and entry.input_text == character), None); conflict = next((entry for entry in self.entries if entry.kind == "文字" and entry.code == glyph_id and entry.input_text != character), None)
        if conflict and QMessageBox.question(self, "Glyph ID は既に使用中", f"0x{glyph_id:02X} は {conflict.input_text!r} にも割り当て済みです。文字を追加しますか？") != QMessageBox.StandardButton.Yes: return
        lines = self.source.splitlines(keepends=True); newline = "\r\n" if "\r\n" in self.source else "\n"; definition = f"'{character}' = {glyph_id:02X}{newline}"
        if existing: lines[existing.line - 1] = definition
        else: lines.append(definition)
        write_with_backup(self.window.root / "charmap.txt", "".join(lines)); self.load(); self.show_glyph(glyph_id); self.window.status(f"Saved Glyph ID 0x{glyph_id:02X}: {character}")

    def delete_mapping(self) -> None:
        character = self.input.text(); entry = next((item for item in self.entries if item.kind == "文字" and item.input_text == character), None)
        if not entry: QMessageBox.warning(self, "文字定義がありません", "削除する文字を選択または入力してください。"); return
        if QMessageBox.question(self, "文字割り当てを削除", f"{entry.input_text!r} = 0x{entry.code:02X} を削除しますか？") != QMessageBox.StandardButton.Yes: return
        lines = self.source.splitlines(keepends=True); del lines[entry.line - 1]; write_with_backup(self.window.root / "charmap.txt", "".join(lines)); self.load(); self.window.status(f"Deleted glyph mapping: {character}")


class DependencyPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; layout = QVBoxLayout(self); bar = QHBoxLayout(); self.query = QLineEdit(); self.query.setPlaceholderText("File path, constant, species, move, or symbol"); self.query.returnPressed.connect(self.resolve); run = QPushButton(); run.clicked.connect(self.resolve); self._run = run; bar.addWidget(self.query); bar.addWidget(run); layout.addLayout(bar)
        split = QSplitter(Qt.Orientation.Horizontal); self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Node", "Kind"]); split.addWidget(self.tree); self.graph = QGraphicsView(); self.graph.setScene(QGraphicsScene()); split.addWidget(self.graph); split.setSizes([600, 600]); layout.addWidget(split); self.retranslate()

    def retranslate(self) -> None: self._run.setText(tr("references", self.window.lang))

    def resolve(self) -> None:
        query = self.query.text().strip(); self.tree.clear(); scene = QGraphicsScene(); self.graph.setScene(scene)
        if not query: return
        root_item = QTreeWidgetItem([query, "selected"]); self.tree.addTopLevelItem(root_item); scene.addText(query).setPos(20, 20)
        refs: list[tuple[str, int, str]] = []
        for path in self.window.root.rglob("*"):
            if path.suffix not in SOURCE_EXTENSIONS or not path.is_file() or ".git" in path.parts: continue
            try: lines = read_utf8(path).splitlines()
            except UnicodeDecodeError: continue
            for number, line in enumerate(lines, 1):
                if query in line: refs.append((rel(self.window.root, path), number, line.strip()))
        for index, (file_name, line, text) in enumerate(refs):
            node = QTreeWidgetItem([f"{file_name}:{line}", "reference"]); node.addChild(QTreeWidgetItem([text[:220], "source"])); root_item.addChild(node)
            label = scene.addText(f"{file_name}:{line}"); label.setPos(250, 40 + index * 32); scene.addLine(130, 35, 240, 50 + index * 32)
        root_item.setExpanded(True); self.window.status(f"{len(refs)} dependencies")


@dataclass
class PoryFile:
    path: Path
    rel_path: str
    modified: datetime
    original: str
    current: str

    @property
    def dirty(self) -> bool:
        return self.original != self.current


PORYSCRIPT_SNIPPETS: list[tuple[str, str]] = [
    ("look / lock + faceplayer", "lock\nfaceplayer\n"),
    ("look / release", "release\nend\n"),
    ("text / msgbox", "msgbox(\"{MESSAGE}\")\n"),
    ("text / yes-no branch", "msgbox(\"{QUESTION}\", MSGBOX_YESNO)\nif (var(VAR_RESULT) == YES) {\n    msgbox(\"{YES_MESSAGE}\")\n} else {\n    msgbox(\"{NO_MESSAGE}\")\n}\n"),
    ("text / multiline message", "msgbox(\"{LINE_1}\\n{LINE_2}\")\n"),
    ("movement / apply movement", "applymovement({LOCAL_ID}, {MOVEMENT_LABEL})\nwaitmovement(0)\n"),
    ("movement / movement block", "movement {MOVEMENT_LABEL} {\n    walk_down\n    step_end\n}\n"),
    ("flow / call", "call {SCRIPT_LABEL}\n"),
    ("flow / goto", "goto {SCRIPT_LABEL}\n"),
    ("flow / if var", "if (var({VAR_NAME}) == {VALUE}) {\n    goto {SCRIPT_LABEL}\n}\n"),
    ("item / give item", "giveitem({ITEM_ID}, {COUNT})\n"),
    ("trainer / trainer battle", "trainerbattle(SINGLE, {TRAINER_ID}, 0, \"{INTRO_MESSAGE}\", \"{DEFEAT_MESSAGE}\")\n"),
    ("warp / warp", "warp({MAP}, {WARP_ID}, {X}, {Y})\n"),
]


TEMPLATE_VARIABLE_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def pory_template_variables(source: str) -> list[str]:
    """Return unique template variables in their first-seen order."""
    return list(dict.fromkeys(TEMPLATE_VARIABLE_RE.findall(source)))


def render_pory_template(source: str, values: dict[str, str]) -> str:
    return TEMPLATE_VARIABLE_RE.sub(lambda match: values.get(match.group(1), match.group(0)), source)


def wrap_inc_as_poryscript(source: str, source_name: str) -> str:
    """Preserve assembly bytecode safely inside a Poryscript raw statement."""
    body = source.rstrip("\n")
    return (
        f"// Imported from {source_name}.\n"
        "// This raw block preserves the original .inc bytecode unchanged.\n"
        "raw `\n"
        f"{body}\n"
        "`\n"
    )


class PoryTemplateDialog(QDialog):
    EMPTY_TEMPLATE = "script {{SCRIPT_NAME}} {\n    end\n}\n"
    DEFAULT_VALUES = {
        "SCRIPT_NAME": "NewScript",
        "MESSAGE": "メッセージ",
        "QUESTION": "質問ですか？",
        "YES_MESSAGE": "はいを選びました。",
        "NO_MESSAGE": "いいえを選びました。",
        "ITEM": "ITEM_POTION",
        "QUANTITY": "1",
        "SUCCESS_MESSAGE": "どうぞ。",
        "BAG_FULL_MESSAGE": "バッグが いっぱいです。",
        "TRAINER": "TRAINER_YOUNGSTER_CALVIN",
        "INTRO_MESSAGE": "勝負だ！",
        "DEFEAT_MESSAGE": "まいった！",
        "MAP": "MAP_LITTLEROOT_TOWN",
        "WARP_ID": "0",
        "X": "0",
        "Y": "0",
        "MART_NAME": "NewMartItems",
        "WELCOME_MESSAGE": "いらっしゃいませ。",
        "GOODBYE_MESSAGE": "また どうぞ。",
        "ITEMS": "ITEM_POTION\nITEM_POKEBALL",
    }

    def __init__(self, window: "Workbench", allow_empty: bool = True) -> None:
        super().__init__(window); self.window = window; self.root = window.root.resolve(); self.template_root = pory_template_root(window.tool_dir); self.allow_empty = allow_empty
        self.fields: dict[str, QLineEdit | QPlainTextEdit] = {}; self.created_path: Path | None = None; self.created_source = ""
        self.setWindowTitle("Poryscript 新規作成"); self.resize(1020, 700)
        layout = QVBoxLayout(self); content = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); left_box = QVBoxLayout(left); left_box.addWidget(QLabel("テンプレート")); self.template_list = QListWidget(); self.template_list.currentItemChanged.connect(self.select_template); left_box.addWidget(self.template_list); content.addWidget(left)
        right = QWidget(); right_box = QVBoxLayout(right); self.form_host = QWidget(); self.form = QFormLayout(self.form_host); self.form_scroll = QScrollArea(); self.form_scroll.setWidgetResizable(True); self.form_scroll.setWidget(self.form_host); right_box.addWidget(QLabel("置換変数")); right_box.addWidget(self.form_scroll, 1); right_box.addWidget(QLabel("プレビュー")); self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); right_box.addWidget(self.preview, 2); destination = QHBoxLayout(); self.destination = QLineEdit(); browse = QPushButton("保存先..."); browse.clicked.connect(self.choose_destination); destination.addWidget(self.destination); destination.addWidget(browse); right_box.addLayout(destination); content.addWidget(right); content.setSizes([300, 700]); layout.addWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.create_file); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.load_templates()

    def load_templates(self) -> None:
        self.template_root = pory_template_root(self.window.tool_dir); self.template_list.clear()
        if self.allow_empty:
            blank = QListWidgetItem("空の Poryscript"); blank.setData(Qt.ItemDataRole.UserRole, None); self.template_list.addItem(blank)
        for path in sorted(self.template_root.glob("*.pory")):
            item = QListWidgetItem(path.stem.replace("_", " ")); item.setData(Qt.ItemDataRole.UserRole, path); self.template_list.addItem(item)
        if self.template_list.count(): self.template_list.setCurrentRow(0)

    def template_source(self) -> tuple[str, Path | None]:
        item = self.template_list.currentItem()
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not path:
            return self.EMPTY_TEMPLATE, None
        try:
            return read_utf8(path), path
        except OSError as error:
            QMessageBox.critical(self, "Template read failed", str(error)); return self.EMPTY_TEMPLATE, None

    def select_template(self) -> None:
        source, path = self.template_source(); self.fields.clear()
        while self.form.count():
            child = self.form.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        for variable in pory_template_variables(source):
            value = self.DEFAULT_VALUES.get(variable, "")
            if "MESSAGE" in variable or variable in {"QUESTION", "ITEMS"}:
                editor = QPlainTextEdit(); editor.setMaximumHeight(74); editor.setPlainText(value); editor.textChanged.connect(self.refresh_preview)
            else:
                editor = QLineEdit(value); editor.textChanged.connect(self.refresh_preview)
            self.fields[variable] = editor; self.form.addRow(variable, editor)
        default_name = path.stem if path else "new_script"
        self.destination.setText(str(self.root / "data" / "scripts" / f"{default_name}.pory")); self.refresh_preview()

    def values(self) -> dict[str, str]:
        return {name: field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text() for name, field in self.fields.items()}

    def rendered(self) -> str:
        source, _path = self.template_source(); return render_pory_template(source, self.values())

    def refresh_preview(self) -> None:
        self.preview.setPlainText(self.rendered())

    def choose_destination(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Poryscript の保存先", self.destination.text(), "Poryscript (*.pory)")
        if name: self.destination.setText(name)

    def create_file(self) -> None:
        raw_target = self.destination.text().strip()
        if not raw_target:
            QMessageBox.warning(self, "保存先が必要です", "保存先を指定してください。"); return
        target = Path(raw_target).expanduser()
        if target.suffix.lower() != ".pory": target = target.with_suffix(".pory")
        try:
            target = target.resolve(); target.relative_to(self.root)
        except ValueError:
            QMessageBox.warning(self, "保存先が無効です", "Poryscript ファイルは選択中のリポジトリ配下に保存してください。"); return
        if target.exists() and QMessageBox.question(self, "既存ファイルを上書き", f"{rel(self.root, target)} を上書きしますか？") != QMessageBox.StandardButton.Yes:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists(): write_with_backup(target, self.rendered())
            else: target.write_text(self.rendered(), encoding="utf-8", newline="")
        except OSError as error:
            QMessageBox.critical(self, "Poryscript save failed", str(error)); return
        self.created_path = target; self.created_source = self.rendered(); self.accept()


class PoryTemplateManagerDialog(QDialog):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(window); self.window = window; self.template_root = pory_template_root(window.tool_dir); self.current_path: Path | None = None
        self.setWindowTitle("Poryscript テンプレート管理"); self.resize(880, 620); layout = QVBoxLayout(self); split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget(); self.list.currentItemChanged.connect(self.select); split.addWidget(self.list)
        detail = QWidget(); detail_box = QVBoxLayout(detail); self.variables = QLabel(); self.variables.setWordWrap(True); detail_box.addWidget(self.variables); self.editor = QPlainTextEdit(); self.editor.textChanged.connect(self.update_variables); detail_box.addWidget(self.editor); split.addWidget(detail); split.setSizes([270, 610]); layout.addWidget(split)
        actions = QHBoxLayout(); create = QPushButton("新規テンプレート"); create.clicked.connect(self.create); duplicate = QPushButton("複製"); duplicate.clicked.connect(self.duplicate); delete = QPushButton("削除"); delete.clicked.connect(self.delete); save = QPushButton("保存"); save.clicked.connect(self.save); close = QPushButton("閉じる"); close.clicked.connect(self.accept)
        for button in (create, duplicate, delete, save, close): actions.addWidget(button)
        actions.addStretch(); layout.addLayout(actions); self.load()

    def load(self, selected: Path | None = None) -> None:
        self.template_root = pory_template_root(self.window.tool_dir); self.list.clear(); selected = selected or self.current_path
        for path in sorted(self.template_root.glob("*.pory")):
            item = QListWidgetItem(path.stem); item.setData(Qt.ItemDataRole.UserRole, path); self.list.addItem(item)
            if path == selected: self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count(): self.list.setCurrentRow(0)

    def select(self) -> None:
        item = self.list.currentItem()
        if not item: self.current_path = None; self.editor.clear(); return
        self.current_path = item.data(Qt.ItemDataRole.UserRole)
        try: self.editor.setPlainText(read_utf8(self.current_path))
        except OSError as error: QMessageBox.critical(self, "Template read failed", str(error))

    def update_variables(self) -> None:
        variables = pory_template_variables(self.editor.toPlainText())
        self.variables.setText("置換変数: " + (", ".join(variables) if variables else "なし"))

    def template_name(self, title: str, initial: str = "") -> str | None:
        name, accepted = QInputDialog.getText(self, title, "テンプレート名", text=initial)
        if not accepted: return None
        name = name.strip().replace(" ", "_")
        if not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            QMessageBox.warning(self, "テンプレート名が無効です", "英数字、_、-、. のみ使用できます。"); return None
        return name.removesuffix(".pory")

    def create(self) -> None:
        name = self.template_name("新規テンプレート")
        if not name: return
        target = self.template_root / f"{name}.pory"
        if target.exists(): QMessageBox.warning(self, "既に存在します", target.name); return
        try: target.write_text(PoryTemplateDialog.EMPTY_TEMPLATE, encoding="utf-8", newline="")
        except OSError as error: QMessageBox.critical(self, "Template save failed", str(error)); return
        self.load(target)

    def duplicate(self) -> None:
        if not self.current_path: return
        name = self.template_name("テンプレートを複製", f"{self.current_path.stem}_copy")
        if not name: return
        target = self.template_root / f"{name}.pory"
        if target.exists(): QMessageBox.warning(self, "既に存在します", target.name); return
        try: target.write_text(self.editor.toPlainText(), encoding="utf-8", newline="")
        except OSError as error: QMessageBox.critical(self, "Template save failed", str(error)); return
        self.load(target)

    def delete(self) -> None:
        if not self.current_path: return
        if QMessageBox.question(self, "テンプレートを削除", f"{self.current_path.name} を削除しますか？") != QMessageBox.StandardButton.Yes: return
        try: shutil.copy2(self.current_path, backup_path(self.current_path)); self.current_path.unlink()
        except OSError as error: QMessageBox.critical(self, "Template delete failed", str(error)); return
        self.current_path = None; self.load()

    def save(self) -> None:
        if not self.current_path: return
        try: write_with_backup(self.current_path, self.editor.toPlainText())
        except OSError as error: QMessageBox.critical(self, "Template save failed", str(error)); return
        self.window.status(f"Saved template {self.current_path.name} with backup")


class PoryIncImportDialog(QDialog):
    def __init__(self, window: "Workbench", source_path: Path) -> None:
        super().__init__(window); self.window = window; self.root = window.root.resolve(); self.source_path = source_path; self.created_path: Path | None = None
        try: self.source = read_utf8(source_path)
        except OSError: self.source = ""
        self.result = wrap_inc_as_poryscript(self.source, rel(self.root, source_path)); self.setWindowTitle(".inc を Poryscript として読み込む"); self.resize(1100, 720)
        layout = QVBoxLayout(self); note = QLabel("安全な初期変換です。元の .inc は変更せず、内容を raw ブロックとして保持します。高水準の Poryscript 構文へは保存後に段階的に書き換えてください。"); note.setWordWrap(True); layout.addWidget(note)
        split = QSplitter(Qt.Orientation.Horizontal); original = QPlainTextEdit(); original.setPlainText(self.source); original.setReadOnly(True); result = QPlainTextEdit(); result.setPlainText(self.result); result.setReadOnly(True); split.addWidget(original); split.addWidget(result); split.setSizes([520, 580]); layout.addWidget(split)
        destination = QHBoxLayout(); self.destination = QLineEdit(str(source_path.with_suffix(".pory"))); browse = QPushButton("保存先..."); browse.clicked.connect(self.choose_destination); destination.addWidget(self.destination); destination.addWidget(browse); layout.addLayout(destination)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.save_as_pory); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def choose_destination(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Poryscript の保存先", self.destination.text(), "Poryscript (*.pory)")
        if name: self.destination.setText(name)

    def save_as_pory(self) -> None:
        target = Path(self.destination.text().strip()).expanduser()
        if target.suffix.lower() != ".pory": target = target.with_suffix(".pory")
        try: target = target.resolve(); target.relative_to(self.root)
        except ValueError:
            QMessageBox.warning(self, "保存先が無効です", "Poryscript ファイルは選択中のリポジトリ配下に保存してください。"); return
        if target.exists() and QMessageBox.question(self, "既存ファイルを上書き", f"{rel(self.root, target)} を上書きしますか？") != QMessageBox.StandardButton.Yes: return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists(): write_with_backup(target, self.result)
            else: target.write_text(self.result, encoding="utf-8", newline="")
        except OSError as error:
            QMessageBox.critical(self, "Poryscript save failed", str(error)); return
        self.created_path = target; self.accept()


class PoryscriptPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.files: list[PoryFile] = []; self.current: PoryFile | None = None; self.loading = False; self.process: QProcess | None = None
        layout = QVBoxLayout(self); split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); left_layout = QVBoxLayout(left); self.search = QLineEdit(); self.search.setPlaceholderText("ファイル名・本文・ラベルを検索"); self.search.textChanged.connect(self.refresh); left_layout.addWidget(self.search)
        creation = QHBoxLayout(); self.new_button = QPushButton("新規作成"); self.new_button.clicked.connect(self.new_from_template); self.template_button = QPushButton("テンプレートから"); self.template_button.clicked.connect(self.template_from_template); self.import_button = QPushButton(".inc 読込"); self.import_button.clicked.connect(self.import_inc); self.manage_button = QPushButton("テンプレート管理"); self.manage_button.clicked.connect(self.manage_templates)
        for button in (self.new_button, self.template_button, self.import_button, self.manage_button): creation.addWidget(button)
        left_layout.addLayout(creation); self.tree = QTreeWidget(); self.tree.setHeaderLabels(["ファイル", "相対パス", "更新日時"]); self.tree.itemSelectionChanged.connect(self.select); left_layout.addWidget(self.tree); split.addWidget(left)
        right = QWidget(); right_layout = QVBoxLayout(right); self.tool_state = QLabel(); self.tool_state.setWordWrap(True); right_layout.addWidget(self.tool_state); self.path_label = QLabel("ファイル未選択"); self.path_label.setWordWrap(True); right_layout.addWidget(self.path_label)
        snippet_bar = QHBoxLayout(); snippet_bar.addWidget(QLabel("挿入")); self.snippet_combo = QComboBox()
        for label, snippet in PORYSCRIPT_SNIPPETS:
            self.snippet_combo.addItem(label, snippet)
        self.insert_snippet_button = QPushButton("呼び出す"); self.insert_snippet_button.clicked.connect(self.insert_snippet); snippet_bar.addWidget(self.snippet_combo, 1); snippet_bar.addWidget(self.insert_snippet_button); right_layout.addLayout(snippet_bar)
        self.editor = QPlainTextEdit(); self.editor.textChanged.connect(self.changed); right_layout.addWidget(self.editor); actions = QHBoxLayout(); self.save_button = QPushButton("保存"); self.save_button.clicked.connect(self.save); self.compile_button = QPushButton("コンパイル"); self.compile_button.clicked.connect(self.compile_current); actions.addWidget(self.save_button); actions.addWidget(self.compile_button); actions.addStretch(); right_layout.addLayout(actions); right_layout.addWidget(QLabel("コンパイルログ")); self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(190); right_layout.addWidget(self.log); split.addWidget(right); split.setSizes([500, 980]); layout.addWidget(split)

    def poryscript_tool_dir(self) -> Path | None:
        raw_dir = str(self.window.settings.value("poryscript/tool_dir", "") or "").strip()
        if raw_dir:
            path = Path(raw_dir)
            return path.parent if path.is_file() else path
        legacy = str(self.window.settings.value("poryscript/executable", "") or "").strip()
        if legacy:
            path = Path(legacy)
            return path.parent if path.is_file() else path
        return None

    def poryscript_executable(self) -> Path | None:
        tool_dir = self.poryscript_tool_dir()
        if not tool_dir:
            return None
        if tool_dir.is_file():
            return tool_dir if tool_dir.exists() else None
        candidates = ["poryscript.exe", "poryscript"]
        for name in candidates:
            executable = tool_dir / name
            if executable.exists():
                return executable
        return None

    def update_tool_state(self) -> None:
        tool_dir = self.poryscript_tool_dir(); executable = self.poryscript_executable(); configured = bool(tool_dir and tool_dir.exists() and executable and executable.exists())
        self.compile_button.setVisible(configured)
        self.tool_state.setText(f"Poryscript: {tool_dir}\nExecutable: {executable}" if configured else "Poryscript は未設定です。イベントの検索・閲覧・保存は利用できます。コンパイルは設定タブで Poryscript フォルダを指定してください。")

    def load(self) -> None:
        self.update_tool_state(); self.files.clear(); self.current = None; self.editor.clear(); self.path_label.setText("ファイル未選択")
        if not self.window.root_valid(): return
        for path in sorted(self.window.root.rglob("*.pory")):
            if ".git" in path.parts or "workspace" in path.parts: continue
            try: source = read_utf8(path)
            except UnicodeDecodeError: continue
            self.files.append(PoryFile(path, rel(self.window.root, path), datetime.fromtimestamp(path.stat().st_mtime), source, source))
        self.refresh(); self.window.status(f"Poryscript: {len(self.files)} .pory files")

    def filtered(self) -> list[PoryFile]:
        query = self.search.text().casefold().strip()
        return [item for item in self.files if not query or query in (item.path.name + "\n" + item.rel_path + "\n" + item.current).casefold()]

    def refresh(self) -> None:
        selected = self.current.path if self.current else None; self.tree.blockSignals(True); self.tree.clear()
        for entry in self.filtered():
            item = QTreeWidgetItem([("* " if entry.dirty else "") + entry.path.name, entry.rel_path, entry.modified.strftime("%Y-%m-%d %H:%M")]); item.setData(0, Qt.ItemDataRole.UserRole, entry); self.tree.addTopLevelItem(item)
            if selected == entry.path: self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

    def select(self) -> None:
        if self.current and not self.loading: self.current.current = self.editor.toPlainText()
        selected = self.tree.selectedItems()
        if not selected: return
        self.current = selected[0].data(0, Qt.ItemDataRole.UserRole); self.loading = True; self.editor.setPlainText(self.current.current); self.loading = False; self.path_label.setText(self.current.rel_path); self.refresh()

    def changed(self) -> None:
        if self.loading or not self.current: return
        self.current.current = self.editor.toPlainText(); self.refresh(); self.window.status(f"Poryscript modified: {self.current.rel_path}")

    def insert_snippet(self) -> None:
        snippet = self.snippet_combo.currentData()
        if not snippet:
            return
        cursor = self.editor.textCursor()
        cursor.insertText(str(snippet))
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def open_entry(self, entry: PoryFile) -> None:
        self.current = entry; self.loading = True; self.editor.setPlainText(entry.current); self.loading = False; self.path_label.setText(entry.rel_path); self.refresh()

    def add_created_file(self, path: Path) -> None:
        try: source = read_utf8(path)
        except OSError as error: QMessageBox.critical(self, "Poryscript read failed", str(error)); return
        existing = next((entry for entry in self.files if entry.path == path), None)
        if existing:
            existing.original = source; existing.current = source; existing.modified = datetime.fromtimestamp(path.stat().st_mtime); entry = existing
        else:
            entry = PoryFile(path, rel(self.window.root, path), datetime.fromtimestamp(path.stat().st_mtime), source, source); self.files.append(entry); self.files.sort(key=lambda item: item.rel_path.casefold())
        self.search.clear(); self.open_entry(entry); self.window.status(f"Created {entry.rel_path}")

    def new_from_template(self) -> None:
        if not self.window.root_valid(): QMessageBox.warning(self, "リポジトリ未選択", "先に有効なリポジトリルートを選択してください。"); return
        dialog = PoryTemplateDialog(self.window, allow_empty=True)
        if dialog.exec() and dialog.created_path: self.add_created_file(dialog.created_path)

    def template_from_template(self) -> None:
        if not self.window.root_valid(): QMessageBox.warning(self, "リポジトリ未選択", "先に有効なリポジトリルートを選択してください。"); return
        dialog = PoryTemplateDialog(self.window, allow_empty=False)
        if dialog.exec() and dialog.created_path: self.add_created_file(dialog.created_path)

    def manage_templates(self) -> None:
        PoryTemplateManagerDialog(self.window).exec()

    def import_inc(self) -> None:
        if not self.window.root_valid(): QMessageBox.warning(self, "リポジトリ未選択", "先に有効なリポジトリルートを選択してください。"); return
        selected, _ = QFileDialog.getOpenFileName(self, ".inc を読み込む", str(self.window.root / "data"), "Assembly include (*.inc)")
        if not selected: return
        path = Path(selected).resolve()
        try: path.relative_to(self.window.root.resolve())
        except ValueError:
            QMessageBox.warning(self, "ファイルが無効です", "選択中のリポジトリ配下の .inc ファイルを選択してください。"); return
        dialog = PoryIncImportDialog(self.window, path)
        if dialog.exec() and dialog.created_path: self.add_created_file(dialog.created_path)

    def save(self) -> bool:
        if not self.current or not self.current.dirty: return True
        try:
            disk = read_utf8(self.current.path)
            if disk != self.current.original: raise RuntimeError("File changed on disk. Reload before saving.")
            write_with_backup(self.current.path, self.current.current)
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Poryscript save failed", str(error)); return False
        self.current.original = self.current.current; self.current.modified = datetime.fromtimestamp(self.current.path.stat().st_mtime); self.refresh(); self.window.status(f"Saved {self.current.rel_path} with backup"); return True

    def compile_current(self) -> None:
        if not self.current: return
        tool_dir = self.poryscript_tool_dir(); executable = self.poryscript_executable()
        if not tool_dir or not tool_dir.exists() or not executable or not executable.exists(): self.update_tool_state(); return
        if not self.save(): return
        source_dir = Path(self.window.settings.value("poryscript/source_dir", str(self.window.root)))
        output_dir = Path(self.window.settings.value("poryscript/output_dir", str(source_dir)))
        try: relative = self.current.path.relative_to(source_dir)
        except ValueError: relative = Path(self.current.path.name)
        output = output_dir / relative.with_suffix(".inc"); output.parent.mkdir(parents=True, exist_ok=True)
        self.log.clear(); self.log.appendPlainText(f"> {executable} -i {self.current.path} -o {output}\nworkdir: {tool_dir}")
        self.process = QProcess(self); self.process.setWorkingDirectory(str(tool_dir))
        environment = QProcessEnvironment.systemEnvironment(); separator = ";" if sys.platform.startswith("win") else ":"; environment.insert("PATH", str(tool_dir) + separator + environment.value("PATH")); self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(lambda: self.log.appendPlainText(bytes(self.process.readAllStandardOutput()).decode(errors="replace")))
        self.process.readyReadStandardError.connect(lambda: self.log.appendPlainText(bytes(self.process.readAllStandardError()).decode(errors="replace")))
        self.process.finished.connect(lambda code, _status: (self.log.appendPlainText(f"\n[終了コード] {code}"), self.window.status("Poryscript compile succeeded" if code == 0 else f"Poryscript compile failed: {code}")))
        self.process.start(str(executable), ["-i", str(self.current.path), "-o", str(output)]); self.window.status(f"Compiling {self.current.rel_path}")


class SettingsPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; layout = QVBoxLayout(self)
        group = QGroupBox("Poryscript 外部ツール"); form = QFormLayout(group); self.poryscript_dir = QLineEdit(); self.executable = self.poryscript_dir; browse_poryscript = QPushButton("参照..."); browse_poryscript.clicked.connect(self.choose_poryscript_dir); poryscript_row = QWidget(); poryscript_box = QHBoxLayout(poryscript_row); poryscript_box.setContentsMargins(0, 0, 0, 0); poryscript_box.addWidget(self.poryscript_dir); poryscript_box.addWidget(browse_poryscript); self.source_dir = QLineEdit(); self.output_dir = QLineEdit(); form.addRow("Poryscript フォルダ", poryscript_row); form.addRow("source directory", self.source_dir); form.addRow("output directory", self.output_dir); layout.addWidget(group)
        command_group = QGroupBox("コマンドライン入力スクリプト"); command_layout = QVBoxLayout(command_group); command_form = QFormLayout(); self.command_enabled = QCheckBox("有効にする（起動時に指定端末を開く）"); self.terminal_type = QComboBox(); self.terminal_command = QLineEdit(); self.run_template = QLineEdit(); self.last_script = QLabel("未実行")
        for label, value in TERMINAL_TYPES:
            self.terminal_type.addItem(label, value)
        self.terminal_type.currentIndexChanged.connect(self.apply_terminal_defaults)
        command_form.addRow("", self.command_enabled); command_form.addRow("端末種別", self.terminal_type); command_form.addRow("端末起動コマンド", self.terminal_command); command_form.addRow("スクリプト実行テンプレート", self.run_template); command_form.addRow("前回実行スクリプト", self.last_script); command_layout.addLayout(command_form)
        note = QLabel("{ROOT} は現在のリポジトリ、{WSL_ROOT} は /mnt/c/... 形式、{SCRIPT} は登録スクリプト本文に置換されます。"); note.setWordWrap(True); command_layout.addWidget(note)
        self.script_names: list[QLineEdit] = []; self.script_bodies: list[QPlainTextEdit] = []; self.script_confirms: list[QCheckBox] = []
        for index in range(1, 6):
            row = QHBoxLayout(); name = QLineEdit(); name.setPlaceholderText(f"スクリプト{index}名"); confirm = QCheckBox("確認"); body = QPlainTextEdit(); body.setPlaceholderText("例: make clean"); body.setMaximumHeight(70); self.script_names.append(name); self.script_bodies.append(body); self.script_confirms.append(confirm); row.addWidget(QLabel(f"{index}")); row.addWidget(name, 1); row.addWidget(confirm); row.addWidget(body, 3); command_layout.addLayout(row)
        layout.addWidget(command_group)
        save = QPushButton("設定を保存"); save.clicked.connect(self.save); layout.addWidget(save); layout.addStretch(); self.load()

    def apply_terminal_defaults(self) -> None:
        terminal_type = self.terminal_type.currentData() or DEFAULT_TERMINAL_TYPE
        open_template, run_template = TERMINAL_TEMPLATES.get(terminal_type, TERMINAL_TEMPLATES[DEFAULT_TERMINAL_TYPE])
        self.terminal_command.setText(open_template)
        self.run_template.setText(run_template)

    def choose_poryscript_dir(self) -> None:
        start = self.poryscript_dir.text().strip() or str(self.window.root)
        selected = QFileDialog.getExistingDirectory(self, "Poryscript フォルダを選択", start)
        if selected:
            self.poryscript_dir.setText(selected)

    def load(self) -> None:
        tool_dir = str(self.window.settings.value("poryscript/tool_dir", "") or "")
        if not tool_dir:
            legacy = str(self.window.settings.value("poryscript/executable", "") or "")
            tool_dir = str(Path(legacy).parent) if legacy else ""
        self.poryscript_dir.setText(tool_dir); self.source_dir.setText(self.window.settings.value("poryscript/source_dir", str(self.window.root))); self.output_dir.setText(self.window.settings.value("poryscript/output_dir", str(self.window.root)))
        self.command_enabled.setChecked(self.window.setting_bool("command_line/enabled", False))
        terminal_type = str(self.window.settings.value("command_line/terminal_type", DEFAULT_TERMINAL_TYPE) or DEFAULT_TERMINAL_TYPE)
        self.terminal_type.blockSignals(True); index = self.terminal_type.findData(terminal_type); self.terminal_type.setCurrentIndex(index if index >= 0 else 0); self.terminal_type.blockSignals(False)
        self.terminal_command.setText(self.window.settings.value("command_line/open_command", DEFAULT_TERMINAL_COMMAND))
        self.run_template.setText(self.window.settings.value("command_line/run_template", DEFAULT_SCRIPT_RUN_TEMPLATE))
        last_index = str(self.window.settings.value("command_line/last_script_index", "") or "")
        last_name = str(self.window.settings.value("command_line/last_script_name", "") or "")
        last_code = str(self.window.settings.value("command_line/last_exit_code", "") or "")
        self.last_script.setText("未実行" if not last_index else f"{last_index}: {last_name} / 終了コード {last_code}")
        defaults = DEFAULT_COMMAND_SCRIPTS
        for index, (name_widget, body_widget, confirm_widget) in enumerate(zip(self.script_names, self.script_bodies, self.script_confirms), 1):
            default_name, default_body = defaults[index - 1]
            name_widget.setText(self.window.settings.value(f"command_line/scripts/{index}/name", default_name))
            body_widget.setPlainText(self.window.settings.value(f"command_line/scripts/{index}/body", default_body))
            confirm_widget.setChecked(self.window.setting_bool(f"command_line/scripts/{index}/confirm", True))

    def save(self) -> None:
        self.window.settings.setValue("poryscript/tool_dir", self.poryscript_dir.text().strip()); self.window.settings.setValue("poryscript/source_dir", self.source_dir.text().strip()); self.window.settings.setValue("poryscript/output_dir", self.output_dir.text().strip())
        self.window.settings.setValue("command_line/enabled", self.command_enabled.isChecked()); self.window.settings.setValue("command_line/terminal_type", self.terminal_type.currentData() or DEFAULT_TERMINAL_TYPE); self.window.settings.setValue("command_line/open_command", self.terminal_command.text().strip()); self.window.settings.setValue("command_line/run_template", self.run_template.text().strip())
        for index, (name_widget, body_widget, confirm_widget) in enumerate(zip(self.script_names, self.script_bodies, self.script_confirms), 1):
            self.window.settings.setValue(f"command_line/scripts/{index}/name", name_widget.text().strip())
            self.window.settings.setValue(f"command_line/scripts/{index}/body", body_widget.toPlainText().strip())
            self.window.settings.setValue(f"command_line/scripts/{index}/confirm", confirm_widget.isChecked())
        self.window.poryscript.update_tool_state(); self.window.update_command_actions(); self.window.status("Tool settings saved")
        if self.command_enabled.isChecked():
            self.window.maybe_auto_open_terminal(force=True)


TYPE_LABELS = {
    "TYPE_NONE": "なし", "TYPE_NORMAL": "ノーマル", "TYPE_FIGHTING": "かくとう",
    "TYPE_FLYING": "ひこう", "TYPE_POISON": "どく", "TYPE_GROUND": "じめん",
    "TYPE_ROCK": "いわ", "TYPE_BUG": "むし", "TYPE_GHOST": "ゴースト",
    "TYPE_STEEL": "はがね", "TYPE_MYSTERY": "???", "TYPE_FIRE": "ほのお",
    "TYPE_WATER": "みず", "TYPE_GRASS": "くさ", "TYPE_ELECTRIC": "でんき",
    "TYPE_PSYCHIC": "エスパー", "TYPE_ICE": "こおり", "TYPE_DRAGON": "ドラゴン",
    "TYPE_DARK": "あく", "TYPE_FAIRY": "フェアリー", "TYPE_STELLAR": "ステラ",
}
CATEGORY_LABELS = {
    "DAMAGE_CATEGORY_PHYSICAL": "物理",
    "DAMAGE_CATEGORY_SPECIAL": "特殊",
    "DAMAGE_CATEGORY_STATUS": "変化",
}
HIDDEN_POWER_TYPE_ORDER = [
    "TYPE_FIGHTING", "TYPE_FLYING", "TYPE_POISON", "TYPE_GROUND",
    "TYPE_ROCK", "TYPE_BUG", "TYPE_GHOST", "TYPE_STEEL",
    "TYPE_FIRE", "TYPE_WATER", "TYPE_GRASS", "TYPE_ELECTRIC",
    "TYPE_PSYCHIC", "TYPE_ICE", "TYPE_DRAGON", "TYPE_DARK",
]
EFFECT_LABELS = {
    "EFFECT_HIT": "通常ダメージ",
    "EFFECT_SLEEP": "ねむり状態にする",
    "EFFECT_POISON": "どく状態にする",
    "EFFECT_BURN": "やけど状態にする",
    "EFFECT_PARALYSIS": "まひ状態にする",
    "EFFECT_CONFUSE": "こんらん状態にする",
}
PRIMARY_EFFECT_LABELS = {
    "EFFECT_HIT": "通常ダメージ", "EFFECT_STAT_CHANGE": "能力変化", "EFFECT_NON_VOLATILE_STATUS": "状態異常",
    "EFFECT_ABSORB": "HP吸収", "EFFECT_RESTORE_HP": "HP回復", "EFFECT_OHKO": "一撃必殺",
    "EFFECT_CONFUSE": "こんらん", "EFFECT_LEECH_SEED": "やどりぎのタネ", "EFFECT_PROTECT": "まもる系",
    "EFFECT_WEATHER": "天候", "EFFECT_TERRAIN_BOOST": "フィールド", "EFFECT_HIT_SWITCH_TARGET": "攻撃して交代",
}
TARGET_LABELS = {
    "TARGET_SELECTED": "選んだ相手", "TARGET_DEPENDS": "技により異なる", "TARGET_RANDOM": "ランダムな相手",
    "TARGET_BOTH": "相手全体", "TARGET_USER": "自分", "TARGET_FOES_AND_ALLY": "自分以外全体",
    "TARGET_OPPONENTS_FIELD": "相手の場", "TARGET_ALLY": "味方", "TARGET_USER_AND_ALLY": "自分と味方",
    "TARGET_USER_OR_ALLY": "自分または味方", "TARGET_FOES_AND_ALLY": "自分以外全体",
}
MOVE_EFFECT_LABELS = {
    "MOVE_EFFECT_SLEEP": "ねむり", "MOVE_EFFECT_POISON": "どく", "MOVE_EFFECT_BURN": "やけど",
    "MOVE_EFFECT_FREEZE": "こおり", "MOVE_EFFECT_FROSTBITE": "しもやけ", "MOVE_EFFECT_PARALYSIS": "まひ",
    "MOVE_EFFECT_TOXIC": "もうどく", "MOVE_EFFECT_CONFUSION": "こんらん", "MOVE_EFFECT_FLINCH": "ひるみ",
    "MOVE_EFFECT_STAT_PLUS": "能力を上げる", "MOVE_EFFECT_STAT_MINUS": "能力を下げる",
    "MOVE_EFFECT_LEECH_SEED": "やどりぎのタネ", "MOVE_EFFECT_WRAP": "バインド",
    "MOVE_EFFECT_PAYDAY": "お金を得る", "MOVE_EFFECT_RECHARGE": "反動で動けない",
}
EVOLUTION_LABELS = {
    "EVO_LEVEL": "Lv{value}", "EVO_LEVEL_BATTLE_ONLY": "バトル中にLv{value}",
    "EVO_TRADE": "通信交換", "EVO_ITEM": "道具: {value}",
    "EVO_FRIENDSHIP": "なつき", "EVO_FRIENDSHIP_DAY": "なつき（昼）",
    "EVO_FRIENDSHIP_NIGHT": "なつき（夜）",
}


def enum_values(path: Path, prefix: str) -> dict[str, int]:
    """Read direct numeric values from the project's ordered enum definitions."""
    result: dict[str, int] = {}
    value = -1
    if not path.exists():
        return result
    for line in read_utf8(path).splitlines():
        match = re.match(rf"\s*({re.escape(prefix)}[A-Z0-9_]+)\s*(?:=\s*([^,\s/]+))?\s*,", line)
        if not match:
            continue
        name, assigned = match.groups()
        if assigned and assigned.isdigit():
            value = int(assigned)
        elif assigned:
            continue
        else:
            value += 1
        result[name] = value
    return result


def define_values(path: Path, prefixes: tuple[str, ...]) -> dict[str, int]:
    """Read simple numeric #define constants used by Frontier data tables."""
    result: dict[str, int] = {}
    if not path.exists():
        return result
    for line in read_utf8(path).splitlines():
        match = re.match(r"\s*#define\s+([A-Z0-9_]+)\s+(.+?)(?:\s*//.*)?$", line)
        if not match:
            continue
        name, value = match.groups()
        if not any(name.startswith(prefix) for prefix in prefixes):
            continue
        value = value.strip()
        if re.fullmatch(r"\d+", value):
            result[name] = int(value)
    return result


def token_value(token: str, values: dict[str, int]) -> int | None:
    """Evaluate the small constant expressions used in Factory range rows."""
    token = token.strip()
    if re.fullmatch(r"\d+", token):
        return int(token)
    if token in values:
        return values[token]
    match = re.fullmatch(r"([A-Z0-9_]+)\s*([-+])\s*(\d+)", token)
    if match and match.group(1) in values:
        base = values[match.group(1)]
        delta = int(match.group(3))
        return base + delta if match.group(2) == "+" else base - delta
    return None


def first_token(value: str, prefix: str, fallback: str) -> str:
    match = re.search(rf"\b({re.escape(prefix)}[A-Z0-9_]+)\b", value)
    return match.group(1) if match else fallback


def numeric_args(value: str, count: int, default: int = 0) -> list[int]:
    args = []
    for arg in macro_arguments(value):
        stripped = arg.strip()
        args.append(int(stripped) if re.fullmatch(r"-?\d+", stripped) else default)
    return (args + [default] * count)[:count]


def bool_literal(value: str) -> bool:
    return value.strip() in {"TRUE", "true", "1"}


def macro_arguments(value: str) -> list[str]:
    start, end = value.find("("), value.rfind(")")
    if start < 0 or end <= start:
        start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        return []
    return [part.strip() for part in value[start + 1:end].split(",")]


def field_arguments(block: str, name: str) -> list[str]:
    found = raw_field(block, name)
    return macro_arguments(found[2]) if found else []


def display_enum_token(value: str, prefix: str, fallback: str) -> str:
    found = re.search(rf"\b({re.escape(prefix)}[A-Z0-9_]+)\b", value)
    return found.group(1) if found else fallback


def unique_tokens(tokens: Iterable[str], keep_none: bool = True) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if not keep_none and token.endswith("_NONE"):
            continue
        if token not in seen:
            seen.add(token); result.append(token)
    return result


def display_integer(value: str) -> int:
    conditional = re.search(r"\?\s*(-?\d+)", value)
    if conditional:
        return int(conditional.group(1))
    direct = re.fullmatch(r"\s*(-?\d+)\s*", value)
    return int(direct.group(1)) if direct else 0


def string_from_record(record: SourceRecord, name: str) -> str:
    parsed = string_field(record.block, name)
    return parsed[2] if parsed else record.values.get(name, "")


def set_record_string_macro(block: str, field_name: str, macro: str) -> str:
    raw = raw_field(block, field_name)
    if not raw:
        return block
    start, end, value = raw
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", value)
    if not match:
        return block
    return block[:start + match.start(1)] + macro + block[start + match.end(1):]


def replace_record_fields(record: SourceRecord, values: dict[str, str], strings: set[str], string_macros: dict[str, str] | None = None) -> str:
    """Apply supported field changes to one record without reformatting its source."""
    string_macros = string_macros or {}
    replacements: list[tuple[int, int, str]] = []
    additions: list[str] = []
    for field_name, value in values.items():
        parsed = string_field(record.block, field_name) if field_name in strings else None
        raw = raw_field(record.block, field_name)
        if parsed:
            start, end, old, _macro = parsed
            if value != old:
                replacements.append((start, end, quote_c_text(value)))
        elif raw:
            if value != raw[2]:
                replacements.append((raw[0], raw[1], value))
        elif value not in {"", "FALSE", "0"}:
            if field_name in strings:
                macro = string_macros.get(field_name, "_")
                additions.append(f"        .{field_name} = {macro}({quote_c_text(value)}),\n")
            else:
                additions.append(f"        .{field_name} = {value},\n")
    updated = record.block
    for start, end, value in sorted(replacements, reverse=True):
        updated = updated[:start] + value + updated[end:]
    for field_name, macro in string_macros.items():
        if field_name in strings and raw_field(updated, field_name):
            updated = set_record_string_macro(updated, field_name, macro)
    if additions:
        updated = ensure_designated_initializer_commas(updated)
        insert_at = updated.rfind("}")
        line_start = updated.rfind("\n", 0, insert_at) + 1
        if line_start > 0:
            insert_at = line_start
        updated = updated[:insert_at] + "".join(additions) + updated[insert_at:]
    return updated


class DiffDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, before: str, after: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(1000, 680)
        layout = QVBoxLayout(self); text = QPlainTextEdit(); text.setReadOnly(True)
        diff = difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile="saved", tofile="pending", lineterm="")
        text.setPlainText("\n".join(diff) or "No changes.")
        layout.addWidget(text); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class RecordStudioBase(QWidget):
    """Shared deferred-save behavior for the species and move studios."""
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.records: list[SourceRecord] = []; self.contents: dict[Path, str] = {}
        self.current: SourceRecord | None = None; self.states: dict[str, dict[str, str]] = {}; self.loading = False

    def values_for(self, record: SourceRecord) -> dict[str, str]:
        raise NotImplementedError

    def proposed_block(self, record: SourceRecord) -> str:
        raise NotImplementedError

    def capture_current(self) -> None:
        if self.current and not self.loading:
            self.states[self.current.key] = self.values_for(self.current)

    def has_changes(self) -> bool:
        self.capture_current()
        return any(self.proposed_block(record) != record.block for record in self.records if record.key in self.states)

    def show_diff(self) -> None:
        self.capture_current()
        if not self.current:
            return
        DiffDialog(self, f"Diff: {self.current.key}", self.current.block, self.proposed_block(self.current)).exec()

    def save(self) -> None:
        self.capture_current()
        changed = [record for record in self.records if record.key in self.states and self.proposed_block(record) != record.block]
        if not changed:
            self.window.status("No pending changes")
            return
        by_path: dict[Path, list[SourceRecord]] = {}
        for record in changed:
            by_path.setdefault(record.path, []).append(record)
        try:
            for path, records in by_path.items():
                source = self.contents[path]
                if read_utf8(path) != source:
                    raise RuntimeError(f"{rel(self.window.root, path)} changed on disk; reload before saving.")
                for record in sorted(records, key=lambda item: item.start, reverse=True):
                    source = source[:record.start] + self.proposed_block(record) + source[record.end:]
                write_with_backup(path, source)
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Save failed", str(error)); return
        selected = self.current.key if self.current else ""
        self.load(); self.select_key(selected)
        self.window.status(f"Saved {len(changed)} record(s) with backups")

    def select_key(self, key: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole).key == key:
                self.table.selectRow(row); return


class PokemonStudioPanel(RecordStudioBase):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(window)
        self.species_numbers: dict[str, int] = {}; self.dex_numbers: dict[str, int] = {}; self.species_names: dict[str, str] = {}
        self.ability_names: dict[str, tuple[str, str]] = {}; self.move_names: dict[str, str] = {}; self.graphics: dict[str, Path] = {}
        self.search = QLineEdit(); self.search.setPlaceholderText("フシギダネ / SPECIES_BULBASAUR"); self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["No.", "ポケモン", "タイプ", "内部 ID"]); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.itemSelectionChanged.connect(self.select)
        self.name = QLineEdit(); self.category = QLineEdit(); self.type1 = self.type_combo(); self.type2 = self.type_combo(); self.height = QSpinBox(); self.height.setRange(0, 999); self.weight = QSpinBox(); self.weight.setRange(0, 99999); self.description = QPlainTextEdit(); self.description.setMaximumHeight(180)
        self.stats: dict[str, QSpinBox] = {field: self.stat_spin() for field in ("baseHP", "baseAttack", "baseDefense", "baseSpAttack", "baseSpDefense", "baseSpeed")}
        self.ability_boxes = [QComboBox(), QComboBox(), QComboBox()]; self.evolutions = QListWidget(); self.evolutions.itemDoubleClicked.connect(lambda item: self.window.open_species(item.data(Qt.ItemDataRole.UserRole))); self.evolution_raw = QPlainTextEdit(); self.evolution_raw.setMaximumHeight(105); self.evolution_raw.textChanged.connect(self.changed); self.evo_method = QComboBox(); self.evo_value = QLineEdit("0"); self.evo_target = QComboBox()
        self.learnset = QTableWidget(0, 2); self.learnset.setHorizontalHeaderLabels(["Lv", "わざ"]); self.learnset.itemDoubleClicked.connect(self.jump_move); self.learnset.itemSelectionChanged.connect(self.select_learnset_row); self.learnset.itemChanged.connect(self.learnset_changed); self.learnset_kind = QComboBox(); self.learnset_source = QComboBox(); self.learnset_kind.currentIndexChanged.connect(self.change_learnset_kind); self.learnset_source.currentIndexChanged.connect(self.load_selected_learnset); self.learn_level = QSpinBox(); self.learn_level.setRange(0, 100); self.learn_move = QComboBox(); self.learnset_dirty = False; self.learnset_original = ""; self.learnset_path: Path | None = None
        self.image = QLabel("画像なし"); self.image.setAlignment(Qt.AlignmentFlag.AlignCenter); self.cry = QLabel(); self.summary_name = QLabel(); self.summary_meta = QLabel(); self.summary_total = QLabel()
        self.build()

    def type_combo(self) -> QComboBox:
        combo = QComboBox()
        for internal, label in TYPE_LABELS.items(): combo.addItem(label, internal)
        combo.currentIndexChanged.connect(self.changed)
        return combo

    @staticmethod
    def stat_spin() -> QSpinBox:
        spin = QSpinBox(); spin.setRange(0, 255); spin.valueChanged.connect(lambda: None); return spin

    def build(self) -> None:
        layout = QVBoxLayout(self); split = QSplitter(Qt.Orientation.Horizontal); left = QWidget(); left_layout = QVBoxLayout(left); left_layout.addWidget(self.search); left_layout.addWidget(self.table); split.addWidget(left)
        right = QWidget(); right_layout = QVBoxLayout(right); card = QFrame(); card.setFrameShape(QFrame.Shape.StyledPanel); card_layout = QVBoxLayout(card); self.summary_name.setStyleSheet("font-size: 24px; font-weight: 700;"); card_layout.addWidget(self.summary_name); card_layout.addWidget(self.summary_meta); card_layout.addWidget(self.summary_total); right_layout.addWidget(card)
        tabs = QTabWidget(); self.tabs = tabs
        basic = QWidget(); basic_form = QFormLayout(basic); basic_form.addRow("名前", self.name); basic_form.addRow("分類", self.category); basic_form.addRow("タイプ1", self.type1); basic_form.addRow("タイプ2", self.type2); basic_form.addRow("高さ (dm)", self.height); basic_form.addRow("重さ (hg)", self.weight); tabs.addTab(basic, "基本")
        stats = QWidget(); stats_form = QFormLayout(stats); labels = {"baseHP": "HP", "baseAttack": "こうげき", "baseDefense": "ぼうぎょ", "baseSpAttack": "とくこう", "baseSpDefense": "とくぼう", "baseSpeed": "すばやさ"}; [stats_form.addRow(labels[key], box) for key, box in self.stats.items()]; tabs.addTab(stats, "能力")
        ability = QWidget(); ability_layout = QVBoxLayout(ability)
        for index, combo in enumerate(self.ability_boxes):
            row = QHBoxLayout(); row.addWidget(combo); button = QPushButton("参照"); button.clicked.connect(lambda _checked=False, slot=index: self.show_ability(slot)); row.addWidget(button); ability_layout.addLayout(row)
        ability_layout.addStretch(); tabs.addTab(ability, "特性")
        evo = QWidget(); evo_layout = QVBoxLayout(evo); evo_layout.addWidget(self.evolutions); evo_layout.addWidget(QLabel("進化定義（複雑な条件もこの式を維持します）")); evo_layout.addWidget(self.evolution_raw); evo_controls = QHBoxLayout();
        for internal, label in (("EVO_LEVEL", "レベル"), ("EVO_TRADE", "通信交換"), ("EVO_ITEM", "道具"), ("EVO_FRIENDSHIP", "なつき")):
            self.evo_method.addItem(label, internal)
        evo_controls.addWidget(self.evo_method); evo_controls.addWidget(self.evo_value); evo_controls.addWidget(self.evo_target); add_evo = QPushButton("進化を追加"); add_evo.clicked.connect(self.add_evolution); evo_controls.addWidget(add_evo); evo_layout.addLayout(evo_controls); tabs.addTab(evo, "進化")
        moves = QWidget(); moves_layout = QVBoxLayout(moves); move_controls = QHBoxLayout(); self.learnset_kind.addItem("レベルアップ", "levelUpLearnset"); self.learnset_kind.addItem("タマゴ技", "eggMoveLearnset"); self.learnset_kind.addItem("教え技・マシン", "teachableLearnset"); move_controls.addWidget(self.learnset_kind); move_controls.addWidget(self.learnset_source); moves_layout.addLayout(move_controls); moves_layout.addWidget(self.learnset); edit_controls = QHBoxLayout(); edit_controls.addWidget(QLabel("レベル")); edit_controls.addWidget(self.learn_level); edit_controls.addWidget(self.learn_move); update_move = QPushButton("追加 / 更新"); update_move.clicked.connect(self.add_or_update_learnset_row); delete_move = QPushButton("選択を削除"); delete_move.clicked.connect(self.delete_learnset_row); edit_controls.addWidget(update_move); edit_controls.addWidget(delete_move); moves_layout.addLayout(edit_controls); learnset_buttons = QHBoxLayout(); diff_learnset = QPushButton("習得技の差分"); diff_learnset.clicked.connect(self.show_learnset_diff); save_learnset = QPushButton("習得技を保存"); save_learnset.clicked.connect(self.save_learnset); learnset_buttons.addStretch(); learnset_buttons.addWidget(diff_learnset); learnset_buttons.addWidget(save_learnset); moves_layout.addLayout(learnset_buttons); tabs.addTab(moves, "技")
        dex = QWidget(); dex_layout = QVBoxLayout(dex); dex_layout.addWidget(QLabel("図鑑説明")); dex_layout.addWidget(self.description); tabs.addTab(dex, "図鑑")
        graphics = QWidget(); graphics_layout = QVBoxLayout(graphics); graphics_layout.addWidget(self.image); graphics_layout.addWidget(self.cry); tabs.addTab(graphics, "画像")
        right_layout.addWidget(tabs); split.addWidget(right); split.setSizes([520, 920]); layout.addWidget(split)
        for control in [self.name, self.category, self.height, self.weight, self.description, *self.stats.values()]:
            signal = control.textChanged if isinstance(control, (QLineEdit, QPlainTextEdit)) else control.valueChanged
            signal.connect(self.changed)

    def load(self) -> None:
        if not self.window.root_valid(): return
        root = self.window.root; paths = list((root / "src/data/pokemon/species_info").glob("*_families.h")) + [root / "src/data/pokemon/species_info.h"]
        wanted = ["speciesName", "categoryName", "description", "types", "baseHP", "baseAttack", "baseDefense", "baseSpAttack", "baseSpDefense", "baseSpeed", "abilities", "height", "weight", "cryId", "frontPic", "levelUpLearnset", "teachableLearnset", "eggMoveLearnset", "evolutions", "natDexNum"]
        self.records, self.contents = indexed_records(root, [path for path in paths if path.exists()], "SPECIES_", wanted); self.states.clear(); self.current = None
        self.species_numbers = enum_values(root / "include/constants/species.h", "SPECIES_"); self.dex_numbers = enum_values(root / "include/constants/pokedex.h", "NATIONAL_DEX_")
        self.species_names = {record.key: string_from_record(record, "speciesName") for record in self.records}
        ability_records, _ = indexed_records(root, [root / "src/data/abilities.h"], "ABILITY_", ["name", "description"])
        self.ability_names = {record.key: (string_from_record(record, "name"), string_from_record(record, "description")) for record in ability_records}
        move_records, _ = indexed_records(root, [root / "src/data/moves_info.h"], "MOVE_", ["name"]); self.move_names = {record.key: string_from_record(record, "name") for record in move_records}
        self.graphics.clear(); graphics_file = root / "src/data/graphics/pokemon.h"
        if graphics_file.exists():
            for match in re.finditer(r"\b(gMon(?:FrontPic|BackPic|Icon)_[A-Za-z0-9_]+)\[\].*?\"(graphics/pokemon/[^\"]+\.png)\"", read_utf8(graphics_file)):
                self.graphics[match.group(1)] = root / match.group(2)
        self.populate_abilities(); self.populate_evolution_targets(); self.populate_move_choices(); self.refresh()

    def populate_evolution_targets(self) -> None:
        self.evo_target.clear()
        for key, name in sorted(self.species_names.items(), key=lambda item: self.number_for(next(record for record in self.records if record.key == item[0]))):
            self.evo_target.addItem(f"{name}  [{key}]", key)

    def populate_move_choices(self) -> None:
        self.learn_move.clear()
        for key, name in sorted(self.move_names.items(), key=lambda item: item[1]):
            self.learn_move.addItem(f"{name}  [{key}]", key)

    def populate_abilities(self) -> None:
        for combo in self.ability_boxes:
            combo.blockSignals(True); combo.clear(); combo.addItem("なし", "ABILITY_NONE")
            for key, (name, _description) in sorted(self.ability_names.items(), key=lambda item: item[1][0]): combo.addItem(f"{name}  [{key}]", key)
            combo.currentIndexChanged.connect(self.changed); combo.blockSignals(False)

    def record_types(self, record: SourceRecord) -> list[str]:
        args = field_arguments(record.block, "types"); return [arg for arg in args if arg in TYPE_LABELS] or ["TYPE_NONE", "TYPE_NONE"]

    def number_for(self, record: SourceRecord) -> int:
        dex = record.values.get("natDexNum", "")
        return self.dex_numbers.get(dex, self.species_numbers.get(record.key, 0))

    def refresh(self) -> None:
        query = self.search.text().casefold(); rows = [record for record in self.records if not query or query in (record.key + " " + self.species_names.get(record.key, "")).casefold()]
        self.table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            types = "/".join(TYPE_LABELS.get(value, value) for value in self.record_types(record))
            values = [f"No.{self.number_for(record):03}" if self.number_for(record) else "-", self.species_names.get(record.key, record.key), types, record.key]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, record); self.table.setItem(row, column, item)

    def default_values(self, record: SourceRecord) -> dict[str, str]:
        types = self.record_types(record); abilities = field_arguments(record.block, "abilities")
        values = {field: string_from_record(record, field) if field in {"speciesName", "categoryName", "description"} else record.values.get(field, "0") for field in ["speciesName", "categoryName", "description", "baseHP", "baseAttack", "baseDefense", "baseSpAttack", "baseSpDefense", "baseSpeed", "height", "weight", "evolutions"]}
        values.update({"types": record.values.get("types", f"MON_TYPES({types[0]}, {types[1] if len(types) > 1 else types[0]})"), "abilities": record.values.get("abilities", "{ " + ", ".join((abilities + ["ABILITY_NONE"] * 3)[:3]) + " }")})
        return values

    def values_for(self, record: SourceRecord) -> dict[str, str]:
        baseline = self.states.get(record.key, self.default_values(record)); baseline_types = macro_arguments(baseline["types"])
        selected_types = [self.type1.currentData(), self.type2.currentData()]
        original_types = [baseline_types[0], baseline_types[1] if len(baseline_types) > 1 else baseline_types[0]] if baseline_types else ["TYPE_NONE", "TYPE_NONE"]
        return {
            "speciesName": self.name.text(), "categoryName": self.category.text(), "description": self.description.toPlainText(),
            "types": baseline["types"] if selected_types == original_types else f"MON_TYPES({selected_types[0]}, {selected_types[1]})",
            "abilities": "{ " + ", ".join(combo.currentData() for combo in self.ability_boxes) + " }",
            "evolutions": self.evolution_raw.toPlainText().strip(),
            "height": str(self.height.value()), "weight": str(self.weight.value()),
            **{field: str(box.value()) for field, box in self.stats.items()},
        }

    def proposed_block(self, record: SourceRecord) -> str:
        return replace_record_fields(record, self.states.get(record.key, self.default_values(record)), {"speciesName", "categoryName", "description"})

    def select(self) -> None:
        self.capture_current(); selected = self.table.selectedItems()
        if not selected: return
        self.current = selected[0].data(Qt.ItemDataRole.UserRole); values = self.states.get(self.current.key, self.default_values(self.current)); self.loading = True
        self.name.setText(values["speciesName"]); self.category.setText(values["categoryName"]); self.description.setPlainText(values["description"]); self.height.setValue(int(values["height"]) if values["height"].isdigit() else 0); self.weight.setValue(int(values["weight"]) if values["weight"].isdigit() else 0)
        for field, box in self.stats.items(): box.setValue(int(values[field]) if values[field].isdigit() else 0)
        types = macro_arguments(values["types"]); self.set_combo(self.type1, types[0] if types else "TYPE_NONE"); self.set_combo(self.type2, types[1] if len(types) > 1 else (types[0] if types else "TYPE_NONE"))
        abilities = re.findall(r"ABILITY_[A-Z0-9_]+", values["abilities"])
        for index, combo in enumerate(self.ability_boxes): self.set_combo(combo, abilities[index] if index < len(abilities) else "ABILITY_NONE")
        self.evolution_raw.setPlainText(values["evolutions"]); self.loading = False; self.update_summary(); self.update_evolutions(); self.rebuild_learnset_sources(); self.update_graphics()

    @staticmethod
    def set_combo(combo: QComboBox, data: str) -> None:
        index = combo.findData(data); combo.setCurrentIndex(index if index >= 0 else 0)

    def changed(self) -> None:
        if not self.loading and self.current: self.update_summary(); self.window.status(f"Pending changes: {self.current.key}")

    def update_summary(self) -> None:
        if not self.current: return
        total = sum(box.value() for box in self.stats.values()); dex = self.number_for(self.current); types = "/".join((self.type1.currentText(), self.type2.currentText()))
        self.summary_name.setText(self.name.text() or self.current.key); self.summary_meta.setText(f"No.{dex:03}  {types}"); self.summary_total.setText(f"種族値合計  {total}")

    def update_evolutions(self) -> None:
        self.evolutions.clear()
        raw = self.evolution_raw.toPlainText().strip()
        for method, value, target in re.findall(r"\{\s*(EVO_[A-Z0-9_]+)\s*,\s*([^,}]+)\s*,\s*(SPECIES_[A-Z0-9_]+)", raw):
            condition = EVOLUTION_LABELS.get(method, method).format(value=value.strip()); name = self.species_names.get(target, target)
            from PySide6.QtWidgets import QListWidgetItem
            row = QListWidgetItem(f"→ {name}  {condition}"); row.setData(Qt.ItemDataRole.UserRole, target); self.evolutions.addItem(row)

    def learnset_files(self, kind: str) -> list[Path]:
        root = self.window.root / "src/data/pokemon"
        if kind == "levelUpLearnset": return sorted((root / "level_up_learnsets").glob("*.h"), key=lambda path: int(re.search(r"\d+", path.stem).group()) if re.search(r"\d+", path.stem) else -1, reverse=True)
        if kind == "eggMoveLearnset": return [root / "egg_moves.h"]
        return [root / "teachable_learnsets.h"]

    def rebuild_learnset_sources(self) -> None:
        self.learnset_kind.blockSignals(True); self.learnset_kind.setCurrentIndex(0); self.learnset_kind.blockSignals(False); self.change_learnset_kind()

    def change_learnset_kind(self) -> None:
        self.learnset_source.blockSignals(True); self.learnset_source.clear()
        if self.current:
            pointer = self.current.values.get(self.learnset_kind.currentData(), "")
            for path in self.learnset_files(self.learnset_kind.currentData()):
                if path.exists() and pointer and re.search(rf"\b{re.escape(pointer)}\[\]\s*=", read_utf8(path)):
                    self.learnset_source.addItem(rel(self.window.root, path), path)
        self.learnset_source.blockSignals(False); self.load_selected_learnset()

    def load_selected_learnset(self) -> None:
        self.learnset.setRowCount(0); self.learnset_dirty = False; self.learnset_original = ""; self.learnset_path = self.learnset_source.currentData()
        if not self.current or not self.learnset_path: return
        pointer = self.current.values.get(self.learnset_kind.currentData(), ""); source = read_utf8(self.learnset_path); match = re.search(rf"(\b{re.escape(pointer)}\[\]\s*=\s*\{{)(.*?)(\n\s*\}};)", source, re.S)
        if not match: return
        self.learnset_original = match.group(2); body = match.group(2); kind = self.learnset_kind.currentData()
        entries = re.findall(r"LEVEL_UP_MOVE\(\s*(\d+)\s*,\s*(MOVE_[A-Z0-9_]+)\s*\)", body) if kind == "levelUpLearnset" else [("", move) for move in re.findall(r"\b(MOVE_[A-Z0-9_]+)\b", body) if move != "MOVE_NONE"]
        self.learnset.blockSignals(True); self.learnset.setRowCount(len(entries))
        for row, (level, move) in enumerate(entries):
            self.learnset.setItem(row, 0, QTableWidgetItem(level)); item = QTableWidgetItem(self.move_names.get(move, move)); item.setData(Qt.ItemDataRole.UserRole, move); self.learnset.setItem(row, 1, item)
        self.learnset.blockSignals(False)

    def select_learnset_row(self) -> None:
        selected = self.learnset.selectedItems()
        if not selected: return
        row = selected[0].row(); self.learn_level.setValue(int(self.learnset.item(row, 0).text() or "0")); key = self.learnset.item(row, 1).data(Qt.ItemDataRole.UserRole); self.set_combo(self.learn_move, key)

    def learnset_changed(self, _item: QTableWidgetItem) -> None:
        if not self.loading: self.learnset_dirty = True

    def add_or_update_learnset_row(self) -> None:
        key = self.learn_move.currentData()
        if not key: return
        selected = self.learnset.selectedItems(); row = selected[0].row() if selected else self.learnset.rowCount()
        if row == self.learnset.rowCount(): self.learnset.insertRow(row)
        self.learnset.blockSignals(True); self.learnset.setItem(row, 0, QTableWidgetItem(str(self.learn_level.value()) if self.learnset_kind.currentData() == "levelUpLearnset" else "")); item = QTableWidgetItem(self.move_names.get(key, key)); item.setData(Qt.ItemDataRole.UserRole, key); self.learnset.setItem(row, 1, item); self.learnset.blockSignals(False); self.learnset_dirty = True

    def delete_learnset_row(self) -> None:
        selected = self.learnset.selectedItems()
        if selected: self.learnset.removeRow(selected[0].row()); self.learnset_dirty = True

    def learnset_body(self) -> str:
        lines: list[str] = []; kind = self.learnset_kind.currentData()
        for row in range(self.learnset.rowCount()):
            move = self.learnset.item(row, 1).data(Qt.ItemDataRole.UserRole)
            if not move: continue
            lines.append(f"    LEVEL_UP_MOVE({int(self.learnset.item(row, 0).text() or '0'):2}, {move})," if kind == "levelUpLearnset" else f"    {move},")
        if kind == "levelUpLearnset": lines.append("    LEVEL_UP_END")
        else: lines.append("    MOVE_UNAVAILABLE")
        return "\n" + "\n".join(lines)

    def show_learnset_diff(self) -> None:
        if self.learnset_path: DiffDialog(self, f"Diff: {self.learnset_path.name}", self.learnset_original, self.learnset_body()).exec()

    def save_learnset(self) -> None:
        if not self.learnset_path or not self.current or not self.learnset_dirty: return
        pointer = self.current.values.get(self.learnset_kind.currentData(), ""); source = read_utf8(self.learnset_path); match = re.search(rf"(\b{re.escape(pointer)}\[\]\s*=\s*\{{)(.*?)(\n\s*\}};)", source, re.S)
        if not match: QMessageBox.warning(self, "Learnset not found", pointer); return
        updated = source[:match.start(2)] + self.learnset_body() + source[match.end(2):]
        write_with_backup(self.learnset_path, updated); self.learnset_original = self.learnset_body(); self.learnset_dirty = False; self.window.status(f"Saved learnset: {rel(self.window.root, self.learnset_path)}")

    def add_evolution(self) -> None:
        target = self.evo_target.currentData()
        if not target: return
        new = f"{{{self.evo_method.currentData()}, {self.evo_value.text().strip() or '0'}, {target}}}"
        raw = self.evolution_raw.toPlainText().strip()
        if raw.startswith("EVOLUTION(") and raw.endswith(")"): raw = raw[:-1] + ", " + new + ")"
        else: raw = f"EVOLUTION({new})"
        self.evolution_raw.setPlainText(raw); self.update_evolutions()

    def has_changes(self) -> bool:
        return self.learnset_dirty or super().has_changes()

    def show_diff(self) -> None:
        if self.learnset_dirty:
            self.show_learnset_diff()
        else:
            super().show_diff()

    def save(self) -> None:
        saved_learnset = self.learnset_dirty
        if saved_learnset:
            self.save_learnset()
        if RecordStudioBase.has_changes(self):
            RecordStudioBase.save(self)
        elif saved_learnset:
            self.window.status("Saved learnset with backup")

    def update_graphics(self) -> None:
        if not self.current: return
        front = self.current.values.get("frontPic", ""); path = self.graphics.get(front); self.cry.setText(f"鳴き声: {self.current.values.get('cryId', '未定義')}")
        if path and path.exists(): self.image.setPixmap(QPixmap(str(path)).scaled(360, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
        else: self.image.setText("画像の参照先が見つかりません")

    def show_ability(self, slot: int) -> None:
        key = self.ability_boxes[slot].currentData(); name, description = self.ability_names.get(key, (key, "")); dialog = QDialog(self); dialog.setWindowTitle(name); layout = QVBoxLayout(dialog); layout.addWidget(QLabel(f"{name}\n{key}")); text = QPlainTextEdit(description); text.setReadOnly(True); layout.addWidget(text); button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); button.rejected.connect(dialog.reject); layout.addWidget(button); dialog.resize(420, 230); dialog.exec()

    def jump_move(self, item: QTableWidgetItem) -> None:
        key = self.learnset.item(item.row(), 1).data(Qt.ItemDataRole.UserRole); self.window.open_move(key)


class MoveStudioPanel(RecordStudioBase):
    FLAG_LABELS = {"makesContact": "接触", "punchingMove": "パンチ", "soundMove": "音技", "windMove": "風技", "bitingMove": "かみつき", "pulseMove": "波動", "slicingMove": "切断", "healingMove": "回復", "ballisticMove": "弾・爆弾", "powderMove": "粉"}
    def __init__(self, window: "Workbench") -> None:
        super().__init__(window); self.move_names: dict[str, str] = {}; self.search = QLineEdit(); self.search.setPlaceholderText("からてチョップ / MOVE_KARATE_CHOP"); self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(["わざ", "タイプ", "分類", "威力", "内部 ID"]); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.itemSelectionChanged.connect(self.select)
        self.name = QLineEdit(); self.description = QPlainTextEdit(); self.description.setMaximumHeight(150); self.type = QComboBox(); self.category = QComboBox(); self.effect = QComboBox(); self.target = QComboBox(); self.power = QSpinBox(); self.accuracy = QSpinBox(); self.pp = QSpinBox(); self.priority = QSpinBox(); self.critical = QSpinBox(); self.flags = {key: QCheckBox(label) for key, label in self.FLAG_LABELS.items()}; self.summary_name = QLabel(); self.summary_meta = QLabel(); self.effect_summary = QLabel(); self.additional_table = QTableWidget(0, 3); self.additional_table.setHorizontalHeaderLabels(["追加効果", "確率", "対象"]); self.additional_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.additional_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.additional_table.itemSelectionChanged.connect(self.select_additional); self.additional_effect = QComboBox(); self.additional_chance = QSpinBox(); self.additional_chance.setRange(0, 100); self.additional_self = QCheckBox("自分に適用"); self.additional_rows: list[dict[str, str]] = []; self.additional_dirty = False; self.build()

    def build(self) -> None:
        for internal, label in TYPE_LABELS.items(): self.type.addItem(label, internal)
        for internal, label in CATEGORY_LABELS.items(): self.category.addItem(label, internal)
        for spin, low, high in ((self.power, 0, 511), (self.accuracy, 0, 100), (self.pp, 0, 99), (self.priority, -7, 7), (self.critical, 0, 3)): spin.setRange(low, high)
        layout = QVBoxLayout(self); split = QSplitter(Qt.Orientation.Horizontal); left = QWidget(); left_layout = QVBoxLayout(left); left_layout.addWidget(self.search); left_layout.addWidget(self.table); split.addWidget(left)
        right = QWidget(); right_layout = QVBoxLayout(right); card = QFrame(); card.setFrameShape(QFrame.Shape.StyledPanel); card_layout = QVBoxLayout(card); self.summary_name.setStyleSheet("font-size: 24px; font-weight: 700;"); card_layout.addWidget(self.summary_name); card_layout.addWidget(self.summary_meta); card_layout.addWidget(self.effect_summary); right_layout.addWidget(card)
        tabs = QTabWidget(); basic = QWidget(); form = QFormLayout(basic); form.addRow("名前", self.name); form.addRow("タイプ", self.type); form.addRow("分類", self.category); form.addRow("威力", self.power); form.addRow("命中", self.accuracy); form.addRow("PP", self.pp); form.addRow("優先度", self.priority); form.addRow("効果", self.effect); form.addRow("対象", self.target); form.addRow("説明", self.description); tabs.addTab(basic, "基本")
        flags = QWidget(); flags_layout = QVBoxLayout(flags); flags_layout.addWidget(QLabel("急所ランク")); flags_layout.addWidget(self.critical)
        for checkbox in self.flags.values(): flags_layout.addWidget(checkbox)
        flags_layout.addStretch(); tabs.addTab(flags, "性質")
        additional = QWidget(); additional_layout = QVBoxLayout(additional); additional_layout.addWidget(self.additional_table); additional_controls = QHBoxLayout(); additional_controls.addWidget(self.additional_effect); additional_controls.addWidget(QLabel("確率")); additional_controls.addWidget(self.additional_chance); additional_controls.addWidget(self.additional_self); update_additional = QPushButton("追加 / 更新"); update_additional.clicked.connect(self.add_or_update_additional); delete_additional = QPushButton("選択を削除"); delete_additional.clicked.connect(self.delete_additional); additional_controls.addWidget(update_additional); additional_controls.addWidget(delete_additional); additional_layout.addLayout(additional_controls); tabs.addTab(additional, "追加効果")
        references = QWidget(); refs_layout = QVBoxLayout(references); self.references = QListWidget(); refs_layout.addWidget(QLabel("この技を参照するソース")); refs_layout.addWidget(self.references); tabs.addTab(references, "参照")
        right_layout.addWidget(tabs); split.addWidget(right); split.setSizes([520, 920]); layout.addWidget(split)
        for control in [self.name, self.type, self.category, self.power, self.accuracy, self.pp, self.priority, self.effect, self.target, self.description, self.critical, *self.flags.values()]:
            signal = control.textChanged if isinstance(control, (QLineEdit, QPlainTextEdit)) else (control.currentIndexChanged if isinstance(control, QComboBox) else (control.valueChanged if isinstance(control, QSpinBox) else control.stateChanged)); signal.connect(self.changed)

    def load(self) -> None:
        path = self.window.root / "src/data/moves_info.h"
        wanted = ["name", "description", "type", "category", "power", "accuracy", "pp", "priority", "effect", "target", "criticalHitStage", "additionalEffects", *self.FLAG_LABELS]
        self.records, self.contents = indexed_records(self.window.root, [path], "MOVE_", wanted) if path.exists() else ([], {}); self.states.clear(); self.current = None; self.move_names = {record.key: string_from_record(record, "name") for record in self.records}; self.populate_primary_options(); self.populate_additional_effects(); self.refresh()

    def populate_primary_options(self) -> None:
        self.effect.clear(); self.target.clear()
        effect_names = set(PRIMARY_EFFECT_LABELS)
        effect_file = self.window.root / "include/constants/battle_move_effects.h"
        if effect_file.exists(): effect_names.update(re.findall(r"\b(EFFECT_[A-Z0-9_]+)\b", read_utf8(effect_file)))
        for name in sorted(effect_names): self.effect.addItem(f"{PRIMARY_EFFECT_LABELS.get(name, name.replace('EFFECT_', '').replace('_', ' ').title())}  [{name}]", name)
        target_names = set(TARGET_LABELS)
        target_file = self.window.root / "include/constants/battle.h"
        if target_file.exists(): target_names.update(re.findall(r"\b(TARGET_[A-Z0-9_]+)\b", read_utf8(target_file)))
        for name in sorted(target_names): self.target.addItem(f"{TARGET_LABELS.get(name, name.replace('TARGET_', '').replace('_', ' ').title())}  [{name}]", name)

    def populate_additional_effects(self) -> None:
        self.additional_effect.clear(); names = set(MOVE_EFFECT_LABELS)
        constants = self.window.root / "include/constants/battle.h"
        if constants.exists(): names.update(re.findall(r"\b(MOVE_EFFECT_[A-Z0-9_]+)\b", read_utf8(constants)))
        for name in sorted(names): self.additional_effect.addItem(f"{MOVE_EFFECT_LABELS.get(name, name)}  [{name}]", name)

    def refresh(self) -> None:
        query = self.search.text().casefold(); rows = [record for record in self.records if not query or query in (record.key + " " + self.move_names.get(record.key, "")).casefold()]; self.table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            values = [self.move_names.get(record.key, record.key), TYPE_LABELS.get(record.values.get("type", ""), record.values.get("type", "")), CATEGORY_LABELS.get(record.values.get("category", ""), record.values.get("category", "")), record.values.get("power", "0"), record.key]
            for column, value in enumerate(values): item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, record); self.table.setItem(row, column, item)

    def default_values(self, record: SourceRecord) -> dict[str, str]:
        values = {field: record.values.get(field, "FALSE" if field in self.FLAG_LABELS else "0") for field in ["type", "category", "power", "accuracy", "pp", "priority", "effect", "target", "criticalHitStage", "additionalEffects", *self.FLAG_LABELS]}
        values["name"] = string_from_record(record, "name"); values["description"] = string_from_record(record, "description"); return values

    def values_for(self, record: SourceRecord) -> dict[str, str]:
        baseline = self.states.get(record.key, self.default_values(record))
        baseline_type = display_enum_token(baseline["type"], "TYPE_", "TYPE_NONE")
        baseline_category = display_enum_token(baseline["category"], "DAMAGE_CATEGORY_", "DAMAGE_CATEGORY_PHYSICAL")
        additional = baseline["additionalEffects"] if not self.additional_dirty else self.additional_effect_value(baseline["additionalEffects"])
        return {"name": self.name.text(), "description": self.description.toPlainText(), "type": baseline["type"] if self.type.currentData() == baseline_type else self.type.currentData(), "category": baseline["category"] if self.category.currentData() == baseline_category else self.category.currentData(), "power": str(self.power.value()), "accuracy": str(self.accuracy.value()), "pp": str(self.pp.value()), "priority": str(self.priority.value()), "effect": self.effect.currentData(), "target": self.target.currentData(), "criticalHitStage": baseline["criticalHitStage"] if self.critical.value() == display_integer(baseline["criticalHitStage"]) else str(self.critical.value()), "additionalEffects": additional, **{key: "TRUE" if control.isChecked() else "FALSE" for key, control in self.flags.items()}}

    def proposed_block(self, record: SourceRecord) -> str:
        return replace_record_fields(record, self.states.get(record.key, self.default_values(record)), {"name", "description"})

    def select(self) -> None:
        self.capture_current(); selected = self.table.selectedItems()
        if not selected: return
        self.current = selected[0].data(Qt.ItemDataRole.UserRole); values = self.states.get(self.current.key, self.default_values(self.current)); self.loading = True
        self.name.setText(values["name"]); self.description.setPlainText(values["description"]); self.set_combo(self.type, display_enum_token(values["type"], "TYPE_", "TYPE_NONE")); self.set_combo(self.category, display_enum_token(values["category"], "DAMAGE_CATEGORY_", "DAMAGE_CATEGORY_PHYSICAL"))
        for control, key in ((self.power, "power"), (self.accuracy, "accuracy"), (self.pp, "pp"), (self.priority, "priority"), (self.critical, "criticalHitStage")): control.setValue(display_integer(values[key]))
        self.set_combo(self.effect, values["effect"]); self.set_combo(self.target, values["target"])
        for key, checkbox in self.flags.items(): checkbox.setChecked(values[key] == "TRUE")
        self.additional_rows = self.parse_additional_effects(values["additionalEffects"]); self.additional_dirty = False; self.refresh_additional_table(); self.loading = False; self.update_summary(); self.update_references()

    @staticmethod
    def set_combo(combo: QComboBox, data: str) -> None:
        index = combo.findData(data); combo.setCurrentIndex(index if index >= 0 else 0)

    def changed(self) -> None:
        if not self.loading and self.current: self.update_summary(); self.window.status(f"Pending changes: {self.current.key}")

    def update_summary(self) -> None:
        if not self.current: return
        primary_effect = self.effect.currentData()
        details = [PRIMARY_EFFECT_LABELS.get(primary_effect, primary_effect)]
        if self.critical.value(): details.append(f"急所ランク +{self.critical.value()}")
        for row in self.additional_rows:
            label = MOVE_EFFECT_LABELS.get(row["effect"], row["effect"]); chance = row["chance"]
            details.append(f"{chance}%で{label}" if chance not in {"0", ""} else label)
        self.summary_name.setText(self.name.text() or self.current.key); self.summary_meta.setText(f"{self.type.currentText()}  {self.category.currentText()}  威力{self.power.value()}  命中{self.accuracy.value()}  PP{self.pp.value()}"); self.effect_summary.setText("エフェクト: " + " / ".join(filter(None, details)))

    def parse_additional_effects(self, value: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for body in re.findall(r"\{([^{}]+)\}", value, re.S):
            effect = re.search(r"\.moveEffect\s*=\s*(MOVE_EFFECT_[A-Z0-9_]+)", body)
            if not effect: continue
            chance = re.search(r"\.chance\s*=\s*([^,\n}]+)", body); self_target = re.search(r"\.self\s*=\s*TRUE", body)
            rows.append({"effect": effect.group(1), "chance": chance.group(1).strip() if chance else "0", "self": "TRUE" if self_target else "FALSE", "raw": "{" + body + "}"})
        return rows

    def refresh_additional_table(self) -> None:
        self.additional_table.setRowCount(len(self.additional_rows))
        for index, row in enumerate(self.additional_rows):
            values = [MOVE_EFFECT_LABELS.get(row["effect"], row["effect"]), row["chance"] + "%" if row["chance"] not in {"", "0"} else "確定", "自分" if row["self"] == "TRUE" else "相手"]
            for column, value in enumerate(values): item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, index); self.additional_table.setItem(index, column, item)

    def select_additional(self) -> None:
        selected = self.additional_table.selectedItems()
        if not selected: return
        row = self.additional_rows[selected[0].data(Qt.ItemDataRole.UserRole)]; self.set_combo(self.additional_effect, row["effect"]); self.additional_chance.setValue(display_integer(row["chance"])); self.additional_self.setChecked(row["self"] == "TRUE")

    def add_or_update_additional(self) -> None:
        entry = {"effect": self.additional_effect.currentData(), "chance": str(self.additional_chance.value()), "self": "TRUE" if self.additional_self.isChecked() else "FALSE", "raw": ""}
        selected = self.additional_table.selectedItems()
        if selected: self.additional_rows[selected[0].data(Qt.ItemDataRole.UserRole)] = entry
        else: self.additional_rows.append(entry)
        self.additional_dirty = True; self.refresh_additional_table(); self.update_summary(); self.changed()

    def delete_additional(self) -> None:
        selected = self.additional_table.selectedItems()
        if selected: self.additional_rows.pop(selected[0].data(Qt.ItemDataRole.UserRole)); self.additional_dirty = True; self.refresh_additional_table(); self.update_summary(); self.changed()

    def additional_effect_value(self, baseline: str) -> str:
        if not self.additional_rows:
            return "NULL, .numAdditionalEffects = 0" if baseline else ""
        parts = []
        for row in self.additional_rows:
            lines = [f"            .moveEffect = {row['effect']},"]
            if row["chance"] not in {"", "0"}: lines.append(f"            .chance = {row['chance']},")
            if row["self"] == "TRUE": lines.append("            .self = TRUE,")
            parts.append("{\n" + "\n".join(lines) + "\n        }")
        return "ADDITIONAL_EFFECTS(" + ",\n        ".join(parts) + ")"

    def update_references(self) -> None:
        self.references.clear()
        if not self.current: return
        key = self.current.key; found = 0
        for path in self.window.root.rglob("*"):
            if path.suffix not in {".c", ".h", ".inc"} or not path.is_file(): continue
            try: lines = read_utf8(path).splitlines()
            except UnicodeDecodeError: continue
            for number, line in enumerate(lines, 1):
                if key in line and path != self.current.path:
                    self.references.addItem(f"{rel(self.window.root, path)}:{number}  {line.strip()[:120]}"); found += 1
                    if found >= 300: self.references.addItem("… 参照が多いため 300 件で省略"); return


FRONTIER_MON_FIELDS = [
    "nickname", "species", "moves", "heldItem", "ev", "iv", "ability", "lvl", "ball", "friendship",
    "nature", "gender", "isShiny", "teraType", "gigantamaxFactor", "shouldUseDynamax",
    "dynamaxLevel", "tags",
]
NATURE_LABELS = {
    "NATURE_HARDY": "がんばりや", "NATURE_LONELY": "さみしがり", "NATURE_BRAVE": "ゆうかん",
    "NATURE_ADAMANT": "いじっぱり", "NATURE_NAUGHTY": "やんちゃ", "NATURE_BOLD": "ずぶとい",
    "NATURE_DOCILE": "すなお", "NATURE_RELAXED": "のんき", "NATURE_IMPISH": "わんぱく",
    "NATURE_LAX": "のうてんき", "NATURE_TIMID": "おくびょう", "NATURE_HASTY": "せっかち",
    "NATURE_SERIOUS": "まじめ", "NATURE_JOLLY": "ようき", "NATURE_NAIVE": "むじゃき",
    "NATURE_MODEST": "ひかえめ", "NATURE_MILD": "おっとり", "NATURE_QUIET": "れいせい",
    "NATURE_BASHFUL": "てれや", "NATURE_RASH": "うっかりや", "NATURE_CALM": "おだやか",
    "NATURE_GENTLE": "おとなしい", "NATURE_SASSY": "なまいき", "NATURE_CAREFUL": "しんちょう",
    "NATURE_QUIRKY": "きまぐれ",
}
BALL_LABELS = {
    "BALL_STRANGE": "ストレンジボール", "BALL_POKE": "モンスターボール", "BALL_GREAT": "スーパーボール",
    "BALL_ULTRA": "ハイパーボール", "BALL_MASTER": "マスターボール", "BALL_PREMIER": "プレミアボール",
    "BALL_HEAL": "ヒールボール", "BALL_NET": "ネットボール", "BALL_NEST": "ネストボール",
    "BALL_DIVE": "ダイブボール", "BALL_DUSK": "ダークボール", "BALL_TIMER": "タイマーボール",
    "BALL_QUICK": "クイックボール", "BALL_REPEAT": "リピートボール", "BALL_LUXURY": "ゴージャスボール",
    "BALL_LEVEL": "レベルボール", "BALL_LURE": "ルアーボール", "BALL_MOON": "ムーンボール",
    "BALL_FRIEND": "フレンドボール", "BALL_LOVE": "ラブラブボール", "BALL_FAST": "スピードボール",
    "BALL_HEAVY": "ヘビーボール", "BALL_DREAM": "ドリームボール", "BALL_SAFARI": "サファリボール",
    "BALL_SPORT": "コンペボール", "BALL_PARK": "パークボール", "BALL_BEAST": "ウルトラボール",
    "BALL_CHERISH": "プレシャスボール", "BALL_RANDOM": "ランダム",
}


@dataclass
class FrontierMacro:
    path: Path
    name: str
    start: int
    end: int
    raw: str
    mons: list[str]
    parameterized: bool = False


@dataclass
class FactoryRangeRecord:
    index: int
    start: int
    end: int
    indent: str
    first: str
    last: str
    comment: str
    newline: str
    mode: str = ""


@dataclass
class FactoryIvRecord:
    index: int
    start: int
    end: int
    indent: str
    low: int
    high: int
    comment: str
    newline: str


@dataclass
class GeneralTrainerBlock:
    path: Path
    key: str
    start: int
    end: int
    raw: str
    name: str
    trainer_class: str
    party_count: int


@dataclass
class MoveMetadata:
    type: str
    category: str


class BattleFrontierPanel(QWidget):
    """Battle Frontier and Battle Factory source editor."""
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.loading = False
        self.records: list[SourceRecord] = []; self.contents: dict[Path, str] = {}; self.mon_states: dict[str, dict[str, str]] = {}; self.current_mon: SourceRecord | None = None
        self.trainer_records: list[SourceRecord] = []; self.trainer_contents: dict[Path, str] = {}; self.current_trainer: SourceRecord | None = None
        self.macros: list[FrontierMacro] = []; self.current_macro: FrontierMacro | None = None; self.macro_original = ""
        self.general_trainer_path = Path(); self.general_trainer_source = ""; self.general_trainers: list[GeneralTrainerBlock] = []; self.general_trainer_states: dict[str, str] = {}; self.current_general_trainer: GeneralTrainerBlock | None = None
        self.factory_path = Path(); self.factory_source = ""; self.factory_ranges: list[FactoryRangeRecord] = []; self.factory_ivs: list[FactoryIvRecord] = []; self.range_states: dict[int, tuple[str, str]] = {}; self.iv_states: dict[int, tuple[int, int]] = {}
        self.species_names: dict[str, str] = {}; self.move_names: dict[str, str] = {}; self.move_metadata: dict[str, MoveMetadata] = {}; self.item_names: dict[str, str] = {}; self.ability_names: dict[str, str] = {}
        self.species_abilities: dict[str, list[str]] = {}; self.item_pockets: dict[str, str] = {}; self.item_hold_effects: dict[str, str] = {}
        self.species_values: dict[str, int] = {}; self.move_values: dict[str, int] = {}; self.item_values: dict[str, int] = {}; self.frontier_values: dict[str, int] = {}; self.frontier_by_value: dict[int, str] = {}
        self.species_learnsets: dict[str, set[str]] = {}; self.species_move_sources: dict[str, dict[str, set[str]]] = {}; self.mon_usage_counts: dict[str, int] = {}; self.factory_usage: set[str] = set()
        self.build()

    def build(self) -> None:
        layout = QVBoxLayout(self); self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.build_mons_tab(); self.build_trainers_tab(); self.build_general_trainers_tab(); self.build_factory_tab()

    @staticmethod
    def set_columns(table: QTableWidget, widths: list[int]) -> None:
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)

    def build_mons_tab(self) -> None:
        page = QWidget(); layout = QVBoxLayout(page); split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); left_layout = QVBoxLayout(left); top = QHBoxLayout(); self.mon_search = QLineEdit(); self.mon_search.setPlaceholderText("FRONTIER_MON / species / item"); self.mon_search.textChanged.connect(self.refresh_mons); top.addWidget(self.mon_search)
        left.setMinimumWidth(LIST_PANEL_MIN_WIDTH)
        self.mon_unused_only = QCheckBox("usage 0"); self.mon_unused_only.stateChanged.connect(self.refresh_mons); top.addWidget(self.mon_unused_only); left_layout.addLayout(top)
        self.mon_table = QTableWidget(0, 12); self.mon_table.setHorizontalHeaderLabels(["No.", "Frontier ID", "Species", "Item", "Use", "Factory", "Mega", "Z", "DMax", "Tera", "Shiny", "Unused"]); self.mon_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.mon_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.mon_table.itemSelectionChanged.connect(self.select_mon); left_layout.addWidget(self.mon_table); split.addWidget(left)
        self.set_columns(self.mon_table, [62, 210, 170, 150, 58, 70, 54, 44, 58, 58, 58, 68])
        right = QWidget(); right.setMinimumWidth(DETAIL_PANEL_MIN_WIDTH); right_layout = QVBoxLayout(right); self.mon_summary = QLabel(); self.mon_summary.setStyleSheet("font-size: 18px; font-weight: 700;"); self.mon_summary.setMinimumHeight(34); right_layout.addWidget(self.mon_summary)
        form_tabs = QTabWidget(); basic = QWidget(); form = QFormLayout(basic)
        self.mon_species = self.combo(); self.mon_nickname = QLineEdit(); self.mon_item_category = QComboBox(); self.mon_item_filter = QLineEdit(); self.mon_item = self.combo(); self.mon_ability = self.combo(); self.mon_nature = self.combo(); self.mon_ball = self.combo(); self.mon_gender = self.combo(); self.mon_level = self.spin(0, 100); self.mon_friendship = self.spin(0, 255)
        self.mon_nickname.setPlaceholderText("空欄なら種族名"); self.mon_item_filter.setPlaceholderText("アイテム名 / ITEM_ / 効果で検索")
        for label, value in (("すべて", "all"), ("効果あり", "hold"), ("Zクリスタル", "z"), ("メガストーン", "mega"), ("きのみ", "berry")):
            self.mon_item_category.addItem(label, value)
        for label, control in (("Species", self.mon_species), ("Nickname", self.mon_nickname), ("Item group", self.mon_item_category), ("Item search", self.mon_item_filter), ("Held item", self.mon_item), ("Ability", self.mon_ability), ("Nature", self.mon_nature), ("Ball", self.mon_ball), ("Gender", self.mon_gender), ("Level override", self.mon_level), ("Friendship", self.mon_friendship)): form.addRow(label, control)
        form_tabs.addTab(basic, "Basic")
        moves = QWidget(); moves_layout = QVBoxLayout(moves)
        move_filters = QHBoxLayout(); self.move_category_filter = QComboBox(); self.move_type_filter = QComboBox()
        self.move_category_filter.addItem("分類: すべて", "")
        for key, label in CATEGORY_LABELS.items():
            self.move_category_filter.addItem(f"分類: {label}", key)
        self.move_type_filter.addItem("タイプ: すべて", "")
        for key, label in TYPE_LABELS.items():
            if key != "TYPE_NONE":
                self.move_type_filter.addItem(f"タイプ: {label}", key)
        stabilize_combo(self.move_category_filter, 16); stabilize_combo(self.move_type_filter, 16)
        self.move_category_filter.currentIndexChanged.connect(self.refresh_move_choices); self.move_type_filter.currentIndexChanged.connect(self.refresh_move_choices)
        move_filters.addWidget(self.move_category_filter); move_filters.addWidget(self.move_type_filter); move_filters.addStretch(); moves_layout.addLayout(move_filters)
        self.move_filter_label = QLabel(); moves_layout.addWidget(self.move_filter_label); self.mon_moves = [self.combo() for _ in range(4)]
        for index, combo in enumerate(self.mon_moves, 1):
            row = QHBoxLayout(); row.addWidget(QLabel(f"Move {index}")); row.addWidget(combo); jump = QPushButton("Open"); jump.clicked.connect(lambda _checked=False, slot=index - 1: self.open_selected_move(slot)); row.addWidget(jump); moves_layout.addLayout(row)
        form_tabs.addTab(moves, "Moves")
        evs = QWidget(); ev_form = QFormLayout(evs); self.ev_boxes = [self.spin(0, 252) for _ in range(6)]; self.iv_boxes = [self.spin(0, 31) for _ in range(6)]
        for label, ev, iv in zip(("HP", "Atk", "Def", "Spe", "SpAtk", "SpDef"), self.ev_boxes, self.iv_boxes):
            row = QHBoxLayout(); row.addWidget(QLabel("EV")); row.addWidget(ev); row.addWidget(QLabel("IV")); row.addWidget(iv); ev_form.addRow(label, row)
        self.hidden_power_label = QLabel(); self.hidden_power_label.setWordWrap(True); ev_form.addRow("Hidden Power", self.hidden_power_label)
        form_tabs.addTab(evs, "EV / IV")
        gimmick = QWidget(); gimmick_form = QFormLayout(gimmick); self.mon_tera = self.combo(); self.mon_dmax = QCheckBox("Use Dynamax"); self.mon_dmax_level = self.spin(0, 10); self.mon_gmax = QCheckBox("Gigantamax factor"); self.mon_shiny = QCheckBox("Shiny"); self.mon_tags = QLineEdit()
        for label, control in (("Tera type", self.mon_tera), ("Dynamax", self.mon_dmax), ("Dynamax level", self.mon_dmax_level), ("Gigantamax", self.mon_gmax), ("Shiny", self.mon_shiny), ("Tags", self.mon_tags)): gimmick_form.addRow(label, control)
        form_tabs.addTab(gimmick, "Gimmick")
        right_layout.addWidget(form_tabs); buttons = QHBoxLayout(); diff = QPushButton("Diff"); diff.clicked.connect(self.show_mon_diff); save = QPushButton("Save pool"); save.clicked.connect(self.save_mons); buttons.addStretch(); buttons.addWidget(diff); buttons.addWidget(save); right_layout.addLayout(buttons); split.addWidget(right); stabilize_splitter(split, 1, 1); split.setSizes([720, 760]); layout.addWidget(split); self.tabs.addTab(page, "Pokemon pool")
        self.mon_species.currentIndexChanged.connect(self.refresh_species_dependent_choices)
        self.mon_item_filter.textChanged.connect(self.refresh_item_choices); self.mon_item_category.currentIndexChanged.connect(self.refresh_item_choices)
        for control in [self.mon_species, self.mon_nickname, self.mon_item, self.mon_ability, self.mon_nature, self.mon_ball, self.mon_gender, self.mon_level, self.mon_friendship, self.mon_tera, self.mon_dmax, self.mon_dmax_level, self.mon_gmax, self.mon_shiny, self.mon_tags, *self.mon_moves, *self.ev_boxes, *self.iv_boxes]:
            self.watch(control, self.mon_changed)

    def build_trainers_tab(self) -> None:
        page = QWidget(); layout = QVBoxLayout(page); split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); left.setMinimumWidth(LIST_PANEL_MIN_WIDTH); left_layout = QVBoxLayout(left); self.trainer_search = QLineEdit(); self.trainer_search.setPlaceholderText("trainer / monSet"); self.trainer_search.textChanged.connect(self.refresh_trainers); left_layout.addWidget(self.trainer_search)
        self.trainer_table = QTableWidget(0, 4); self.trainer_table.setHorizontalHeaderLabels(["Trainer", "Name", "Class", "monSet"]); self.trainer_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.trainer_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.trainer_table.itemSelectionChanged.connect(self.select_trainer); left_layout.addWidget(self.trainer_table); split.addWidget(left)
        self.set_columns(self.trainer_table, [190, 150, 170, 210])
        right = QWidget(); right.setMinimumWidth(DETAIL_PANEL_MIN_WIDTH); right_layout = QVBoxLayout(right); trainer_box = QGroupBox("Trainer monSet"); trainer_form = QFormLayout(trainer_box); self.trainer_name = QLabel(); self.trainer_monset = self.combo(); self.trainer_monset.setEditable(True); trainer_form.addRow("Name", self.trainer_name); trainer_form.addRow("monSet inner", self.trainer_monset); trainer_buttons = QHBoxLayout(); trainer_diff = QPushButton("Trainer diff"); trainer_diff.clicked.connect(self.show_trainer_diff); trainer_save = QPushButton("Save trainer"); trainer_save.clicked.connect(self.save_trainer); trainer_buttons.addStretch(); trainer_buttons.addWidget(trainer_diff); trainer_buttons.addWidget(trainer_save); trainer_form.addRow(trainer_buttons); right_layout.addWidget(trainer_box)
        macro_box = QGroupBox("Pool macro body"); macro_layout = QVBoxLayout(macro_box); self.macro_select = QComboBox(); stabilize_combo(self.macro_select); self.macro_select.currentIndexChanged.connect(self.select_macro); macro_layout.addWidget(self.macro_select); self.macro_editor = QPlainTextEdit(); self.macro_editor.textChanged.connect(self.macro_changed); macro_layout.addWidget(self.macro_editor); self.macro_mons = QTableWidget(0, 3); self.macro_mons.setHorizontalHeaderLabels(["Frontier ID", "Species", "Item"]); self.macro_mons.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.macro_mons.itemDoubleClicked.connect(self.open_macro_mon); self.set_columns(self.macro_mons, [230, 180, 170]); macro_layout.addWidget(self.macro_mons); macro_buttons = QHBoxLayout(); macro_diff = QPushButton("Macro diff"); macro_diff.clicked.connect(self.show_macro_diff); macro_save = QPushButton("Save macro"); macro_save.clicked.connect(self.save_macro); macro_buttons.addStretch(); macro_buttons.addWidget(macro_diff); macro_buttons.addWidget(macro_save); macro_layout.addLayout(macro_buttons); right_layout.addWidget(macro_box); split.addWidget(right); stabilize_splitter(split, 1, 1); split.setSizes([720, 760]); layout.addWidget(split); self.tabs.addTab(page, "Trainer pools")

    def build_general_trainers_tab(self) -> None:
        page = QWidget(); layout = QVBoxLayout(page); split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); left.setMinimumWidth(LIST_PANEL_MIN_WIDTH); left_layout = QVBoxLayout(left)
        self.general_trainer_search = QLineEdit(); self.general_trainer_search.setPlaceholderText("TRAINER_ / name / class / Pokemon"); self.general_trainer_search.textChanged.connect(self.refresh_general_trainers); left_layout.addWidget(self.general_trainer_search)
        self.general_trainer_table = QTableWidget(0, 5); self.general_trainer_table.setHorizontalHeaderLabels(["Trainer", "Name", "Class", "Pokemon", "Flags"]); self.general_trainer_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.general_trainer_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.general_trainer_table.itemSelectionChanged.connect(self.select_general_trainer); left_layout.addWidget(self.general_trainer_table); split.addWidget(left)
        self.set_columns(self.general_trainer_table, [240, 150, 170, 80, 170])
        right = QWidget(); right.setMinimumWidth(DETAIL_PANEL_MIN_WIDTH); right_layout = QVBoxLayout(right)
        self.general_trainer_label = QLabel("Select a trainer.party block."); self.general_trainer_label.setWordWrap(True); right_layout.addWidget(self.general_trainer_label)
        self.general_trainer_editor = QPlainTextEdit(); self.general_trainer_editor.textChanged.connect(self.general_trainer_changed); right_layout.addWidget(self.general_trainer_editor)
        buttons = QHBoxLayout(); diff = QPushButton("Trainer.party diff"); diff.clicked.connect(self.show_general_trainer_diff); save = QPushButton("Save trainer.party block"); save.clicked.connect(self.save_general_trainer); buttons.addStretch(); buttons.addWidget(diff); buttons.addWidget(save); right_layout.addLayout(buttons)
        split.addWidget(right); stabilize_splitter(split, 1, 1); split.setSizes([720, 760]); layout.addWidget(split); self.tabs.addTab(page, "General trainers")

    def build_factory_tab(self) -> None:
        page = QWidget(); layout = QVBoxLayout(page); split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); left.setMinimumWidth(LIST_PANEL_MIN_WIDTH); left_layout = QVBoxLayout(left); self.range_table = QTableWidget(0, 6); self.range_table.setHorizontalHeaderLabels(["Mode", "Challenge", "Start", "End", "Count", "Comment"]); self.range_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.range_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.range_table.itemSelectionChanged.connect(self.select_range); left_layout.addWidget(self.range_table)
        self.set_columns(self.range_table, [120, 90, 190, 190, 80, 160])
        self.iv_table = QTableWidget(0, 3); self.iv_table.setHorizontalHeaderLabels(["Challenge", "Low", "High"]); self.iv_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.iv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.iv_table.itemSelectionChanged.connect(self.select_iv); left_layout.addWidget(self.iv_table); split.addWidget(left)
        self.set_columns(self.iv_table, [120, 90, 90])
        right = QWidget(); right.setMinimumWidth(DETAIL_PANEL_MIN_WIDTH); right_layout = QVBoxLayout(right); range_box = QGroupBox("Factory rental range"); range_form = QFormLayout(range_box); self.range_start = self.combo(); self.range_start.setEditable(True); self.range_end = self.combo(); self.range_end.setEditable(True); self.range_status = QLabel(); range_form.addRow("Start", self.range_start); range_form.addRow("End", self.range_end); range_form.addRow("Status", self.range_status); right_layout.addWidget(range_box)
        iv_box = QGroupBox("Factory fixed IV table"); iv_form = QFormLayout(iv_box); self.iv_low = self.spin(0, 31); self.iv_high = self.spin(0, 31); iv_form.addRow("Low", self.iv_low); iv_form.addRow("High", self.iv_high); right_layout.addWidget(iv_box)
        buttons = QHBoxLayout(); diff = QPushButton("Factory diff"); diff.clicked.connect(self.show_factory_diff); save = QPushButton("Save Factory"); save.clicked.connect(self.save_factory); buttons.addStretch(); buttons.addWidget(diff); buttons.addWidget(save); right_layout.addLayout(buttons); right_layout.addStretch(); split.addWidget(right); stabilize_splitter(split, 1, 1); split.setSizes([760, 520]); layout.addWidget(split); self.tabs.addTab(page, "Battle Factory")
        for control in [self.range_start, self.range_end, self.iv_low, self.iv_high]: self.watch(control, self.factory_changed)

    @staticmethod
    def combo() -> QComboBox:
        combo = QComboBox(); stabilize_combo(combo); return combo

    @staticmethod
    def spin(low: int, high: int) -> QSpinBox:
        spin = QSpinBox(); spin.setRange(low, high); return spin

    def watch(self, control: QWidget, callback: Callable[[], None]) -> None:
        if isinstance(control, QComboBox):
            control.currentIndexChanged.connect(callback); control.editTextChanged.connect(callback)
        elif isinstance(control, QSpinBox):
            control.valueChanged.connect(callback)
        elif isinstance(control, QCheckBox):
            control.stateChanged.connect(callback)
        elif isinstance(control, QLineEdit):
            control.textChanged.connect(callback)

    @staticmethod
    def combo_value(combo: QComboBox) -> str:
        data = combo.currentData()
        if isinstance(data, str) and data:
            return data
        text = combo.currentText().strip()
        match = re.search(r"\[([A-Z0-9_]+)\]\s*$", text)
        return match.group(1) if match else text

    @staticmethod
    def set_combo(combo: QComboBox, data: str) -> None:
        index = combo.findData(data); combo.setCurrentIndex(index if index >= 0 else 0)
        if index < 0 and combo.isEditable(): combo.setEditText(data)

    def load(self) -> None:
        if not self.window.root_valid(): return
        self.load_reference_data(); self.load_frontier_mons(); self.load_macros(); self.load_trainers(); self.load_general_trainers(); self.load_factory()
        self.refresh_mons(); self.refresh_trainers(); self.refresh_macro_select(); self.refresh_general_trainers(); self.refresh_factory()

    def load_reference_data(self) -> None:
        root = self.window.root
        species_paths = list((root / "src/data/pokemon/species_info").glob("*_families.h")) + [root / "src/data/pokemon/species_info.h"]
        species_records, _ = indexed_records(root, [path for path in species_paths if path.exists()], "SPECIES_", ["speciesName", "abilities", "levelUpLearnset", "eggMoveLearnset", "teachableLearnset"])
        move_records, _ = indexed_records(root, [root / "src/data/moves_info.h"], "MOVE_", ["name", "type", "category"])
        item_records, _ = indexed_records(root, [root / "src/data/items.h"], "ITEM_", ["name", "pocket", "holdEffect"])
        ability_records, _ = indexed_records(root, [root / "src/data/abilities.h"], "ABILITY_", ["name"])
        self.species_values = enum_values(root / "include/constants/species.h", "SPECIES_"); self.move_values = enum_values(root / "include/constants/moves.h", "MOVE_"); self.item_values = enum_values(root / "include/constants/items.h", "ITEM_")
        self.species_names = {record.key: string_from_record(record, "speciesName") for record in species_records}; self.move_names = {record.key: string_from_record(record, "name") for record in move_records}; self.item_names = {record.key: string_from_record(record, "name") or record.key for record in item_records}; self.ability_names = {record.key: string_from_record(record, "name") for record in ability_records}
        self.move_metadata = {record.key: MoveMetadata(first_token(record.values.get("type", ""), "TYPE_", "TYPE_NONE"), first_token(record.values.get("category", ""), "DAMAGE_CATEGORY_", "")) for record in move_records}
        self.species_abilities = {record.key: unique_tokens(re.findall(r"\bABILITY_[A-Z0-9_]+\b", record.values.get("abilities", "")), keep_none=False) or ["ABILITY_NONE"] for record in species_records}
        self.item_pockets = {record.key: record.values.get("pocket", "") for record in item_records}; self.item_hold_effects = {record.key: record.values.get("holdEffect", "HOLD_EFFECT_NONE") for record in item_records}
        self.frontier_values = define_values(root / "include/constants/battle_frontier_mons.h", ("FRONTIER_MON_", "FRONTIER_MONS_", "NUM_FRONTIER_MONS"))
        self.frontier_by_value = {value: key for key, value in self.frontier_values.items() if key.startswith("FRONTIER_MON_")}
        self.populate_static_combos(); self.species_learnsets = self.build_species_learnsets(species_records)

    def populate_static_combos(self) -> None:
        self.fill_combo(self.mon_species, self.species_values, self.species_names, "SPECIES_NONE")
        self.refresh_item_choices("ITEM_NONE")
        self.refresh_ability_choices("ABILITY_NONE")
        self.fill_combo(self.mon_nature, define_values(self.window.root / "include/constants/pokemon.h", ("NATURE_",)), NATURE_LABELS, "NATURE_HARDY")
        self.fill_combo(self.mon_ball, enum_values(self.window.root / "include/constants/pokeball.h", "BALL_"), BALL_LABELS, "BALL_POKE")
        self.mon_gender.blockSignals(True); self.mon_gender.clear()
        for label, value in (("Default", "0"), ("Male", "TRAINER_MON_MALE"), ("Female", "TRAINER_MON_FEMALE"), ("Random gender", "TRAINER_MON_RANDOM_GENDER")): self.mon_gender.addItem(f"{label} [{value}]", value)
        self.mon_gender.blockSignals(False)
        self.mon_tera.blockSignals(True); self.mon_tera.clear()
        for key, label in TYPE_LABELS.items(): self.mon_tera.addItem(f"{label} [{key}]", key)
        self.mon_tera.blockSignals(False)
        range_entries = {key: value for key, value in self.frontier_values.items() if key.startswith(("FRONTIER_MON_", "FRONTIER_MONS_", "NUM_FRONTIER_MONS"))}
        self.fill_combo(self.range_start, range_entries, {}, "FRONTIER_MON_SUNKERN"); self.fill_combo(self.range_end, range_entries, {}, "FRONTIER_MON_SUNKERN")

    def item_allowed_for_frontier(self, key: str) -> bool:
        if key == "ITEM_NONE":
            return True
        pocket = self.item_pockets.get(key, "")
        if pocket in {"POCKET_TM_HM", "POCKET_KEY_ITEMS"}:
            return False
        if pocket == "POCKET_BERRIES":
            return True
        return self.item_hold_effects.get(key, "HOLD_EFFECT_NONE") not in {"", "HOLD_EFFECT_NONE"}

    def item_matches_category(self, key: str, category: str) -> bool:
        if key == "ITEM_NONE":
            return category == "all"
        pocket = self.item_pockets.get(key, "")
        hold = self.item_hold_effects.get(key, "HOLD_EFFECT_NONE")
        if category == "berry":
            return pocket == "POCKET_BERRIES"
        if category == "z":
            return hold == "HOLD_EFFECT_Z_CRYSTAL" or "_Z" in key or "Z_CRYSTAL" in key
        if category == "mega":
            return hold == "HOLD_EFFECT_MEGA_STONE"
        if category == "hold":
            return hold not in {"", "HOLD_EFFECT_NONE"} or pocket == "POCKET_BERRIES"
        return True

    def item_search_text(self, key: str) -> str:
        return " ".join([key, self.item_names.get(key, ""), self.item_pockets.get(key, ""), self.item_hold_effects.get(key, "")]).casefold()

    def refresh_item_choices(self, current: object | None = None) -> None:
        if not hasattr(self, "mon_item"):
            return
        selected = current if isinstance(current, str) and current.startswith("ITEM_") else self.combo_value(self.mon_item)
        category = self.mon_item_category.currentData() if hasattr(self, "mon_item_category") else "all"
        query = self.mon_item_filter.text().casefold().strip() if hasattr(self, "mon_item_filter") else ""
        keys = []
        for key in self.item_values:
            if not self.item_allowed_for_frontier(key):
                continue
            if not self.item_matches_category(key, category):
                continue
            if query and query not in self.item_search_text(key):
                continue
            keys.append(key)
        keys = sorted(keys, key=lambda key: (self.item_names.get(key, key).casefold(), self.item_values.get(key, 0)))
        if isinstance(selected, str) and selected and selected not in keys and selected in self.item_values:
            keys.append(selected)
        self.mon_item.blockSignals(True); self.mon_item.clear(); self.mon_item.setEditable(True)
        for key in keys:
            extra = "" if self.item_allowed_for_frontier(key) else " / 範囲外"
            self.mon_item.addItem(f"{self.item_names.get(key, key)}{extra} [{key}]", key)
        self.set_combo(self.mon_item, selected if isinstance(selected, str) and selected else "ITEM_NONE")
        self.mon_item.blockSignals(False)

    def refresh_ability_choices(self, current: object | None = None) -> None:
        if not hasattr(self, "mon_ability"):
            return
        selected = current if isinstance(current, str) and current.startswith("ABILITY_") else self.combo_value(self.mon_ability)
        species = self.combo_value(self.mon_species) if hasattr(self, "mon_species") else "SPECIES_NONE"
        keys = list(self.species_abilities.get(species, ["ABILITY_NONE"]))
        if isinstance(selected, str) and selected and selected not in keys:
            if self.loading:
                keys.append(selected)
            else:
                selected = keys[0] if keys else "ABILITY_NONE"
        self.mon_ability.blockSignals(True); self.mon_ability.clear()
        for key in keys:
            extra = "" if key in self.species_abilities.get(species, keys) else " / 種族外"
            self.mon_ability.addItem(f"{self.ability_names.get(key, key)}{extra} [{key}]", key)
        self.set_combo(self.mon_ability, selected if isinstance(selected, str) and selected else (keys[0] if keys else "ABILITY_NONE"))
        self.mon_ability.blockSignals(False)

    def refresh_species_dependent_choices(self) -> None:
        self.refresh_ability_choices()
        self.refresh_move_choices()

    def move_matches_filters(self, move: str) -> bool:
        if move == "MOVE_NONE":
            return True
        category = self.move_category_filter.currentData() if hasattr(self, "move_category_filter") else ""
        move_type = self.move_type_filter.currentData() if hasattr(self, "move_type_filter") else ""
        metadata = self.move_metadata.get(move, MoveMetadata("TYPE_NONE", ""))
        if category and metadata.category != category:
            return False
        if move_type and metadata.type != move_type:
            return False
        return True

    def move_label(self, move: str, sources: dict[str, set[str]], off_filter: bool = False) -> str:
        if move == "MOVE_NONE":
            return "なし [MOVE_NONE]"
        metadata = self.move_metadata.get(move, MoveMetadata("TYPE_NONE", ""))
        details = []
        if metadata.type in TYPE_LABELS:
            details.append(TYPE_LABELS[metadata.type])
        if metadata.category in CATEGORY_LABELS:
            details.append(CATEGORY_LABELS[metadata.category])
        source_labels = []
        if move in sources.get("level", set()): source_labels.append("Lv")
        if move in sources.get("egg", set()): source_labels.append("Egg")
        if move in sources.get("teachable", set()): source_labels.append("TM")
        if source_labels:
            details.append("/".join(source_labels))
        if off_filter:
            details.append("filter外")
        suffix = f" ({' / '.join(details)})" if details else ""
        return f"{self.move_names.get(move, move)}{suffix} [{move}]"

    def fill_combo(self, combo: QComboBox, values: dict[str, int], labels: dict[str, str], fallback: str) -> None:
        combo.blockSignals(True); editable = combo.isEditable(); combo.clear(); combo.setEditable(editable)
        for key, _value in sorted(values.items(), key=lambda item: item[1]):
            combo.addItem(f"{labels.get(key, key)} [{key}]", key)
        if combo.findData(fallback) >= 0: combo.setCurrentIndex(combo.findData(fallback))
        combo.blockSignals(False)

    def build_species_learnsets(self, species_records: list[SourceRecord]) -> dict[str, set[str]]:
        root = self.window.root / "src/data/pokemon"

        def parse_arrays(paths: Iterable[Path]) -> dict[str, set[str]]:
            indexed: dict[str, set[str]] = {}
            pattern = re.compile(r"\b([A-Za-z0-9_]+)\[\]\s*=\s*\{(.*?)(?:\n\s*\};)", re.S)
            for path in paths:
                if not path.exists():
                    continue
                source = read_utf8(path)
                for match in pattern.finditer(source):
                    moves = {move for move in re.findall(r"\bMOVE_[A-Z0-9_]+\b", match.group(2)) if move not in {"MOVE_NONE", "MOVE_UNAVAILABLE"}}
                    indexed[match.group(1)] = moves
            return indexed

        indexed_by_source = {
            "level": parse_arrays(sorted((root / "level_up_learnsets").glob("*.h"))),
            "egg": parse_arrays([root / "egg_moves.h"]),
            "teachable": parse_arrays([root / "teachable_learnsets.h"]),
        }
        self.species_move_sources = {}
        result: dict[str, set[str]] = {}
        for record in species_records:
            groups = {
                "level": indexed_by_source["level"].get(record.values.get("levelUpLearnset", ""), set()),
                "egg": indexed_by_source["egg"].get(record.values.get("eggMoveLearnset", ""), set()),
                "teachable": indexed_by_source["teachable"].get(record.values.get("teachableLearnset", ""), set()),
            }
            self.species_move_sources[record.key] = groups
            result[record.key] = set().union(*groups.values())
        return result

    def load_frontier_mons(self) -> None:
        path = self.window.root / "src/data/battle_frontier/battle_frontier_mons.h"
        self.records, self.contents = indexed_records(self.window.root, [path], "FRONTIER_MON_", FRONTIER_MON_FIELDS) if path.exists() else ([], {})
        self.mon_states.clear(); self.current_mon = None

    def load_macros(self) -> None:
        path = self.window.root / "src/data/battle_frontier/battle_frontier_trainer_mons.h"; self.macros.clear()
        if not path.exists(): return
        source = read_utf8(path); offset = 0
        while offset < len(source):
            line_end = source.find("\n", offset); line_end = len(source) if line_end < 0 else line_end + 1
            line = source[offset:line_end]; match = re.match(r"\s*#define\s+(FRONTIER_MONS_[A-Z0-9_]+)(\([^)]*\))?", line)
            if not match:
                offset = line_end; continue
            end = line_end
            while end < len(source):
                previous = source[source.rfind("\n", 0, end) + 1:end].rstrip("\r\n")
                if not previous.rstrip().endswith("\\"): break
                next_end = source.find("\n", end); end = len(source) if next_end < 0 else next_end + 1
            raw = source[offset:end]; mons = re.findall(r"\bFRONTIER_MON_[A-Z0-9_]+\b", raw)
            self.macros.append(FrontierMacro(path, match.group(1), offset, end, raw, mons, bool(match.group(2))))
            offset = end
        self.rebuild_usage_counts()

    def load_trainers(self) -> None:
        path = self.window.root / "src/data/battle_frontier/battle_frontier_trainers.h"
        self.trainer_records, self.trainer_contents = indexed_records(self.window.root, [path], "FRONTIER_TRAINER_", ["facilityClass", "trainerName", "monSet"]) if path.exists() else ([], {})
        self.current_trainer = None

    def load_general_trainers(self) -> None:
        self.general_trainer_path = self.window.root / "src/data/trainers.party"; self.general_trainers.clear(); self.general_trainer_states.clear(); self.current_general_trainer = None
        if not self.general_trainer_path.exists():
            self.general_trainer_source = ""; return
        self.general_trainer_source = read_utf8(self.general_trainer_path)
        headers = list(re.finditer(r"(?m)^===\s*(TRAINER_[A-Z0-9_]+)\s*===\s*(?:\r?\n|$)", self.general_trainer_source))
        for index, match in enumerate(headers):
            start = match.start(); end = headers[index + 1].start() if index + 1 < len(headers) else len(self.general_trainer_source)
            raw = self.general_trainer_source[start:end]
            self.general_trainers.append(GeneralTrainerBlock(self.general_trainer_path, match.group(1), start, end, raw, self.trainer_party_field(raw, "Name"), self.trainer_party_field(raw, "Class"), self.trainer_party_count(raw)))

    @staticmethod
    def trainer_party_field(block: str, name: str) -> str:
        match = re.search(rf"(?m)^{re.escape(name)}:\s*(.*)$", block)
        return match.group(1).strip() if match else ""

    @staticmethod
    def trainer_party_count(block: str) -> int:
        body = block.split("\n\n", 1)[1] if "\n\n" in block else ""
        count = 0
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("-", "/*", "*")) or ":" in stripped:
                continue
            if stripped.startswith("==="):
                continue
            count += 1
        return count

    def load_factory(self) -> None:
        self.factory_path = self.window.root / "src/battle_factory.c"; self.factory_source = read_utf8(self.factory_path) if self.factory_path.exists() else ""; self.factory_ranges.clear(); self.factory_ivs.clear(); self.range_states.clear(); self.iv_states.clear()
        self.parse_factory_ranges(); self.parse_factory_ivs(); self.rebuild_factory_usage()

    def parse_factory_ranges(self) -> None:
        match = re.search(r"static\s+const\s+u16\s+sInitialRentalMonRanges\[\]\[2\]\s*=\s*\{", self.factory_source)
        if not match: return
        body_start = self.factory_source.find("{", match.end() - 1) + 1; body_end = balanced_end(self.factory_source, body_start - 1)
        if body_end is None: return
        body = self.factory_source[body_start:body_end - 1]
        pattern = re.compile(r"(?m)^([ \t]*)\{\s*([^,{}]+?)\s*,\s*([^{}]+?)\s*\}\s*,?([ \t]*(?://[^\r\n]*)?)(\r?\n|$)")
        for index, row in enumerate(pattern.finditer(body)):
            self.factory_ranges.append(FactoryRangeRecord(index, body_start + row.start(), body_start + row.end(), row.group(1), row.group(2).strip(), row.group(3).strip(), row.group(4).strip(), row.group(5)))
        half = len(self.factory_ranges) // 2
        for row in self.factory_ranges: row.mode = "Level 50" if row.index < half else "Open Level"

    def parse_factory_ivs(self) -> None:
        match = re.search(r"static\s+const\s+u8\s+sFixedIVTable\[\]\[2\]\s*=\s*\{", self.factory_source)
        if not match: return
        body_start = self.factory_source.find("{", match.end() - 1) + 1; body_end = balanced_end(self.factory_source, body_start - 1)
        if body_end is None: return
        body = self.factory_source[body_start:body_end - 1]
        pattern = re.compile(r"(?m)^([ \t]*)\{\s*(\d+)\s*,\s*(\d+)\s*\}\s*,?([ \t]*(?://[^\r\n]*)?)(\r?\n|$)")
        for index, row in enumerate(pattern.finditer(body)):
            self.factory_ivs.append(FactoryIvRecord(index, body_start + row.start(), body_start + row.end(), row.group(1), int(row.group(2)), int(row.group(3)), row.group(4).strip(), row.group(5)))

    def rebuild_usage_counts(self) -> None:
        self.mon_usage_counts = {}
        for macro in self.macros:
            for mon in macro.mons: self.mon_usage_counts[mon] = self.mon_usage_counts.get(mon, 0) + 1

    def rebuild_factory_usage(self) -> None:
        self.factory_usage = set()
        for row in self.factory_ranges:
            first = token_value(row.first, self.frontier_values); last = token_value(row.last, self.frontier_values)
            if first is None or last is None: continue
            for value in range(first, last + 1):
                key = self.frontier_by_value.get(value)
                if key: self.factory_usage.add(key)

    def mon_flag_values(self, record: SourceRecord) -> dict[str, bool]:
        item = first_token(record.values.get("heldItem", ""), "ITEM_", "ITEM_NONE")
        hold = self.item_hold_effects.get(item, "")
        tera = first_token(record.values.get("teraType", ""), "TYPE_", "TYPE_NONE")
        return {
            "mega": hold == "HOLD_EFFECT_MEGA_STONE",
            "z": hold == "HOLD_EFFECT_Z_CRYSTAL" or "_Z" in item or "Z_CRYSTAL" in item,
            "dmax": bool_literal(record.values.get("shouldUseDynamax", "FALSE")) or bool_literal(record.values.get("gigantamaxFactor", "FALSE")) or display_integer(record.values.get("dynamaxLevel", "0")) > 0,
            "tera": tera not in {"", "TYPE_NONE"},
            "shiny": bool_literal(record.values.get("isShiny", "FALSE")),
            "unused": self.mon_usage_counts.get(record.key, 0) == 0,
        }

    def visible_mons(self) -> list[SourceRecord]:
        query = self.mon_search.text().casefold(); rows = []
        for record in self.records:
            species = first_token(record.values.get("species", ""), "SPECIES_", "SPECIES_NONE")
            haystack = " ".join([record.key, species, self.species_names.get(species, ""), record.values.get("heldItem", "")]).casefold()
            if query and query not in haystack: continue
            if self.mon_unused_only.isChecked() and self.mon_usage_counts.get(record.key, 0): continue
            rows.append(record)
        return rows

    def refresh_mons(self) -> None:
        rows = self.visible_mons(); self.mon_table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            species = first_token(record.values.get("species", ""), "SPECIES_", "SPECIES_NONE"); item = first_token(record.values.get("heldItem", ""), "ITEM_", "ITEM_NONE")
            flags = self.mon_flag_values(record)
            values = [str(self.frontier_values.get(record.key, "")), record.key, self.species_names.get(species, species), self.item_names.get(item, item), str(self.mon_usage_counts.get(record.key, 0)), "yes" if record.key in self.factory_usage else "", *["✓" if flags[key] else "" for key in ("mega", "z", "dmax", "tera", "shiny", "unused")]]
            for column, value in enumerate(values):
                item_widget = QTableWidgetItem(value); item_widget.setData(Qt.ItemDataRole.UserRole, record); self.mon_table.setItem(row, column, item_widget)

    def default_mon_values(self, record: SourceRecord) -> dict[str, str]:
        return {
            "nickname": string_from_record(record, "nickname") if raw_field(record.block, "nickname") is not None else "",
            "species": first_token(record.values.get("species", ""), "SPECIES_", "SPECIES_NONE"),
            "moves": record.values.get("moves", "{MOVE_NONE, MOVE_NONE, MOVE_NONE, MOVE_NONE}"),
            "heldItem": first_token(record.values.get("heldItem", ""), "ITEM_", "ITEM_NONE"),
            "ev": record.values.get("ev", ""), "iv": record.values.get("iv", ""),
            "ability": first_token(record.values.get("ability", ""), "ABILITY_", "ABILITY_NONE"),
            "lvl": record.values.get("lvl", "0"), "ball": first_token(record.values.get("ball", ""), "BALL_", "BALL_POKE"),
            "friendship": record.values.get("friendship", "0"), "nature": first_token(record.values.get("nature", ""), "NATURE_", "NATURE_HARDY"),
            "gender": first_token(record.values.get("gender", ""), "TRAINER_MON_", "0"), "isShiny": record.values.get("isShiny", "FALSE"),
            "teraType": first_token(record.values.get("teraType", ""), "TYPE_", "TYPE_NONE"), "gigantamaxFactor": record.values.get("gigantamaxFactor", "FALSE"),
            "shouldUseDynamax": record.values.get("shouldUseDynamax", "FALSE"), "dynamaxLevel": record.values.get("dynamaxLevel", "0"), "tags": record.values.get("tags", "0"),
        }

    def select_mon(self) -> None:
        previous = self.current_mon
        if previous and not self.loading:
            self.mon_states[previous.key] = self.values_for_mon(previous)
        selected = self.mon_table.selectedItems()
        if not selected: return
        self.current_mon = selected[0].data(Qt.ItemDataRole.UserRole); values = self.mon_states.get(self.current_mon.key, self.default_mon_values(self.current_mon)); self.loading = True
        self.mon_nickname.setText(values["nickname"]); self.set_combo(self.mon_species, values["species"]); self.refresh_ability_choices(values["ability"]); self.refresh_item_choices(values["heldItem"])
        for combo, key in ((self.mon_item, "heldItem"), (self.mon_ability, "ability"), (self.mon_nature, "nature"), (self.mon_ball, "ball"), (self.mon_gender, "gender"), (self.mon_tera, "teraType")): self.set_combo(combo, values[key])
        self.refresh_move_choices(); moves = re.findall(r"\bMOVE_[A-Z0-9_]+\b", values["moves"]); moves = (moves + ["MOVE_NONE"] * 4)[:4]
        for combo, move in zip(self.mon_moves, moves): self.set_combo(combo, move)
        self.refresh_move_choices()
        for spin, value in zip(self.ev_boxes, numeric_args(values["ev"], 6)): spin.setValue(value)
        for spin, value in zip(self.iv_boxes, numeric_args(values["iv"], 6)): spin.setValue(value)
        self.mon_level.setValue(display_integer(values["lvl"])); self.mon_friendship.setValue(display_integer(values["friendship"])); self.mon_dmax_level.setValue(display_integer(values["dynamaxLevel"]))
        self.mon_shiny.setChecked(bool_literal(values["isShiny"])); self.mon_gmax.setChecked(bool_literal(values["gigantamaxFactor"])); self.mon_dmax.setChecked(bool_literal(values["shouldUseDynamax"])); self.mon_tags.setText(values["tags"])
        self.loading = False; self.update_mon_summary()

    def refresh_move_choices(self) -> None:
        if not hasattr(self, "mon_moves"): return
        species = self.combo_value(self.mon_species) or "SPECIES_NONE"; preferred = self.species_learnsets.get(species, set()); selected = [self.combo_value(combo) or "MOVE_NONE" for combo in self.mon_moves]
        sources = self.species_move_sources.get(species, {})
        ordered = ["MOVE_NONE"]
        for group in ("level", "egg", "teachable"):
            for move in sorted(sources.get(group, set()), key=lambda key: self.move_names.get(key, key)):
                if move not in ordered:
                    ordered.append(move)
        for move in selected:
            if move and move not in ordered: ordered.append(move)
        for move in sorted(self.move_values, key=lambda key: self.move_names.get(key, key)):
            if move not in ordered: ordered.append(move)
        filtered = [move for move in ordered if self.move_matches_filters(move)]
        for move in selected:
            if move and move not in filtered:
                filtered.append(move)
        for combo, current in zip(self.mon_moves, selected):
            combo.blockSignals(True); combo.clear(); combo.setEditable(True)
            for move in filtered:
                combo.addItem(self.move_label(move, sources, off_filter=move not in ordered or not self.move_matches_filters(move)), move)
            self.set_combo(combo, current); combo.blockSignals(False)
        off_list = [move for move in selected if move not in preferred and move != "MOVE_NONE"]
        self.move_filter_label.setText(f"Lv {len(sources.get('level', set()))} / Egg {len(sources.get('egg', set()))} / TM {len(sources.get('teachable', set()))} / Total {len(preferred)} / shown {len(filtered)} / off-list: {', '.join(off_list) if off_list else 'none'}")

    @staticmethod
    def hidden_power_type_from_ivs(ivs: list[int]) -> str:
        values = (ivs + [0] * 6)[:6]
        type_bits = ((values[0] & 1) << 0) | ((values[1] & 1) << 1) | ((values[2] & 1) << 2) | ((values[3] & 1) << 3) | ((values[4] & 1) << 4) | ((values[5] & 1) << 5)
        index = ((len(HIDDEN_POWER_TYPE_ORDER) - 1) * type_bits) // 63
        return HIDDEN_POWER_TYPE_ORDER[index]

    def current_hidden_power_type(self) -> str:
        return self.hidden_power_type_from_ivs([box.value() for box in self.iv_boxes])

    def selected_moves(self) -> list[str]:
        return [self.combo_value(combo) or "MOVE_NONE" for combo in self.mon_moves]

    def values_for_mon(self, record: SourceRecord) -> dict[str, str]:
        ev_values = [box.value() for box in self.ev_boxes]; iv_values = [box.value() for box in self.iv_boxes]
        raw_ev = raw_field(record.block, "ev") is not None; raw_iv = raw_field(record.block, "iv") is not None
        return {
            "nickname": self.mon_nickname.text().strip(),
            "species": self.combo_value(self.mon_species), "moves": "{" + ", ".join(self.combo_value(combo) or "MOVE_NONE" for combo in self.mon_moves) + "}",
            "heldItem": self.combo_value(self.mon_item) or "ITEM_NONE", "ev": f"TRAINER_PARTY_EVS({', '.join(str(value) for value in ev_values)})" if any(ev_values) or raw_ev else "",
            "iv": f"TRAINER_PARTY_IVS({', '.join(str(value) for value in iv_values)})" if any(iv_values) or raw_iv else "",
            "ability": self.combo_value(self.mon_ability) or "ABILITY_NONE", "lvl": str(self.mon_level.value()), "ball": self.combo_value(self.mon_ball) or "BALL_POKE",
            "friendship": str(self.mon_friendship.value()), "nature": self.combo_value(self.mon_nature) or "NATURE_HARDY", "gender": self.combo_value(self.mon_gender) or "0",
            "isShiny": "TRUE" if self.mon_shiny.isChecked() else "FALSE", "teraType": self.combo_value(self.mon_tera) or "TYPE_NONE",
            "gigantamaxFactor": "TRUE" if self.mon_gmax.isChecked() else "FALSE", "shouldUseDynamax": "TRUE" if self.mon_dmax.isChecked() else "FALSE",
            "dynamaxLevel": str(self.mon_dmax_level.value()), "tags": self.mon_tags.text().strip() or "0",
        }

    def capture_mon(self, record: SourceRecord | None = None) -> None:
        target = record or self.current_mon
        if target and not self.loading:
            self.mon_states[target.key] = self.values_for_mon(target)

    def proposed_mon_block(self, record: SourceRecord) -> str:
        values = dict(self.mon_states.get(record.key, self.default_mon_values(record)))
        missing_defaults = {"nickname": "", "heldItem": "ITEM_NONE", "ev": "", "iv": "", "ability": "ABILITY_NONE", "lvl": "0", "ball": "BALL_POKE", "friendship": "0", "nature": "NATURE_HARDY", "gender": "0", "isShiny": "FALSE", "teraType": "TYPE_NONE", "gigantamaxFactor": "FALSE", "shouldUseDynamax": "FALSE", "dynamaxLevel": "0", "tags": "0"}
        for field, default in missing_defaults.items():
            if raw_field(record.block, field) is None and values.get(field) == default: values[field] = ""
        return ensure_designated_initializer_commas(replace_record_fields(record, values, {"nickname"}, {"nickname": "J_COMPOUND_STRING"}))

    def mon_changed(self) -> None:
        if self.loading or not self.current_mon: return
        self.update_mon_summary(); self.window.status(f"Pending Frontier mon: {self.current_mon.key}")

    def update_mon_summary(self) -> None:
        if not self.current_mon: return
        species = self.combo_value(self.mon_species); item = self.combo_value(self.mon_item); ev_total = sum(box.value() for box in self.ev_boxes)
        hidden_power = self.current_hidden_power_type(); hidden_power_label = TYPE_LABELS.get(hidden_power, hidden_power)
        uses_hidden_power = "MOVE_HIDDEN_POWER" in self.selected_moves()
        self.hidden_power_label.setText(f"{hidden_power_label} [{hidden_power}]" + (" / 現在の技に設定あり" if uses_hidden_power else ""))
        self.mon_summary.setText(f"{self.current_mon.key} / {self.species_names.get(species, species)} / {self.item_names.get(item, item)} / EV {ev_total} / Hidden Power {hidden_power_label}")

    def open_selected_move(self, slot: int) -> None:
        if 0 <= slot < len(self.mon_moves): self.window.open_move(self.combo_value(self.mon_moves[slot]))

    def save_mons(self) -> None:
        self.capture_mon(); changed = [record for record in self.records if record.key in self.mon_states and self.proposed_mon_block(record) != record.block]
        if not changed: self.window.status("No Frontier mon changes"); return
        try:
            for path, records in self.group_records(changed).items():
                source = self.contents[path]
                if read_utf8(path) != source: raise RuntimeError(f"{rel(self.window.root, path)} changed on disk; reload before saving.")
                for record in sorted(records, key=lambda item: item.start, reverse=True): source = source[:record.start] + self.proposed_mon_block(record) + source[record.end:]
                assert_no_concatenated_designators(path, source, self.window.root)
                write_with_backup(path, source)
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Save failed", str(error)); return
        selected = self.current_mon.key if self.current_mon else ""; self.load_frontier_mons(); self.refresh_mons(); self.select_mon_key(selected); self.window.status(f"Saved {len(changed)} Frontier mon record(s)")

    @staticmethod
    def group_records(records: list[SourceRecord]) -> dict[Path, list[SourceRecord]]:
        by_path: dict[Path, list[SourceRecord]] = {}
        for record in records: by_path.setdefault(record.path, []).append(record)
        return by_path

    def select_mon_key(self, key: str) -> None:
        for row in range(self.mon_table.rowCount()):
            item = self.mon_table.item(row, 1)
            if item and item.text() == key: self.mon_table.selectRow(row); return

    def show_mon_diff(self) -> None:
        self.capture_mon()
        if self.current_mon: DiffDialog(self, f"Diff: {self.current_mon.key}", self.current_mon.block, self.proposed_mon_block(self.current_mon)).exec()

    def visible_trainers(self) -> list[SourceRecord]:
        query = self.trainer_search.text().casefold(); rows = []
        for record in self.trainer_records:
            text = " ".join([record.key, string_from_record(record, "trainerName"), record.values.get("facilityClass", ""), record.values.get("monSet", "")]).casefold()
            if not query or query in text: rows.append(record)
        return rows

    def refresh_trainers(self) -> None:
        rows = self.visible_trainers(); self.trainer_table.setRowCount(len(rows)); macro_names = [macro.name for macro in self.macros]
        self.trainer_monset.blockSignals(True); self.trainer_monset.clear(); self.trainer_monset.setEditable(True)
        for name in macro_names: self.trainer_monset.addItem(name, name)
        self.trainer_monset.blockSignals(False)
        for row, record in enumerate(rows):
            values = [record.key, string_from_record(record, "trainerName"), record.values.get("facilityClass", ""), self.monset_inner(record.values.get("monSet", ""))]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, record); self.trainer_table.setItem(row, column, item)

    @staticmethod
    def monset_inner(value: str) -> str:
        start, end = value.find("{"), value.rfind("}")
        return value[start + 1:end].strip() if start >= 0 and end > start else value.strip()

    def select_trainer(self) -> None:
        selected = self.trainer_table.selectedItems()
        if not selected: return
        self.current_trainer = selected[0].data(Qt.ItemDataRole.UserRole); inner = self.monset_inner(self.current_trainer.values.get("monSet", ""))
        self.trainer_name.setText(f"{string_from_record(self.current_trainer, 'trainerName')} [{self.current_trainer.key}]"); self.set_combo(self.trainer_monset, inner)
        first_macro = re.search(r"\b(FRONTIER_MONS_[A-Z0-9_]+)\b", inner)
        if first_macro: self.set_combo(self.macro_select, first_macro.group(1))

    def save_trainer(self) -> None:
        if not self.current_trainer: return
        inner = self.combo_value(self.trainer_monset); new_block = replace_record_fields(self.current_trainer, {"monSet": f"(const u16[]){{{inner}}}"}, set())
        if new_block == self.current_trainer.block: self.window.status("No trainer monSet changes"); return
        try:
            source = self.trainer_contents[self.current_trainer.path]
            if read_utf8(self.current_trainer.path) != source: raise RuntimeError(f"{rel(self.window.root, self.current_trainer.path)} changed on disk; reload before saving.")
            write_with_backup(self.current_trainer.path, source[:self.current_trainer.start] + new_block + source[self.current_trainer.end:])
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Save failed", str(error)); return
        selected = self.current_trainer.key; self.load_trainers(); self.refresh_trainers(); self.window.status(f"Saved trainer monSet: {selected}")

    def show_trainer_diff(self) -> None:
        if not self.current_trainer: return
        inner = self.combo_value(self.trainer_monset); new_block = replace_record_fields(self.current_trainer, {"monSet": f"(const u16[]){{{inner}}}"}, set())
        DiffDialog(self, f"Diff: {self.current_trainer.key}", self.current_trainer.block, new_block).exec()

    def capture_general_trainer(self) -> None:
        if self.current_general_trainer and not self.loading:
            self.general_trainer_states[self.current_general_trainer.key] = self.general_trainer_editor.toPlainText()

    def general_trainer_text(self, block: GeneralTrainerBlock) -> str:
        return self.general_trainer_states.get(block.key, block.raw)

    def visible_general_trainers(self) -> list[GeneralTrainerBlock]:
        query = self.general_trainer_search.text().casefold(); rows: list[GeneralTrainerBlock] = []
        for block in self.general_trainers:
            text = " ".join([block.key, block.name, block.trainer_class, block.raw]).casefold()
            if not query or query in text:
                rows.append(block)
        return rows

    @staticmethod
    def general_trainer_flags(block: GeneralTrainerBlock) -> str:
        flags = []
        raw = block.raw.casefold()
        if re.search(r"(?mi)^double battle:\s*yes", block.raw): flags.append("Double")
        if re.search(r"(?mi)^items:\s*\S", block.raw): flags.append("Items")
        if "shiny: yes" in raw: flags.append("Shiny")
        if "dynamax level:" in raw or "gigantamax: yes" in raw: flags.append("DMax")
        if "tera type:" in raw: flags.append("Tera")
        return ", ".join(flags)

    def refresh_general_trainers(self) -> None:
        rows = self.visible_general_trainers(); self.general_trainer_table.setRowCount(len(rows))
        for row, block in enumerate(rows):
            dirty = self.general_trainer_text(block) != block.raw
            values = [("*" if dirty else "") + block.key, block.name, block.trainer_class, str(block.party_count), self.general_trainer_flags(block)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, block); self.general_trainer_table.setItem(row, column, item)

    def select_general_trainer(self) -> None:
        previous = self.current_general_trainer
        if previous:
            self.capture_general_trainer()
        selected = self.general_trainer_table.selectedItems()
        if not selected: return
        self.current_general_trainer = selected[0].data(Qt.ItemDataRole.UserRole)
        self.loading = True
        self.general_trainer_editor.setPlainText(self.general_trainer_text(self.current_general_trainer))
        self.loading = False
        self.general_trainer_label.setText(f"{self.current_general_trainer.key} / {self.current_general_trainer.name} / {self.current_general_trainer.trainer_class} / Pokemon {self.current_general_trainer.party_count}")

    def general_trainer_changed(self) -> None:
        if self.loading or not self.current_general_trainer: return
        self.general_trainer_states[self.current_general_trainer.key] = self.general_trainer_editor.toPlainText()
        self.refresh_general_trainers(); self.window.status(f"Pending trainer.party block: {self.current_general_trainer.key}")

    def save_general_trainer(self) -> None:
        self.capture_general_trainer()
        if not self.current_general_trainer: return
        new_block = self.general_trainer_text(self.current_general_trainer)
        if new_block == self.current_general_trainer.raw:
            self.window.status("No trainer.party changes"); return
        try:
            disk = read_utf8(self.general_trainer_path)
            if disk[self.current_general_trainer.start:self.current_general_trainer.end] != self.current_general_trainer.raw:
                raise RuntimeError(f"{rel(self.window.root, self.general_trainer_path)} changed on disk; reload before saving.")
            write_with_backup(self.general_trainer_path, disk[:self.current_general_trainer.start] + new_block + disk[self.current_general_trainer.end:])
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Save failed", str(error)); return
        selected = self.current_general_trainer.key; self.load_general_trainers(); self.refresh_general_trainers(); self.select_general_trainer_key(selected); self.window.status(f"Saved trainer.party block: {selected}")

    def show_general_trainer_diff(self) -> None:
        self.capture_general_trainer()
        if self.current_general_trainer:
            DiffDialog(self, f"Diff: {self.current_general_trainer.key}", self.current_general_trainer.raw, self.general_trainer_text(self.current_general_trainer)).exec()

    def select_general_trainer_key(self, key: str) -> None:
        for row in range(self.general_trainer_table.rowCount()):
            item = self.general_trainer_table.item(row, 0)
            if item and item.text().lstrip("*") == key:
                self.general_trainer_table.selectRow(row); return

    def refresh_macro_select(self) -> None:
        self.macro_select.blockSignals(True); self.macro_select.clear()
        for macro in self.macros:
            suffix = " (args)" if macro.parameterized else ""; self.macro_select.addItem(f"{macro.name}{suffix} / use {self.macro_usage(macro.name)} / mons {len(macro.mons)}", macro.name)
        self.macro_select.blockSignals(False)
        if self.macros: self.macro_select.setCurrentIndex(0); self.select_macro()

    def macro_usage(self, name: str) -> int:
        return sum(1 for record in self.trainer_records if name in record.values.get("monSet", ""))

    def select_macro(self) -> None:
        name = self.macro_select.currentData(); self.current_macro = next((macro for macro in self.macros if macro.name == name), None)
        self.loading = True; self.macro_editor.setPlainText(self.current_macro.raw if self.current_macro else ""); self.macro_original = self.macro_editor.toPlainText(); self.loading = False; self.refresh_macro_mons()

    def refresh_macro_mons(self) -> None:
        raw = self.macro_editor.toPlainText(); mons = re.findall(r"\bFRONTIER_MON_[A-Z0-9_]+\b", raw); self.macro_mons.setRowCount(len(mons)); by_key = {record.key: record for record in self.records}
        for row, key in enumerate(mons):
            record = by_key.get(key); species = first_token(record.values.get("species", ""), "SPECIES_", "SPECIES_NONE") if record else ""; held = first_token(record.values.get("heldItem", ""), "ITEM_", "ITEM_NONE") if record else ""
            for column, value in enumerate((key, self.species_names.get(species, species), self.item_names.get(held, held))):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, key); self.macro_mons.setItem(row, column, item)

    def macro_changed(self) -> None:
        if self.loading: return
        self.refresh_macro_mons()
        if self.current_macro: self.window.status(f"Pending macro body: {self.current_macro.name}")

    def save_macro(self) -> None:
        if not self.current_macro: return
        new_raw = self.macro_editor.toPlainText()
        if new_raw == self.current_macro.raw: self.window.status("No macro changes"); return
        try:
            source = read_utf8(self.current_macro.path)
            if source[self.current_macro.start:self.current_macro.end] != self.current_macro.raw: raise RuntimeError(f"{rel(self.window.root, self.current_macro.path)} changed on disk; reload before saving.")
            write_with_backup(self.current_macro.path, source[:self.current_macro.start] + new_raw + source[self.current_macro.end:])
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Save failed", str(error)); return
        selected = self.current_macro.name; self.load_macros(); self.refresh_macro_select(); self.set_combo(self.macro_select, selected); self.window.status(f"Saved macro: {selected}")

    def show_macro_diff(self) -> None:
        if self.current_macro: DiffDialog(self, f"Diff: {self.current_macro.name}", self.current_macro.raw, self.macro_editor.toPlainText()).exec()

    def open_macro_mon(self, item: QTableWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key: self.tabs.setCurrentIndex(0); self.select_mon_key(key)

    def refresh_factory(self) -> None:
        self.range_table.setRowCount(len(self.factory_ranges))
        for row, record in enumerate(self.factory_ranges):
            first, last = self.range_states.get(record.index, (record.first, record.last)); count = self.range_count(first, last)
            values = [record.mode, str((record.index % max(1, len(self.factory_ranges) // 2)) + 1), first, last, str(count) if count is not None else "?", record.comment]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, record.index); self.range_table.setItem(row, column, item)
        self.iv_table.setRowCount(len(self.factory_ivs))
        for row, record in enumerate(self.factory_ivs):
            low, high = self.iv_states.get(record.index, (record.low, record.high))
            for column, value in enumerate((str(record.index + 1), str(low), str(high))):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, record.index); self.iv_table.setItem(row, column, item)

    def range_count(self, first: str, last: str) -> int | None:
        start = token_value(first, self.frontier_values); end = token_value(last, self.frontier_values)
        if start is None or end is None or end < start: return None
        return end - start + 1

    def select_range(self) -> None:
        selected = self.range_table.selectedItems()
        if not selected: return
        index = selected[0].data(Qt.ItemDataRole.UserRole); record = self.factory_ranges[index]; first, last = self.range_states.get(index, (record.first, record.last))
        self.loading = True; self.set_combo(self.range_start, first); self.set_combo(self.range_end, last); self.loading = False; self.update_range_status()

    def select_iv(self) -> None:
        selected = self.iv_table.selectedItems()
        if not selected: return
        index = selected[0].data(Qt.ItemDataRole.UserRole); record = self.factory_ivs[index]; low, high = self.iv_states.get(index, (record.low, record.high))
        self.loading = True; self.iv_low.setValue(low); self.iv_high.setValue(high); self.loading = False

    def factory_changed(self) -> None:
        if self.loading: return
        selected_range = self.range_table.selectedItems()
        if selected_range:
            index = selected_range[0].data(Qt.ItemDataRole.UserRole); self.range_states[index] = (self.combo_value(self.range_start), self.combo_value(self.range_end)); self.update_range_status()
        selected_iv = self.iv_table.selectedItems()
        if selected_iv:
            index = selected_iv[0].data(Qt.ItemDataRole.UserRole); self.iv_states[index] = (self.iv_low.value(), self.iv_high.value())
        self.refresh_factory()

    def update_range_status(self) -> None:
        first = self.combo_value(self.range_start); last = self.combo_value(self.range_end); count = self.range_count(first, last)
        self.range_status.setText("Invalid range" if count is None else f"{count} mons")

    def pending_factory_source(self) -> str:
        replacements: list[tuple[int, int, str]] = []
        for record in self.factory_ranges:
            first, last = self.range_states.get(record.index, (record.first, record.last))
            if (first, last) != (record.first, record.last):
                if self.range_count(first, last) is None: raise RuntimeError(f"Invalid Factory range at row {record.index + 1}: {first} - {last}")
                replacements.append((record.start, record.end, f"{record.indent}{{{first}, {last}}}," + (f" {record.comment}" if record.comment else "") + record.newline))
        for record in self.factory_ivs:
            low, high = self.iv_states.get(record.index, (record.low, record.high))
            if (low, high) != (record.low, record.high):
                replacements.append((record.start, record.end, f"{record.indent}{{{low}, {high}}}," + (f" {record.comment}" if record.comment else "") + record.newline))
        source = self.factory_source
        for start, end, value in sorted(replacements, reverse=True): source = source[:start] + value + source[end:]
        return source

    def save_factory(self) -> None:
        try:
            new_source = self.pending_factory_source()
            if new_source == self.factory_source: self.window.status("No Factory changes"); return
            if read_utf8(self.factory_path) != self.factory_source: raise RuntimeError(f"{rel(self.window.root, self.factory_path)} changed on disk; reload before saving.")
            write_with_backup(self.factory_path, new_source)
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(self, "Save failed", str(error)); return
        self.load_factory(); self.refresh_factory(); self.window.status("Saved Battle Factory ranges / IV table")

    def show_factory_diff(self) -> None:
        try: after = self.pending_factory_source()
        except RuntimeError as error: QMessageBox.warning(self, "Invalid Factory data", str(error)); return
        DiffDialog(self, "Diff: battle_factory.c", self.factory_source, after).exec()

    def show_diff(self) -> None:
        if self.tabs.currentIndex() == 0: self.show_mon_diff()
        elif self.tabs.currentIndex() == 1: self.show_macro_diff() if self.macro_editor.hasFocus() else self.show_trainer_diff()
        elif self.tabs.currentIndex() == 2: self.show_general_trainer_diff()
        else: self.show_factory_diff()

    def save(self) -> None:
        if self.tabs.currentIndex() == 0: self.save_mons()
        elif self.tabs.currentIndex() == 1:
            self.save_trainer()
            if self.current_macro and self.macro_editor.toPlainText() != self.current_macro.raw: self.save_macro()
        elif self.tabs.currentIndex() == 2: self.save_general_trainer()
        else: self.save_factory()


class Workbench(QMainWindow):
    def __init__(self) -> None:
        super().__init__(); self.settings = QSettings("PokemonDecompTools", "ExpansionStudio"); self.lang = self.settings.value("ui/language", "ja"); self.root = Path(self.settings.value("repo/root", str(Path.cwd()))); self.tool_dir = writable_tool_dir(); self.process: QProcess | None = None; self.command_log: QDialog | None = None
        self.loaded_panels: set[str] = set(); self.loading_depth = 0; self.auto_terminal_key = ""
        self.setStatusBar(QStatusBar()); self.make_toolbar(); self.loading_label = QLabel("読み込み中..."); self.loading_label.setVisible(False); self.statusBar().addPermanentWidget(self.loading_label); self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.translation = TranslationPanel(self); self.constants = ConstantsPanel(self); self.files = FileSearchPanel(self); self.index = CodeIndexPanel(self); self.species = PokemonStudioPanel(self); self.moves = MoveStudioPanel(self); self.frontier = BattleFrontierPanel(self); self.assets = AssetPanel(self); self.dependencies = DependencyPanel(self); self.fonts = FontPanel(self); self.poryscript = PoryscriptPanel(self); self.tool_settings = SettingsPanel(self)
        self.panels: list[tuple[str, QWidget, Callable[[], None] | None]] = [("translation", self.translation, self.translation.load), ("constants", self.constants, self.constants.load), ("files", self.files, None), ("index", self.index, self.index.load), ("species", self.species, self.species.load), ("moves", self.moves, self.moves.load), ("frontier", self.frontier, self.frontier.load), ("assets", self.assets, self.assets.load), ("dependencies", self.dependencies, None), ("fonts", self.fonts, self.fonts.load), ("poryscript", self.poryscript, self.poryscript.load), ("settings", self.tool_settings, self.tool_settings.load)]
        for key, panel, _loader in self.panels: self.tabs.addTab(panel, tr(key, self.lang))
        self.tabs.currentChanged.connect(lambda _index: self.load_current())
        self.retranslate(); self.apply_readability_style(); self.resize(1580, 960)

    def apply_readability_style(self) -> None:
        font = QFont(self.font())
        font.setPointSize(UI_FONT_POINT_SIZE)
        self.setFont(font)
        self.setStyleSheet("""
            QWidget { font-size: 11pt; }
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget, QTreeWidget { font-size: 11pt; }
            QTableWidget { font-size: 11pt; gridline-color: #d4d4d4; }
            QTableWidget::item { padding: 2px 6px; }
            QHeaderView::section { padding: 4px 6px; }
        """)
        for table in self.findChildren(QTableWidget):
            configure_table(table)
        for combo in self.findChildren(QComboBox):
            stabilize_combo(combo)
        for splitter in self.findChildren(QSplitter):
            stabilize_splitter(splitter)

    def make_toolbar(self) -> None:
        bar = QToolBar(); self.addToolBar(bar); self.root_label = QLabel(); bar.addWidget(self.root_label); self.root_edit = QLineEdit(str(self.root)); self.root_edit.setMinimumWidth(450); bar.addWidget(self.root_edit)
        self.browse = QAction(self); self.browse.triggered.connect(self.choose_root); bar.addAction(self.browse); self.reload_action = QAction(self); self.reload_action.triggered.connect(self.reload_current); bar.addAction(self.reload_action)
        bar.addSeparator(); self.diff_action = QAction(self); self.diff_action.triggered.connect(self.show_active_diff); bar.addAction(self.diff_action); self.save_action = QAction(self); self.save_action.triggered.connect(self.save_active); bar.addAction(self.save_action)
        self.terminal_action = QAction(self); self.terminal_action.triggered.connect(self.open_configured_terminal); bar.addAction(self.terminal_action)
        self.script_actions: list[QAction] = []
        for index in range(1, 6):
            action = QAction(self); action.triggered.connect(lambda _checked=False, slot=index: self.run_command_script(slot)); self.script_actions.append(action); bar.addAction(action)
        self.configure_action = QAction(self); self.configure_action.triggered.connect(self.open_tool_settings); bar.addAction(self.configure_action)
        bar.addSeparator(); self.language_label = QLabel(); bar.addWidget(self.language_label); self.language = QComboBox(); self.language.addItem("日本語", "ja"); self.language.addItem("English", "en"); self.language.setCurrentIndex(0 if self.lang == "ja" else 1); self.language.currentIndexChanged.connect(self.set_language); bar.addWidget(self.language)

    def retranslate(self) -> None:
        self.setWindowTitle("Expansion Studio"); self.root_label.setText(tr("root", self.lang) + ":"); self.browse.setText(tr("browse", self.lang)); self.reload_action.setText(tr("reload", self.lang)); self.diff_action.setText(tr("diff", self.lang)); self.save_action.setText(tr("save", self.lang)); self.terminal_action.setText(tr("terminal", self.lang)); self.configure_action.setText(tr("command_settings", self.lang)); self.language_label.setText(tr("language", self.lang) + ":"); self.update_command_actions()
        for index, (key, panel, _loader) in enumerate(self.panels): self.tabs.setTabText(index, tr(key, self.lang)); getattr(panel, "retranslate", lambda: None)()

    def set_language(self) -> None:
        self.lang = self.language.currentData(); self.settings.setValue("ui/language", self.lang); self.retranslate()

    def root_valid(self) -> bool:
        return self.root.exists() and (self.root / "src").exists() and (self.root / "include").exists()

    def choose_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Repository root", self.root_edit.text())
        if selected: self.root_edit.setText(selected); self.reset_loaded(); self.load_current(force=True); self.maybe_auto_open_terminal(force=True)

    def sync_root(self) -> bool:
        new_root = Path(self.root_edit.text()).resolve()
        if new_root != self.root:
            self.root = new_root
            self.auto_terminal_key = ""
            self.reset_loaded()
        else:
            self.root = new_root
        self.settings.setValue("repo/root", str(self.root))
        if self.root_valid(): return True
        QMessageBox.warning(self, "Invalid repository", "Select a repository root containing src and include."); return False

    def reset_loaded(self) -> None:
        self.loaded_panels.clear()
        for _key, panel, _loader in getattr(self, "panels", []):
            reset = getattr(panel, "reset_loaded", None)
            if reset:
                reset()

    def begin_loading(self, text: str) -> None:
        self.loading_depth += 1
        self.loading_label.setText(text)
        self.loading_label.setVisible(True)
        self.status(text)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()

    def end_loading(self) -> None:
        if self.loading_depth:
            self.loading_depth -= 1
        if self.loading_depth == 0:
            self.loading_label.setVisible(False)
            QApplication.restoreOverrideCursor()

    def load_current(self, force: bool = False) -> None:
        if not self.sync_root(): return
        index = self.tabs.currentIndex()
        if index < 0: return
        key, panel, loader = self.panels[index]
        if key in self.loaded_panels and not force:
            return
        self.begin_loading(f"読み込み中: {tr(key, self.lang)}")
        try:
            if force:
                reset = getattr(panel, "reset_loaded", None)
                if reset:
                    reset()
            if loader:
                loader()
            self.loaded_panels.add(key)
        except Exception as error:
            QMessageBox.critical(self, "Load failed", str(error))
        finally:
            self.end_loading()

    def reload_current(self) -> None:
        self.load_current(force=True)

    def load_all(self) -> None:
        self.reload_current()

    def active_editor(self) -> QWidget:
        return self.tabs.currentWidget()

    def show_active_diff(self) -> None:
        panel = self.active_editor(); callback = getattr(panel, "show_diff", None)
        if callback: callback()
        else: self.status("This workspace has no editable source record selected")

    def save_active(self) -> None:
        panel = self.active_editor(); callback = getattr(panel, "save", None)
        if callback: callback()
        else: self.status("This workspace has no pending source edits")

    def open_species(self, key: str) -> None:
        self.tabs.setCurrentWidget(self.species); self.species.select_key(key)

    def open_move(self, key: str) -> None:
        self.tabs.setCurrentWidget(self.moves); self.moves.select_key(key)

    def setting_bool(self, key: str, default: bool = False) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() in {"1", "true", "yes", "on"}

    def wsl_root_path(self) -> str:
        root = self.root.resolve()
        drive = root.drive.rstrip(":").lower()
        if drive:
            tail = root.as_posix()[3:]
            return f"/mnt/{drive}/{tail}"
        return root.as_posix()

    def expand_command_template(self, template: str, script: str = "") -> str:
        root = str(self.root.resolve())
        return (template
                .replace("{ROOT}", root.replace("'", "''"))
                .replace("{WSL_ROOT}", self.wsl_root_path().replace('"', '\\"'))
                .replace("{SCRIPT}", script))

    def command_line_enabled(self) -> bool:
        return self.setting_bool("command_line/enabled", False)

    def script_name(self, index: int) -> str:
        default = DEFAULT_COMMAND_SCRIPTS[index - 1][0] if 1 <= index <= len(DEFAULT_COMMAND_SCRIPTS) else f"Script {index}"
        return str(self.settings.value(f"command_line/scripts/{index}/name", default) or f"Script {index}").strip() or f"Script {index}"

    def script_body(self, index: int) -> str:
        default = DEFAULT_COMMAND_SCRIPTS[index - 1][1] if 1 <= index <= len(DEFAULT_COMMAND_SCRIPTS) else ""
        return str(self.settings.value(f"command_line/scripts/{index}/body", default) or "").strip()

    def script_confirmation_enabled(self, index: int) -> bool:
        return self.setting_bool(f"command_line/scripts/{index}/confirm", True)

    def update_command_actions(self) -> None:
        enabled = self.command_line_enabled()
        self.terminal_action.setEnabled(enabled)
        last_index = str(self.settings.value("command_line/last_script_index", "") or "")
        for index, action in enumerate(self.script_actions, 1):
            body = self.script_body(index)
            name = self.script_name(index)
            action.setText(("▶ " if str(index) == last_index else "") + name)
            action.setEnabled(enabled and bool(body))

    def open_tool_settings(self) -> None:
        self.tabs.setCurrentWidget(self.tool_settings)
        self.tool_settings.load()

    def open_configured_terminal(self, auto: bool = False) -> None:
        if not self.sync_root(): return
        if not self.command_line_enabled():
            if not auto:
                self.status("コマンドライン入力スクリプトが無効です。設定タブで有効にしてください。")
                self.open_tool_settings()
            return
        template = str(self.settings.value("command_line/open_command", DEFAULT_TERMINAL_COMMAND) or "").strip()
        if not template:
            if not auto:
                QMessageBox.warning(self, "端末起動コマンド未設定", "設定タブで端末起動コマンドを指定してください。")
            return
        command = self.expand_command_template(template)
        parts = QProcess.splitCommand(command)
        if not parts:
            if not auto:
                QMessageBox.warning(self, "端末起動コマンド未設定", "設定タブで端末起動コマンドを指定してください。")
            return
        started = QProcess.startDetached(parts[0], parts[1:], str(self.root))
        if isinstance(started, tuple):
            started = started[0]
        if not started:
            QMessageBox.warning(self, "端末起動失敗", command)
            return
        self.status(f"Started terminal: {command}")

    def maybe_auto_open_terminal(self, force: bool = False) -> None:
        if not self.command_line_enabled() or not self.root_valid():
            return
        command = str(self.settings.value("command_line/open_command", DEFAULT_TERMINAL_COMMAND) or "").strip()
        key = f"{self.root.resolve()}|{command}"
        if not force and getattr(self, "auto_terminal_key", "") == key:
            return
        self.auto_terminal_key = key
        self.open_configured_terminal(auto=True)

    def run_command_script(self, index: int) -> None:
        if not self.sync_root(): return
        if not self.command_line_enabled():
            self.status("コマンドライン入力スクリプトが無効です。設定タブで有効にしてください。")
            self.open_tool_settings()
            return
        script = self.script_body(index)
        if not script:
            self.status(f"Script {index} is empty")
            return
        template = str(self.settings.value("command_line/run_template", DEFAULT_SCRIPT_RUN_TEMPLATE) or "").strip()
        if not template:
            QMessageBox.warning(self, "実行テンプレート未設定", "設定タブでスクリプト実行テンプレートを指定してください。")
            return
        command = self.expand_command_template(template, script)
        title = self.script_name(index)
        if self.script_confirmation_enabled(index):
            message = f"{title} を実行しますか？\n\n作業場所:\n{self.root}\n\nスクリプト:\n{script}"
            if QMessageBox.question(self, "スクリプト実行確認", message) != QMessageBox.StandardButton.Yes:
                self.status(f"Canceled script {index}: {title}")
                return
        self.process = QProcess(self); self.process.setWorkingDirectory(str(self.root)); environment = QProcessEnvironment.systemEnvironment(); separator = ";" if sys.platform.startswith("win") else ":"; environment.insert("PATH", str(self.root) + separator + environment.value("PATH")); self.process.setProcessEnvironment(environment); dialog = QDialog(self); dialog.setWindowTitle(f"Script {index}: {title}"); dialog.resize(960, 600); layout = QVBoxLayout(dialog); output = QPlainTextEdit(); output.setReadOnly(True); output.appendPlainText(f"> {command}\n"); layout.addWidget(output); exit_label = QLabel("終了コード: 実行中"); layout.addWidget(exit_label); close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.reject); layout.addWidget(close); self.command_log = dialog
        self.process.readyReadStandardOutput.connect(lambda: output.appendPlainText(bytes(self.process.readAllStandardOutput()).decode(errors="replace")))
        self.process.readyReadStandardError.connect(lambda: output.appendPlainText(bytes(self.process.readAllStandardError()).decode(errors="replace")))
        self.process.errorOccurred.connect(lambda error: output.appendPlainText(f"\n[実行エラー] {getattr(error, 'name', str(error))}"))
        def finished(code: int, _status: QProcess.ExitStatus) -> None:
            output.appendPlainText(f"\n[終了コード] {code}")
            exit_label.setText(f"終了コード: {code}")
            self.settings.setValue("command_line/last_script_index", index)
            self.settings.setValue("command_line/last_script_name", title)
            self.settings.setValue("command_line/last_exit_code", code)
            self.update_command_actions()
            if hasattr(self.tool_settings, "last_script"):
                self.tool_settings.last_script.setText(f"{index}: {title} / 終了コード {code}")
            self.status(f"{title} finished with exit code {code}")
        self.process.finished.connect(finished)
        self.process.startCommand(command); dialog.show(); self.status(f"Started script {index}: {title}")

    def status(self, text: str) -> None: self.statusBar().showMessage(text)


def main() -> int:
    app = QApplication(sys.argv); app.setOrganizationName("PokemonDecompTools"); app.setApplicationName("ExpansionStudio")
    icon = resource_path("em.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = Workbench(); window.show(); QTimer.singleShot(0, window.load_current); QTimer.singleShot(250, window.maybe_auto_open_terminal); return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
