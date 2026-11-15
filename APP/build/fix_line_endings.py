"""Normalise the Windows batch files to CRLF line endings.

cmd.exe is unreliable at matching `call :label` targets in files that
use bare LF endings - it silently reports "The system cannot find the
batch label specified". Every .bat and .cmd file in the project is
therefore converted to CRLF before the build runs.

Two details this script has to survive:

  * cmd.exe keeps the running .bat open, so rewriting build.bat while
    it is executing can fail with a sharing violation. That is caught
    and reported, never fatal.
  * The build output folders are skipped - they hold thousands of files
    and no batch files at all.

Run:  python build/fix_line_endings.py
"""

import os
import sys

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BUILD_DIR)

# Folders that hold build output rather than tooling.
SKIP_DIRS = ('dist', 'tools', 'msitest', 'zipstage', '__pycache__')


def find_batch_files():
    """Every .bat / .cmd file in the build tooling and the app folder."""
    found = []
    for folder in (APP_DIR, BUILD_DIR):
        for dirpath, dirs, names in os.walk(folder):
            # Prune the walk instead of skipping the files in a folder.
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in names:
                if name.lower().endswith(('.bat', '.cmd')):
                    found.append(os.path.join(dirpath, name))
    return found


def to_crlf(path):
    """Convert one file to CRLF. Returns True when it was changed."""
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
        fixed = (data.replace(b'\r\n', b'\n')
                      .replace(b'\r', b'\n')
                      .replace(b'\n', b'\r\n'))
        if fixed == data:
            return False
        with open(path, 'wb') as handle:
            handle.write(fixed)
        return True
    except OSError as exc:
        print('   could not convert %s (%s)' % (os.path.basename(path), exc))
        return False


def main():
    changed = []
    for path in find_batch_files():
        if to_crlf(path):
            changed.append(os.path.relpath(path, APP_DIR))
    if changed:
        print('line endings fixed: %s' % ', '.join(changed))
    else:
        print('line endings already CRLF')
    return 0


if __name__ == '__main__':
    sys.exit(main())
