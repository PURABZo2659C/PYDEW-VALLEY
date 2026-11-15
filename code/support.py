from os import walk
import os
import math
import pygame
from settings import asset_path, ISO_TILE_HEIGHT, TILE_SIZE

_click_snd = None
_error_snd = None

# Item name -> overlay file stem when they differ
ICON_ALIASES = {
	'wood': 'oak_wood',
	'health_potion': 'health',
	'miner_potion': 'miner',
	'night_vision_potion': 'night_vision',
	'speed_potion': 'speed',
	'diamond': 'daimond',
	'heart_of_valley': 'heart of valley',
	'oak_sapling': 'oaktree_sapling',
	'birch_sapling': 'birchtree_sapling',
	'cherry_sapling': 'cherrytree_sapling',
	'pine_sapling': 'pinetree_sapling',
}

# Crop seed stacks share the harvested-crop item key, so the HUD resolves
# their icons separately (graphics/overlay/saplings and seeds/*_seed.png).
SEED_ICON_ALIASES = {
	'wheat': 'wheat_seed',
	'tomato': 'tomato_seed',
}

def load_overlay_icons(items, folder=None, aliases=None):
	"""Resolve item icons from graphics/overlay recursively.

	Icons live in subfolders (Tools/, Fruits and vegetables/, ores/...), so a
	flat lookup misses most of them. Matching is case-insensitive and item
	names can be aliased (e.g. 'wood' -> Oak_wood). Missing icons stay None.
	Pickable world items with no overlay art (flowers, mushrooms) fall back
	to their biome folder under graphics/Biomes/.
	"""
	if folder is None:
		folder = asset_path('graphics', 'overlay')
	stems = {}
	for root, _, files in walk(folder):
		for name in files:
			if name.lower().endswith('.png'):
				stems.setdefault(os.path.splitext(name)[0].lower(), os.path.join(root, name))
	if folder == asset_path('graphics', 'overlay'):
		# Extra icon sources for the default lookup: biome art for
		# foraged flowers/fungi and the world folder for placeables
		# (e.g. Bridge.png). Overlay art always wins on a name clash.
		for extra in (asset_path('graphics', 'Biomes'),
		              asset_path('graphics', 'world')):
			if os.path.isdir(extra):
				for root, _, files in walk(extra):
					for name in files:
						if name.lower().endswith('.png'):
							stems.setdefault(os.path.splitext(name)[0].lower(), os.path.join(root, name))

	alias_map = ICON_ALIASES
	if aliases:
		alias_map = dict(ICON_ALIASES)
		alias_map.update({str(k).lower(): str(v).lower()
		                  for k, v in aliases.items()})

	icons = {}
	for item in items:
		key = alias_map.get(item.lower(), item.lower())
		path = stems.get(key)
		surf = None
		if path:
			try:
				surf = pygame.image.load(path).convert_alpha()
			except Exception as exc:  # unreadable icon; fall back to no icon
				log_once(f'[Support] icon {os.path.basename(path)!r} failed', exc)
				surf = None
		icons[item] = surf
	return icons

# Diagnostics printed at most once per key: several of these guards sit
# in per-frame paths, where an unconditional print would flood the console.
_logged_warnings = set()


def log_once(key, exc):
	"""Print `exc` the first time `key` is seen, then stay quiet.

	Bare `except: pass` hides real bugs; printing every occurrence in a
	per-frame path buries them in spam instead. One line per failure site
	surfaces the error (plan item 3) without either failure mode.
	"""
	if key in _logged_warnings:
		return
	_logged_warnings.add(key)
	print(f'{key}: {exc!r}')


def click_sound():
	"""The shared UI click sound, loaded on first use.

	Returns the Sound (so volume settings can be applied to the very
	sound play_click() will play) or None when the file is missing."""
	global _click_snd
	if _click_snd is None:
		try:
			_click_snd = pygame.mixer.Sound(asset_path('audio', 'buttons click.mp3'))
			_click_snd.set_volume(0.5)
		except Exception as exc:  # missing audio: clicks stay silent, but say why
			log_once('[Support] buttons click.mp3 failed', exc)
			_click_snd = False
	return _click_snd if _click_snd else None


def play_click():
	"""Play the shared UI button-click sound (lazy-loaded, safe to call early)."""
	snd = click_sound()
	if snd:
		snd.play()

