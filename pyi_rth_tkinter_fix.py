import os
import sys
from pathlib import Path


def _set_tk_dirs():
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return

    root = Path(meipass)
    tcl_dir = root / "_tcl_data"
    tk_dir = root / "_tk_data"

    if tcl_dir.is_dir():
        os.environ["TCL_LIBRARY"] = str(tcl_dir)
    if tk_dir.is_dir():
        os.environ["TK_LIBRARY"] = str(tk_dir)


_set_tk_dirs()
