import pywinauto
from pywinauto import Desktop

print("Listing all visible windows that contain 'Travelport' or 'Smartpoint' in the title:")
desktop = Desktop(backend="uia")
for window in desktop.windows():
    title = window.window_text()
    if title and ('Travelport' in title or 'Smartpoint' in title):
        print(f"  FOUND: '{title}'")
        
print("Listing using win32 backend just in case:")
desktop_win32 = Desktop(backend="win32")
for window in desktop_win32.windows():
    title = window.window_text()
    if title and ('Travelport' in title or 'Smartpoint' in title):
        print(f"  FOUND (win32): '{title}'")
