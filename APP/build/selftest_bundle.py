"""Exercise the built bundle the way the frozen game will.

Smart App Control refuses to launch an unsigned executable, so the
bundle cannot simply be started to prove it works. This script fakes
the frozen environment instead - same sys._MEIPASS, same asset paths -
and then loads every kind of asset the game touches, so a broken
bundle shows up here instead of on a friend's screen.

Run:  python build/selftest_bundle.py
"""

import os
import sys

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
if BUILD_DIR not in sys.path:
    sys.path.insert(0, BUILD_DIR)

import filters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_ROOT = filters.find_game_root(ROOT)
if len(sys.argv) > 1:
    INTERNAL = os.path.abspath(sys.argv[1])
else:
    INTERNAL = os.path.join(ROOT, 'dist', 'PydewValley', 'data')

# The executable the bundle belongs to - user files live beside it.
EXECUTABLE = os.path.join(os.path.dirname(INTERNAL), 'PydewValley.exe')

failures = []


def check(condition, message):
    if condition:
        print('  PASS  %s' % message)
    else:
        print('  FAIL  %s' % message)
        failures.append(message)


def main():
    if not os.path.isdir(INTERNAL):
        raise SystemExit('bundle not found: %s' % INTERNAL)

    # Pretend to be the frozen onefile/onedir game.
    sys.frozen = True
    sys._MEIPASS = INTERNAL
    # A packaged game keeps its user files next to its executable, so
    # point sys.executable at the build to test the same layout.
    sys.executable = EXECUTABLE
    sys.path.insert(0, os.path.join(GAME_ROOT, 'code'))
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

    import pygame
    pygame.init()
    # convert_alpha() needs a video mode - the real game sets one in
    # Game.__init__ before any asset is loaded.
    pygame.display.set_mode((320, 200))

    import settings
    print('BASE_DIR : %s' % settings.BASE_DIR)
    print('user data: %s' % settings.user_data_dir())
    check(os.path.normcase(settings.BASE_DIR) == os.path.normcase(INTERNAL),
          'BASE_DIR points at the bundle')
    check(settings.FROZEN is True, 'FROZEN is detected')
    check(os.path.normcase(settings.user_data_dir())
          == os.path.normcase(os.path.dirname(EXECUTABLE)),
          'user data goes beside the executable')
    check(settings.app_version() != 'dev',
          'the bundled VERSION.txt is found (version %s)'
          % settings.app_version())

    # ---- every image in the bundle ------------------------------------
    print('\nImages')
    images = []
    for dirpath, _dirs, names in os.walk(INTERNAL):
        for name in names:
            if name.lower().endswith('.png'):
                images.append(os.path.join(dirpath, name))
    bad = []
    for path in images:
        try:
            pygame.image.load(path).convert_alpha()
        except Exception as exc:
            bad.append((path, exc))
    check(not bad, 'all %d PNGs load (%d failed)' % (len(images), len(bad)))
    for path, exc in bad[:5]:
        print('        %s -> %r' % (os.path.basename(path), exc))

    # ---- fonts ---------------------------------------------------------
    print('\nFonts')
    for name in ('ui.ttf', 'pixelFont-7-8x14-sproutLands.ttf'):
        path = settings.asset_path('font', name)
        try:
            font = pygame.font.Font(path, 24)
            font.render('test', True, (255, 255, 255))
            check(True, '%s loads and renders' % name)
        except Exception as exc:
            check(False, '%s -> %r' % (name, exc))

    # ---- audio ---------------------------------------------------------
    print('\nAudio')
    for name in ('Title_background.wav', 'music.mp3', 'success.wav',
                 'hoe.wav', 'plant.wav', 'water.mp3', 'axe.mp3',
                 'error.mp3', 'buttons click.mp3'):
        path = settings.asset_path('audio', name)
        try:
            pygame.mixer.Sound(path)
            check(True, 'audio/%s loads' % name)
        except Exception as exc:
            check(False, 'audio/%s -> %r' % (name, exc))

    # ---- the title screen video (OpenCV) -------------------------------
    print('\nOpenCV')
    try:
        import cv2
        video = settings.asset_path('graphics', 'world', 'Background.mp4')
        cap = cv2.VideoCapture(video)
        opened = cap.isOpened()
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if opened else 0
        ok, frame = cap.read() if opened else (False, None)
        cap.release()
        check(opened and ok and frames > 0,
              'Background.mp4 decodes (%d frames)' % frames)
    except Exception as exc:
        check(False, 'OpenCV video -> %r' % (exc,))

    # ---- the TMX map (PyTMX) -------------------------------------------
    print('\nPyTMX')
    try:
        from support import load_map
        tmx = load_map(settings.asset_path('data', 'map.tmx'))
        check(tmx.width > 0 and tmx.height > 0,
              'map.tmx loads (%dx%d tiles)' % (tmx.width, tmx.height))
    except Exception as exc:
        check(False, 'map.tmx -> %r' % (exc,))

    # ---- the folders the game walks at runtime -------------------------
    print('\nAsset folders')
    for folder in ('graphics/Biomes/Oak_Woods/ground',
                   'graphics/Caves/ground',
                   'graphics/Growing/Oaktree',
                   'graphics/overlay/Tools',
                   'graphics/character/Villagers/Baker/Down',
                   'graphics/UI',
                   'graphics/Village',
                   'graphics/Tiles_Sets'):
        path = settings.asset_path(*folder.split('/'))
        check(os.path.isdir(path), '%s exists' % folder)

    # ---- the help page -------------------------------------------------
    print('\nHelp page')
    check(os.path.exists(settings.help_doc_path()),
          'help page resolves: %s' % os.path.basename(settings.help_doc_path()))

    print('\n' + '=' * 60)
    if failures:
        print('%d CHECK(S) FAILED:' % len(failures))
        for failure in failures:
            print('  - %s' % failure)
        return 1
    print('Bundle self-test passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
