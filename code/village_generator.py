"""Villages: procedurally placed settlements of homes around a green.
One deterministic site per sector, inset by a dead zone and kept clear of
the starting farm. Villages stream like chunks; while loaded the world
generator forces the core flat + dry and reserves its tiles from props.
"""
import os
import math
from random import Random

import pygame
from pygame.math import Vector2

from settings import *
from support import (import_folder, visible_bottom_pad,
                     clean_sprite_background, asset_path)
from collision import (
	structure_footprint, structure_outline_blockers, structure_front_tiles,
)
from sprites import Generic, Interaction
from world_generator import white_noise, _det_hash, TILES_PER_CHUNK


# Shared village art (cleaned, cropped, native size): file name -> (surface, sole pad).
_VILLAGE_ASSET_CACHE = {}
# Chebyshev upper bound on a village's land/reserve radius (true max ~20; 40 has headroom).
_VILLAGE_AREA_MAX_RADIUS = 40
_VILLAGE_BASE_FILES = {
	key: fname for key, fname, _tiles, _anchor in VILLAGE_BUILDINGS
}

# Per-structure collision masks (graphics/world/Collisions/), used instead of art alpha.
_VILLAGE_COLLISION_FILES = {
	'town_hall': 'Town Hall_collision.png',
	'bakery': 'Bakery_collision.png',
	'smith': 'Blacksmith_collision.png',
	'potion': 'Wizard_collision.png',
	'lumber': 'Lumber_collision.png',
	'farmer': 'Farmer_collision.png',
	'shop': 'Shop_collision.png',
}