def play_error():
	"""Play the error / blocked-action sound (lazy-loaded, safe to call early)."""
	global _error_snd
	if _error_snd is None:
		try:
			_error_snd = pygame.mixer.Sound(asset_path('audio', 'error.mp3'))
			_error_snd.set_volume(0.5)
		except Exception as exc:  # missing audio: feedback stays silent, but say why
			log_once('[Support] error.mp3 failed', exc)
			_error_snd = False
	if _error_snd:
		_error_snd.play()

def load_map(path):
	"""Load a TMX map, tolerating tileset images that no longer exist on disk.

	The world is drawn procedurally now, so TMX tile art is only needed by
	Tiled; a deleted/renamed sheet must never abort startup. The map is
	consulted only for its LAYERS - the farmable zones and the player
	start - and its tilesets are never rendered.
	"""
	from pytmx.util_pygame import pygame_image_loader
	import pytmx

	def safe_image_loader(filename, colorkey=None, **kwargs):
		try:
			loader = pygame_image_loader(filename, colorkey, **kwargs)
		except Exception:
			return lambda rect=None, flags=None: None

		def load(rect=None, flags=None):
			try:
				return loader(rect, flags)
			except Exception:
				return None
		return load

	return pytmx.TiledMap(path, image_loader=safe_image_loader)

def import_folder(path):
	surface_list = []

	# sort numerically so frames load as 0,1,2,3 not 0,1,10,2
	def _sort_key(name):
		stem = os.path.splitext(name)[0]
		return (0, int(stem)) if stem.isdigit() else (1, name)

	for _, __, img_files in walk(path):
		for image in sorted(img_files, key=_sort_key):
			if not image.lower().endswith('.png'):
				continue
			full_path = path + '/' + image
			image_surf = pygame.image.load(full_path).convert_alpha()
			surface_list.append(image_surf)

	return surface_list

def import_folder_dict(path):
	surface_dict = {}

	for _, __, img_files in walk(path):
		for image in img_files:
			full_path = path + '/' + image
			image_surf = pygame.image.load(full_path).convert_alpha()
			surface_dict[image.split('.')[0]] = image_surf

	return surface_dict

