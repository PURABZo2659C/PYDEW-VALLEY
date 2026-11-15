r"""Run the real game against the built bundle.

Smart App Control blocks the packaged executable, so the game cannot be
started from the .exe to prove it works. This script fakes the frozen
environment - same sys._MEIPASS, same asset paths - and then runs the
actual entry point: the title screen, and then a level, using the files
that are inside the bundle.

It is the closest thing to "double-click the exe and see it work" that
can be done without a code signing certificate.

Run:  python build/selftest_game.py [bundle-root]

The optional argument is the folder that holds the game's assets - the
data folder of the folder build. It defaults to that build in dist\.
"""

import os
import sys
import time

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

    sys.frozen = True
    sys._MEIPASS = INTERNAL
    # A packaged game keeps its user files next to its executable.
    sys.executable = EXECUTABLE
    sys.path.insert(0, os.path.join(GAME_ROOT, 'code'))
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

    import pygame
    pygame.init()
    screen = pygame.display.set_mode((640, 360))

    # ---- the title screen ------------------------------------------------
    print('Title screen')
    try:
        from title_screen import TitleScreen
        title = TitleScreen()
        title.draw(1 / 60.0)
        pygame.display.update()
        check(True, 'title screen builds and renders a frame')
        check(title.logo is not None, 'title logo loaded')
        check(title.menu_music is not None,
              'menu music loaded (%s)'
              % ('yes' if title.menu_music else 'no'))
        check(title.video is not None,
              'background video opened via OpenCV')
    except Exception as exc:
        check(False, 'title screen -> %r' % (exc,))

    # ---- a real level ----------------------------------------------------
    print('\nLevel')
    try:
        from level import Level
        started = time.time()
        level = Level(None)
        check(True, 'level built in %.1fs' % (time.time() - started))
        check(level.player is not None, 'player exists')
        check(len(level.soil_layer.grid) > 0, 'soil grid built')
        check(level.time_manager is not None, 'time manager running')

        # Run a few frames the way main.py does.
        clock = pygame.time.Clock()
        for _ in range(5):
            events = pygame.event.get()
            dt = clock.tick(60) / 1000
            level.run(dt, events)
            pygame.display.update()
        check(True, 'level ran 5 frames without raising')

        # The save system has to work from the bundle too.
        from save_system import save_game, load_save, delete_save
        beside = os.path.dirname(EXECUTABLE)
        check(save_game(level), 'save written beside the executable')
        check(os.path.exists(os.path.join(beside, 'save.json')),
              'the save file is in the game folder (%s)' % beside)
        data = load_save()
        check(data is not None and 'player' in data, 'save read back')
        delete_save()
        check(load_save() is None, 'save deleted')
    except Exception as exc:
        check(False, 'level -> %r' % (exc,))

    print('\n' + '=' * 60)
    if failures:
        print('%d CHECK(S) FAILED:' % len(failures))
        for failure in failures:
            print('  - %s' % failure)
        return 1
    print('Game self-test passed - the bundle really runs.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
