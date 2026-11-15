"""Explicit rules for what goes into the packaged build.

PyInstaller happily copies a whole folder, which is exactly how an
un-licensed or user-specific file ends up inside a redistributable
executable by accident. This module walks the asset tree file by file
and applies an explicit deny list, so the bundle contains only what the
game actually needs to run.

Used by PydewValley.spec (datas) and by build/make_msi.bat (the
installer payload).
"""

import os

# The game source (code/, graphics/, audio/, font/, data/) and the build
# tooling (build.bat, PydewValley.spec, build/, dist/) live in two
# different folders: the tooling sits in an "APP" subfolder of the game
# root. These helpers find each of them no matter how they are nested.
GAME_MARKERS = ('code', 'graphics')


def find_game_root(start):
	"""Walk up from `start` until the game source folder is found.

	That folder is the one holding `code/` and `graphics/` side by side.
	"""
	current = os.path.abspath(start)
	for _ in range(6):
		if all(os.path.isdir(os.path.join(current, marker))
		       for marker in GAME_MARKERS):
			return current
		parent = os.path.dirname(current)
		if parent == current:
			break
		current = parent
	raise RuntimeError(
		'could not find the game source folder (a folder with code/ and '
		'graphics/) above %s' % start)


def find_app_dir(start):
	"""The folder holding the build tooling - the one with build/ in it."""
	current = os.path.abspath(start)
	for _ in range(6):
		if os.path.isdir(os.path.join(current, 'build')):
			return current
		parent = os.path.dirname(current)
		if parent == current:
			break
		current = parent
	return os.path.abspath(start)


# Folders that are copied into the bundle, relative to the project root.
ASSET_FOLDERS = ('graphics', 'audio', 'font')

# Individual files that must never ship. Matched against the path
# relative to the project root, lower-cased.
EXCLUDED_FILES = {
	# NOTE: the shipped title theme is audio/Title_background.wav by
	# Yoiyami (CC0). graphics/world/background.mp3 is only an optional
	# user-supplied fallback and is not part of the project; keep it out
	# of a public build unless you have distribution rights.
}

# Folders that must never ship. Matched against the path relative to
# the project root, lower-cased.
EXCLUDED_DIRS = {
	# Player-made camera screenshots - user data, not game assets. The
	# game writes new ones to the user data folder at runtime.
	'graphics/shots',
}

# Extra files copied into the bundle root.
EXTRA_FILES = (
	'PYDEW VALLEY DOCUMENTATION.html',
	'THIRD_PARTY_NOTICES.txt',
	'VERSION.txt',
)

# Read-only data files that ship with the game. Everything else in
# data/ is player state (save file, key bindings, volume) and must NOT
# be bundled - it would hand one player's save to everyone else.
#
# Only the TMX map is needed. The map's tile LAYERS carry the farmable
# zones and the player start, but its tilesets are never drawn - the
# world is generated in code - and the .tsx files pointed at art that
# does not exist. They were also inherited from the Clear Code
# tutorial, so they were dropped and the <tileset> references removed
# from map.tmx.
DATA_FILES = (
	'data/map.tmx',
)


def _normalise(path):
	return os.path.normpath(path).replace('\\', '/').lower()


def is_excluded(rel_path):
	"""True when a project-relative path must stay out of the bundle."""
	rel = _normalise(rel_path)
	if rel in EXCLUDED_FILES:
		return True
	# A file inside an excluded folder is excluded too.
	for excluded in EXCLUDED_DIRS:
		if rel.startswith(excluded + '/'):
			return True
	return False


def collect_data(root, app_dir=None):
	"""Return PyInstaller `datas` entries for the whole asset tree.

	Each asset becomes its own entry so the deny list can be applied per
	file. `dest` is the directory the file keeps inside the bundle, so
	graphics/world/logo.png lands at <bundle>/graphics/world/logo.png -
	the same layout the source tree has, which is what asset_path()
	expects.

	`app_dir` is the build tooling folder. Files in EXTRA_FILES live
	there rather than in the game source, so both are searched.
	"""
	datas = []
	for folder in ASSET_FOLDERS:
		top = os.path.join(root, folder)
		if not os.path.isdir(top):
			continue
		for dirpath, _dirnames, filenames in os.walk(top):
			for name in filenames:
				full = os.path.join(dirpath, name)
				rel = os.path.relpath(full, root)
				if is_excluded(rel):
					continue
				datas.append((full, os.path.dirname(rel)))
	for extra in EXTRA_FILES:
		full = None
		for base in (root, app_dir, os.path.join(app_dir, 'build')):
			if not base:
				continue
			candidate = os.path.join(base, extra)
			if os.path.exists(candidate):
				full = candidate
				break
		if full:
			datas.append((full, '.'))
	for rel in DATA_FILES:
		full = os.path.normpath(os.path.join(root, rel))
		if os.path.exists(full):
			datas.append((full, os.path.dirname(rel)))
	return datas


def payload_files(root, folder):
	"""Project-relative files of one folder that belong in the bundle."""
	out = []
	top = os.path.join(root, folder)
	if not os.path.isdir(top):
		return out
	for dirpath, _dirnames, filenames in os.walk(top):
		for name in filenames:
			full = os.path.join(dirpath, name)
			rel = os.path.relpath(full, root)
			if not is_excluded(rel):
				out.append(rel)
	return out


def describe_excluded(root):
	"""Human-readable list of what the deny list removed, for the log."""
	removed = []
	for folder in ASSET_FOLDERS:
		top = os.path.join(root, folder)
		if not os.path.isdir(top):
			continue
		for dirpath, _dirnames, filenames in os.walk(top):
			for name in filenames:
				full = os.path.join(dirpath, name)
				rel = os.path.relpath(full, root)
				if is_excluded(rel):
					removed.append(rel.replace('\\', '/'))
	return sorted(removed)
