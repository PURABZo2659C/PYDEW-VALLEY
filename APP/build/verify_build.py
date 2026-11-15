"""Check the built artifacts before they are handed out.

Verifies that the bundle contains everything the game needs, and -
just as important - that it does NOT contain the things it must not
carry: somebody else's save file, or the build output itself.

Run:  python build/verify_build.py
"""

import ast
import os
import shutil
import sys
import tempfile
import zipfile

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
if BUILD_DIR not in sys.path:
    sys.path.insert(0, BUILD_DIR)

import filters

ROOT = os.path.dirname(BUILD_DIR)
GAME_ROOT = filters.find_game_root(ROOT)
DIST = os.path.join(ROOT, 'dist')

EXE_NAME = 'PydewValley.exe'
FOLDER_NAME = 'PydewValley'
ZIP_GLOB = 'Pydew Valley [v*] Windows.zip'

# Must be present.
REQUIRED = [
    'graphics/world/logo.png',
    'graphics/world/Background.mp4',
    'graphics/UI/inventory.png',
    'graphics/Biomes/Oak_Woods/Oaktree_small.png',
    'audio/Title_background.wav',
    'audio/music.mp3',
    'font/ui.ttf',
    'font/pixelFont-7-8x14-sproutLands.ttf',
    'data/map.tmx',
    'PYDEW VALLEY DOCUMENTATION.html',
    'THIRD_PARTY_NOTICES.txt',
    'VERSION.txt',
]

# Must NOT be present.
FORBIDDEN = [
    'data/save.json',                  # player data
    'data/keybindings.json',           # player data
    'data/volume.json',                # player data
]

# The ZIP must contain exactly this, and nothing else.
ZIP_REQUIRED = [
    'Pydew Valley/PydewValley.exe',
    'Pydew Valley/README.txt',
    'Pydew Valley/THIRD_PARTY_NOTICES.txt',
    'Pydew Valley/PYDEW VALLEY DOCUMENTATION.html',
]
ZIP_FORBIDDEN = [
    'Pydew Valley/save.json',
    'Pydew Valley/save.json.bak',
    'Pydew Valley/keybindings.json',
    'Pydew Valley/volume.json',
]

failures = []
notes = []


def check(condition, message):
    if condition:
        print('  PASS  %s' % message)
    else:
        print('  FAIL  %s' % message)
        failures.append(message)


