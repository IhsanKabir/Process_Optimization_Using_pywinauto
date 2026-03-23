from pywinauto.application import Application
import traceback

def dump_tree():
    try:
        app = Application(backend="uia").connect(title_re=".*Application Window 1.*", timeout=5)
        win = app.window(title_re=".*Application Window 1.*")
        
        print("Dumping UI tree to tree_dump.txt...")
        with open("tree_dump.txt", "w", encoding="utf-8") as f:
            win.dump_tree(depth=7, filename="tree_dump.txt")
        print("Dump complete!")
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    dump_tree()
