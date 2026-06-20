#!/usr/bin/env python3
"""Pokemon Emerald Expansion workbench.

This desktop utility reads the project sources directly.  It intentionally keeps
the C source as the source of truth: fields it cannot parse are displayed but
are not rewritten automatically.
"""

from __future__ import annotations

import csv
import difflib
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

try:
    from PySide6.QtCore import QProcess, QSettings, QTimer, Qt, Signal
    from PySide6.QtGui import QAction, QIcon, QImage, QPixmap
    from PySide6.QtWidgets import (
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
SOURCE_EXTENSIONS = {".c", ".h", ".inc", ".s", ".mk", ".json", ".txt"}
TEXT_EXTENSIONS = {".c", ".h", ".inc"}
LANG = {
    "ja": {
        "window": "ポケモン デコンプ作業ツール", "root": "リポジトリ", "browse": "参照",
        "reload": "再読込", "save": "保存", "search": "検索", "clear": "クリア",
        "translation": "翻訳", "constants": "定数", "files": "ファイル検索",
        "species": "ポケモン", "moves": "わざ", "assets": "アセット",
        "dependencies": "依存関係", "fonts": "Glyph Table", "poryscript": "Poryscript", "settings": "設定",
        "language": "言語", "results": "件", "original": "原文", "edited": "編集後",
        "untranslated": "未翻訳のみ", "dirty": "変更済みのみ", "file": "ファイル",
        "export": "CSV 出力", "import": "CSV 読込", "add_template": "雛形を作成",
        "copy": "追加", "delete": "削除", "references": "参照", "configure": "設定",
        "not_configured": "Poryscript は未設定です。外部ツールの場所を設定してください。",
        "diff": "差分", "build": "ビルド", "launch": "ROM 起動", "configure_build": "ビルド設定",
    },
    "en": {
        "window": "Pokemon Decomp Workbench", "root": "Repository", "browse": "Browse",
        "reload": "Reload", "save": "Save", "search": "Search", "clear": "Clear",
        "translation": "Translation", "constants": "Constants", "files": "File Search",
        "species": "Pokemon", "moves": "Moves", "assets": "Assets",
        "dependencies": "Dependencies", "fonts": "Glyph Table", "poryscript": "Poryscript", "settings": "Settings",
        "language": "Language", "results": "results", "original": "Original", "edited": "Edited",
        "untranslated": "Untranslated only", "dirty": "Changed only", "file": "File",
        "export": "Export CSV", "import": "Import CSV", "add_template": "Create template",
        "copy": "Add", "delete": "Delete", "references": "References", "configure": "Configure",
        "not_configured": "Poryscript is not configured. Set the external tool location.",
        "diff": "Diff", "build": "Build", "launch": "Launch ROM", "configure_build": "Build settings",
    },
}


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


def backup_path(path: Path) -> Path:
    candidate = path.with_name(path.name + ".bak")
    if not candidate.exists():
        return candidate
    return path.with_name(path.name + f".bak.{datetime.now():%Y%m%d-%H%M%S}")


def write_with_backup(path: Path, content: str) -> None:
    shutil.copy2(path, backup_path(path))
    path.write_text(content, encoding="utf-8", newline="")


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
        save = QPushButton(); save.clicked.connect(self.save); self._save = save
        buttons.addWidget(export); buttons.addWidget(import_button); buttons.addStretch(); buttons.addWidget(save)
        layout.addLayout(buttons)
        self.retranslate()

    def retranslate(self) -> None:
        lang = self.window.lang
        self.untranslated.setText(tr("untranslated", lang)); self.changed.setText(tr("dirty", lang))
        self._clear_button.setText(tr("clear", lang)); self.original_label.setText(tr("original", lang))
        self.edited_label.setText(tr("edited", lang)); self._export.setText(tr("export", lang))
        self._import.setText(tr("import", lang)); self._save.setText(tr("save", lang))

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
        detail = QWidget(); detail_layout = QVBoxLayout(detail); self.detail = QLabel("テキストまたはイベントを選択してください。"); self.detail.setWordWrap(True); detail_layout.addWidget(self.detail); detail_layout.addWidget(QLabel("イベント本文 / 相互参照")); self.context = QPlainTextEdit(); self.context.setReadOnly(True); self.context.setMaximumHeight(160); detail_layout.addWidget(self.context); detail_layout.addWidget(QLabel("元のテキスト（INC の末尾 $ は非表示）")); self.original = QPlainTextEdit(); self.original.setReadOnly(True); self.original.setMaximumHeight(110); detail_layout.addWidget(self.original); detail_layout.addWidget(QLabel("翻訳テキスト")); self.editor = QPlainTextEdit(); self.editor.setEnabled(False); self.editor.textChanged.connect(self.edit_changed); detail_layout.addWidget(self.editor); detail_layout.addWidget(QLabel("使用箇所 / 使用テキスト")); self.references = QListWidget(); self.references.itemDoubleClicked.connect(self.open_reference); detail_layout.addWidget(self.references); controls = QHBoxLayout(); revert = QPushButton("元に戻す"); revert.clicked.connect(self.revert); self.diff_button = QPushButton("差分"); self.diff_button.clicked.connect(self.show_diff); self.save_button = QPushButton("保存"); self.save_button.clicked.connect(self.save); controls.addWidget(revert); controls.addWidget(self.diff_button); controls.addStretch(); controls.addWidget(self.save_button); detail_layout.addLayout(controls); split.addWidget(detail); split.setSizes([850, 650]); layout.addWidget(split)

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
        self.save_button.setText(tr("save", self.window.lang))

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


class TranslationPanel(QWidget):
    """Translation workspace with source strings and event-aware text browsing."""
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.text = TranslationTextPanel(window); self.events = EventBrowserPanel(window, self.text); layout = QVBoxLayout(self); self.tabs = QTabWidget(); self.tabs.addTab(self.text, "文字列"); self.tabs.addTab(self.events, "イベントブラウザ"); layout.addWidget(self.tabs)

    def retranslate(self) -> None:
        self.text.retranslate(); self.events.retranslate(); self.tabs.setTabText(0, "文字列" if self.window.lang == "ja" else "Strings"); self.tabs.setTabText(1, "イベントブラウザ" if self.window.lang == "ja" else "Event Browser")

    def load(self) -> None:
        self.text.load(); self.events.load()

    def save(self) -> None:
        (self.events if self.tabs.currentWidget() is self.events else self.text).save()

    def show_diff(self) -> None:
        (self.events if self.tabs.currentWidget() is self.events else self.text).show_diff()


@dataclass
class SourceRecord:
    path: Path
    key: str
    start: int
    end: int
    block: str
    values: dict[str, str] = field(default_factory=dict)


def raw_field(block: str, name: str) -> tuple[int, int, str] | None:
    match = re.search(rf"\.{re.escape(name)}\s*=\s*", block)
    if not match: return None
    start = match.end(); pos = start; depth = 0
    while pos < len(block):
        char = block[pos]
        if char in "\"'": pos = skip_string(block, pos, char); continue
        if char in "({[": depth += 1
        elif char in ")}]": depth -= 1
        elif char == "," and depth == 0: return start, pos, block[start:pos].strip()
        pos += 1
    return None


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


@dataclass
class AssetGroup:
    key: str
    members: list[Path]

    @property
    def primary_image(self) -> Path | None:
        return next((path for path in self.members if path.suffix.lower() == ".png"), None)


class AssetPanel(QWidget):
    """Static reference based image-group browser with reversible quarantine moves."""
    ASSET_SUFFIXES = {".png", ".pal", ".bin", ".4bpp", ".gbapal"}
    SOURCE_SUFFIXES = {".c", ".h", ".inc", ".mk", ".s", ".json"}
    ASSET_PATH_RE = re.compile(r"graphics/[A-Za-z0-9_./-]+\.(?:png|pal|bin|4bpp|gbapal)")

    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; self.assets: list[Path] = []; self.groups: list[AssetGroup] = []; self.reference_index: dict[Path, set[str]] = {}
        layout = QVBoxLayout(self); bar = QHBoxLayout(); self.filter = QLineEdit(); self.filter.textChanged.connect(self.refresh); self.filter.setPlaceholderText("Filter path"); self.include_non_png = QCheckBox("PNG以外のみのグループも表示"); self.include_non_png.stateChanged.connect(self.refresh); self.sort = QComboBox(); self.sort.addItem("パス順", "path"); self.sort.addItem("未使用候補を先頭", "unused"); self.sort.addItem("参照数順", "references"); self.sort.currentIndexChanged.connect(self.refresh)
        add = QPushButton(); add.clicked.connect(self.add_asset); self._add = add; quarantine = QPushButton("quarantineへ移動"); quarantine.clicked.connect(self.quarantine_group); self._quarantine = quarantine
        bar.addWidget(self.filter); bar.addWidget(self.include_non_png); bar.addWidget(QLabel("並び順")); bar.addWidget(self.sort); bar.addWidget(add); bar.addWidget(quarantine); layout.addLayout(bar)
        split = QSplitter(Qt.Orientation.Horizontal); self.list = QListWidget(); self.list.currentItemChanged.connect(self.select); split.addWidget(self.list)
        detail = QWidget(); box = QVBoxLayout(detail); self.preview = QLabel("No asset selected"); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(560, 380); box.addWidget(self.preview)
        self.asset_path = QLabel(); self.asset_path.setWordWrap(True); box.addWidget(self.asset_path); self.usage = QLabel(); self.usage.setWordWrap(True); box.addWidget(self.usage); self.members = QListWidget(); box.addWidget(QLabel("画像グループ (.png / .gbapal / .pal / .bin / .4bpp)")); box.addWidget(self.members); self.refs = QListWidget(); box.addWidget(QLabel("静的参照箇所")); box.addWidget(self.refs); split.addWidget(detail); split.setSizes([520, 760]); layout.addWidget(split); self.retranslate()

    def retranslate(self) -> None:
        self._add.setText(tr("copy", self.window.lang)); self._quarantine.setText("quarantineへ移動")

    def group_key(self, asset: Path) -> str:
        return rel(self.window.root, asset.with_suffix(""))

    def build_reference_index(self) -> None:
        self.reference_index = {asset: set() for asset in self.assets}; by_name = {rel(self.window.root, asset): asset for asset in self.assets}
        excluded = {".git", "workspace", "build", "dist", "quarantine"}
        for path in self.window.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.SOURCE_SUFFIXES: continue
            try:
                if excluded.intersection(path.relative_to(self.window.root).parts): continue
                source = read_utf8(path)
            except (UnicodeDecodeError, OSError): continue
            for match in self.ASSET_PATH_RE.finditer(source):
                asset = by_name.get(match.group(0))
                if asset: self.reference_index[asset].add(rel(self.window.root, path))

    def group_references(self, group: AssetGroup) -> list[str]:
        return sorted({reference for member in group.members for reference in self.reference_index.get(member, set())})

    def load(self) -> None:
        base = self.window.root / "graphics"; self.assets = sorted((path for path in base.rglob("*") if path.is_file() and path.suffix.lower() in self.ASSET_SUFFIXES), key=lambda path: path.as_posix().casefold()) if base.exists() else []
        grouped: dict[str, list[Path]] = {}
        for asset in self.assets: grouped.setdefault(self.group_key(asset), []).append(asset)
        self.groups = [AssetGroup(key, members) for key, members in grouped.items()]; self.build_reference_index(); self.refresh()

    def visible_groups(self) -> list[AssetGroup]:
        query = self.filter.text().casefold().strip(); groups = [group for group in self.groups if (self.include_non_png.isChecked() or group.primary_image) and (not query or query in group.key.casefold() or any(query in path.name.casefold() for path in group.members))]
        sort_mode = self.sort.currentData()
        if sort_mode == "unused": return sorted(groups, key=lambda group: (bool(self.group_references(group)), group.key.casefold()))
        if sort_mode == "references": return sorted(groups, key=lambda group: (-len(self.group_references(group)), group.key.casefold()))
        return sorted(groups, key=lambda group: group.key.casefold())

    def refresh(self) -> None:
        current = self.list.currentItem().data(Qt.ItemDataRole.UserRole) if self.list.currentItem() else None; self.list.blockSignals(True); self.list.clear()
        for group in self.visible_groups():
            references = self.group_references(group); prefix = "[未使用候補] " if not references else ""; label = f"{prefix}{group.key}  ({len(group.members)} files / {len(references)} refs)"; row = QListWidgetItem(label); row.setData(Qt.ItemDataRole.UserRole, group); self.list.addItem(row)
            if current and current.key == group.key: self.list.setCurrentItem(row)
        self.list.blockSignals(False); self.window.status(f"{self.list.count()} image groups | 未使用候補: {sum(not self.group_references(group) for group in self.groups)}")

    def select(self) -> None:
        item = self.list.currentItem(); self.refs.clear(); self.members.clear(); self.preview.clear(); self.asset_path.clear(); self.usage.clear()
        if not item: return
        group: AssetGroup = item.data(Qt.ItemDataRole.UserRole); references = self.group_references(group); self.asset_path.setText(group.key)
        self.usage.setText(f"使用中: {len(references)} ファイル" if references else "未使用候補: 静的参照は見つかりません（動的・生成時参照は確認してください）")
        self.members.addItems([rel(self.window.root, path) for path in group.members]); self.refs.addItems(references)
        image = group.primary_image
        if image:
            pixmap = QPixmap(str(image)); self.preview.setPixmap(pixmap.scaled(620, 460, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
        else: self.preview.setText("PNG画像なしの関連アセットグループ")

    def add_asset(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, "Select asset")
        if not source: return
        target_dir = QFileDialog.getExistingDirectory(self, "Target graphics directory", str(self.window.root / "graphics"))
        if not target_dir: return
        target = Path(target_dir) / Path(source).name
        if target.exists(): QMessageBox.warning(self, "Asset exists", str(target)); return
        shutil.copy2(source, target); self.load(); self.window.status(f"Added {target}")

    def quarantine_group(self) -> None:
        item = self.list.currentItem()
        if not item: return
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
        right = QWidget(); right_layout = QVBoxLayout(right); self.tool_state = QLabel(); self.tool_state.setWordWrap(True); right_layout.addWidget(self.tool_state); self.path_label = QLabel("ファイル未選択"); self.path_label.setWordWrap(True); right_layout.addWidget(self.path_label); self.editor = QPlainTextEdit(); self.editor.textChanged.connect(self.changed); right_layout.addWidget(self.editor); actions = QHBoxLayout(); self.save_button = QPushButton("保存"); self.save_button.clicked.connect(self.save); self.compile_button = QPushButton("コンパイル"); self.compile_button.clicked.connect(self.compile_current); actions.addWidget(self.save_button); actions.addWidget(self.compile_button); actions.addStretch(); right_layout.addLayout(actions); right_layout.addWidget(QLabel("コンパイルログ")); self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(190); right_layout.addWidget(self.log); split.addWidget(right); split.setSizes([500, 980]); layout.addWidget(split)

    def update_tool_state(self) -> None:
        raw = self.window.settings.value("poryscript/executable", ""); executable = Path(raw) if raw else None; configured = bool(executable and executable.exists())
        self.compile_button.setVisible(configured)
        self.tool_state.setText(f"Poryscript: {executable}" if configured else "Poryscript は未設定です。イベントの検索・閲覧・保存は利用できます。コンパイルは設定タブで poryscript.exe を指定してください。")

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
        raw_executable = str(self.window.settings.value("poryscript/executable", "") or "")
        if not raw_executable: self.update_tool_state(); return
        executable = Path(raw_executable)
        if not executable.exists(): self.update_tool_state(); return
        if not self.save(): return
        source_dir = Path(self.window.settings.value("poryscript/source_dir", str(self.window.root)))
        output_dir = Path(self.window.settings.value("poryscript/output_dir", str(source_dir)))
        try: relative = self.current.path.relative_to(source_dir)
        except ValueError: relative = Path(self.current.path.name)
        output = output_dir / relative.with_suffix(".inc"); output.parent.mkdir(parents=True, exist_ok=True)
        self.log.clear(); self.log.appendPlainText(f"> {executable} -i {self.current.path} -o {output}")
        self.process = QProcess(self); self.process.setWorkingDirectory(str(source_dir if source_dir.exists() else self.window.root))
        self.process.readyReadStandardOutput.connect(lambda: self.log.appendPlainText(bytes(self.process.readAllStandardOutput()).decode(errors="replace")))
        self.process.readyReadStandardError.connect(lambda: self.log.appendPlainText(bytes(self.process.readAllStandardError()).decode(errors="replace")))
        self.process.finished.connect(lambda code, _status: self.window.status("Poryscript compile succeeded" if code == 0 else f"Poryscript compile failed: {code}"))
        self.process.start(str(executable), ["-i", str(self.current.path), "-o", str(output)]); self.window.status(f"Compiling {self.current.rel_path}")


class SettingsPanel(QWidget):
    def __init__(self, window: "Workbench") -> None:
        super().__init__(); self.window = window; layout = QVBoxLayout(self); group = QGroupBox("Poryscript 外部ツール"); form = QFormLayout(group); self.executable = QLineEdit(); self.source_dir = QLineEdit(); self.output_dir = QLineEdit(); form.addRow("poryscript.exe", self.executable); form.addRow("source directory", self.source_dir); form.addRow("output directory", self.output_dir); save = QPushButton("設定を保存"); save.clicked.connect(self.save); layout.addWidget(group); layout.addWidget(save); layout.addStretch(); self.load()

    def load(self) -> None:
        self.executable.setText(self.window.settings.value("poryscript/executable", "")); self.source_dir.setText(self.window.settings.value("poryscript/source_dir", str(self.window.root))); self.output_dir.setText(self.window.settings.value("poryscript/output_dir", str(self.window.root)))

    def save(self) -> None:
        self.window.settings.setValue("poryscript/executable", self.executable.text().strip()); self.window.settings.setValue("poryscript/source_dir", self.source_dir.text().strip()); self.window.settings.setValue("poryscript/output_dir", self.output_dir.text().strip()); self.window.poryscript.update_tool_state(); self.window.status("Poryscript settings saved")


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


def display_integer(value: str) -> int:
    conditional = re.search(r"\?\s*(-?\d+)", value)
    if conditional:
        return int(conditional.group(1))
    direct = re.fullmatch(r"\s*(-?\d+)\s*", value)
    return int(direct.group(1)) if direct else 0


def string_from_record(record: SourceRecord, name: str) -> str:
    parsed = string_field(record.block, name)
    return parsed[2] if parsed else record.values.get(name, "")


def replace_record_fields(record: SourceRecord, values: dict[str, str], strings: set[str]) -> str:
    """Apply supported field changes to one record without reformatting its source."""
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
            additions.append(f"        .{field_name} = {value},\n")
    updated = record.block
    for start, end, value in sorted(replacements, reverse=True):
        updated = updated[:start] + value + updated[end:]
    if additions:
        insert_at = updated.rfind("}")
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


class Workbench(QMainWindow):
    def __init__(self) -> None:
        super().__init__(); self.settings = QSettings("PokemonDecompTools", "ExpansionStudio"); self.lang = self.settings.value("ui/language", "ja"); self.root = Path(self.settings.value("repo/root", str(Path.cwd()))); self.tool_dir = writable_tool_dir(); self.process: QProcess | None = None; self.command_log: QDialog | None = None
        self.setStatusBar(QStatusBar()); self.make_toolbar(); self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.translation = TranslationPanel(self); self.constants = ConstantsPanel(self); self.files = FileSearchPanel(self); self.species = PokemonStudioPanel(self); self.moves = MoveStudioPanel(self); self.assets = AssetPanel(self); self.dependencies = DependencyPanel(self); self.fonts = FontPanel(self); self.poryscript = PoryscriptPanel(self); self.tool_settings = SettingsPanel(self)
        self.panels: list[tuple[str, QWidget, Callable[[], None] | None]] = [("translation", self.translation, self.translation.load), ("constants", self.constants, self.constants.load), ("files", self.files, None), ("species", self.species, self.species.load), ("moves", self.moves, self.moves.load), ("assets", self.assets, self.assets.load), ("dependencies", self.dependencies, None), ("fonts", self.fonts, self.fonts.load), ("poryscript", self.poryscript, self.poryscript.load), ("settings", self.tool_settings, self.tool_settings.load)]
        for key, panel, _loader in self.panels: self.tabs.addTab(panel, tr(key, self.lang))
        self.retranslate(); self.resize(1580, 960)

    def make_toolbar(self) -> None:
        bar = QToolBar(); self.addToolBar(bar); self.root_label = QLabel(); bar.addWidget(self.root_label); self.root_edit = QLineEdit(str(self.root)); self.root_edit.setMinimumWidth(450); bar.addWidget(self.root_edit)
        self.browse = QAction(self); self.browse.triggered.connect(self.choose_root); bar.addAction(self.browse); self.reload_action = QAction(self); self.reload_action.triggered.connect(self.load_all); bar.addAction(self.reload_action)
        bar.addSeparator(); self.diff_action = QAction(self); self.diff_action.triggered.connect(self.show_active_diff); bar.addAction(self.diff_action); self.save_action = QAction(self); self.save_action.triggered.connect(self.save_active); bar.addAction(self.save_action)
        self.build_action = QAction(self); self.build_action.triggered.connect(lambda: self.run_saved_command("build/command", "make", "Build")); bar.addAction(self.build_action); self.launch_action = QAction(self); self.launch_action.triggered.connect(lambda: self.run_saved_command("rom/command", "", "ROM")); bar.addAction(self.launch_action); self.configure_action = QAction(self); self.configure_action.triggered.connect(self.configure_commands); bar.addAction(self.configure_action)
        bar.addSeparator(); self.language_label = QLabel(); bar.addWidget(self.language_label); self.language = QComboBox(); self.language.addItem("日本語", "ja"); self.language.addItem("English", "en"); self.language.setCurrentIndex(0 if self.lang == "ja" else 1); self.language.currentIndexChanged.connect(self.set_language); bar.addWidget(self.language)

    def retranslate(self) -> None:
        self.setWindowTitle("Expansion Studio"); self.root_label.setText(tr("root", self.lang) + ":"); self.browse.setText(tr("browse", self.lang)); self.reload_action.setText(tr("reload", self.lang)); self.diff_action.setText(tr("diff", self.lang)); self.save_action.setText(tr("save", self.lang)); self.build_action.setText(tr("build", self.lang)); self.launch_action.setText(tr("launch", self.lang)); self.configure_action.setText(tr("configure_build", self.lang)); self.language_label.setText(tr("language", self.lang) + ":")
        for index, (key, panel, _loader) in enumerate(self.panels): self.tabs.setTabText(index, tr(key, self.lang)); getattr(panel, "retranslate", lambda: None)()

    def set_language(self) -> None:
        self.lang = self.language.currentData(); self.settings.setValue("ui/language", self.lang); self.retranslate()

    def root_valid(self) -> bool:
        return self.root.exists() and (self.root / "src").exists() and (self.root / "include").exists()

    def choose_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Repository root", self.root_edit.text())
        if selected: self.root_edit.setText(selected); self.load_all()

    def sync_root(self) -> bool:
        self.root = Path(self.root_edit.text()).resolve(); self.settings.setValue("repo/root", str(self.root))
        if self.root_valid(): return True
        QMessageBox.warning(self, "Invalid repository", "Select a repository root containing src and include."); return False

    def load_current(self) -> None:
        if not self.sync_root(): return
        _key, _panel, loader = self.panels[self.tabs.currentIndex()]
        if loader: loader()

    def load_all(self) -> None:
        if not self.sync_root(): return
        for _key, _panel, loader in self.panels:
            if loader: loader()
        self.status(f"Loaded {self.root}")

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

    def run_saved_command(self, setting: str, default: str, purpose: str) -> None:
        if not self.sync_root(): return
        command = self.settings.value(setting, default)
        if not command:
            command, accepted = QInputDialog.getText(self, f"{purpose} command", f"{purpose} command", text=default)
            if not accepted or not command.strip(): return
            self.settings.setValue(setting, command)
        self.process = QProcess(self); self.process.setWorkingDirectory(str(self.root)); dialog = QDialog(self); dialog.setWindowTitle(f"{purpose}: {command}"); dialog.resize(900, 560); layout = QVBoxLayout(dialog); output = QPlainTextEdit(); output.setReadOnly(True); layout.addWidget(output); close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.reject); layout.addWidget(close); self.command_log = dialog
        self.process.readyReadStandardOutput.connect(lambda: output.appendPlainText(bytes(self.process.readAllStandardOutput()).decode(errors="replace")))
        self.process.readyReadStandardError.connect(lambda: output.appendPlainText(bytes(self.process.readAllStandardError()).decode(errors="replace")))
        self.process.finished.connect(lambda code, _status: self.status(f"{purpose} finished with exit code {code}"))
        self.process.startCommand(command); dialog.show(); self.status(f"Started {purpose}: {command}")

    def configure_commands(self) -> None:
        build, accepted = QInputDialog.getText(self, "Build command", "Build command", text=self.settings.value("build/command", "make"))
        if not accepted:
            return
        rom, accepted = QInputDialog.getText(self, "ROM launch command", "ROM launch command", text=self.settings.value("rom/command", ""))
        if not accepted:
            return
        self.settings.setValue("build/command", build.strip()); self.settings.setValue("rom/command", rom.strip()); self.status("Build and ROM commands saved")

    def status(self, text: str) -> None: self.statusBar().showMessage(text)


def main() -> int:
    app = QApplication(sys.argv); app.setOrganizationName("PokemonDecompTools"); app.setApplicationName("ExpansionStudio")
    icon = resource_path("em.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = Workbench(); window.show(); QTimer.singleShot(0, window.load_all); return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
