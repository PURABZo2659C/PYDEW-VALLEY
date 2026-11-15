"""Build the Pydew Valley Windows ZIP - the whole distribution in one file.

The Aseprite model: one ZIP that a friend unzips and plays. No
installer, no admin rights, no registry entries. The game is fully
portable - everything it writes (the save, the settings, the logs) goes
into the folder next to the executable, so deleting that folder removes
the game and all its data.

    Pydew Valley [v2.6] Windows.zip
    `-- Pydew Valley/
         |-- PydewValley.exe
         |-- PYDEW VALLEY Documentation.html
         |-- THIRD_PARTY_NOTICES.txt
         |-- README.txt

Run:  python build/make_zip.py
"""

import io
import os
import shutil
import zipfile

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BUILD_DIR)
ROOT = os.path.dirname(APP_DIR)
DIST = os.path.join(APP_DIR, 'dist')
STAGE = os.path.join(BUILD_DIR, 'zipstage')

FOLDER_NAME = 'Pydew Valley'
EXE_NAME = 'PydewValley.exe'
DOC_NAME = 'PYDEW VALLEY DOCUMENTATION.html'
NOTICES_NAME = 'THIRD_PARTY_NOTICES.txt'
README_NAME = 'README.txt'

README_TEMPLATE = """PYDEW VALLEY {version}
====================

HOW TO PLAY
-----------
1. Extract this ZIP somewhere you can write to - your Desktop or
   Documents. Do NOT put it in C:\\Program Files: the game saves your
   progress next to the executable, and that folder is read-only for
   normal programs.
2. Double-click Pydew Valley\\PydewValley.exe.
3. The first start unpacks the game into a temporary folder, so give it
   a few seconds before the window appears.

WHERE YOUR SAVE IS
------------------
Everything the game writes goes into the Pydew Valley folder next to
the executable:

    save.json          your world, inventory and progress
    keybindings.json   your key bindings
    volume.json        music and sound volume
    Shots\\             camera screenshots you took
    game.log           written only if something goes wrong

That means the whole game is portable. Copy the folder to a USB stick
and your world comes with it. Delete the folder and the game and all
its data are gone.

UPDATING
--------
Unzip the new version straight over the old folder. Your save stays
where it is, so you keep your world.

TROUBLESHOOTING
---------------
Windows may warn that the file is from the internet. Click
"More info" and then "Run anyway".

If Windows blocks the game entirely with "Windows protected your PC",
it is Smart App Control refusing to run an unsigned program. Either
right-click the ZIP before extracting and tick "Unblock", or install
pydew-valley.cer (if it came with this download) into
Trusted Root Certification Authorities.

THIRD PARTY ASSETS
------------------
This game uses third-party art, fonts and music. The full list, with
the authors and their licence terms, is in THIRD_PARTY_NOTICES.txt.
"""


def read_version():
    with open(os.path.join(BUILD_DIR, 'VERSION.txt'), 'r', encoding='utf-8') as handle:
        return handle.read().strip()


def find_source(*candidates):
    """First existing path among the candidates."""
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def build():
    version = read_version()
    exe = os.path.join(DIST, EXE_NAME)
    if not os.path.exists(exe):
        raise SystemExit(
            '%s is missing.\nBuild it first:  build.bat exe' % exe)

    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE, ignore_errors=True)
    folder = os.path.join(STAGE, FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)

    # The executable itself.
    shutil.copy2(exe, os.path.join(folder, EXE_NAME))

    # The in-game help page and the licence notices.
    doc = find_source(os.path.join(ROOT, DOC_NAME))
    if doc:
        shutil.copy2(doc, os.path.join(folder, DOC_NAME))
    notices = find_source(os.path.join(APP_DIR, NOTICES_NAME),
                          os.path.join(BUILD_DIR, NOTICES_NAME),
                          os.path.join(ROOT, NOTICES_NAME))
    if notices:
        shutil.copy2(notices, os.path.join(folder, NOTICES_NAME))

    # A readme for the player.
    with open(os.path.join(folder, README_NAME), 'w', encoding='utf-8') as handle:
        handle.write(README_TEMPLATE.format(version=version))

    # Zip it. A fixed timestamp keeps the build reproducible.
    zip_name = 'Pydew Valley [v%s] Windows.zip' % version
    zip_path = os.path.join(DIST, zip_name)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    entries = []
    for dirpath, _dirs, names in os.walk(STAGE):
        for name in names:
            full = os.path.join(dirpath, name)
            entries.append((full, os.path.relpath(full, STAGE).replace('\\', '/')))

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for full, arcname in sorted(entries, key=lambda item: item[1]):
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, 'rb') as handle:
                archive.writestr(info, handle.read())

    shutil.rmtree(STAGE, ignore_errors=True)

    size = os.path.getsize(zip_path) / 1048576.0
    print('wrote %s' % zip_path)
    print('   %d files, %.1f MB' % (len(entries), size))
    for _full, arcname in sorted(entries, key=lambda item: item[1]):
        print('     %s' % arcname)


if __name__ == '__main__':
    build()