def tile_center(gx, gy):
	return Vector2(gx * TILE_SIZE + TILE_SIZE // 2,
	               gy * TILE_SIZE + TILE_SIZE // 2)


def _collision_asset(assets, key):
	"""The surface a house's ground footprint is measured from: the authored
	collision mask in graphics/world/Collisions when there is one, otherwise
	the house art itself. Both are (surf, pad).
	"""
	cname = _VILLAGE_COLLISION_FILES.get(key)
	asset = assets.get(cname) if cname else None
	if not asset or not asset[0]:
		asset = assets.get(_VILLAGE_BASE_FILES.get(key))
	if not asset or not asset[0]:
		return None
	return asset


def _block_rect(wx, wy, scaled):
	"""The collision rect for one structure.
	From the authored collision mask when there is one, else the art's own
	alpha, merged into one run rect per row.
	"""
	half = TILE_SIZE // 2
	x0 = (wx - scaled - half) // TILE_SIZE
	y0 = (wy - scaled - half) // TILE_SIZE
	x1 = (wx + half - 1) // TILE_SIZE
	y1 = (wy + half - 1) // TILE_SIZE
	return pygame.Rect(x0 * TILE_SIZE, y0 * TILE_SIZE,
	                   (x1 - x0 + 1) * TILE_SIZE,
	                   (y1 - y0 + 1) * TILE_SIZE)


def _block_tiles(ax, ay, tiles):
	"""Layout reservation tiles for an anchored building — the whole
	tile square the layout reserves around it (see _block_rect). The
	collision footprint is computed separately from the art itself."""
	wx = ax * TILE_SIZE + TILE_SIZE // 2
	wy = ay * TILE_SIZE + TILE_SIZE // 2
	scaled = int(round(tiles * TILE_SIZE))
	r = _block_rect(wx, wy, scaled)
	return (r.left // TILE_SIZE, r.top // TILE_SIZE,
	        (r.right - 1) // TILE_SIZE, (r.bottom - 1) // TILE_SIZE)


class Building(Generic):
	"""Bottom-anchored village house: the anchor tile holds the art's
	ground contact point, the sole pad grounds it on the tile diamond
	exactly like the player's feet."""

	def __init__(self, pos, surf, groups, foot_pad=None, building_key=None):
		super().__init__(pos, surf, groups, z=LAYERS['house bottom'])
		self.rect = self.image.get_rect(center=pos)
		self.foot_pad = visible_bottom_pad(surf) if foot_pad is None else foot_pad
		self.building_key = building_key


class Villager(Generic):
	"""Wandering village NPC: 4-direction walk cycle, grounded on the tile
	diamond like the player. Walks a BFS route that dodges building blockers,
	trees/rocks and water.
	"""

	def __init__(self, name, pos, animations, zone, world_gen, seed, groups,
	             home_pos=None, collision_sprites=None):
		self.name = name
		self.animations = animations
		self.pads = animations['_pads']
		super().__init__(pos, animations['down'][0], groups, z=LAYERS['main'])
		self.rect = self.image.get_rect(center=pos)
		self.hitbox = self.rect.copy().inflate(-self.rect.width * 0.5,
		                                       -self.rect.height * 0.4)
		self.foot_pad = self.pads['down']
		self.pos = Vector2(self.rect.center)
		self.home_pos = Vector2(home_pos if home_pos is not None
		                        else self.rect.center)
		self.inside = False
		self.zone = zone
		self.world_gen = world_gen
		self.collision_sprites = collision_sprites
		self.rng = Random(seed)
		self.status = 'down'
		self.frame_index = 0.0
		self.moving = False
		self.target = None
		self.path = []
		self.path_index = 0
		self.idle_timer = self.rng.uniform(0.0, VILLAGER_IDLE_MAX)

	def enter_home(self):
		self.inside = True
		self.moving = False
		self.target = None
		self.path = []
		self.path_index = 0
		self.pos.update(self.home_pos)
		self.rect.center = (round(self.pos.x), round(self.pos.y))
		self.hitbox.center = self.rect.center
		self.status = 'down'
		self.frame_index = 0.0
		self.image = self.animations['down'][0]
		self.foot_pad = self.pads['down']

	def leave_home(self):
		self.inside = False
		self.idle_timer = self.rng.uniform(VILLAGER_IDLE_MIN,
		                                   VILLAGER_IDLE_MAX)

	# -- walk planning --
	def _tile_of(self, pos):
		return (int(pos[0]) // TILE_SIZE, int(pos[1]) // TILE_SIZE)

	def _tile_center(self, tile):
		return Vector2(tile[0] * TILE_SIZE + TILE_SIZE // 2,
		               tile[1] * TILE_SIZE + TILE_SIZE // 2)

	def _plan_bounds(self):
		"""Search area in TILE coordinates: the wander zone, widened to
		include the tile the villager currently stands on (leaving home
		starts at the door)."""
		z = self.zone
		bounds = pygame.Rect(z.left // TILE_SIZE, z.top // TILE_SIZE,
		                     max(1, (z.width + TILE_SIZE - 1) // TILE_SIZE),
		                     max(1, (z.height + TILE_SIZE - 1) // TILE_SIZE))
		tx, ty = self._tile_of(self.pos)
		bounds = bounds.union(pygame.Rect(tx, ty, 1, 1))
		return bounds.inflate(2, 2)

	def _blocked_tiles(self, bounds):
		"""Tiles whose centre overlaps a solid hitbox (building blocker,
		tree, rock, bush, water collider). Tiles just outside the search
		area are ignored for speed."""
		blocked = set()
		if not self.collision_sprites:
			return blocked
		body_w = max(16, int(TILE_SIZE * 0.44))
		body_h = max(12, int(TILE_SIZE * 0.26))
		rects = []
		for sprite in self.collision_sprites.sprites():
			hit = getattr(sprite, 'hitbox', None)
			if hit is None:
				hit = getattr(sprite, 'rect', None)
			if hit is None or hit.width <= 0 or hit.height <= 0:
				continue
			if (hit.right < bounds.left * TILE_SIZE
					or hit.left > bounds.right * TILE_SIZE
					or hit.bottom < bounds.top * TILE_SIZE
					or hit.top > bounds.bottom * TILE_SIZE):
				continue
			rects.append(hit)
		if not rects:
			return blocked
		for tx in range(bounds.left, bounds.right + 1):
			for ty in range(bounds.top, bounds.bottom + 1):
				cx = tx * TILE_SIZE + TILE_SIZE // 2
				cy = ty * TILE_SIZE + TILE_SIZE // 2
				body = pygame.Rect(0, 0, body_w, body_h)
				body.center = (cx, cy)
				if any(body.colliderect(hit) for hit in rects):
					blocked.add((tx, ty))
		return blocked

	def _tile_walkable(self, tile, blocked):
		if tile in blocked:
			return False
		if self.world_gen is not None:
			if self.world_gen.is_water_at(tile[0], tile[1]):
				return False
		return True

	def _plan_path(self):
		"""BFS from the current tile to a random walkable tile inside the
		zone. Returns a list of tile-centre waypoints (may be empty)."""
		start = self._tile_of(self.pos)
		bounds = self._plan_bounds()
		blocked = self._blocked_tiles(bounds)
		parent = {start: None}
		queue = [start]
		head = 0
		steps = ((1, 0), (-1, 0), (0, 1), (0, -1),
		         (1, 1), (1, -1), (-1, 1), (-1, -1))
		while head < len(queue):
			tile = queue[head]
			head += 1
			x, y = tile
			for dx, dy in steps:
				nxt = (x + dx, y + dy)
				if nxt in parent:
					continue
				if not bounds.collidepoint(nxt[0], nxt[1]):
					continue
				if not self._tile_walkable(nxt, blocked):
					continue
				# Diagonals may only slip between two open orthogonal tiles: no corner cuts.
				if dx and dy:
					if not (self._tile_walkable((x + dx, y), blocked)
					        and self._tile_walkable((x, y + dy), blocked)):
						continue
				parent[nxt] = tile
				queue.append(nxt)
		candidates = []
		for tile in parent:
			if tile == start:
				continue
			if self.zone.collidepoint(*self._tile_center(tile)):
				candidates.append(tile)
		if not candidates:
			return []
		goal = self.rng.choice(candidates)
		path = []
		tile = goal
		while tile is not None and tile != start:
			path.append(self._tile_center(tile))
			tile = parent[tile]
		path.reverse()
		return path

	def _stop_walking(self):
		self.moving = False
		self.path = []
		self.path_index = 0
		self.idle_timer = self.rng.uniform(VILLAGER_IDLE_MIN,
		                                   VILLAGER_IDLE_MAX)

	def _face_delta(self, delta):
		# facing from the SCREEN direction of travel (iso axes)
		sdx = delta.x - delta.y
		sdy = delta.x + delta.y
		if abs(sdx) > abs(sdy):
			self.status = 'right' if sdx > 0 else 'left'
		else:
			self.status = 'down' if sdy > 0 else 'up'

	def _think(self, dt):
		if not self.moving:
			self.idle_timer -= dt
			if self.idle_timer <= 0:
				path = self._plan_path()
				if not path:
					self.idle_timer = self.rng.uniform(0.4, 1.0)
					return
				self.path = path
				self.path_index = 0
				self.target = Vector2(path[-1])
				self.moving = True
			return

		if self.path_index >= len(self.path):
			self._stop_walking()
			return

		waypoint = self.path[self.path_index]
		delta = waypoint - self.pos
		dist = delta.length()
		step = VILLAGER_SPEED * dt
		if dist <= step or dist == 0:
			self.pos.update(waypoint)
			self.path_index += 1
			if self.path_index >= len(self.path):
				self._stop_walking()
		else:
			self._face_delta(delta / dist)
			self.pos += delta / dist * step
		self.rect.center = (round(self.pos.x), round(self.pos.y))

	def animate(self, dt):
		frames = self.animations[self.status]
		if self.moving:
			self.frame_index = (self.frame_index + 5.0 * dt) % len(frames)
		else:
			self.frame_index = 0.0
		self.image = frames[int(self.frame_index)]
		self.foot_pad = self.pads[self.status]

	def update(self, dt):
		self._think(dt)
		self.animate(dt)


class VillageGenerator:
	"""Deterministic village sites, streamed around the player. Needs no
	save state: every site is a pure function of (tile, world seed)."""

	def __init__(self, all_sprites, collision_sprites, interaction_sprites,
	             world_gen, time_manager=None, seed=None):
		self.all_sprites = all_sprites
		self.collision_sprites = collision_sprites
		self.interaction_sprites = interaction_sprites
		self.world_gen = world_gen
		self.time_manager = time_manager
		self.seed = WORLD_SEED if seed is None else seed
		self._sector_cache = {}    # (sx, sy) -> spec or None
		self._sector_center_cache = {}  # (sx, sy) -> site centre or None
		self._reserve_cache = {}   # chunk -> frozenset of reserved tiles
		self._loaded = {}          # (sx, sy) -> live record
		self._villager_anims = {}
		self._invisible = pygame.Surface((8, 8), pygame.SRCALPHA)
		self.heart_placed = False
		self._ensure_assets()

	# ---- STREAMING ----

	def update(self, player_pos):
		"""Load villages near the player, recycle the ones left behind.
		Runs BEFORE WorldGenerator.update so a freshly loaded village's
		land override is in place when its chunks re-generate."""
		pgx = int(player_pos.x) // TILE_SIZE
		pgy = int(player_pos.y) // TILE_SIZE

		unload = VILLAGE_UNLOAD_DISTANCE
		for key, rec in list(self._loaded.items()):
			cx, cy = rec['spec']['center']
			if max(abs(cx - pgx), abs(cy - pgy)) > unload:
				self._unload(key)

		load = VILLAGE_LOAD_DISTANCE
		span = VILLAGE_SECTOR_SIZE
		for sx in range((pgx - load) // span, (pgx + load) // span + 1):
			for sy in range((pgy - load) // span, (pgy + load) // span + 1):
				if (sx, sy) in self._loaded:
					continue
				spec = self._sector_village(sx, sy)
				if spec is None:
					continue
				cx, cy = spec['center']
				if max(abs(cx - pgx), abs(cy - pgy)) <= load:
					self._load((sx, sy), spec)

		self._update_villager_schedule()

		if len(self._reserve_cache) > 4096:
			self._reserve_cache.clear()

	def reset(self):
		"""Unload every live village (day reset / world re-init)."""
		for key in list(self._loaded):
			self._unload(key)

	def set_heart_placed(self, placed):
		"""Swap the town hall to its heart variant (or back) in every
		loaded village; future villages pick the same art on load."""
		placed = bool(placed)
		if placed == self.heart_placed:
			return
		self.heart_placed = placed
		for rec in self._loaded.values():
			for sprite in rec['sprites']:
				key = getattr(sprite, 'building_key', None)
				if key not in VILLAGE_BUILDING_AFTER:
					continue
				art = self._building_art(key)
				if art is None:
					continue
				center = sprite.rect.center
				sprite.image = art[0]
				sprite.rect = sprite.image.get_rect(center=center)
				sprite.foot_pad = art[1]
				ax = sprite.rect.centerx // TILE_SIZE
				ay = sprite.rect.centery // TILE_SIZE
				sprite.front_tiles = {
					(ax + dx, ay + dy)
					for dx, dy in structure_front_tiles(
						art[0], art[1], door=(1, 1),
						radius=STRUCTURE_FRONT_RADIUS)}

	# ---- WORLD-GENERATOR INTERFACE ----

	def reserved_tiles_for_chunk(self, cx, cy):
		"""Tiles of this chunk too close to (or inside) a village site —
		trees, rocks and other props must never spawn there. Pure and
		cached; safe to call while no village is loaded."""
		key = (cx, cy)
		cached = self._reserve_cache.get(key)
		if cached is not None:
			return cached
		out = set()
		tx0 = cx * TILES_PER_CHUNK
		ty0 = cy * TILES_PER_CHUNK
		tx1 = tx0 + TILES_PER_CHUNK - 1
		ty1 = ty0 + TILES_PER_CHUNK - 1
		pad = VILLAGE_SECTOR_SIZE + 40
		span = VILLAGE_SECTOR_SIZE
		for sx in range((tx0 - pad) // span, (tx1 + pad) // span + 1):
			for sy in range((ty0 - pad) // span, (ty1 + pad) // span + 1):
				center = self._sector_village_center(sx, sy)
				if center is None:
					continue
				# Chebyshev distance from site centre to chunk: past the bound, skip the build.
				dx = max(tx0 - center[0], 0, center[0] - tx1)
				dy = max(ty0 - center[1], 0, center[1] - ty1)
				if max(dx, dy) > _VILLAGE_AREA_MAX_RADIUS:
					continue
				spec = self._sector_village(sx, sy)
				if spec is None:
					continue
				if 'reserve_tiles' in spec:
					for x, y in spec['reserve_tiles']:
						if tx0 <= x <= tx1 and ty0 <= y <= ty1:
							out.add((x, y))
					continue
				x0, y0, x1, y1 = spec['reserve_rect']
				ox0 = max(tx0, x0)
				ox1 = min(tx1, x1)
				oy0 = max(ty0, y0)
				oy1 = min(ty1, y1)
				if ox0 <= ox1 and oy0 <= oy1:
					for x in range(ox0, ox1 + 1):
						for y in range(oy0, oy1 + 1):
							out.add((x, y))
		frozen = frozenset(out)
		self._reserve_cache[key] = frozen
		return frozen

	def is_reserved_tile(self, gx, gy):
		"""Is this single tile inside a village's reserved footprint?
		Used by the cave-entrance scan so doorways never open inside a
		village (and vice-versa, deterministically)."""
		span = VILLAGE_SECTOR_SIZE
		pad = span + 40
		for sx in range((gx - pad) // span, (gx + pad) // span + 1):
			for sy in range((gy - pad) // span, (gy + pad) // span + 1):
				center = self._sector_village_center(sx, sy)
				if center is None:
					continue
				if (abs(center[0] - gx) > _VILLAGE_AREA_MAX_RADIUS
						or abs(center[1] - gy) > _VILLAGE_AREA_MAX_RADIUS):
					continue
				spec = self._sector_village(sx, sy)
				if spec is None:
					continue
				if 'reserve_tiles' in spec:
					if (gx, gy) in spec['reserve_tiles']:
						return True
					continue
				x0, y0, x1, y1 = spec['reserve_rect']
				if x0 <= gx <= x1 and y0 <= gy <= y1:
					return True
		return False

	def is_village_area_tile(self, gx, gy):
		"""True anywhere inside a village's flattened site (including the
		open ground between buildings). Used to keep cave doorways out of
		settlements; natural props use the narrower reserved-tile test."""
		span = VILLAGE_SECTOR_SIZE
		pad = span + 40
		for sx in range((gx - pad) // span, (gx + pad) // span + 1):
			for sy in range((gy - pad) // span, (gy + pad) // span + 1):
				center = self._sector_village_center(sx, sy)
				if center is None:
					continue
				if (abs(center[0] - gx) > _VILLAGE_AREA_MAX_RADIUS
						or abs(center[1] - gy) > _VILLAGE_AREA_MAX_RADIUS):
					continue
				spec = self._sector_village(sx, sy)
				if spec is None:
					continue
				x0, y0, x1, y1 = spec['land_rect']
				if x0 <= gx <= x1 and y0 <= gy <= y1:
					return True
		return False

	# ---- SITE SAMPLING + LAYOUT (pure functions of the site tile) ----

	def _sector_village(self, sx, sy):
		"""The sector's village spec, or None.
		Scans stride-ordered candidates in the dead zone; the only rejection rule
		is the starting-farm clearance.
		"""
		key = (sx, sy)
		if key in self._sector_cache:
			return self._sector_cache[key]
		center = self._sector_village_center(sx, sy)
		spec = self._build_layout(*center) if center is not None else None
		self._sector_cache[key] = spec
		return spec

	def _sector_village_center(self, sx, sy):
		"""The village site tile for a sector.
		One site per sector, inset from the borders so villages keep a minimum
		distance from each other.
		"""
		key = (sx, sy)
		if key in self._sector_center_cache:
			return self._sector_center_cache[key]
		center = None
		margin = VILLAGE_DEAD_ZONE
		span = VILLAGE_SECTOR_SIZE - 2 * margin
		if span > 0:
			total = span * span
			# Legacy WORLD_SEED keeps the original walk; fresh seeds rotate the start.
			start = (0 if self.seed == WORLD_SEED else
			         _det_hash(sx, sy, 'village-site', self.seed) % total)
			for i in range(min(total, 12)):
				k = (start + i * 53) % total
				cx = sx * VILLAGE_SECTOR_SIZE + margin + k % span
				cy = sy * VILLAGE_SECTOR_SIZE + margin + k // span
				ex, ey = VILLAGE_START_TILE
				if max(abs(cx - ex), abs(cy - ey)) >= VILLAGE_START_CLEARANCE:
					center = (cx, cy)
					break
		self._sector_center_cache[key] = center
		return center

	def _build_layout(self, cx, cy):
		rng = Random(_det_hash(cx, cy, 'village', self.seed))

		plaza_cfg = VILLAGE_PLAZA
		plaza_anchor = (cx + plaza_cfg['anchor'][0],
		                cy + plaza_cfg['anchor'][1])

		canon_targets = {}
		for key, _file, _tiles, (ax, ay) in VILLAGE_BUILDINGS:
			canon_targets[(ax + 1, ay + 1)] = key

		anchors = {}      # key -> (x, y) tile
		for key, _file, _tiles, (ax, ay) in VILLAGE_BUILDINGS:
			anchors[key] = (cx + ax, cy + ay)
		config = {key: (fname, tiles)
		          for key, fname, tiles, _anchor in VILLAGE_BUILDINGS}

		def art_tiles(key):
			"""How many tiles a village building's art covers.
			Measured from the art file itself: it renders at its native size, so the
			fallback width column is only used for a missing file.
			"""
			art = self._assets.get(_VILLAGE_BASE_FILES.get(key))
			if art and art[0]:
				return art[0].get_width() / TILE_SIZE
			return config[key][1]   # missing file: configured fallback

		def foot_of(key, x, y):
			"""The bottom-anchored foot of a village structure's art.
			Village art is drawn bottom-centred on its anchor tile's diamond centre.
			"""
			asset = _collision_asset(self._assets, key)
			if not asset:
				return set()
			return structure_footprint(
				asset[0], asset[1],
				x * TILE_SIZE + TILE_SIZE // 2,
				y * TILE_SIZE + TILE_SIZE // 2)

		def blocks_of(jitters):
			out = []
			for key, (x, y) in anchors.items():
				jx, jy = jitters.get(key, (0, 0))
				out.append(_block_tiles(x + jx, y + jy, art_tiles(key)))
			return out

		def foots_of(jitters):
			out = {}
			for key, (x, y) in anchors.items():
				jx, jy = jitters.get(key, (0, 0))
				out[key] = foot_of(key, x + jx, y + jy)
			return out

		def routes_of(jitters):
			routes = set()
			rx, ry0, ry1 = VILLAGE_ROAD
			for y in range(cy + ry0, cy + ry1 + 1):
				routes.add((cx + rx, y))
			for (tx, ty), (sx, sy), mode in VILLAGE_PATHS:
				key = canon_targets.get((tx, ty))
				jx, jy = jitters.get(key, (0, 0))
				t = (cx + tx + jx, cy + ty + jy)
				s = (cx + sx, cy + sy)
				routes.update(self._route_tiles(s, t, mode))
			return routes

		def clean(jitters, blocks, routes, foots=None):
			for b in range(len(blocks)):
				bx0, by0, bx1, by1 = blocks[b]
				for other in blocks[b + 1:]:
					if bx0 <= other[2] and other[0] <= bx1 \
							and by0 <= other[3] and other[1] <= by1:
						return False
			for t in routes:
				for bx0, by0, bx1, by1 in blocks:
					if bx0 <= t[0] <= bx1 and by0 <= t[1] <= by1:
						return False
				# Collision blocks the real art footprint, so a path crossing it is a dead end.
				if foots and any(t in foot for foot in foots.values()):
					return False
			return True

		# Canonical layout first; accept jitter only while routes + footprints stay clean.
		jitters = {key: (0, 0) for key in anchors}
		for key, _file, _tiles, _anchor in VILLAGE_BUILDINGS:
			jx = rng.randint(-VILLAGE_ANCHOR_JITTER, VILLAGE_ANCHOR_JITTER)
			jy = rng.randint(-VILLAGE_ANCHOR_JITTER, VILLAGE_ANCHOR_JITTER)
			if (jx, jy) == (0, 0):
				continue
			trial = dict(jitters)
			trial[key] = (jx, jy)
			trial_blocks = blocks_of(trial)
			trial_routes = routes_of(trial)
			if clean(trial, trial_blocks, trial_routes, foots_of(trial)):
				jitters = trial
		blocks = blocks_of(jitters)
		foots = foots_of(jitters)
		path_tiles = routes_of(jitters)

		# Reserve only what props must avoid: footprints, paths, plaza; gaps stay farmable.
		reserve_tiles = set(path_tiles)
		for bx0, by0, bx1, by1 in blocks:
			for x in range(bx0, bx1 + 1):
				for y in range(by0, by1 + 1):
					reserve_tiles.add((x, y))
			# Keep tall props off the facade: a canopy touching a roof reads wrong.
			clr = VILLAGE_BUILDING_CLEARANCE
			for x in range(bx0 - clr, bx1 + clr + 1):
				for y in range(by0 - clr, by1 + clr + 1):
					reserve_tiles.add((x, y))
		# Plus the art's true collision footprint, with the same clearance.
		clr = VILLAGE_BUILDING_CLEARANCE
		for foot in foots.values():
			for tx, ty in foot:
				for x in range(tx - clr, tx + clr + 1):
					for y in range(ty - clr, ty + clr + 1):
						reserve_tiles.add((x, y))
		plaza = plaza_cfg['tiles']
		plaza_span = math.ceil(plaza)
		for dx in range(-plaza_span, plaza_span + 1):
			for dy in range(-plaza_span, plaza_span + 1):
				reserve_tiles.add((cx + plaza_cfg['anchor'][0] + dx,
				                   cy + plaza_cfg['anchor'][1] + dy))


		buildings = []
		for key, fname, tiles, _anchor in VILLAGE_BUILDINGS:
			jx, jy = jitters[key]
			buildings.append({
				'key': key,
				'file': fname,
				# real on-screen width in tiles (native art, unscaled)
				'tiles': art_tiles(key),
				'anchor': (anchors[key][0] + jx, anchors[key][1] + jy),
				'block': blocks[len(buildings)],
				# Whole tiles the art covers = collision shape (support.ground_footprint_tiles).
				'foot': frozenset(foots[key]),
			})

		shop_front = (cx + 1, cy + 1)
		for b in buildings:
			if b['key'] == 'shop':
				shop_front = (b['anchor'][0] + 1, b['anchor'][1] + 1)

		home_tiles = {
			b['key']: (b['anchor'][0] + 1, b['anchor'][1] + 1)
			for b in buildings
		}

		npcs = []
		for name, home, zone in VILLAGERS:
			zx0, zy0, zx1, zy1 = zone
			spawn = (cx + (zx0 + zx1) // 2, cy + (zy0 + zy1) // 2)
			# Zone centre may sit under a building: spawn on the nearest free tile instead.
			def inside_block(tile):
				if any(bx0 <= tile[0] <= bx1 and by0 <= tile[1] <= by1
				       for bx0, by0, bx1, by1 in blocks):
					return True
				# ...or on ground the art covers (collision blocks it)
				return any(tile in foot for foot in foots.values())
			if inside_block(spawn):
				free = []
				for x in range(cx + zx0, cx + zx1 + 1):
					for y in range(cy + zy0, cy + zy1 + 1):
						if not inside_block((x, y)):
							free.append((x, y))
				free.sort(key=lambda t: (t[0] - spawn[0]) ** 2
				                      + (t[1] - spawn[1]) ** 2)
				if free:
					spawn = free[0]
			npcs.append({
				'name': name,
				'home': home,
				'home_door': home_tiles.get(home, spawn),
				'zone': (cx + zx0, cy + zy0, cx + zx1, cy + zy1),
				'spawn': spawn,
				'seed': _det_hash(cx, cy, 'villager', name, self.seed),
			})

		# Flattened land rect: everything the layout touches plus a margin, forced dry.
		pa = plaza_cfg['tiles']
		plaza_span = math.ceil(pa)
		xs = [plaza_anchor[0] - plaza_span, plaza_anchor[0]]
		ys = [plaza_anchor[1] - plaza_span, plaza_anchor[1]]
		for bx0, by0, bx1, by1 in blocks:
			xs += [bx0, bx1]
			ys += [by0, by1]
		for foot in foots.values():
			for tx, ty in foot:
				xs.append(tx)
				ys.append(ty)
		for t in path_tiles:
			xs.append(t[0])
			ys.append(t[1])
		for n in npcs:
			zx0, zy0, zx1, zy1 = n['zone']
			xs += [zx0, zx1]
			ys += [zy0, zy1]
		lx0 = min(xs) - VILLAGE_LAND_MARGIN
		ly0 = min(ys) - VILLAGE_LAND_MARGIN
		lx1 = max(xs) + VILLAGE_LAND_MARGIN
		ly1 = max(ys) + VILLAGE_LAND_MARGIN
		rm = VILLAGE_RESERVE_MARGIN
		reserve_rect = (lx0 - rm, ly0 - rm, lx1 + rm, ly1 + rm)

		return {
			'center': (cx, cy),
			'buildings': buildings,
			'plaza': {'anchor': plaza_anchor},
			'path_tiles': frozenset(path_tiles),
			'reserve_tiles': frozenset(reserve_tiles),
			'land_rect': (lx0, ly0, lx1, ly1),
			'reserve_rect': reserve_rect,
			'shop_front': shop_front,
			'quest_front': home_tiles.get('town_hall', shop_front),
			'npcs': npcs,
		}

	@staticmethod
	def _route_tiles(s, t, mode):
		"""L-shaped dirt path from s to t: 'vh' walks the column first,
		'hv' the row first (scripted per building so routes never cross
		a footprint)."""
		tiles = []
		x0, y0 = s
		x1, y1 = t
		if mode == 'hv':
			step = 1 if x1 >= x0 else -1
			for x in range(x0, x1 + step, step):
				tiles.append((x, y0))
			step = 1 if y1 >= y0 else -1
			for y in range(y0 + step, y1 + step, step):
				tiles.append((x1, y))
		else:
			step = 1 if y1 >= y0 else -1
			for y in range(y0, y1 + step, step):
				tiles.append((x0, y))
			step = 1 if x1 >= x0 else -1
			for x in range(x0 + step, x1 + step, step):
				tiles.append((x, y1))
		return tiles

	def is_trading_time(self):
		if self.time_manager is None:
			return True
		hour = self.time_manager.hour
		return (VILLAGER_ACTIVE_START_HOUR <= hour
		        < VILLAGER_ACTIVE_END_HOUR)

	def _update_villager_schedule(self):
		outside = self.is_trading_time()
		for rec in self._loaded.values():
			for npc in rec['npcs']:
				if outside:
					if npc.inside:
						npc.leave_home()
						self.all_sprites.add(npc)
				elif not npc.inside:
					npc.enter_home()
					self.all_sprites.remove(npc)

	def npc_near(self, pos, max_dist):
		"""Nearest loaded villager within max_dist world px of pos — the
		RSHIFT talk target. None when nobody is close or awake."""
		if not self.is_trading_time():
			return None
		best = None
		best_d = max_dist * max_dist
		for rec in self._loaded.values():
			for npc in rec['npcs']:
				if npc.inside:
					continue
				dx = npc.rect.centerx - pos[0]
				dy = npc.rect.centery - pos[1]
				d = dx * dx + dy * dy
				if d <= best_d:
					best = npc
					best_d = d
		return best

	# ---- LOAD / UNLOAD (sprite lifetime) ----

	def _building_art(self, key):
		base = _VILLAGE_BASE_FILES.get(key)
		if base is None:
			return None
		if self.heart_placed:
			return (self._assets.get(VILLAGE_BUILDING_AFTER.get(key, base))
			        or self._assets.get(base))
		return self._assets.get(base)

	def _load(self, key, spec):
		sprites = []
		extras = []
		npcs = []

		lx0, ly0, lx1, ly1 = spec['land_rect']
		land = {(x, y) for x in range(lx0, lx1 + 1)
		        for y in range(ly0, ly1 + 1)}
		paths = spec['path_tiles']
		self.world_gen.add_village_land(land, paths)
		# Chunks built before the village loaded may hold props on the layout: rebuild.
		self.world_gen.invalidate_chunks_in_rect(*spec['reserve_rect'])

		for b in spec['buildings']:
			art = self._building_art(b['key'])
			if not art:
				continue
			pos = tile_center(*b['anchor'])
			ax, ay = b['anchor']
			building = Building(pos, art[0], [self.all_sprites],
			                    foot_pad=art[1],
			                    building_key=b['key'])
			building.front_tiles = {
				(ax + dx, ay + dy)
				for dx, dy in structure_front_tiles(
					art[0], art[1], door=(1, 1),
					radius=STRUCTURE_FRONT_RADIUS)}
			sprites.append(building)
			# Invisible blockers that trace the authored collision mask's
			# outline (graphics/world/Collisions); the doorstep is carved
			# out so the door stays walkable.
			wx = int(pos.x)
			wy = int(pos.y)
			src = _collision_asset(self._assets, b['key']) or art
			door = pygame.Rect((ax + 1) * TILE_SIZE, (ay + 1) * TILE_SIZE,
			                   TILE_SIZE, TILE_SIZE)
			for block in structure_outline_blockers(
					src[0], src[1], wx, wy,
					step=STRUCTURE_COLLISION_STEP, hole=door):
				blocker = Generic(block.topleft, self._invisible,
				                  [self.collision_sprites], z=0)
				blocker.hitbox = block
				blocker.building_key = b['key']
				sprites.append(blocker)

		fx, fy = spec['shop_front']
		fcx = fx * TILE_SIZE + TILE_SIZE // 2
		fcy = fy * TILE_SIZE + TILE_SIZE // 2
		extras.append(Interaction((fcx - 160, fcy - 160), (320, 320),
		                          self.interaction_sprites, 'VillageShop'))

		qx, qy = spec['quest_front']
		qcx = qx * TILE_SIZE + TILE_SIZE // 2
		qcy = qy * TILE_SIZE + TILE_SIZE // 2
		extras.append(Interaction((qcx - 160, qcy - 160), (320, 320),
		                          self.interaction_sprites, 'TownHall'))

		for n in spec['npcs']:
			anims = self._villager_animations(n['name'])
			if not anims:
				continue
			zx0, zy0, zx1, zy1 = n['zone']
			zone = pygame.Rect(zx0 * TILE_SIZE, zy0 * TILE_SIZE,
			                   (zx1 - zx0 + 1) * TILE_SIZE,
			                   (zy1 - zy0 + 1) * TILE_SIZE)
			npcs.append(Villager(
				n['name'], tile_center(*n['spawn']), anims, zone,
				self.world_gen, n['seed'], [self.all_sprites],
				home_pos=tile_center(*n['home_door']),
				collision_sprites=self.collision_sprites))

		self._loaded[key] = {
			'spec': spec, 'sprites': sprites, 'extras': extras,
			'npcs': npcs, 'land': land, 'paths': paths,
		}

	def _unload(self, key):
		rec = self._loaded.pop(key, None)
		if rec is None:
			return
		for s in rec['sprites']:
			s.kill()
		for s in rec['extras']:
			s.kill()
		for n in rec['npcs']:
			n.kill()
		self.world_gen.remove_village_land(rec['land'], rec['paths'])
		# Rebuild reshaped chunks so the terrain returns to its natural state.
		self.world_gen.invalidate_chunks_in_rect(*rec['spec']['reserve_rect'])

	# ---- ASSETS ----

	def _ensure_assets(self):
		"""Load every village art file once per process, at its NATIVE pixel size -
		nothing is scaled, so the houses render exactly as drawn.
		"""
		files = [fname for _key, fname, _tiles, _anchor in VILLAGE_BUILDINGS]
		for fname in VILLAGE_BUILDING_AFTER.values():
			if fname not in files:
				files.append(fname)
		self._assets = {}
		folder = asset_path('graphics', 'Village')
		for fname in files:
			if fname not in _VILLAGE_ASSET_CACHE:
				_VILLAGE_ASSET_CACHE[fname] = self._process_art(
					os.path.join(folder, fname))
			self._assets[fname] = _VILLAGE_ASSET_CACHE[fname]
		# Authored collision masks (red on transparent): ground-footprint source of truth.
		cfolder = asset_path('graphics', 'world', 'Collisions')
		for cname in _VILLAGE_COLLISION_FILES.values():
			if cname not in _VILLAGE_ASSET_CACHE:
				_VILLAGE_ASSET_CACHE[cname] = self._process_art(
					os.path.join(cfolder, cname))
			self._assets[cname] = _VILLAGE_ASSET_CACHE[cname]

	def _process_art(self, path):
		"""Clean a village art file: strip the background and crop to the art.
		Shared across Level instances, keyed by source file name.
		"""
		try:
			surf = pygame.image.load(path).convert_alpha()
		except (pygame.error, FileNotFoundError):
			return None
		clean_sprite_background(surf)
		crop = surf.get_bounding_rect(10)
		if crop.w > 0 and crop.h > 0:
			surf = surf.subsurface(crop).copy()
		return (surf, visible_bottom_pad(surf))

	def _villager_animations(self, name):
		anims = self._villager_anims.get(name)
		if anims is not None:
			return anims or None
		folder = asset_path('graphics', 'character', 'Villagers', name)
		anims = {}
		pads = {}
		ok = True
		for d in ('Down', 'Up', 'Left', 'Right'):
			try:
				frames = import_folder(os.path.join(folder, d))
			except Exception:
				frames = []
			if not frames:
				ok = False
				break
			anims[d.lower()] = frames
			pads[d.lower()] = visible_bottom_pad(frames[0])
		if ok:
			anims['_pads'] = pads
		else:
			anims = {}
		self._villager_anims[name] = anims
		return anims or None
