import math
import os
import pygame
from settings import *
from support import import_folder, log_once
from world_generator import PerlinNoise, white_noise
from sprites import Rock, Ore, Crate, Pot


class CaveGenerator:
	"""Terrain for the cave world space - a FLAT plane where everything that
	is not land is lava. Land comes from one Perlin band around 0.5.
	"""

	def __init__(self, all_sprites=None, collision_sprites=None,
	             interaction_sprites=None, player_add=None, prop_sprites=None,
	             decor_sprites=None, seed=None):
		self.all_sprites = all_sprites
		self.collision_sprites = collision_sprites
		self.interaction_sprites = interaction_sprites
		self.player_add = player_add
		self.prop_sprites = prop_sprites if prop_sprites is not None else pygame.sprite.Group()
		self.decor_sprites = decor_sprites if decor_sprites is not None else pygame.sprite.Group()
		self.seed = WORLD_SEED if seed is None else seed
		# Kept for interface parity with WorldGenerator (the cave has no
		# chunk-placed sprites yet - ground is emitted per tile on demand).
		self.active_chunks = {}

		self.perlin_shape = PerlinNoise(seed=self.seed + 900)

		self._lava_cache = {}
		self._lava_phase = {}
		self._ground_variant_cache = {}
		self._surf_bounds = {}

		# Cave props (rocks / ore veins / decorations): session state.
		# Deterministic per tile; the ones the player mined stay mined.
		self._placed = {}        # (gx, gy) -> sprite (alive, in groups)
		self._mined = set()      # tiles whose prop was destroyed
		self._prop_center = None
		# Incremented on every cave entry so ores/rocks/decor roll a fresh layout
		# instead of replaying the same deterministic tiles.
		self._entry_nonce = 0

		self._load_assets()
		self._calibrate_band()

	# ---- ASSETS ----

	def _load_assets(self):
		self.ground_pool = self._load_ground_pool()
		self.lava_frames = self._load_lava_frames()
		self._load_prop_assets()

	def _load_folder_named(self, *parts):
		"""[(stem_lower, surf)] for every .png in a graphics folder,
		sorted by filename so variant indices are deterministic."""
		folder = asset_path('graphics', *parts)
		try:
			names = sorted(os.listdir(folder))
		except OSError:
			return []
		out = []
		for name in names:
			if not name.lower().endswith('.png'):
				continue
			try:
				surf = pygame.image.load(os.path.join(folder, name)).convert_alpha()
			except pygame.error:
				continue
			out.append((os.path.splitext(name)[0].lower(), surf))
		return out

	def _load_prop_assets(self):
		"""Ore vein art keyed by item name, plus the rock and decoration pools.
		'loaded' crates can yield an ore, 'pot' is a punch pickup.
		"""
		self.ore_surfs = dict(self._load_folder_named('Caves', 'Ores'))
		self.rock_surfs = [s for _n, s in self._load_folder_named('Caves', 'Rocks')]
		# 'double crates' (the small empty crate pair) is retired - filtered out
		# so the art file stays but never spawns.
		self.decor_entries = [e for e in
			self._load_folder_named('Caves', 'decorations')
			if e[0] != 'double crates']

	def _load_ground_pool(self):
		"""Cave ground cubes (graphics/Caves/ground/), numeric order."""
		pool = []
		try:
			pool = import_folder(asset_path('graphics', 'Caves', 'ground'))
		except (pygame.error, FileNotFoundError):
			pool = []
		scaled = []
		for surf in pool:
			if surf.get_size() != (ISO_TILE_WIDTH, ISO_TILE_WIDTH):
				surf = pygame.transform.scale(surf, (ISO_TILE_WIDTH, ISO_TILE_WIDTH))
			scaled.append(surf)
		if not scaled:
			scaled = [self._fallback_cube((168, 124, 84), (140, 98, 64), (196, 152, 108))]
		return scaled

	def _load_lava_frames(self):
		"""Animated lava tiles (graphics/Caves/lava/), drawn raw and
		hollow — placed exactly like normal tile tops, nothing added."""
		frames = []
		try:
			frames = import_folder(asset_path('graphics', 'Caves', 'lava'))
		except (pygame.error, FileNotFoundError):
			frames = []
		scaled = []
		for surf in frames:
			if surf.get_size() != (ISO_TILE_WIDTH, ISO_TILE_WIDTH):
				surf = pygame.transform.scale(surf, (ISO_TILE_WIDTH, ISO_TILE_WIDTH))
			scaled.append(surf)
		if not scaled:
			scaled = [self._fallback_cube((230, 70, 30), (190, 45, 20), (255, 110, 40))]
		return scaled

	def _fallback_cube(self, left, right, top):
		"""Procedural iso cube if art is missing: top diamond 128x64."""
		s = pygame.Surface((ISO_TILE_WIDTH, ISO_TILE_WIDTH), pygame.SRCALPHA)
		hw, hh = ISO_TILE_WIDTH // 2, ISO_TILE_HEIGHT // 2
		pygame.draw.polygon(s, left, [(0, hh), (hw, ISO_TILE_HEIGHT),
		                              (hw, hh + ISO_TILE_HEIGHT), (0, hh + hh)])
		pygame.draw.polygon(s, right, [(hw, ISO_TILE_HEIGHT), (ISO_TILE_WIDTH, hh),
		                               (ISO_TILE_WIDTH, hh + hh), (hw, hh + ISO_TILE_HEIGHT)])
		pygame.draw.polygon(s, top, [(hw, 0), (ISO_TILE_WIDTH, hh),
		                             (hw, ISO_TILE_HEIGHT), (0, hh)])
		return s

	# ---- SHAPE BAND (50% land / 50% lava, calibrated from quantiles) ----

	def _shape_value(self, gx, gy):
		return self.perlin_shape.fractal(
			gx, gy,
			octaves=CAVE_NOISE_OCTAVES,
			persistence=NOISE_PERSISTENCE,
			lacunarity=NOISE_LACUNARITY,
			scale=CAVE_NOISE_SCALE)

	def _calibrate_band(self):
		"""Land stays where the shape value lies inside [p25, p75] of the noise's
		distribution - by construction ~50% of tiles, symmetric around 0.5.
		"""
		samples = []
		for gy in range(0, 96, 2):
			for gx in range(0, 96, 2):
				samples.append(self._shape_value(gx, gy))
		samples.sort()
		n = len(samples)
		self.band_lo = samples[n // 4]
		self.band_hi = samples[(3 * n) // 4]

	def _is_lava_shape(self, gx, gy):
		"""Cached: does this tile belong to the lava fill? (Band-out of
		the shape noise, or outside the world — the exit pad always
		overrides to land.)"""
		key = (gx, gy)
		if key in self._lava_cache:
			return self._lava_cache[key]
		ex, ey = CAVE_EXIT_TILE
		if max(abs(gx - ex), abs(gy - ey)) <= CAVE_EXIT_PAD_RADIUS:
			lava = False
		elif gx < 0 or gy < 0:
			lava = True
		else:
			v = self._shape_value(gx, gy)
			lava = v < self.band_lo or v > self.band_hi
		self._lava_cache[key] = lava
		return lava

	def height_at(self, gx, gy):
		"""FLAT cave: 0 everywhere. Water is decided by is_water_at;
		kept for the shared movement/debug interface."""
		return 0

	def is_void_at(self, gx, gy):
		"""Void no longer exists — outside the world is lava, so this is
		always False (kept for duck-typing compatibility)."""
		return False

	def is_lava_at(self, gx, gy):
		"""True for the lava fill — the fluid plane tiles."""
		return self._is_lava_shape(gx, gy)

	def is_water_at(self, gx, gy):
		"""Lava plays the water role in every shared code path (target
		blocking, bucket checks, dry-spawn scans): True on lava tiles."""
		return self._is_lava_shape(gx, gy)

	def is_point_in_water(self, wx, wy):
		return self.is_water_at(int(wx) // TILE_SIZE, int(wy) // TILE_SIZE)

	# ---- DEBUG-PANEL / SNOW-CHECK SHIMS ----

	def get_terrain_type(self, gx, gy):
		if self._is_lava_shape(gx, gy):
			return 'lava'
		return 'cave'

	def biome_at(self, gx, gy):
		return 'Cave'

	# ---- GROUND TILES ----

	def _ground_variant(self, gx, gy):
		"""Deterministic per-tile index into the cave ground pool.
		Blue-noise: a tile is decorated only when its roll beats its 4
		neighbours, so no two decorated tiles share an edge.
		"""
		count = len(self.ground_pool)
		if count <= 1:
			return 0
		cached = self._ground_variant_cache.get((gx, gy))
		if cached is not None:
			return cached
		r = white_noise(gx, gy, seed=self.seed + 901)
		for nx, ny in ((gx - 1, gy), (gx + 1, gy),
				(gx, gy - 1), (gx, gy + 1)):
			if white_noise(nx, ny, seed=self.seed + 901) >= r:
				v = count - 1
				break
		else:
			v = min(count - 2,
				int(white_noise(gx, gy, seed=self.seed + 902)
					* (count - 1)))
		self._ground_variant_cache[(gx, gy)] = v
		return v

	def _top_cube(self, gidx):
		"""This tile's cave ground art, used AS-IS.
		Every variant is already a full iso cube, so there is no base to composite
		onto.
		"""
		return self.ground_pool[gidx % len(self.ground_pool)]

	def _content_bounds(self, surf):
		"""Minimal src rect covering a surface's non-transparent pixels."""
		b = self._surf_bounds.get(surf)
		if b is None:
			b = surf.get_bounding_rect()
			if b.w <= 0 or b.h <= 0:
				b = surf.get_rect()
			self._surf_bounds[surf] = b
		return b

	# ---- RENDERING (same contract as WorldGenerator's iso ground pass) ----

	def iter_ground_entries(self, sw, sh, ox, oy):
		"""Yield every visible cave ground piece for the painter pass.
		The lava art pitches down its box so it reads as a recessed plane.
		"""
		half_w = ISO_TILE_WIDTH // 2
		half_h = ISO_TILE_HEIGHT // 2
		pad = ISO_TILE_WIDTH
		sunk = WATER_SUNK_OFFSET

		lava_frames = self.lava_frames
		lava_count = len(lava_frames)
		now_ms = pygame.time.get_ticks()
		# One bounds rect per frame (frames can differ by a pixel).
		lava_bounds = [self._content_bounds(f) for f in lava_frames]

		u0 = (ox - pad) // half_w
		u1 = (ox + sw + pad) // half_w
		v0 = (oy - pad) // half_h
		v1 = (oy + sh + pad) // half_h

		bounds = self._content_bounds
		is_lava = self._is_lava_shape

		for v in range(v0, v1 + 1):
			u = u0 + ((v - u0) & 1)
			for u2 in range(u, u1 + 1, 2):
				gx = (v + u2) // 2
				gy = (v - u2) // 2
				iso_x = u2 * half_w
				iso_y = v * half_h
				dx = iso_x - ox
				if dx <= -pad or dx >= sw:
					continue
				dy = iso_y - oy

				ray = v * 128 + 128

				if is_lava(gx, gy):
					# Lava fill drawn raw and hollow, like the overworld's water plane.
					# Each tile runs its own phase, so the ocean bubbles out of lockstep.
					if dy >= sh or dy + pad <= 0:
						continue
					key = (gx, gy)
					phase = self._lava_phase.get(key)
					if phase is None:
						phase = int(white_noise(gx, gy, self.seed + 925)
						            * lava_count * 500)
						self._lava_phase[key] = phase
					idx = ((now_ms + phase) * 2 // 1000) % lava_count
					yield (ray, 0.0, lava_frames[idx], dx, dy, lava_bounds[idx])
					continue

				if dy >= sh or dy + pad <= 0:
					continue

				top_cube = self._top_cube(self._ground_variant(gx, gy))
				yield (ray, 0.0, top_cube, dx, dy, bounds(top_cube))

	def draw_ground(self, display_surface, camera_offset, isometric=False):
		"""Black backdrop — the cave's ground is emitted per tile by
		iter_ground_entries in Level.custom_draw's painter pass."""
		display_surface.fill((0, 0, 0))

	# ---- PROPS (rocks, ore veins, decorations) ----

	def update(self, player_pos, isometric=True):
		"""Stream cave props around the player: place what is inside the keep
		radius and not yet placed or mined, despawn what is left far behind.
		"""
		pgx = int(player_pos.x) // TILE_SIZE
		pgy = int(player_pos.y) // TILE_SIZE
		if (pgx, pgy) == self._prop_center:
			return
		self._prop_center = (pgx, pgy)
		self._stream_props(pgx, pgy)

	def _stream_props(self, pcx, pcy):
		# Retire props the player destroyed since the last pass.
		for key, spr in list(self._placed.items()):
			if not getattr(spr, 'alive', True):
				self._mined.add(key)
				del self._placed[key]
		# Despawn props left far behind (they respawn unchanged later).
		unload = CAVE_PROP_RADIUS + CAVE_PROP_UNLOAD
		for key in [k for k in self._placed
		            if abs(k[0] - pcx) > unload or abs(k[1] - pcy) > unload]:
			self._placed.pop(key).kill()
		# Place everything in the keep radius.
		r = CAVE_PROP_RADIUS
		for gy in range(pcy - r, pcy + r + 1):
			for gx in range(pcx - r, pcx + r + 1):
				key = (gx, gy)
				if key in self._placed or key in self._mined:
					continue
				spec = self._tile_prop(gx, gy)
				if spec is None:
					continue
				spr = self._spawn_prop(gx, gy, spec)
				if spr is not None:
					self._placed[key] = spr

	def _tile_prop(self, gx, gy):
		"""Deterministic prop for a land tile: ('ore', item) | ('rock',
		idx) | ('decor', idx) | None. Lava tiles and the cleared ring
		around the exit stay bare. One prop max per tile."""
		if self._is_lava_shape(gx, gy):
			return None
		ex, ey = CAVE_EXIT_TILE
		if max(abs(gx - ex), abs(gy - ey)) <= CAVE_EXIT_PAD_RADIUS + 1:
			return None
		base = self.seed + self._entry_nonce * 104729
		roll = white_noise(gx, gy, base + 921)
		if roll < CAVE_ORE_CHANCE:
			if not self.ore_surfs:
				return None
			item = self._ore_for_depth(
				math.hypot(gx - ex, gy - ey),
				white_noise(gx, gy, base + 922))
			if item is None or item not in self.ore_surfs:
				return None
			return ('ore', item)
		if roll < CAVE_ORE_CHANCE + CAVE_ROCK_CHANCE:
			if not self.rock_surfs:
				return None
			idx = int(white_noise(gx, gy, base + 923) * len(self.rock_surfs))
			return ('rock', min(idx, len(self.rock_surfs) - 1))
		if roll < CAVE_ORE_CHANCE + CAVE_ROCK_CHANCE + CAVE_DECOR_CHANCE:
			if not self.decor_entries:
				return None
			idx = int(white_noise(gx, gy, base + 924) * len(self.decor_entries))
			return ('decor', min(idx, len(self.decor_entries) - 1))
		return None

	def _ore_for_depth(self, depth, t):
		"""Weighted ore pick for a tile `depth` tiles from the exit. A rare ore's
		weight fades in across its ramp, so coal and copper dominate near the
		lift and gems only appear far out. `t` is the caller's roll in [0, 1).
		"""
		weights = []
		total = 0.0
		for item, w_near, w_deep, d0, d1, _hits, _lo, _hi in CAVE_ORES:
			if d1 > d0:
				f = min(1.0, max(0.0, (depth - d0) / (d1 - d0)))
			else:
				f = 1.0
			w = w_near + (w_deep - w_near) * f
			weights.append((item, w))
			total += w
		if total <= 0:
			return None
		pick = t * total
		for item, w in weights:
			pick -= w
			if pick <= 0:
				return item
		return weights[-1][0]

	def _spawn_prop(self, gx, gy, spec):
		wx = gx * TILE_SIZE + TILE_SIZE // 2
		wy = gy * TILE_SIZE + TILE_SIZE // 2
		kind, arg = spec
		if kind == 'ore':
			surf = self.ore_surfs.get(arg)
			if surf is None:
				return None
			row = next(r for r in CAVE_ORES if r[0] == arg)
			hits, lo, hi = row[5], row[6], row[7]
			return Ore(
				pos = (wx, wy), surf = surf,
				groups = [self.all_sprites, self.collision_sprites, self.prop_sprites],
				player_add = self.player_add,
				item = CAVE_ORE_DROPS.get(arg, arg), health = hits, drop = (lo, hi))
		if kind == 'rock':
			return Rock(
				pos = (wx, wy), surf = self.rock_surfs[arg],
				groups = [self.all_sprites, self.collision_sprites, self.prop_sprites],
				player_add = self.player_add)
		# Decorations: solid scenery. Crates/shelves are cut with the axe (loaded
		# ones can yield an ore); pots are punched for pickup.
		stem, surf = self.decor_entries[arg]
		groups = [self.all_sprites, self.collision_sprites, self.decor_sprites]
		if 'pot' in stem:
			return Pot(
				pos = (wx, wy), surf = surf, groups = groups,
				player_add = self.player_add)
		loaded = 'loaded' in stem or 'shelf' in stem
		return Crate(
			pos = (wx, wy), surf = surf, groups = groups,
			player_add = self.player_add,
			health = CAVE_CRATE_HEALTH, loaded = loaded)

	# ---- LIFECYCLE (interface parity; no chunk sprites yet) ----

	def init(self, player_pos, isometric=True):
		pass

	def reset_props(self):
		"""Cave entry reset: clear mined state and reroll prop placement, so every
		visit has a fresh set of ores, rocks and decorations.
		"""
		for spr in list(self._placed.values()):
			try:
				spr.kill()
			except Exception as exc:  # teardown of an already-dead sprite
				log_once('[Cave] prop kill failed', exc)
		self._placed = {}
		self._mined = set()
		self._prop_center = None
		self._entry_nonce += 1

	def reset(self):
		self._lava_cache = {}
		self._lava_phase = {}
		self._ground_variant_cache = {}
