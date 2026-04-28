"""d_click_diagnostic.py — measure where the actual D button is.

Run this on the failing PC AFTER you've opened an FS pricing screen
(any FS<route>/<airline> command result that shows BOOK / +TQ rows).

The script gives you 8 seconds, then captures the cursor position.
Hover the mouse cursor exactly over the D button (the literal letter D
at the end of a BOOK/+TQ row, the one TravelportAuto would normally
click). When the timer hits 0, the script prints the cursor coords.

You then compare those coords to what TravelportAuto computed in its
log:

    [D-CLICK] Trying (1752, 248) [x=0, y=0]

The delta between actual and computed tells us exactly how to fix the
positioning logic on this machine.

Usage:
    python d_click_diagnostic.py

No dependencies beyond pyautogui (already a TravelportAuto requirement).
"""

import time
import pyautogui


COMPUTED_FROM_LATEST_LOG = (1752, 248)  # Update if your log differs


def main() -> None:
    print("=" * 60)
    print("D-button position diagnostic")
    print("=" * 60)
    print()
    print("Steps:")
    print("  1. Make sure Smartpoint is showing an FS pricing screen")
    print("     (one with BOOK or +TQ rows visible).")
    print("  2. When the countdown finishes, the mouse position will be")
    print("     captured. Hover your cursor over the D button BEFORE")
    print("     the countdown reaches 0.")
    print()
    print("Starting in...")
    for i in range(8, 0, -1):
        print(f"  {i}... (move cursor onto the D)", flush=True)
        time.sleep(1)

    actual_x, actual_y = pyautogui.position()
    expected_x, expected_y = COMPUTED_FROM_LATEST_LOG

    print()
    print("=" * 60)
    print(f"Actual D position    : ({actual_x}, {actual_y})")
    print(f"TravelportAuto tried : ({expected_x}, {expected_y})")
    print(f"X offset (actual - tried): {actual_x - expected_x:+d}px")
    print(f"Y offset (actual - tried): {actual_y - expected_y:+d}px")
    print("=" * 60)
    print()
    if abs(actual_x - expected_x) <= 15 and abs(actual_y - expected_y) <= 9:
        print("Cursor was within the ±15px X / ±9px Y fan-out — the click")
        print("SHOULD have hit. If it didn't, the issue is not positioning")
        print("(perhaps focus, or the D click isn't actually clickable).")
    else:
        print("Cursor is OUTSIDE the fan-out range. This is the bug.")
        print()
        print(f"The fix is to shift TravelportAuto's computed position by")
        print(f"({actual_x - expected_x:+d}, {actual_y - expected_y:+d}) pixels on this machine.")


if __name__ == "__main__":
    main()
