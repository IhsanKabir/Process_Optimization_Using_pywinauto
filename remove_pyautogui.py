import re

def main():
    with open('smartpoint_automation.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace imports
    content = content.replace('import pyautogui', 'from pywinauto.keyboard import send_keys\nfrom pywinauto.mouse import click')
    
    # Remove FAILSAFE
    content = content.replace('pyautogui.FAILSAFE = True', '# pyautogui removed')
    
    # Helper to escape text for send_keys
    helper = '''    def _typewrite(self, text, interval=0):
        # pywinauto send_keys uses { } for special keys, so we must escape them
        escaped = text.replace('{', '{{').replace('}', '}}').replace('+', '{+}').replace('^', '{^}').replace('%', '{%}').replace('~', '{~}')
        send_keys(escaped, with_spaces=True, pause=0.01)'''
        
    # Insert helper method after def focus(self...
    if 'def _typewrite(' not in content:
        content = re.sub(r'(def clear_screen\(self\):)', r'\1\n        pass\n\n' + helper + r'\n\n    def __old_clear_screen(self):', content)
        # Actually a better insertion point: just search for def clear_screen and replace it
        content = content.replace('def clear_screen(self):', helper + '\n\n    def clear_screen(self):')

    # Replace pyautogui.typewrite(..., interval=...) with self._typewrite(...)
    content = re.sub(r'pyautogui\.typewrite\(([^,]+)(,\s*interval=[^\)]+)?\)', r'self._typewrite(\1)', content)
    
    # Replace pyautogui.press('enter') with send_keys('{ENTER}')
    content = content.replace("pyautogui.press('enter')", "send_keys('{ENTER}')")
    content = content.replace("pyautogui.press('enter', interval=constants.KEYBOARD_INTERVAL)", "send_keys('{ENTER}')")
    
    # Replace pyautogui.press('escape') -> send_keys('{VK_ESCAPE}')
    content = content.replace("pyautogui.press('escape')", "send_keys('{VK_ESCAPE}')")
    content = re.sub(r"pyautogui\.press\('escape',\s*presses=([0-9]+)[^\)]*\)", r"send_keys('{VK_ESCAPE \1}')", content)

    # Replace pyautogui.press('tab') -> send_keys('{TAB}')
    content = re.sub(r"pyautogui\.press\('tab'[^\)]*\)", r"send_keys('{TAB}')", content)
    
    # Replace pyautogui.hotkey('ctrl', '...
    content = content.replace("pyautogui.hotkey('ctrl', 'a')", "send_keys('^a')")
    content = content.replace("pyautogui.hotkey('ctrl', 'c')", "send_keys('^c')")
    
    # Replace pyautogui.click(x=safe_x, y=safe_y)
    content = re.sub(r"pyautogui\.click\(x=([^,]+),\s*y=([^\)]+)\)", r"click(coords=(int(\1), int(\2)))", content)

    with open('smartpoint_automation.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print("Replaced successfully")

if __name__ == '__main__':
    main()
