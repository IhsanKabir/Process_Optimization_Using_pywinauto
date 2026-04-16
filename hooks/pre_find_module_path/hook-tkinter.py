# Allow local packaging to keep tkinter importable even when PyInstaller's
# auto-probe decides the host Tcl/Tk installation is "broken".
#
# We bundle Tcl/Tk explicitly in TravelportAuto.spec and set TCL_LIBRARY /
# TK_LIBRARY via a runtime hook, so clearing search_dirs here would wrongly
# strip the GUI from the final executable.


def pre_find_module_path(hook_api):
    return
