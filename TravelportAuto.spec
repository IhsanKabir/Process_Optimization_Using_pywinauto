# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

import _tkinter

from PyInstaller.utils.hooks import collect_data_files


def _collect_tree(root: Path, dest_root: str, exclude_names=None, exclude_suffixes=None):
    exclude_names = set(exclude_names or [])
    exclude_suffixes = {suffix.lower() for suffix in (exclude_suffixes or [])}
    items = []
    if not root.is_dir():
        return items

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in exclude_names for part in path.parts):
            continue
        if path.name in exclude_names:
            continue
        if path.suffix.lower() in exclude_suffixes:
            continue

        rel_parent = path.relative_to(root).parent.as_posix()
        dest = f"{dest_root}/{rel_parent}" if rel_parent != "." else dest_root
        items.append((str(path), dest))
    return items


_PY_BASE = Path(sys.base_prefix)
_TCL_MAJOR_MINOR = ".".join(_tkinter.TCL_VERSION.split(".")[:2])
_TCL_MAJOR = _tkinter.TCL_VERSION.split(".")[0]
_TCL_DIR = _PY_BASE / "tcl" / f"tcl{_TCL_MAJOR_MINOR}"
_TK_DIR = _PY_BASE / "tcl" / f"tk{_TCL_MAJOR_MINOR}"
_TCL_MODULE_DIR = _PY_BASE / "tcl" / f"tcl{_TCL_MAJOR}"

# Help PyInstaller's isolated subprocess see the same Tcl/Tk locations.
if _TCL_DIR.is_dir():
    os.environ.setdefault("TCL_LIBRARY", str(_TCL_DIR))
if _TK_DIR.is_dir():
    os.environ.setdefault("TK_LIBRARY", str(_TK_DIR))

_datas = [
    ('config.json', '.'),
    ('commands.txt', '.'),
]
_datas += _collect_tree(_TCL_DIR, '_tcl_data', exclude_names={'demos'}, exclude_suffixes={'.lib'})
_datas += _collect_tree(_TK_DIR, '_tk_data', exclude_names={'demos'}, exclude_suffixes={'.lib'})
_datas += _collect_tree(_TCL_MODULE_DIR, f"tcl{_TCL_MAJOR}")

# airportsdata ships its IATA/ICAO JSON tables inside the package dir; without
# collect_data_files they're not bundled, and the global FTAX airport directory
# silently comes back empty in the frozen exe (venv/tests don't catch this).
_datas += collect_data_files('airportsdata')


_BUILD_MODE = os.environ.get("TPA_PYINSTALLER_MODE", "onedir").strip().lower()
_ONEFILE = _BUILD_MODE in {"onefile", "single", "singlefile"}


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        '_tkinter',
        'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext',
        'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.simpledialog',
        'pywinauto', 'pywinauto.application', 'pywinauto.controls',
        'pywinauto.keyboard', 'pywinauto.mouse',
        'pyautogui', 'pyperclip',
        'PIL', 'PIL.Image', 'PIL.ImageGrab', 'PIL.ImageTk',
        'mouseinfo', 'pygetwindow', 'pymsgbox', 'pyrect', 'pyscreeze',
        'pytweening',
        'openpyxl', 'tqdm',
        'airportsdata',
        'ctypes', 'ctypes.wintypes', 'webbrowser', 'subprocess', 'hashlib',
        'json', 'logging', 'queue', 're', 'shutil', 'threading',
        'urllib.request', 'urllib.error',
        'clipboard_util',
        # keyring + Windows Credential Locker backend
        'keyring', 'keyring.backends', 'keyring.backends.Windows',
        'win32ctypes', 'win32ctypes.pywin32', 'win32ctypes.pywin32.pywintypes',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['pyi_rth_tkinter_fix.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

_exe_kwargs = dict(
    name='TravelportAuto',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest="TravelportAuto.manifest",
)

if _ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        runtime_tmpdir=None,
        **_exe_kwargs,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **_exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='TravelportAuto',
    )
