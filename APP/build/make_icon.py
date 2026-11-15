"""Generate the Windows .ico for the packaged game.

The repo only had graphics/world/logo.png, which is a single 606x329
image - Windows wants a square icon at several sizes or it looks muddy
in the task bar and the Programs list.

Run:  python build/make_icon.py

If Pillow isn't available, fall back to copying logo.png as a simple
ICO-style file (Windows can read PNGs as icons in many contexts).
"""

import os
import sys

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
if BUILD_DIR not in sys.path:
    sys.path.insert(0, BUILD_DIR)

import filters

# The game source may sit above this folder (the build tooling lives in
# an "APP" subfolder).
GAME_ROOT = filters.find_game_root(BUILD_DIR)

SOURCE = os.path.join(GAME_ROOT, 'graphics', 'world', 'logo.png')
TARGET = os.path.join(BUILD_DIR, 'pydew_valley.ico')

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
         (128, 128), (256, 256)]


def build_icon():
    if not os.path.exists(SOURCE):
        raise SystemExit('logo not found: %s' % SOURCE)

    try:
        from PIL import Image
    except ImportError:
        # Pillow isn't available - copy logo.png as a fallback.
        # Windows can display PNG as an icon in many contexts.
        import shutil
        os.makedirs(os.path.dirname(TARGET), exist_ok=True)
        shutil.copy2(SOURCE, TARGET)
        print('wrote %s (Pillow not available, copied as-is)' % TARGET)
        return

    logo = Image.open(SOURCE).convert('RGBA')

    # The logo is wide (606x329). Windows icons are square, so it goes
    # on a square transparent canvas with the aspect ratio kept.
    side = max(logo.size)
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(logo, ((side - logo.width) // 2,
                        (side - logo.height) // 2), logo)

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    canvas.save(TARGET, format='ICO', sizes=SIZES)
    print('wrote %s (%d bytes)' % (TARGET, os.path.getsize(TARGET)))

    # Verify every size really made it in.
    with Image.open(TARGET) as check:
        print('icon sizes: %s' % sorted(check.info.get('sizes', [])))


if __name__ == '__main__':
    build_icon()
