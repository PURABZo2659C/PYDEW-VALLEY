import pygame
from settings import *
from support import *
from random import choice

class SoilTile(pygame.sprite.Sprite):
	def __init__(self, pos, surf, groups):
		super().__init__(groups)
		self.image = surf
		self.rect = self.image.get_rect(topleft = pos)
		self.z = LAYERS['soil']
		self.level = 0

class FarmPatch(pygame.sprite.Sprite):
	def __init__(self, pos, surf, groups, invisible=False):
		super().__init__(groups)
		if invisible:
			self.image = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
		else:
			self.image = surf
		self.rect = self.image.get_rect(topleft = pos)
		self.z = LAYERS['soil']
		self.level = 0

class WaterTile(pygame.sprite.Sprite):
	# Legacy watered-soil sprite, only for the non-iso debug view (iso uses farm_patch).
	def __init__(self, pos, surf, groups):
		super().__init__(groups)
		self.image = surf
		self.rect = self.image.get_rect(center = pos)
		self.z = LAYERS['soil water']
		self.level = 0
		self.iso_anchor = 'center'

class Plant(pygame.sprite.Sprite):
	def __init__(self, plant_type, groups, soil, check_watered, isometric=False):
		super().__init__(groups)

		# setup
		self.plant_type = plant_type
		self.frames = import_folder(asset_path('graphics', 'Growing', plant_type))
		if not self.frames:
			placeholder = pygame.Surface((32, 32), pygame.SRCALPHA)
			pygame.draw.ellipse(placeholder, (90, 160, 70), (4, 8, 24, 20))
			self.frames = [placeholder]
		self.soil = soil
		self.check_watered = check_watered
		self.isometric = isometric

		# plant growing
		self.age = 0
		self.max_age = len(self.frames) - 1
		self.grow_speed = GROW_SPEED[plant_type]
		self.harvestable = False

		# Transparent sole rows; lifted by foot_pad so the visible bottom hits the tile center.
		self._pads = [visible_bottom_pad(f) for f in self.frames]
		self.foot_pad = 0
		# 'center' anchor: image center on the tile diamond center (wheat); tomato uses bottom.
		self.iso_anchor = 'center' if plant_type == 'wheat' else 'bottom'
		self.y_anchor_offset = -16 if plant_type == 'wheat' else 0

		# sprite setup
		self.image = self.frames[self.age]
		self.y_offset = -16 if plant_type == 'wheat' else -8
		self.level = getattr(soil, 'level', 0)
		self._update_rect()
		self.z = LAYERS['ground plant']

	def _update_rect(self):
		if self.isometric:
			tile_cx = self.soil.rect.x + TILE_SIZE // 2
			tile_cy = self.soil.rect.y + TILE_SIZE // 2
			idx = min(int(self.age), self.max_age)
			if self.iso_anchor == 'center':
				# Image CENTER on tile diamond center (wheat, etc.)
				self.rect = self.image.get_rect(center = (tile_cx, tile_cy))
			else:
				# Image BOTTOM on tile diamond center, lifted by sole padding (tomato, etc.).
				self.rect = self.image.get_rect(center = (tile_cx, tile_cy))
				self.foot_pad = self._pads[idx]
		else:
			self.rect = self.image.get_rect(midbottom = self.soil.rect.midbottom + pygame.math.Vector2(0,self.y_offset))

	def grow(self):
		if self.check_watered(self.rect.center):
			self.age += self.grow_speed

			if int(self.age) > 0:
				self.z = LAYERS['main']
				self.hitbox = self.rect.copy().inflate(-26,-self.rect.height * 0.4)

			if self.age >= self.max_age:
				self.age = self.max_age
				self.harvestable = True

			self.image = self.frames[int(self.age)]
			self._update_rect()

