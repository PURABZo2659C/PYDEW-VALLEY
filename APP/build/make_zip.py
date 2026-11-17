"""Build the Pydew Valley Windows ZIP - the whole distribution in one file.

The Aseprite model: one ZIP that a friend unzips and plays. No
installer, no admin rights, no registry entries. The game is fully
portable - everything it writes (the save, the settings, the logs) goes
into the folder next to the executable, so deleting that folder removes
the game and all its data.

    Pydew Valley [v*] Windows.zip
    `-- Pydew Valley/
         |-- PydewValley.exe
         |-- PYDEW VALLEY Documentation.html

Run:  python build/make_zip.py
"""

import io
import os
import re
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

    # The in-game help page, with version substituted from VERSION.txt
    doc = find_source(os.path.join(ROOT, DOC_NAME))
    if doc:
        with open(doc, 'r', encoding='utf-8') as handle:
            html = handle.read()
        html = re.sub(r'v\d+\.\d+(?:\.\d+)?', 'v%s' % version, html)
        with open(os.path.join(folder, DOC_NAME), 'w', encoding='utf-8') as handle:
            handle.write(html)

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
