import re

def main():
    text = open('smartpoint_automation.py', 'r', encoding='utf-8').read()

    # 1. Replace moveTo + click
    text = re.sub(
        r'pyautogui\.moveTo\(([^,]+),\s*([^,]+)[^\)]*\)\s*\n\s*pyautogui\.click\(\)',
        r'click(coords=(int(\1), int(\2)))',
        text
    )

    # 2. Replace one-line click
    text = re.sub(
        r'pyautogui\.click\(([^,]+),\s*([^\)]+)\)',
        r'click(coords=(int(\1), int(\2)))',
        text
    )

    # 3. Replace pagedown
    text = text.replace(
        "pyautogui.press('pagedown', presses=4, interval=constants.KEYBOARD_INTERVAL)",
        "send_keys('{PGDN 4}', pause=constants.KEYBOARD_INTERVAL)"
    )

    with open('smartpoint_automation.py', 'w', encoding='utf-8') as f:
        f.write(text)

    print('Leftovers replaced!')

if __name__ == '__main__':
    main()