def _import_graph(game_root):
    """The game modules reachable from the entry point, and the rest.

    PyInstaller only bundles what is actually imported, so the check has
    to follow the imports rather than assume every file in code/ is
    used. Modules that nothing imports are reported separately - they
    are dead code, not a broken build.
    """
    code_dir = os.path.join(game_root, 'code')
    modules = {name[:-3] for name in os.listdir(code_dir)
               if name.endswith('.py')}

    reachable = set()
    stack = ['launcher']
    while stack:
        name = stack.pop()
        if name in reachable or name not in modules:
            continue
        reachable.add(name)
        path = os.path.join(code_dir, name + '.py')
        try:
            with open(path, encoding='utf-8') as handle:
                tree = ast.parse(handle.read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split('.')[0]
                    if root in modules:
                        stack.append(root)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                if node.module:
                    root = node.module.split('.')[0]
                    if root in modules:
                        stack.append(root)
    return reachable, modules


def check_modules(exe, game_root):
    """Every module the game imports must actually be inside the bundle.

    PyInstaller does NOT fail the build when a module has a syntax
    error - it reports it in the warning log and quietly leaves the
    module out. The game then crashes on startup with an ImportError
    that never showed up at build time. This reads the archive's module
    table and compares it with the import graph.
    """
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(exe)
    pyz = reader.open_embedded_archive('PYZ.pyz')
    bundled = set(pyz.toc)

    reachable, modules = _import_graph(game_root)
    # launcher.py is the entry script and sits in the archive root.
    required = reachable - {'launcher'}
    missing = sorted(m for m in required if m not in bundled)

    check(not missing,
          'all %d imported game modules are in the bundle%s'
          % (len(required),
             '' if not missing else ' - MISSING: %s' % ', '.join(missing)))

    unused = sorted(modules - reachable)
    if unused:
        notes.append('not imported by anything (dead code): %s'
                     % ', '.join(unused))


def check_folder(root):
    """Check the folder build (the Aseprite layout)."""
    print('\nFolder build: %s' % root)
    bundle = os.path.join(root, 'data')
    if not os.path.isdir(bundle):
        bundle = root
        notes.append('no data folder - checked the install root')

    files = set()
    for dirpath, _dirs, names in os.walk(bundle):
        for name in names:
            full = os.path.join(dirpath, name)
            files.add(os.path.relpath(full, bundle).replace('\\', '/'))

    for rel in REQUIRED:
        check(rel in files, 'contains %s' % rel)
    for rel in FORBIDDEN:
        check(rel not in files, 'does NOT contain %s' % rel)

    exe = os.path.join(root, EXE_NAME)
    check(os.path.exists(exe), 'has %s' % EXE_NAME)
    if os.path.exists(exe):
        check_modules(exe, GAME_ROOT)
    notes.append('folder build: %d files in the bundle' % len(files))


def check_onefile(exe):
    """Check the single-file build by reading its archive table."""
    print('\nSingle file build: %s' % exe)
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(exe)
    entries = [name.replace('\\', '/') for name in reader.toc]

    def has(suffix):
        return any(name.endswith(suffix) for name in entries)

    def contains(fragment):
        fragment = fragment.lower()
        return any(fragment in name.lower() for name in entries)

    for rel in REQUIRED:
        check(has(rel), 'contains %s' % rel)
    for rel in FORBIDDEN:
        check(not has(rel), 'does NOT contain %s' % rel)

    check(has('launcher'), 'contains the entry script (launcher)')
    check(has('PYZ.pyz'), 'contains the PYZ archive with the game code')
    check(has('SDL2.dll'), 'contains the pygame SDL2 runtime')
    check(contains('cv2') and contains('cv2.pyd'),
          'contains OpenCV (cv2.pyd + its loader)')
    check(contains('numpy'), 'contains NumPy')

    check_modules(exe, GAME_ROOT)

    notes.append('onefile build: %d archive entries' % len(entries))


def check_zip(path):
    """Check the ZIP - the file that is actually shared."""
    print('\nZIP: %s' % path)
    check(os.path.exists(path), 'the ZIP exists')
    size = os.path.getsize(path) / 1048576.0
    notes.append('ZIP: %.1f MB' % size)

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        bad = archive.testzip()
        check(bad is None, 'the archive is not corrupt')
        for rel in ZIP_REQUIRED:
            check(rel in names, 'contains %s' % rel)
        for rel in ZIP_FORBIDDEN:
            check(rel not in names, 'does NOT contain %s' % rel)
        check(not any(n.endswith('.pyc') or '__pycache__' in n for n in names),
              'contains no python cache files')
        check(len(names) == len(ZIP_REQUIRED),
              'contains only the expected files (%d found)' % len(names))

    # Extract it and confirm the executable is really there and sane.
    target = os.path.join(tempfile.gettempdir(), 'pydew_zip_check')
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        archive.extractall(target)
    exe = os.path.join(target, 'Pydew Valley', EXE_NAME)
    check(os.path.exists(exe), 'extracts a working %s' % EXE_NAME)
    if os.path.exists(exe):
        exe_mb = os.path.getsize(exe) / 1048576.0
        check(exe_mb > 50,
              'the extracted exe is the single file build (%.1f MB)' % exe_mb)
    shutil.rmtree(target, ignore_errors=True)


def main():
    folder = os.path.join(DIST, FOLDER_NAME)
    onefile = os.path.join(DIST, EXE_NAME)
    zips = sorted(f for f in os.listdir(DIST) if f.endswith('.zip')) \
        if os.path.isdir(DIST) else []

    print('=' * 62)
    print('PYDEW VALLEY - build verification')
    print('=' * 62)

    if os.path.isdir(folder):
        check_folder(folder)
    else:
        print('\nFolder build not found at %s (skipped)' % folder)

    if os.path.exists(onefile):
        check_onefile(onefile)
    else:
        print('\nSingle file build not found at %s (skipped)' % onefile)

    for name in zips:
        check_zip(os.path.join(DIST, name))
    if not zips:
        print('\nNo ZIP found (skipped)')

    print('\n' + '=' * 62)
    for note in notes:
        print('  %s' % note)
    if failures:
        print('\n%d CHECK(S) FAILED:' % len(failures))
        for failure in failures:
            print('  - %s' % failure)
        return 1
    print('\nAll checks passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
