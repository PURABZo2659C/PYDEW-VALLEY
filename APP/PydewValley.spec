# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PYDEW VALLEY.

Two builds come out of this one file:

  single file   pyinstaller --clean --noconfirm PydewValley.spec
                -> dist/PydewValley.exe

  folder        set PYDEW_ONEDIR=1 first
                -> dist/PydewValley/  (+ _internal/ with the assets)
                This is the payload the MSI installer ships: it starts
                instantly and is far less likely to trip antivirus
                heuristics, because nothing is unpacked at runtime.

The asset list comes from build/filters.py, which keeps unlicensed and
player-specific files out of the bundle.
"""

import os
import sys

SPEC_DIR = os.path.abspath(SPECPATH)
BUILD_DIR = os.path.join(SPEC_DIR, 'build')
if BUILD_DIR not in sys.path:
    sys.path.insert(0, BUILD_DIR)

import filters

# The game source may sit above this folder (the build tooling lives in
# an "APP" subfolder), so look for it instead of assuming.
ROOT = filters.find_game_root(SPEC_DIR)
APP_DIR = SPEC_DIR

ONEDIR = os.environ.get('PYDEW_ONEDIR', '') == '1'
NAME = 'PydewValley'
ICON = os.path.join(BUILD_DIR, 'pydew_valley.ico')
VERSION = os.path.join(BUILD_DIR, 'version_info.py')
ENTRY = os.path.join(ROOT, 'code', 'launcher.py')

datas = filters.collect_data(ROOT, APP_DIR)
removed = filters.describe_excluded(ROOT)
print('game root: %s' % ROOT)
print('app dir  : %s' % APP_DIR)
print('bundle: %d data files' % len(datas))
print('bundle excludes: %s' % (', '.join(removed) if removed else 'nothing'))

# pygame ships its own PyInstaller hook (pygame/__pyinstaller/), and
# pyinstaller-hooks-contrib ships one for OpenCV - both are picked up
# automatically. Everything below is what neither of them knows about.
hiddenimports = [
    'pygame', 'pygame.base', 'pygame.constants', 'pygame.display',
    'pygame.draw', 'pygame.event', 'pygame.font', 'pygame.freetype',
    'pygame.image', 'pygame.key', 'pygame.mask', 'pygame.math',
    'pygame.mixer', 'pygame.mixer_music', 'pygame.mouse', 'pygame.pixelarray',
    'pygame.pixelcopy', 'pygame.rect', 'pygame.rwobject', 'pygame.scrap',
    'pygame.sndarray', 'pygame.sprite', 'pygame.surfarray', 'pygame.surface',
    'pygame.surflock', 'pygame.sysfont', 'pygame.time', 'pygame.transform',
    'numpy', 'cv2', 'pytmx', 'pytmx.pytmx', 'pytmx.util_pygame',
    'webbrowser', 'shutil',
]

# Nothing here is imported by the game - dropping them keeps the
# executable (and the installer) a lot smaller.
excludes = [
    'scipy', 'skimage', 'matplotlib', 'pandas', 'tkinter', 'IPython',
    'pytest', 'PIL', 'setuptools', 'pip', 'distutils', 'test',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
]

a = Analysis(
    [ENTRY],
    pathex=[os.path.join(ROOT, 'code')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

if ONEDIR:
    # The Aseprite layout: the executable plus a "data" folder holding
    # the runtime and the assets. The game resolves its resources
    # through sys._MEIPASS, so it finds them whatever the folder is
    # called - and the player's own files stay next to the executable.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=ICON,
        version=VERSION,
        contents_directory='data',
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=NAME,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=ICON,
        version=VERSION,
    )
    if sys.platform == 'darwin':
        app = BUNDLE(
            exe,
            name=NAME + '.app',
            bundle_identifier='com.pydewvalley.game',
            info_plist={
                'NSPrincipalClass': 'NSApplication',
                'NSHighResolutionCapable': True,
            },
        )
