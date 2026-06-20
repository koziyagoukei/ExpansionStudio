#!/usr/bin/env python3
"""Build a distributable Windows executable for Expansion Studio."""

from __future__ import annotations

import sys
import pathlib
import site
from datetime import datetime
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parent
ENTRY_POINT = TOOL_DIR / "ポケモンデコンプ作業ツール.py"
ICON_PNG = TOOL_DIR / "em.png"
ICON_ICO = TOOL_DIR / "em.ico"
TEMPLATE_DIR = TOOL_DIR / "templates"
DIST_DIR = TOOL_DIR / "dist"
BUILD_ROOT = TOOL_DIR / "build" / "pyinstaller"


def make_ico() -> Path | None:
    if not ICON_PNG.exists():
        return None
    try:
        from PySide6.QtGui import QImage

        image = QImage(str(ICON_PNG))
        if not image.isNull() and image.save(str(ICON_ICO), "ICO"):
            return ICON_ICO
    except Exception as error:
        print(f"Icon conversion skipped: {error}")
    return None


def patch_pyinstaller_site_scan() -> None:
    """Skip inaccessible user site-packages directories during DLL analysis."""
    import PyInstaller.depend.bindepend as bindepend

    def accessible_parent_paths():
        raw_paths = list(site.getsitepackages())
        try:
            raw_paths.append(site.getusersitepackages())
        except OSError:
            pass
        excluded = {
            pathlib.Path(sys.base_prefix), pathlib.Path(sys.base_prefix).resolve(),
            pathlib.Path(sys.prefix), pathlib.Path(sys.prefix).resolve(),
        }
        paths = set()
        for raw_path in raw_paths:
            if not raw_path:
                continue
            try:
                path = pathlib.Path(raw_path)
                resolved = path.resolve()
                for candidate in (path, resolved):
                    if candidate.is_dir() and candidate not in excluded:
                        paths.add(candidate)
            except OSError:
                continue
        return sorted(paths, key=lambda path: len(path.parents), reverse=True)

    bindepend._get_paths_for_parent_directory_preservation = accessible_parent_paths


def main() -> int:
    if not ENTRY_POINT.exists():
        print(f"Entry point not found: {ENTRY_POINT}")
        return 1
    try:
        from PyInstaller.__main__ import run
    except ImportError:
        print('Install build requirements first: python -m pip install -r "requirements-build.txt"')
        return 1

    patch_pyinstaller_site_scan()

    icon = make_ico()
    # Never reuse PyInstaller's working directory. Its analysis cache can be
    # locked by Explorer, antivirus, or a previous failed build on Windows.
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    dist = DIST_DIR
    work = BUILD_ROOT / run_id
    spec = BUILD_ROOT / "spec"
    for path in (dist, work, spec):
        path.mkdir(parents=True, exist_ok=True)

    args = [
        "--noconfirm",
        "--windowed",
        "--onefile",
        "--name", "ExpansionStudio",
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(spec),
        "--add-data", f"{ICON_PNG}{';' if sys.platform == 'win32' else ':'}.",
    ]
    if TEMPLATE_DIR.exists():
        args.extend(["--add-data", f"{TEMPLATE_DIR}{';' if sys.platform == 'win32' else ':'}templates"])
    if icon:
        args.extend(["--icon", str(icon)])
    args.append(str(ENTRY_POINT))
    run(args)
    print(f"Created: {dist / 'ExpansionStudio.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
