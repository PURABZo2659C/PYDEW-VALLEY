"""Fetch the macOS and Linux ZIPs for this version from GitHub Releases.

PyInstaller cannot cross-compile: build.bat builds Windows here, and the
Build and Release workflow builds the other two on native runners. This
script copies them into dist/ so all three sit together.

Run:  python build/fetch_other_os.py          (skip files already present)
      python build/fetch_other_os.py --force  (download again)
"""

import os
import subprocess
import sys
import urllib.request
import zipfile

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BUILD_DIR)
DIST = os.path.join(APP_DIR, 'dist')
FALLBACK_REPO = 'PURABZo2659C/PYDEW-VALLEY'


def read_version():
    with open(os.path.join(BUILD_DIR, 'VERSION.txt'), 'r', encoding='utf-8') as handle:
        return handle.read().strip()


def repo_slug():
    """owner/repo from the origin remote, or the known repository."""
    try:
        url = subprocess.check_output(
            ['git', 'config', '--get', 'remote.origin.url'],
            cwd=APP_DIR, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return FALLBACK_REPO
    if 'github.com' not in url:
        return FALLBACK_REPO
    slug = url.split('github.com', 1)[1].lstrip('/:')
    if slug.endswith('.git'):
        slug = slug[:-4]
    parts = slug.split('/')
    if len(parts) < 2:
        return FALLBACK_REPO
    return '%s/%s' % (parts[0], parts[1])


def _reporter():
    """Print a progress line every 25%, so a large download is not silent."""
    state = {'shown': -25}

    def report(blocks, block_size, total):
        if total <= 0:
            return
        percent = min(100, int(blocks * block_size * 100 / total))
        step = percent - percent % 25
        if step > state['shown']:
            state['shown'] = step
            print('    %d%%' % step)

    return report


def download(url, target):
    """Download to a .part file, verify the ZIP, then move it into place."""
    part = target + '.part'
    try:
        urllib.request.urlretrieve(url, part, reporthook=_reporter())
        with zipfile.ZipFile(part) as archive:
            if archive.testzip() is not None:
                raise ValueError('archive is corrupt')
        os.replace(part, target)
        return True
    except Exception as exc:
        print('  failed: %s' % exc)
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
        return False


def main():
    version = read_version()
    tag = 'v' + version
    slug = repo_slug()
    force = '--force' in sys.argv
    os.makedirs(DIST, exist_ok=True)

    missing = []
    for name in ('Pydew-Valley-v%s-linux.zip' % version,
                 'Pydew-Valley-v%s-macos.zip' % version):
        target = os.path.join(DIST, name)
        if os.path.exists(target) and not force:
            print('  have %s' % name)
            continue
        url = 'https://github.com/%s/releases/download/%s/%s' % (slug, tag, name)
        print('  downloading %s' % name)
        if not download(url, target):
            missing.append(name)

    if missing:
        print('\n  release %s is missing: %s' % (tag, ', '.join(missing)))
        print('  Push a %s tag or run the Build and Release workflow first.' % tag)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
