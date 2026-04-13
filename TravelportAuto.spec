# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[('config.json', '.'), ('commands.txt', '.')],
    hiddenimports=[
        'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext',
        'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.simpledialog',
        'pywinauto', 'pywinauto.application', 'pywinauto.controls',
        'pywinauto.keyboard', 'pywinauto.mouse',
        'openpyxl', 'tqdm',
        'ctypes', 'ctypes.wintypes', 'webbrowser', 'subprocess', 'hashlib',
        'json', 'logging', 'queue', 're', 'shutil', 'threading',
        'urllib.request', 'urllib.error',
        'clipboard_util',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pyautogui', 'pyperclip'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TravelportAuto',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest="TravelportAuto.manifest",
)
