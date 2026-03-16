import sys
import os
from pywinauto import Desktop

def list_controls(window_title="Application Window 1"):
    print(f"Searching for '{window_title}'...")
    try:
        desktop = Desktop(backend="uia")
        window = desktop.window(best_match=window_title)
        
        if not window.exists():
            print(f"Error: Window '{window_title}' not found.")
            return

        window.set_focus()
        print(f"Connected to: {window.window_text()}")
        print("-" * 50)
        
        # Print control identifiers - this is the "gold mine" for finding buttons
        window.print_control_identifiers()
        
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "Application Window 1"
    list_controls(title)