def smooth_scale_rgba(surf, size):
	"""smoothscale an RGBA surface with premultiplied alpha.

	Pygame's smoothscale resamples R,G,B and A independently; transparent
	pixels often carry stale RGB (white grids, magenta placeholders), which
	would bleed colored halos into the art edges when downscaling. This
	premultiplies, scales RGB+A separately and un-premultiplies, so fully
	transparent areas contribute nothing to the resulting color.
	"""
	if surf.get_size() == size:
		return surf
	import numpy as np
	# Big downscales (2048px art -> a few hundred px) alias badly in one
	# pass; halving down to ~2x first box-filters the result AND cuts the
	# per-pixel premultiply work of the final pass by 4x per stage.
	w, h = surf.get_size()
	tw, th = size
	while w > tw * 2 and h > th * 2 and w > 16 and h > 16:
		w = max(tw, w // 2)
		h = max(th, h // 2)
		surf = pygame.transform.smoothscale(surf, (w, h))
	arr = pygame.surfarray.array3d(surf).astype(np.float32)
	alpha = pygame.surfarray.array_alpha(surf).astype(np.float32)
	premult = np.clip(arr * (alpha / 255.0)[:, :, None], 0, 255).astype(np.uint8)
	rgb = pygame.transform.smoothscale(pygame.surfarray.make_surface(premult), size)
	a3 = np.dstack([alpha, alpha, alpha]).astype(np.uint8)
	asurf = pygame.transform.smoothscale(pygame.surfarray.make_surface(a3), size)
	out = rgb.convert_alpha()
	pa = pygame.surfarray.pixels_alpha(out)
	pa[:] = pygame.surfarray.array2d(asurf)
	del pa
	oarr = pygame.surfarray.pixels3d(out)
	oa = pygame.surfarray.array_alpha(out).astype(np.float32) / 255.0
	keep = ((oa > (1.0 / 255.0)) / np.maximum(oa, 1e-3))[:, :, None]
	oarr[:] = np.clip(oarr.astype(np.float32) * keep, 0, 255).astype(np.uint8)
	del oarr
	return out


def clean_sprite_background(surf, noise_alpha=25, faint_alpha=215):
	"""Strip faint leftovers from AI-scaling artifacts: near-invisible
	alpha noise (borders, checkerboards) and faint light/neutral pixels
	(construction grids) that are clearly below the art's AA edge range.
	Operates in place; returns the surface."""
	import numpy as np
	arr = pygame.surfarray.array3d(surf).astype(np.int32)
	a = pygame.surfarray.array_alpha(surf).astype(np.int32)
	a[a < noise_alpha] = 0
	r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
	maxc = np.maximum(np.maximum(r, g), b)
	minc = np.minimum(np.minimum(r, g), b)
	a[(maxc > 150) & ((maxc - minc) < 75) & (a < faint_alpha)] = 0
	pa = pygame.surfarray.pixels_alpha(surf)
	pa[:] = a.astype(np.uint8)
	del pa
	return surf


def visible_bottom_pad(surf, alpha_threshold=10):
	"""Transparent rows between the image bottom and the lowest opaque pixel.

	Used to ground sprites on their isometric tile: the render step lifts the
	image by this amount so the VISIBLE art bottom (not the image edge) sits
	on the tile diamond center. Returns 0 for fully opaque/empty images.
	"""
	h = surf.get_height()
	w = surf.get_width()
	for y in range(h - 1, -1, -1):
		for x in range(w):
			if surf.get_at((x, y)).a > alpha_threshold:
				return h - 1 - y
	return 0

_FOOTPRINT_CACHE = {}

def ground_footprint_tiles(surf, foot_pad, wx, wy, tile=None,
                           alpha_threshold=10, min_frac=0.5):
	"""Whole ground tiles this bottom-anchored art physically covers.

	The art is drawn bottom-centred on (wx, wy) and lifted by ``foot_pad``
	screen px, so pixel (c, r) sits on screen at (c - w/2, r - h + foot_pad)
	from the anchor — the same projection support.occlusion_bands uses.
	Every opaque pixel maps back to exactly one ground point (the point
	that projects onto that screen pixel); the tiles those points fall in
	are the footprint: the ground the structure stands on PLUS the ground
	its height hides behind it.

	Collision built from these tiles is the river-bank rule applied to a
	structure: the player stops on the tile line exactly at the art's
	visible outline (no invisible wall standing in open ground, no
	squeezing between art pixels), and the ground the roof/rocks hide
	stays solid so nobody walks into the building and vanishes.

	``min_frac`` drops tiles the art only CLIPS: 1 art pixel covers
	4 ground units², so a full tile is tile²/4 pixels and a tile counts
	only when at least ``min_frac`` of it lies under the art. Without
	the cut, a roof edge shaving a couple of pixels off a doorstep would
	tile it solid and the door would be unwalkable. 0.125 keeps every
	tile the structure genuinely stands on (even the corner a wall just
	clips, which is what makes the shop's anchor tile solid) while
	doorsteps — which sit on 0 px of mask — and paths stay open.

	The result only depends on the anchor's position INSIDE its tile, so
	it is cached per surface + padding and translated for each caller.
	"""
	import numpy as np
	if tile is None:
		tile = TILE_SIZE
	rx, ry = wx % tile, wy % tile
	key = (surf, foot_pad, tile, alpha_threshold, min_frac, rx, ry)
	rel = _FOOTPRINT_CACHE.get(key)
	if rel is None:
		w, h = surf.get_size()
		alpha = pygame.surfarray.array_alpha(surf)
		# array_alpha is indexed [x][y] (shape (w, h)), so np.nonzero
		# hands back the pixel's COLUMN first and its ROW second:
		# xs = the art's c (horizontal), ys = its r (vertical).
		xs, ys = np.nonzero(alpha > alpha_threshold)
		if xs.size == 0:
			rel = frozenset()
		else:
			mx = xs.astype(np.float64) - w / 2.0
			my = ys.astype(np.float64) - (h - foot_pad)
			qx = rx + mx + 2.0 * my
			qy = ry + 2.0 * my - mx
			tx = np.floor(qx / tile).astype(np.int64)
			ty = np.floor(qy / tile).astype(np.int64)
			if min_frac > 0:
				# count pixels per tile, keep the well-covered ones
				counts = {}
				for x, y in zip(tx.tolist(), ty.tolist()):
					counts[(x, y)] = counts.get((x, y), 0) + 1
				need = min_frac * tile * tile / 4.0
				rel = frozenset(t for t, n in counts.items() if n >= need)
			else:
				rel = frozenset(zip(tx.tolist(), ty.tolist()))
		_FOOTPRINT_CACHE[key] = rel
	ox, oy = (wx - rx) // tile, (wy - ry) // tile
	if not ox and not oy:
		return set(rel)
	return {(x + ox, y + oy) for x, y in rel}


def tile_runs(tiles, tile=None):
	"""Merge whole tiles into one rect per row run: [(Rect, ...)].

	Every rect is tile-aligned and tile-sized, so collision built from
	them behaves exactly like a river bank tile — edge to edge, never a
	ragged art-pixel rim.
	"""
	if tile is None:
		tile = TILE_SIZE
	rects = []
	rows = {}
	for tx, ty in tiles:
		rows.setdefault(ty, []).append(tx)
	for ty in sorted(rows):
		xs = sorted(rows[ty])
		start = prev = xs[0]
		for tx in xs[1:] + [None]:
			if tx is not None and tx == prev + 1:
				prev = tx
				continue
			rects.append(pygame.Rect(start * tile, ty * tile,
			                         (prev - start + 1) * tile, tile))
			if tx is not None:
				start = prev = tx
	return rects


def flatten_bridge_deck(surf):
	"""Cut Bridge.png down to its bare deck DIAMOND (one 128x64 tile).

	The source art is a 3D slab: the deck diamond on top, 16px of side
	faces below it. A placed bridge has to be an ordinary ground tile —
	flush with the bank tops and the water plane, never a raised block —
	so keep only the pixels inside the deck's isometric diamond. The
	result drops into the terrain pass and renders exactly like any
	other tile.
	"""
	w, h = surf.get_size()
	deck_h = min(ISO_TILE_HEIGHT, h)
	flat = pygame.Surface((w, deck_h), pygame.SRCALPHA)
	mid = (w - 1) / 2.0
	for x in range(w):
		# Diamond edges: half-height of the column grows 0.5px per px
		# from either side vertex, so the column spans top..bottom
		# around the deck's centre row.
		top = int(round(abs(x - mid) / 2.0))
		bottom = deck_h - 1 - top
		if bottom < top:
			continue
		flat.blit(surf, (x, top), (x, top, 1, bottom - top + 1))
	return flat


_base_anchor_cache = {}

def iso_base_anchor(surf, alpha_threshold=10):
	"""Pixel inside the art where its isometric BASE DIAMOND CENTER sits.

	Many cave decor exports are not centered in their image: the box is
	drawn somewhere inside a wider canvas, so centering the image on the
	tile leaves the prop floating. This walks up from the bottom vertex
	while the row span keeps growing; the first plateau is the base
	diamond's equator, whose center is the anchor. Returns None for
	flat-bottomed art (pots), where the legacy bottom-pad convention is
	already correct.
	"""
	key = (surf, alpha_threshold)
	if key in _base_anchor_cache:
		return _base_anchor_cache[key]
	mask = pygame.mask.from_surface(surf, alpha_threshold)
	w, h = mask.get_size()
	spans = []
	for y in range(h):
		row = None
		for x in range(w):
			if mask.get_at((x, y)):
				row = (x, x)
				break
		if row is not None:
			for x in range(w - 1, row[0], -1):
				if mask.get_at((x, y)):
					row = (row[0], x)
					break
		spans.append(row)
	yb = None
	for y in range(h - 1, -1, -1):
		if spans[y]:
			yb = y
			break
	anchor = None
	if yb is not None:
		x0, x1 = spans[yb]
		if x1 - x0 + 1 <= 6:
			best_y = yb
			best_span = x1 - x0 + 1
			y = yb - 1
			while y >= 0 and spans[y]:
				span = spans[y][1] - spans[y][0] + 1
				if span <= best_span:
					break
				best_y = y
				best_span = span
				y -= 1
			x0, x1 = spans[best_y]
			anchor = ((x0 + x1 + 1) / 2.0, float(best_y))
	_base_anchor_cache[key] = anchor
	return anchor

# Player sprite metrics used to decide occlusion (keep in sync with
# Player: frame size and sole lift). (width, height, foot_pad)
CHARACTER_BOX = (172, 124, 24)

def occlusion_bands(surf, foot_pad, char_size=None, char_pad=None, step=32,
                    carve=None, alpha_threshold=10):
	"""Collision rects covering every ground spot where this bottom-anchored
	prop's art would draw OVER a character sprite (the character box shares
	an opaque pixel's screen space AND the iso depth key draws the prop in
	front). Returns ints [(x0, y0, w, h), ...] offset from the prop's tile
	centre; carve (same units) stays walkable.

	Renderer facts (CameraGroup.custom_draw): the prop's rect is centred on
	its tile centre and drawn with a +foot_pad screen lift; ground px and
	screen px are 1:1, so art pixel (c, r) sits on screen at
	(c - w/2, r - h + foot_pad) from the tile centre, i.e. over the ground
	point Q = (2*my + mx, 2*my - mx) with mx = c - w/2,
	my = r - (h - foot_pad). A character with feet at F is covered by that
	pixel when
	    du = (Q - F).x + (Q - F).y  in  [-4*(ch - pad), 4*pad]
	    dv = (Q - F).x - (Q - F).y  in  [-cw, cw]
	(the pixel's screen offset from the feet stays inside the sprite box).
	Depth: both keys are x + y floored at their own tile centre, so the
	prop only draws over the character where
	max(fx + fy, own_tile_offset) < 0 for feet offset (fx, fy) from the
	prop's tile centre — SE of the anti-diagonal the character draws on
	top, so overlap there is safe and stays walkable.
	"""
	if char_size is None:
		char_size = CHARACTER_BOX[:2]
	if char_pad is None:
		char_pad = CHARACTER_BOX[2]
	import numpy as np
	w, h = surf.get_size()
	alpha = pygame.surfarray.array_alpha(surf)  # (w, h) u8
	rows, cols = np.nonzero(alpha > alpha_threshold)
	if rows.size == 0:
		return []
	mx = cols.astype(np.float64) - w / 2.0
	my = rows.astype(np.float64) - (h - foot_pad)
	qx = 2.0 * my + mx
	qy = 2.0 * my - mx
	cw, ch = char_size
	du0, du1 = -4.0 * (ch - char_pad), 4.0 * char_pad
	dv0, dv1 = -float(cw), float(cw)
	dxlo = int(math.floor((du0 + dv0) / 2.0))   # -286 for the player box
	dxhi = int(math.ceil((du1 + dv1) / 2.0))
	dylo = int(math.floor((du0 - dv1) / 2.0))
	dyhi = int(math.ceil((du1 - dv0) / 2.0))
	xs = np.arange(int(np.floor(qx.min())) - dxhi,
	               int(np.ceil(qx.max())) - dxlo + 1, step)
	ys = np.arange(int(np.floor(qy.min())) - dyhi,
	               int(np.ceil(qy.max())) - dylo + 1, step)
	if xs.size == 0 or ys.size == 0:
		return []
	# depth eligibility per cell (feet offset from the tile centre)
	xi = xs.astype(np.int64)
	yi = ys.astype(np.int64)
	own = (((64 + xi) // 128)[None, :] + ((64 + yi) // 128)[:, None]) * 128
	elig = np.maximum(xi[None, :] + yi[:, None], own) < 0
	if carve is not None:
		cx0, cy0, cw_, ch_ = carve
		inside = ((xs[None, :] >= cx0) & (xs[None, :] < cx0 + cw_) &
		          (ys[:, None] >= cy0) & (ys[:, None] < cy0 + ch_))
		elig &= ~inside
	# coverage raster: pixels sorted by qy, per row only the qy slice that
	# can reach it (delta qy in [-286, 134])
	order = np.argsort(qy)
	qs, qxs = qy[order], qx[order]
	covered = np.zeros((ys.size, xs.size), dtype=bool)
	for ri in range(ys.size):
		fy = int(ys[ri])
		i0 = int(np.searchsorted(qs, fy + dylo, side='left'))
		i1 = int(np.searchsorted(qs, fy + dyhi, side='right'))
		if i0 >= i1:
			continue
		dx_ = qxs[i0:i1][:, None] - xs[None, :]
		dy_ = qs[i0:i1][:, None] - fy
		du = dx_ + dy_
		dv = dx_ - dy_
		covered[ri] = ((du >= du0) & (du <= du1) &
		               (dv >= dv0) & (dv <= dv1)).any(axis=0)
	covered &= elig
	# merge cells into rects: run-length per row, extend equal runs down
	rects = []
	open_runs = {}
	for ri in range(ys.size):
		row = covered[ri]
		runs = set()
		j = 0
		while j < xs.size:
			if row[j]:
				k = j
				while k + 1 < xs.size and row[k + 1]:
					k += 1
				runs.add((int(xs[j]), (k - j + 1) * step))
				j = k + 1
			else:
				j += 1
		new_open = {}
		for key in runs:
			if key in open_runs:
				y0, hgt = open_runs[key]
				new_open[key] = (y0, hgt + step)
			else:
				new_open[key] = (int(ys[ri]), step)
		for key, (y0, hgt) in open_runs.items():
			if key not in new_open:
				rects.append((key[0], y0, key[1], hgt))
		open_runs = new_open
	for key, (y0, hgt) in open_runs.items():
		rects.append((key[0], y0, key[1], hgt))
	return rects