class SoilLayer:
	def __init__(self, all_sprites, collision_sprites, world_gen=None):

		# sprite groups
		self.all_sprites = all_sprites
		self.collision_sprites = collision_sprites
		self.soil_sprites = pygame.sprite.Group()
		self.water_sprites = pygame.sprite.Group()
		self.plant_sprites = pygame.sprite.Group()
		self.world_gen = world_gen
		self.time_manager = None
		self.tilled_at = {}
		self.raining = False

		# Isometric mode flag
		self.isometric_mode = True

		# Grid offsets: grid[0][0] corresponds to world grid (ox, oy)
		self._grid_ox = 0
		self._grid_oy = 0

		# graphics
		self.soil_surfs = self._load_soil_surfs()
		self.water_surfs = self._load_water_surfs()

		# Farm patch tile
		try:
			farm_patch = pygame.image.load(asset_path('graphics', 'world', 'farm_patch.png')).convert_alpha()
			self.farm_patch_surf = pygame.transform.smoothscale(farm_patch, (TILE_SIZE, TILE_SIZE))
		except Exception as exc:  # missing art: fall back, but say why
			print(f"[Soil] farm_patch.png load failed, using solid tile: {exc!r}")
			surf = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
			surf.fill((195, 165, 125))
			self.farm_patch_surf = surf

		self.create_soil_grid()
		self.create_hit_rects()

		# sounds
		self.hoe_sound = pygame.mixer.Sound(asset_path('audio', 'hoe.wav'))
		self.hoe_sound.set_volume(0.1)

		self.plant_sound = pygame.mixer.Sound(asset_path('audio', 'plant.wav')) 
		self.plant_sound.set_volume(0.2)

	def _load_soil_surfs(self):
		"""Tilled-soil frames keyed by edge-variant tile_type.
		There is no dedicated soil folder: the single farm patch tile is reused
		for every variant.
		"""
		keys = ('o', 'x', 'r', 'l', 'lr', 'b', 't', 'tb', 'tr', 'tl',
				'br', 'bl', 'tbr', 'tbl', 'lrb', 'lrt')
		try:
			farm = pygame.image.load(asset_path('graphics', 'world', 'farm_patch.png')).convert_alpha()
			farm = pygame.transform.smoothscale(farm, (TILE_SIZE, TILE_SIZE))
		except Exception as exc:  # missing art: solid fallback, but say why
			print(f"[Soil] farm_patch.png load failed, using solid tile: {exc!r}")
			farm = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
			farm.fill((195, 165, 125, 255))
		return {key: farm for key in keys}

	def _load_water_surfs(self):
		"""Watered-soil overlay frame (single PNG, no folder).
		Authored like the other ground tiles, so it blits flush on the tile.
		"""
		try:
			water = pygame.image.load(asset_path('graphics', 'world', 'soil_water.png')).convert_alpha()
			return [pygame.transform.smoothscale(water, (ISO_TILE_WIDTH, ISO_TILE_WIDTH))]
		except Exception as exc:  # missing art: flat fallback, but say why
			print(f"[Soil] soil_water.png load failed, using flat overlay: {exc!r}")
			water = pygame.Surface((ISO_TILE_WIDTH, ISO_TILE_HEIGHT), pygame.SRCALPHA)
			pygame.draw.ellipse(water, (90, 140, 220, 180), water.get_rect())
			return [water]

	def create_soil_grid(self):
		tmx_map = load_map(asset_path('data', 'map.tmx'))
		h_tiles, v_tiles = tmx_map.width, tmx_map.height

		self.grid = [[[] for col in range(h_tiles)] for row in range(v_tiles)]
		for x, y, _ in tmx_map.get_layer_by_name('Farmable').tiles():
			# Extend grid if TMX coordinates exceed grid size (due to tile size change)
			while len(self.grid) <= y:
				self.grid.append([[] for _ in range(len(self.grid[0]) if self.grid else 0)])
			if self.grid and x >= len(self.grid[0]):
				for row in self.grid:
					while len(row) <= x:
						row.append([])
			self.grid[y][x].append('F')

	def create_hit_rects(self):
		self.hit_rects = []
		for index_row, row in enumerate(self.grid):
			for index_col, cell in enumerate(row):
				if 'F' in cell:
					x = (index_col + self._grid_ox) * TILE_SIZE
					y = (index_row + self._grid_oy) * TILE_SIZE
					rect = pygame.Rect(x,y,TILE_SIZE, TILE_SIZE)
					self.hit_rects.append(rect)

	def _ensure_grid(self, gx, gy):
		"""Extend the 2D grid so that world grid coords (gx, gy) are accessible."""
		ax = gx - self._grid_ox
		ay = gy - self._grid_oy
		cols = len(self.grid[0]) if self.grid else 0
		# Extend upward (negative y)
		while ay < 0:
			self.grid.insert(0, [[] for _ in range(cols)])
			self._grid_oy -= 1
			ay += 1
		# Extend downward (positive y)
		while ay >= len(self.grid):
			self.grid.append([[] for _ in range(cols)])
		# Extend leftward (negative x)
		while ax < 0:
			for row in self.grid:
				row.insert(0, [])
			self._grid_ox -= 1
			ax += 1
		# Extend rightward (positive x)
		while ax >= len(self.grid[0]):
			for row in self.grid:
				row.append([])

	def _cell(self, gx, gy):
		"""Get the cell list at world grid coords (gx, gy), extending if needed."""
		self._ensure_grid(gx, gy)
		return self.grid[gy - self._grid_oy][gx - self._grid_ox]

	def _has_cell(self, gx, gy):
		"""Check if world grid coords (gx, gy) are within the current grid bounds."""
		ax = gx - self._grid_ox
		ay = gy - self._grid_oy
		return 0 <= ay < len(self.grid) and 0 <= ax < len(self.grid[0])

	def _now_minutes(self):
		return float(getattr(self.time_manager, 'total_minutes', 0.0))

	def get_hit(self, point):
		x = int(point[0]) // TILE_SIZE
		y = int(point[1]) // TILE_SIZE

		cell = self._cell(x, y)

		if 'X' in cell:
			return

		if self.world_gen and self.world_gen.is_water_at(x, y):
			return

		# Don't farm if an object (tree, rock, bush, bed, flower) occupies this tile
		tile_rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
		if self.world_gen:
			for sprite in self.world_gen.tree_sprites.sprites():
				if sprite.rect.colliderect(tile_rect):
					return
			for sprite in self.world_gen.rock_sprites.sprites():
				if sprite.rect.colliderect(tile_rect):
					return
			for sprite in self.world_gen.bush_sprites.sprites():
				if sprite.rect.colliderect(tile_rect):
					return
			for sprite in self.world_gen.flower_sprites.sprites():
				if sprite.rect.colliderect(tile_rect):
					return

		self.hoe_sound.play()

		if 'F' not in cell:
			cell.append('F')
		cell.append('X')
		self.tilled_at[(x, y)] = self._now_minutes()

		rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
		self.hit_rects.append(rect)

		# Add farm patch sprite on the tile (invisible, for planting collision only)
		farm = FarmPatch(
			pos = (x * TILE_SIZE, y * TILE_SIZE),
			surf = self.farm_patch_surf,
			groups = [self.all_sprites, self.soil_sprites],
			invisible = self.isometric_mode)
		if self.world_gen:
			farm.level = self.world_gen.height_at(x, y)

		# Replace ground tile with farm patch on chunk surface
		if self.isometric_mode and self.world_gen:
			self.world_gen.set_farm_patch(x * TILE_SIZE, y * TILE_SIZE)

		if self.raining:
			self.water_all()

	def water(self, target_pos):
		x = int(target_pos[0]) // TILE_SIZE
		y = int(target_pos[1]) // TILE_SIZE

		if not self._has_cell(x, y):
			return False

		cell = self._cell(x, y)

		if 'X' not in cell:
			return False

		if 'W' in cell:
			return False

		cell.append('W')

		if self.isometric_mode and self.world_gen:
			# watered-soil overlay through the farm_patch pipeline
			self.world_gen.set_soil_water(x * TILE_SIZE, y * TILE_SIZE)
			return True

		# legacy tile-sprite fallback (non-iso debug view)
		for soil_sprite in self.soil_sprites.sprites():
			sx = soil_sprite.rect.x // TILE_SIZE
			sy = soil_sprite.rect.y // TILE_SIZE
			if sx == x and sy == y:
				pos = (soil_sprite.rect.x + TILE_SIZE // 2, soil_sprite.rect.y + TILE_SIZE // 2)
				surf = choice(self.water_surfs)
				wt = WaterTile(pos, surf, [self.all_sprites, self.water_sprites])
				wt.level = soil_sprite.level
				return True
		return True

	def water_all(self):
		use_overlay = self.isometric_mode and self.world_gen
		for index_row, row in enumerate(self.grid):
			for index_col, cell in enumerate(row):
				if 'X' not in cell or 'W' in cell:
					continue
				cell.append('W')
				if use_overlay:
					x = (index_col + self._grid_ox) * TILE_SIZE
					y = (index_row + self._grid_oy) * TILE_SIZE
					self.world_gen.set_soil_water(x, y)

	def remove_water(self):
		if self.isometric_mode and self.world_gen:
			self.world_gen.clear_soil_water()

		# destroy any leftover water sprites (legacy non-iso view)
		for sprite in self.water_sprites.sprites():
			sprite.kill()

		# clean up the grid
		for row in self.grid:
			for cell in row:
				if 'W' in cell:
					cell.remove('W')

	def check_watered(self, pos):
		x = pos[0] // TILE_SIZE
		y = pos[1] // TILE_SIZE
		if not self._has_cell(x, y):
			return False
		cell = self._cell(x, y)
		is_watered = 'W' in cell
		return is_watered

	def ensure_plant_anchor(self, gx, gy):
		"""Return a logical soil sprite for a tile, creating one on load."""
		for soil_sprite in self.soil_sprites.sprites():
			if (soil_sprite.rect.x // TILE_SIZE == gx
			    and soil_sprite.rect.y // TILE_SIZE == gy):
				return soil_sprite
		anchor = pygame.sprite.Sprite()
		anchor.rect = pygame.Rect(
			gx * TILE_SIZE, gy * TILE_SIZE, TILE_SIZE, TILE_SIZE)
		anchor.level = 0
		self.soil_sprites.add(anchor)
		return anchor

	def plant_seed(self, target_pos, seed):
		x = int(target_pos[0]) // TILE_SIZE
		y = int(target_pos[1]) // TILE_SIZE

		if not self._has_cell(x, y):
			return False

		cell = self._cell(x, y)

		if 'X' not in cell:
			return False

		if 'P' in cell:
			return False

		soil_sprite = self.ensure_plant_anchor(x, y)
		self.plant_sound.play()
		cell.append('P')
		self.tilled_at[(x, y)] = self._now_minutes()
		Plant(seed, [self.all_sprites, self.plant_sprites,
		             self.collision_sprites], soil_sprite,
		      self.check_watered, self.isometric_mode)
		return True

	def plant_at_tile(self, gx, gy):
		for plant in self.plant_sprites.sprites():
			soil = getattr(plant, 'soil', None)
			if soil is None:
				continue
			if (soil.rect.x // TILE_SIZE == gx
			    and soil.rect.y // TILE_SIZE == gy):
				return plant
		return None

	def harvestable_plant_at(self, point):
		gx = int(point[0]) // TILE_SIZE
		gy = int(point[1]) // TILE_SIZE
		if not self._has_cell(gx, gy):
			return None
		if 'P' not in self._cell(gx, gy):
			return None
		plant = self.plant_at_tile(gx, gy)
		if plant is not None and plant.harvestable:
			return plant
		return None

	def remove_plant(self, plant):
		soil = getattr(plant, 'soil', None)
		if soil is not None:
			gx = soil.rect.x // TILE_SIZE
			gy = soil.rect.y // TILE_SIZE
			if self._has_cell(gx, gy):
				cell = self._cell(gx, gy)
				if 'P' in cell:
					cell.remove('P')
				self.tilled_at[(gx, gy)] = self._now_minutes()
		plant.kill()

	def clear_tile(self, gx, gy):
		"""Revert one tilled tile to plain farmable ground."""
		if self._has_cell(gx, gy):
			cell = self._cell(gx, gy)
			for flag in ('X', 'W'):
				while flag in cell:
					cell.remove(flag)

		for sprite in list(self.soil_sprites.sprites()):
			if (sprite.rect.x // TILE_SIZE == gx
			    and sprite.rect.y // TILE_SIZE == gy):
				sprite.kill()
		for sprite in list(self.water_sprites.sprites()):
			if (sprite.rect.centerx // TILE_SIZE == gx
			    and sprite.rect.centery // TILE_SIZE == gy):
				sprite.kill()

		self.hit_rects = [
			rect for rect in self.hit_rects
			if not (rect.x // TILE_SIZE == gx
			        and rect.y // TILE_SIZE == gy)
		]

		if self.world_gen:
			x = gx * TILE_SIZE
			y = gy * TILE_SIZE
			self.world_gen.clear_farm_patch(x, y)
			self.world_gen.clear_soil_water_at(x, y)

	def update_farmland(self, now=None):
		"""Expire empty tilled tiles after FARMLAND_EMPTY_MINUTES."""
		if now is None:
			now = self._now_minutes()
		now = float(now)
		for key, tilled in list(self.tilled_at.items()):
			gx, gy = key
			if not self._has_cell(gx, gy):
				self.tilled_at.pop(key, None)
				continue
			cell = self._cell(gx, gy)
			if 'X' not in cell:
				self.tilled_at.pop(key, None)
				continue
			if 'P' in cell:
				continue
			if now - float(tilled) < FARMLAND_EMPTY_MINUTES:
				continue
			self.clear_tile(gx, gy)
			self.tilled_at.pop(key, None)

	def serialize_tilled_at(self):
		return [[gx, gy, round(float(tilled), 3)]
		        for (gx, gy), tilled in sorted(self.tilled_at.items())]

	def restore_tilled_at(self, entries, now=None):
		if now is None:
			now = self._now_minutes()
		now = float(now)
		self.tilled_at = {}
		for entry in entries or ():
			try:
				gx, gy, tilled = entry
				key = (int(gx), int(gy))
				value = float(tilled)
			except (TypeError, ValueError):
				continue
			if self._has_cell(*key) and 'X' in self._cell(*key):
				self.tilled_at[key] = value
		# Old saves have no timestamps: start their expiry clock now.
		for row_index, row in enumerate(self.grid):
			for col_index, cell in enumerate(row):
				if 'X' not in cell:
					continue
				gx = col_index + self._grid_ox
				gy = row_index + self._grid_oy
				self.tilled_at.setdefault((gx, gy), now)

	def update_plants(self):
		for plant in self.plant_sprites.sprites():
			plant.grow()

	def create_soil_tiles(self):
		self.soil_sprites.empty()
		if self.isometric_mode:
			return

		for index_row, row in enumerate(self.grid):
			for index_col, cell in enumerate(row):
				if 'X' in cell:
					t = index_row > 0 and 'X' in self.grid[index_row - 1][index_col]
					b = index_row < len(self.grid) - 1 and 'X' in self.grid[index_row + 1][index_col]
					r = index_col < len(row) - 1 and 'X' in row[index_col + 1]
					l = index_col > 0 and 'X' in row[index_col - 1]

					tile_type = 'o'

					if all((t,r,b,l)): tile_type = 'x'
					if l and not any((t,r,b)): tile_type = 'r'
					if r and not any((t,l,b)): tile_type = 'l'
					if r and l and not any((t,b)): tile_type = 'lr'
					if t and not any((r,l,b)): tile_type = 'b'
					if b and not any((r,l,t)): tile_type = 't'
					if b and t and not any((r,l)): tile_type = 'tb'
					if l and b and not any((t,r)): tile_type = 'tr'
					if r and b and not any((t,l)): tile_type = 'tl'
					if l and t and not any((b,r)): tile_type = 'br'
					if r and t and not any((b,l)): tile_type = 'bl'
					if all((t,b,r)) and not l: tile_type = 'tbr'
					if all((t,b,l)) and not r: tile_type = 'tbl'
					if all((l,r,t)) and not b: tile_type = 'lrb'
					if all((l,r,b)) and not t: tile_type = 'lrt'

					SoilTile(
						pos = (index_col * TILE_SIZE,index_row * TILE_SIZE),
						surf = self.soil_surfs[tile_type],
						groups = [self.all_sprites, self.soil_sprites])