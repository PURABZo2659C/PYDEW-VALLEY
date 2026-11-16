import pygame
import time
from settings import *
from support import *
from timer import Timer
from sprites import Generic, PlaceableBed, PlaceableBridge, can_store
from inventory_model import (
	Inventory, HotbarView, SEED_ITEMS, crop_type_for_seed,
	HOTBAR_SIZE, MAIN_START, SLOT_COUNT,
)
import input_manager

class Player(pygame.sprite.Sprite):
	def __init__(self, pos, group, collision_sprites, tree_sprites, rock_sprites, bush_sprites, flower_sprites, bed_sprites, interaction, soil_layer, toggle_shop, try_sleep, toggle_crafting, toggle_inventory, level):
		super().__init__(group)

		self.import_assets()
		self.status = 'down'
		self.frame_index = 0

		# general setup
		self.image = self.animations[self.status][self.frame_index]
		self.rect = self.image.get_rect(center = pos)
		self.z = LAYERS['main']

		# movement attributes
		self.direction = pygame.math.Vector2()
		self.pos = pygame.math.Vector2(self.rect.center)
		self.base_speed = 400
		self.speed = self.base_speed
		self.target_grid = None
		self.target_object = None
		# Frames are 172x124 with 24px transparent sole padding; the iso renderer lifts by it.
		self.foot_pad = 24

		# collision
		self.hitbox = self.rect.copy().inflate((-126,-70))
		self.collision_sprites = collision_sprites
		# Rebuilt when the player changes tile; the old code rescanned the chunk ring per frame.
		self._collider_cache = None
		self.world_direction = pygame.math.Vector2(0, 0)
		# True while a UI text box owns the keyboard, blocking movement and tool swings.
		self.input_locked = False
		# Flat world: level stays 0 everywhere (kept for the depth-sort interface).
		self.level = 0

		# timers 
		self.timers = {
			'tool use': Timer(350,self.use_tool),
			'water bucket': Timer(600,self.use_water_bucket),
			# 'punch' only gates the animation; the hit fires on 'punch impact'.
			'punch': Timer(300),
			'punch impact': Timer(300,self.use_punch),
			'interact': Timer(400),
		}

		# unified hotbar: tools + seeds (stick is craft-only, not a tool)
		self.tools = ['hoe', 'axe', 'pickaxe', 'water_bucket']
		self.seeds = list(SEED_ITEMS)

		self.inventory = Inventory()
		self.completed_quests = set()
		self.heart_placed = False
		self.credits_seen = False
		self.water_bucket_amount = 0
		self._use_tool_was_pressed = False
		self._use_item_was_pressed = False
		self._inventory_was_pressed = False
		self.potion_effects = {}
		self.money = 200
		self.energy = 100.0
		self.max_energy = 100.0

		# inventory and hotbar start empty on a fresh game
		self.hotbar_index = 0
		self.selected_tool = self.tools[0]
		self.selected_seed = None

		# interaction
		self.tree_sprites = tree_sprites
		self.rock_sprites = rock_sprites
		self.bush_sprites = bush_sprites
		self.flower_sprites = flower_sprites
		self.bed_sprites = bed_sprites
		# Placed bridge decks (axe-breakable); level re-points the group on scene swaps.
		self.bridge_sprites = (getattr(level, 'bridge_sprites', None)
		                       if level is not None else None)
		if self.bridge_sprites is None:
			self.bridge_sprites = pygame.sprite.Group()
		self.interaction = interaction
		self.sleep = False
		self.soil_layer = soil_layer
		self.toggle_shop = toggle_shop
		self.try_sleep = try_sleep
		self.toggle_crafting = toggle_crafting
		self.toggle_inventory = toggle_inventory

		self.level_ref = level

		# sound
		self.watering = pygame.mixer.Sound(asset_path('audio', 'water.mp3'))
		self.watering.set_volume(0.2)

		# bed surf for placing
		self.bed_surf = pygame.image.load(asset_path('graphics', 'overlay', 'bed.png')).convert_alpha()

	@property
	def hotbar(self):
		return HotbarView(self.inventory)

	def _stock_starting_inventory(self):
		starting_hotbar = [
			['hoe', 1], ['axe', 1], ['pickaxe', 1], ['water_bucket', 1],
			['wheat_seed', 5], ['tomato_seed', 5], ['oak_sapling', 2],
			None, None,
		]
		for index, slot in enumerate(starting_hotbar):
			self.inventory.set_slot(index, slot)
		for item, count in {
			'wood': 20, 'apple': 20, 'wheat': 20, 'tomato': 20,
			'oak_sapling': 2, 'birch_sapling': 2,
			'cherry_sapling': 2, 'pine_sapling': 2,
		}.items():
			self.inventory.add(item, count, hotbar_first=False)

	def item_count(self, item):
		return self.inventory.count(item)

	def add_item(self, item, count=1):
		"""Bag-first store: main bag first, hotbar last."""
		return self.inventory.add(item, count, hotbar_first=False)

	def add_loot(self, item, count=1):
		"""Store an item that was broken, picked, harvested, crafted or bought.
		Hotbar first: an item already held stacks onto its existing pile, a fresh
		item takes the first hotbar slot with room, a full hotbar spills over.
		"""
		return self.inventory.add(item, count, hotbar_first=True)

	def take_item(self, item, count=1):
		return self.inventory.remove(item, count)

	def drop_selected(self):
		"""Q: throw the held slot's item onto the ground, Minecraft-style.
		One item leaves the stack. The drop flies a short way, floats until the
		bag has room, then hops back in.
		"""
		if self.sleep or getattr(self, 'input_locked', False):
			return False
		if not 0 <= self.hotbar_index < len(self.hotbar):
			return False
		slot = self.hotbar[self.hotbar_index]
		if not slot:
			play_error()
			return False
		item, count = slot
		remaining = int(count) - 1
		self.hotbar[self.hotbar_index] = (
			[item, remaining] if remaining > 0 else None)
		self._update_hotbar_selection()
		level = getattr(self, 'level_ref', None)
		if level is None:
			return False
		# Throw in the facing direction so the drop never lands back on the feet.
		facing = self._facing_vector(
			self.status.replace('_idle', ''), False)
		throw = (facing.x * 52.0, facing.y * 52.0) if facing else None
		level.drop_item(item, 1, throw=throw)
		return True

	def stock_trial_quest_items(self):
		for page in TOWN_QUEST_PAGES:
			for item, _label, _is_seed in page:
				self.inventory.ensure_count(item, QUEST_STACK)
		self.inventory.ensure_count(HEART_RECIPE, 1)
		for potion in ('speed_potion', 'miner_potion', 'night_vision_potion'):
			self.inventory.ensure_count(potion, 1)

	def _get_target_cell(self):
		gx = int(self.target_pos[0]) // TILE_SIZE
		gy = int(self.target_pos[1]) // TILE_SIZE
		return self.soil_layer._cell(gx, gy)

	def _can_hoe(self):
		cell = self._get_target_cell()
		if cell is not None and 'X' in cell:
			return False
		gx = int(self.target_pos[0]) // TILE_SIZE
		gy = int(self.target_pos[1]) // TILE_SIZE
		if self.level_ref.is_planted_tile(gx, gy):
			return False
		if self.level_ref.world_gen.is_water_at(gx, gy):
			return False
		tile_rect = pygame.Rect(gx * TILE_SIZE, gy * TILE_SIZE, TILE_SIZE, TILE_SIZE)
		for sprite in self.tree_sprites.sprites():
			if sprite.rect.colliderect(tile_rect):
				return False
		for sprite in self.rock_sprites.sprites():
			if sprite.rect.colliderect(tile_rect):
				return False
		for sprite in self.bush_sprites.sprites():
			if sprite.rect.colliderect(tile_rect):
				return False
		for sprite in self.bed_sprites.sprites():
			if sprite.rect.colliderect(tile_rect):
				return False
		for sprite in self.flower_sprites.sprites():
			if sprite.rect.colliderect(tile_rect):
				return False
		return True

	def _can_water(self):
		cell = self._get_target_cell()
		return cell is not None and 'X' in cell and 'W' not in cell

	def _can_plant(self):
		cell = self._get_target_cell()
		if cell is None or 'X' not in cell or 'P' in cell:
			return False
		gx = int(self.target_pos[0]) // TILE_SIZE
		gy = int(self.target_pos[1]) // TILE_SIZE
		if self.level_ref.is_planted_tile(gx, gy):
			return False
		return True

	def _can_plant_sapling(self):
		if self.energy <= 0:
			return False
		gx = int(self.target_pos[0]) // TILE_SIZE
		gy = int(self.target_pos[1]) // TILE_SIZE
		return self.level_ref.can_plant_sapling_at(gx, gy)

	def _tool_allowed(self, sprite, tool):
		"""Sprites can restrict which tool damages them (crates: axe,
		pots: punch, ores/rocks: pickaxe). No attribute = legacy sprite
		where every tool works."""
		allowed = getattr(sprite, 'allowed_tools', None)
		return allowed is None or tool in allowed

	def _can_axe(self):
		for bed in self.bed_sprites.sprites():
			if not self._tool_allowed(bed, 'axe'):
				continue
			if bed.rect.collidepoint(self.target_pos):
				return True
		for tree in self.tree_sprites.sprites():
			if not self._tool_allowed(tree, 'axe'):
				continue
			if tree.rect.collidepoint(self.target_pos):
				return True
		for flower in self.flower_sprites.sprites():
			if not self._tool_allowed(flower, 'axe'):
				continue
			if flower.rect.collidepoint(self.target_pos):
				return True
		for bush in self.bush_sprites.sprites():
			if not self._tool_allowed(bush, 'axe'):
				continue
			if bush.rect.collidepoint(self.target_pos):
				return True
		for bridge in self.bridge_sprites.sprites():
			if not self._tool_allowed(bridge, 'axe'):
				continue
			if not getattr(bridge, 'alive', True):
				continue
			if bridge.rect.collidepoint(self.target_pos):
				return True
		return False

	def _can_pickaxe(self):
		for rock in self.rock_sprites.sprites():
			if not self._tool_allowed(rock, 'pickaxe'):
				continue
			if rock.rect.collidepoint(self.target_pos):
				return True
		return False

	def _can_punch(self):
		"""True when a punchable target (rock/pot or tree) sits under the
		crosshair, so the swing animation only plays when it connects."""
		return self._punch_target() is not None

	def _punch_target(self):
		for group in (self.rock_sprites, self.tree_sprites):
			for sprite in group.sprites():
				if not self._tool_allowed(sprite, 'punch'):
					continue
				if not getattr(sprite, 'alive', True):
					continue
				if getattr(sprite, 'broken', False):
					continue
				if sprite.rect.collidepoint(self.target_pos):
					return sprite
		return None

	def _axe_target(self):
		for group in (self.bed_sprites, self.tree_sprites, self.flower_sprites,
		              self.bush_sprites, self.bridge_sprites):
			for sprite in group.sprites():
				if not self._tool_allowed(sprite, 'axe'):
					continue
				if not getattr(sprite, 'alive', True):
					continue
				if getattr(sprite, 'broken', False):
					continue
				if sprite.rect.collidepoint(self.target_pos):
					return sprite
		return None

	def _pickaxe_target(self):
		for sprite in self.rock_sprites.sprites():
			if not self._tool_allowed(sprite, 'pickaxe'):
				continue
			if not getattr(sprite, 'alive', True):
				continue
			if getattr(sprite, 'broken', False):
				continue
			if sprite.rect.collidepoint(self.target_pos):
				return sprite
		return None

	def _miner_finish(self, sprite):
		"""Miner potion: this swing drops the target to its last hit point."""
		if self.has_potion_effect('miner_potion') and hasattr(sprite, 'health'):
			sprite.health = 1

	def _panel_error(self, text):
		"""Route a blocked-action hint to the top instruction panel."""
		level = getattr(self, 'level_ref', None)
		panel = getattr(level, 'instruction_panel', None)
		if panel is not None:
			panel.show_error(text)

	def use_tool(self):
		if self.energy <= 0:
			play_error()
			self._panel_error('Too tired to keep working - eat some food to recover.')
			return
		# Inventory-full short-circuit: no energy spend or damage when loot cannot be stored.
		level = self.level_ref
		if level is not None and self.selected_tool in ('axe', 'pickaxe'):
			target = (self._axe_target() if self.selected_tool == 'axe'
			          else self._pickaxe_target())
			if target is not None:
				items = getattr(target, 'drop_items', lambda: [])()
				if isinstance(target, PlaceableBed):
					# A bed only needs bag room on the hit that actually breaks it.
					effective_health = (1 if self.has_potion_effect('miner_potion')
					                    else target.health)
					items = ([('Bed', 1)] if effective_health - 2 <= 0
					         else [])
				elif isinstance(target, PlaceableBridge):
					# Same as the bed: only the deck-breaking hit needs bag room.
					effective_health = (1 if self.has_potion_effect('miner_potion')
					                    else target.health)
					items = ([('bridge', 1)] if effective_health - 1 <= 0
					         else [])
				if not can_store(getattr(level, 'player_add', None), items):
					play_error()
					level.show_inventory_full()
					return
		self.spend_energy(0.5)
		try:
			tool_pos = getattr(self, '_tool_target_pos', self.target_pos)
			if self.selected_tool == 'hoe':
				self.soil_layer.get_hit(tool_pos)
			elif self.selected_tool == 'axe':
				hit_bed = False
				for bed in self.bed_sprites.sprites():
					if not self._tool_allowed(bed, 'axe'):
						continue
					if bed.rect.collidepoint(tool_pos):
						self._miner_finish(bed)
						bed.damage(2)
						hit_bed = True
						break
				if not hit_bed:
					for tree in self.tree_sprites.sprites():
						if not self._tool_allowed(tree, 'axe'):
							continue
						if tree.rect.collidepoint(tool_pos):
							self._miner_finish(tree)
							tree.damage(2)
							break
					else:
						for flower in self.flower_sprites.sprites():
							if not self._tool_allowed(flower, 'axe'):
								continue
							if flower.rect.collidepoint(tool_pos):
								flower.damage()
								break
						else:
							for bush in self.bush_sprites.sprites():
								if not self._tool_allowed(bush, 'axe'):
									continue
								if bush.rect.collidepoint(tool_pos):
									bush.damage()
									break
							else:
								# Axe only, one hit per swing, so three swings break the deck.
								for bridge in self.bridge_sprites.sprites():
									if not self._tool_allowed(bridge, 'axe'):
										continue
									if not getattr(bridge, 'alive', True):
										continue
									if bridge.rect.collidepoint(tool_pos):
										self._miner_finish(bridge)
										bridge.damage(1)
										break
			elif self.selected_tool == 'pickaxe':
				for rock in self.rock_sprites.sprites():
					if not self._tool_allowed(rock, 'pickaxe'):
						continue
					if rock.rect.collidepoint(tool_pos):
						self._miner_finish(rock)
						rock.damage(2)
						break
		except Exception as exc:  # keep the swing alive, never swallow silently
			print(f"[{self.__class__.__name__}] pickaxe/rock error: {exc!r}")

	def use_punch(self):
		# Fired by the 'punch impact' timer so damage and sound land together.
		if self.energy <= 0:
			return
		# Inventory-full short-circuit: no stamina drain or swing when loot cannot fit.
		level = self.level_ref
		target = self._punch_target()
		if level is not None and target is not None:
			items = getattr(target, 'drop_items', lambda: [])()
			if not can_store(getattr(level, 'player_add', None), items):
				play_error()
				level.show_inventory_full()
				return
		self.spend_energy(0.5)
		try:
			# Punch picks up pots, breaks rocks like the stick, then falls back to trees.
			for rock in self.rock_sprites.sprites():
				if not self._tool_allowed(rock, 'punch'):
					continue
				if rock.rect.collidepoint(self.target_pos):
					self._miner_finish(rock)
					rock.damage()
					return
			for tree in self.tree_sprites.sprites():
				if not self._tool_allowed(tree, 'punch'):
					continue
				if tree.rect.collidepoint(self.target_pos):
					self._miner_finish(tree)
					tree.damage()
					break
		except Exception as exc:  # keep the swing alive, never swallow silently
			print(f"[{self.__class__.__name__}] axe/tree error: {exc!r}")

	def is_near_water(self):
		if hasattr(self, 'level_ref') and self.level_ref:
			world_gen = getattr(self.level_ref, 'world_gen', None)
			if world_gen:
				gx = int(self.target_pos[0]) // TILE_SIZE
				gy = int(self.target_pos[1]) // TILE_SIZE
				return world_gen.is_water_at(gx, gy)
		return False

	def use_water_bucket(self):
		if self.water_bucket_amount > 0:
			if self.energy <= 0:
				play_error()
				return
			if self.soil_layer.water(self.target_pos):
				self.spend_energy(0.3)
				self.watering.play()
				self.water_bucket_amount -= 1
		elif self.is_near_water():
			self.water_bucket_amount = 5
			self.watering.play()

	ISO_GRID_OFFSETS = {
		'right':      (1, -1),
		'left':       (-1, 1),
		'down':       (1, 1),
		'up':         (-1, -1),
		'down_right': (1, 0),
		'down_left':  (0, 1),
		'up_right':   (0, -1),
		'up_left':    (-1, 0),
	}

	def _hotbar_tool(self):
		"""Hotbar slot as a tool id; an empty slot reads as 'punch'."""
		slot = self.hotbar[self.hotbar_index] if 0 <= self.hotbar_index < len(self.hotbar) else None
		return (slot[0] if slot else None) or 'punch'

	def _snap_groups(self):
		# Which breakables the current hotbar slot may snap to.
		item = self._hotbar_tool()
		if item == 'axe':
			return [self.tree_sprites, self.bush_sprites, self.flower_sprites, self.bed_sprites]
		if item == 'pickaxe':
			return [self.rock_sprites]
		if item == 'punch':
			# Empty hand punches rocks/trees and snaps to RShift pickups (flowers, bushes).
			return [self.rock_sprites, self.tree_sprites, self.flower_sprites, self.bush_sprites]
		return []

	def _facing_vector(self, status_dir, is_iso):
		if is_iso:
			gx, gy = self.ISO_GRID_OFFSETS.get(
				status_dir or 'down', self.ISO_GRID_OFFSETS['down'])
			facing = pygame.math.Vector2(gx, gy)
		else:
			facing = PLAYER_TOOL_OFFSET.get(
				status_dir or 'down', PLAYER_TOOL_OFFSET['down']).copy()
		if facing.length_squared() == 0:
			return None
		return facing.normalize()

	def _best_snap(self, groups, origin, facing, tool):
		"""Nearest sprite in `groups` sitting inside the facing cone.
		`tool` is the held tool id; None disables the filter for forage objects.
		"""
		best = None
		best_dist = SNAP_RANGE
		for group in groups:
			for sprite in group.sprites():
				if tool is not None and not self._tool_allowed(sprite, tool):
					continue
				if not getattr(sprite, 'alive', True):
					continue
				if getattr(sprite, 'broken', False):
					continue
				rect = sprite.rect
				# Distance to the nearest rect point so touching/large objects qualify.
				near = pygame.math.Vector2(
					max(rect.left, min(origin.x, rect.right)),
					max(rect.top, min(origin.y, rect.bottom)),
				)
				to = near - origin
				dist = to.length()
				if dist >= best_dist:
					continue
				if dist > 0 and facing.dot(to) < SNAP_CONE_COS * dist:
					continue
				best = sprite
				best_dist = dist
		return best

	def _find_snap_target(self, status_dir):
		groups = self._snap_groups()
		tool = self._hotbar_tool()
		is_iso = (hasattr(self.level_ref, 'isometric_mode')
		          and self.level_ref.isometric_mode)
		facing = self._facing_vector(status_dir, is_iso)
		if facing is None:
			return None

		origin = pygame.math.Vector2(self.rect.center)

		# Pass 1: tool-damageable objects win, so a swing aims at what it can hit.
		if groups:
			best = self._best_snap(groups, origin, facing, tool)
			if best is not None:
				return best

		# Pass 2: forage; bushes and flowers are gathered with RShift, any tool.
		return self._best_snap([self.bush_sprites, self.flower_sprites],
		                       origin, facing, None)

	def _soil_action(self):
		if self.hotbar_index >= len(self.hotbar):
			return None
		slot = self.hotbar[self.hotbar_index]
		if not slot or slot[1] <= 0:
			return 'harvest'
		item = slot[0]
		if item == 'water_bucket' and self.water_bucket_amount > 0:
			return 'water'
		if item in self.seeds:
			return 'plant'
		return None

	def _farm_tile_valid(self, gx, gy, action):
		"""Validity check shared by _find_soil_tile."""
		if getattr(self.level_ref, 'scene', 'overworld') != 'overworld':
			return False
		soil = self.soil_layer
		cell = soil._cell(gx, gy)
		if 'X' not in cell:
			return False
		if action == 'water' and 'W' in cell:
			return False
		if action in ('plant', 'harvest') and 'P' in cell:
			if action == 'plant':
				return False
			plant = soil.plant_at_tile(gx, gy)
			if plant is None:
				return False
		if action == 'harvest' and 'P' not in cell:
			return False
		return True

	def _find_soil_tile(self, status_dir):
		"""Nearest in-cone farm tile relevant to the current hotbar slot."""
		if getattr(self.level_ref, 'scene', 'overworld') != 'overworld':
			return None
		soil = self.soil_layer
		action = self._soil_action()
		if action is None:
			return None
		facing = self._facing_vector(status_dir, True)
		if facing is None:
			return None

		origin = pygame.math.Vector2(self.rect.center)
		player_gx = self.rect.centerx // TILE_SIZE
		player_gy = self.rect.centery // TILE_SIZE
		# Prefer the faced ISO-direction tile so cross-row input does not snap away.
		gx_off, gy_off = self.ISO_GRID_OFFSETS.get(
			status_dir or 'down', self.ISO_GRID_OFFSETS['down'])
		facing_tile = (player_gx + gx_off, player_gy + gy_off)
		if self._farm_tile_valid(facing_tile[0], facing_tile[1], action):
			return facing_tile
		best = None
		best_dist = SNAP_RANGE
		for row_index, row in enumerate(soil.grid):
			for col_index, cell in enumerate(row):
				if 'X' not in cell:
					continue
				gx = col_index + soil._grid_ox
				gy = row_index + soil._grid_oy
				if (gx, gy) == (player_gx, player_gy):
					continue
				if not self._farm_tile_valid(gx, gy, action):
					continue
				# Immature crops stay selectable so an empty hand reports "crop not ready".

				center = pygame.math.Vector2(
					gx * TILE_SIZE + TILE_SIZE // 2,
					gy * TILE_SIZE + TILE_SIZE // 2)
				to = center - origin
				dist = to.length()
				if dist <= 0 or dist >= best_dist:
					continue
				if facing.dot(to) < SNAP_CONE_COS * dist:
					continue
				best = (gx, gy)
				best_dist = dist
		return best

	def get_target_pos(self):
		is_iso = hasattr(self.level_ref, 'isometric_mode') and self.level_ref.isometric_mode

		status_dir = None
		for dir_name in ['up_left', 'up_right', 'down_left', 'down_right', 'up', 'down', 'left', 'right']:
			if self.status.startswith(dir_name):
				status_dir = dir_name
				break

		if is_iso:
			if not status_dir:
				status_dir = 'down'
			player_gx = self.rect.centerx // TILE_SIZE
			player_gy = self.rect.centery // TILE_SIZE
			gx_off, gy_off = self.ISO_GRID_OFFSETS[status_dir]
			target_gx = player_gx + gx_off
			target_gy = player_gy + gy_off
			self.target_grid = (target_gx, target_gy)
			self.target_pos = pygame.math.Vector2(
				target_gx * TILE_SIZE + TILE_SIZE // 2,
				target_gy * TILE_SIZE + TILE_SIZE // 2,
			)
		elif not is_iso and status_dir:
			self.target_pos = self.rect.center + PLAYER_TOOL_OFFSET.get(status_dir, pygame.math.Vector2())
			self.target_grid = None
		else:
			self.target_pos = self.rect.center
			self.target_grid = None

		# Auto-selector: snap to the nearest in-cone breakable matching the tool.
		snapped = self._find_snap_target(status_dir)
		if snapped is not None:
			self.target_object = snapped
			self.target_pos = pygame.math.Vector2(snapped.rect.center)
			if is_iso:
				self.target_grid = (
					snapped.rect.centerx // TILE_SIZE,
					snapped.rect.centery // TILE_SIZE,
				)
		else:
			self.target_object = None

		# Farming snaps past the face tile so adjacent crop rows stay usable.
		soil_tile = self._find_soil_tile(status_dir)
		if soil_tile is not None:
			self.target_grid = soil_tile
			self.target_pos = pygame.math.Vector2(
				soil_tile[0] * TILE_SIZE + TILE_SIZE // 2,
				soil_tile[1] * TILE_SIZE + TILE_SIZE // 2)
			if self._soil_action() == 'harvest':
				self.target_object = self.soil_layer.plant_at_tile(*soil_tile)

	def _potion_now(self):
		"""Potions tick on the REAL wall clock, not the accelerated game clock.
		The clock only runs while the game does, so closing the game freezes the
		countdown.
		"""
		return time.time()

	def restore_potion_effects(self, values):
		"""Rebuild potion_effects expiries from save data.
		A save holds seconds LEFT, so a potion resumes where it left off.
		"""
		if not isinstance(values, dict):
			self.potion_effects = {}
			self._refresh_potion_speed()
			return
		now = self._potion_now()
		restored = {}
		for effect, value in values.items():
			if effect not in POTION_ITEMS:
				continue
			try:
				left = float(value)
			except (TypeError, ValueError):
				continue
			if left > POTION_EFFECT_DURATION_SECONDS:
				# legacy absolute expiry -> seconds it had left
				left = left - now
			left = max(0.0, min(left, POTION_EFFECT_DURATION_SECONDS))
			if left > 0:
				restored[effect] = now + left
		self.potion_effects = restored
		self._refresh_potion_speed()

	def has_potion_effect(self, effect, now=None):
		expiry = self.potion_effects.get(effect)
		if expiry is None:
			return False
		if now is None:
			now = self._potion_now()
		return now < expiry

	def potion_remaining(self, effect):
		"""Real seconds left on an effect (0.0 when inactive).
		The HUD uses this to draw live countdowns without knowing which clock the
		potion system runs on.
		"""
		expiry = self.potion_effects.get(effect)
		if expiry is None:
			return 0.0
		return max(0.0, expiry - self._potion_now())

	def spend_energy(self, amount):
		# Every swing costs stamina; the miner potion finishes in one hit, not for free.
		self.energy = max(0, self.energy - amount)

	def _refresh_potion_speed(self):
		multiplier = (SPEED_POTION_MULTIPLIER
		              if self.has_potion_effect('speed_potion') else 1.0)
		self.speed = self.base_speed * multiplier

	def update_potion_effects(self, now=None):
		if now is None:
			now = self._potion_now()
		expired = [effect for effect, expiry in self.potion_effects.items()
		           if now >= expiry]
		for effect in expired:
			del self.potion_effects[effect]
		self._refresh_potion_speed()

	def use_potion(self, item):
		if item not in POTION_ITEMS:
			return False
		expiry = (self._potion_now()
		          + POTION_EFFECT_DURATION_SECONDS)
		self.potion_effects[item] = expiry
		if item == 'health_potion':
			self.energy = self.max_energy
		self._refresh_potion_speed()
		play_click()
		return True

	def consume_selected_potion(self):
		if not 0 <= self.hotbar_index < len(self.hotbar):
			return False
		slot = self.hotbar[self.hotbar_index]
		if not slot or slot[0] not in POTION_ITEMS or slot[1] <= 0:
			return False
		if not self.use_potion(slot[0]):
			return False
		slot[1] -= 1
		if slot[1] <= 0:
			self.hotbar[self.hotbar_index] = None
		return True

	def _is_consumable(self, item):
		"""True for the items RSHIFT consumes: potions and food."""
		return (item in POTION_ITEMS or item == 'bread'
		        or item in EDIBLE_HEAL)

	def _consume_selected_food_or_potion(self):
		"""RSHIFT on the selected slot: drink a potion or eat food.
		Potions are always usable; food only restores energy, so eating at full
		energy is refused (the food stays in the bag).
		"""
		if not 0 <= self.hotbar_index < len(self.hotbar):
			return False
		slot = self.hotbar[self.hotbar_index]
		if not slot:
			return False
		item, count = slot
		if count <= 0:
			return False
		if item in POTION_ITEMS:
			if not self.use_potion(item):
				return False
			slot[1] -= 1
			if slot[1] <= 0:
				self.hotbar[self.hotbar_index] = None
			return True
		if item == 'bread' or item in EDIBLE_HEAL:
			if self.energy >= self.max_energy:
				play_error()
				self._panel_error(
					'You are not tired - save the food for later.')
				return False
			heal = 30 if item == 'bread' else EDIBLE_HEAL[item]
			self.energy = min(self.max_energy, self.energy + heal)
			slot[1] -= 1
			if slot[1] <= 0:
				self.hotbar[self.hotbar_index] = None
			play_click()
			return True
		return False

	def _try_sleep_near_bed(self):
		"""Enter/RSHIFT next to a placed bed starts sleep. Returns True
		when a bed was in range so the caller can skip other actions."""
		px, py = self.rect.center
		try:
			for bed in self.bed_sprites.sprites():
				bx, by = bed.rect.center
				if ((bx - px) ** 2 + (by - py) ** 2
						<= TILE_SIZE * TILE_SIZE):
					self.level_ref.try_sleep()
					return True
		except Exception as exc:  # keep input alive, never swallow silently
			print(f"[{self.__class__.__name__}] bed-sleep error: {exc!r}")
		return False

	def use_seed(self):
		if self.energy <= 0:
			play_error()
			return
		if self.selected_seed:
			slot = self.hotbar[self.hotbar_index]
			if slot and slot[0] == self.selected_seed and slot[1] > 0:
				plant_type = crop_type_for_seed(self.selected_seed)
				if plant_type and self.soil_layer.plant_seed(
					self.target_pos, plant_type):
					self.spend_energy(0.3)
					slot[1] -= 1
					if slot[1] <= 0:
						self.hotbar[self.hotbar_index] = None

	def use_sapling(self):
		if self.energy <= 0:
			play_error()
			return False
		slot = self.hotbar[self.hotbar_index]
		if not slot or slot[0] not in SAPLING_ITEMS or slot[1] <= 0:
			return False
		if not self.level_ref.plant_sapling(slot[0], self.target_pos):
			return False
		self.spend_energy(0.3)
		slot[1] -= 1
		if slot[1] <= 0:
			self.hotbar[self.hotbar_index] = None
		return True

	# graphics/character/<Folder>/<action>: one folder per facing with animation subfolders.
	DIR_FOLDERS = {
		'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right',
		'up_left': 'Up_Left', 'up_right': 'Up_Right',
		'down_left': 'Down_Left', 'down_right': 'Down_Right',
	}
	ACTION_SUFFIXES = ['', '_idle', '_axe', '_hoe', '_pickaxe', '_punch', '_water_bucket']

	def import_assets(self):
		self.animations = {}
		for dir_name, folder in self.DIR_FOLDERS.items():
			for suffix in self.ACTION_SUFFIXES:
				animation = dir_name + suffix
				full_path = asset_path('graphics', 'character', folder, animation)
				frames = import_folder(full_path)
				# Idle animations use only first frame (static image)
				if suffix == '_idle':
					frames = frames[:1] if frames else []
				self.animations[animation] = frames

	def animate(self,dt):
		self.frame_index += 4 * dt
		frames = self.animations.get(self.status, [])
		if not frames:
			# Try base direction (e.g. up_right_hoe -> up_right)
			for suffix in ['_water_bucket', '_pickaxe', '_axe', '_hoe', '_punch']:
				if self.status.endswith(suffix):
					base = self.status[:-len(suffix)]
					frames = self.animations.get(base, [])
					break
		if not frames:
			# Try idle fallback (e.g. up_right -> up_right_idle)
			if not self.status.endswith('_idle'):
				frames = self.animations.get(self.status + '_idle', [])
		if not frames:
			# Try 4-direction fallback
			base = self.status.split('_')[0]
			frames = self.animations.get(base + '_idle', self.animations.get(base, []))
		if not frames:
			frames = self.animations.get('down_idle', self.animations.get('down', []))
		
		# Idle animations use only first frame (static)
		if '_idle' in self.status:
			self.frame_index = 0
		
		if frames and self.frame_index >= len(frames):
			self.frame_index = 0

		if frames:
			self.image = frames[int(self.frame_index)]

	def input(self):
		# A focused debug text box owns the keyboard: freeze movement, tools, menus.
		if getattr(self, 'input_locked', False):
			self.direction.update(0, 0)
			return
		keys = pygame.key.get_pressed()

		if not self.timers['tool use'].active and not self.timers['water bucket'].active and not self.timers['punch'].active and not self.timers['punch impact'].active and not self.sleep:
			# 8-directional movement
			up = input_manager.is_action_pressed_keys(keys, 'move_up')
			down = input_manager.is_action_pressed_keys(keys, 'move_down')
			left = input_manager.is_action_pressed_keys(keys, 'move_left')
			right = input_manager.is_action_pressed_keys(keys, 'move_right')

			# Calculate direction vector
			self.direction.y = -1 if up else (1 if down else 0)
			self.direction.x = -1 if left else (1 if right else 0)

			# Set status based on 8 directions or idle
			if up and right:
				self.status = 'up_right'
			elif up and left:
				self.status = 'up_left'
			elif down and right:
				self.status = 'down_right'
			elif down and left:
				self.status = 'down_left'
			elif up:
				self.status = 'up'
			elif down:
				self.status = 'down'
			elif left:
				self.status = 'left'
			elif right:
				self.status = 'right'
			else:
				# No movement - use idle animation based on last direction
				base = self.status.split('_')[0] if '_' not in self.status.replace('_idle','') else self.status.split('_idle')[0]
				for dir_name in ['up_left', 'up_right', 'down_left', 'down_right', 'up', 'down', 'left', 'right']:
					if self.status.startswith(dir_name):
						base = dir_name
						break
				self.status = base + '_idle'

			# Enter: use tool / place / punch. Tools & punch repeat; bed placement is edge-triggered.
			use_tool_pressed = input_manager.is_action_pressed_keys(keys, 'use_tool')
			in_cave = getattr(self.level_ref, 'scene', 'overworld') == 'cave'
			# Enter also enters/exits the cave, taking precedence over the tool swing.
			cave_triggered = False
			quest_triggered = False
			if use_tool_pressed and not self._use_tool_was_pressed:
				cave_triggered = self._try_cave_transition()
				if not cave_triggered:
					quest_triggered = self._try_open_quests()
			if use_tool_pressed and not cave_triggered and not quest_triggered:
				slot = self.hotbar[self.hotbar_index]
				if slot:
					item, count = slot
					# Food and potions are used with RSHIFT (use_item), not the tool key.
					if item in self.tools and item != 'water_bucket':
						if in_cave and item == 'hoe':
							# no farmland in the cave
							if not self._use_tool_was_pressed:
								play_error()
								self._panel_error('You cannot farm inside the cave.')
						elif item == 'axe' or item == 'pickaxe':
							target = (self._axe_target() if item == 'axe'
							          else self._pickaxe_target())
							level = self.level_ref
							blocked = (target is not None and level is not None
							           and not can_store(
							               getattr(level, 'player_add', None),
							               getattr(target, 'drop_items', lambda: [])()))
							if not self._use_tool_was_pressed:
								if blocked:
									play_error()
									level.show_inventory_full()
								elif (item == 'axe' and not self._can_axe()) or \
								     (item == 'pickaxe' and not self._can_pickaxe()):
									play_error()
									if item == 'axe':
										self._panel_error('Stand facing a tree or bush, then press the use-tool key to chop.')
									else:
										self._panel_error('Stand facing a rock or ore vein, then press the use-tool key to mine.')
							if (not blocked and
									((item == 'axe' and self._can_axe())
								 or (item == 'pickaxe' and self._can_pickaxe()))):
								self.selected_tool = item
								self.selected_seed = None
								self._tool_target_pos = self.target_pos.copy()
								self.timers['tool use'].activate()
								self.direction = pygame.math.Vector2()
								self.frame_index = 0
						elif item == 'hoe' and not self._can_hoe():
							if not self._use_tool_was_pressed:
								play_error()
								self._panel_error('The hoe needs an empty grass tile - clear trees, rocks, and plants first.')
						elif item == 'hoe':
							self.selected_tool = item
							self.selected_seed = None
							self._tool_target_pos = self.target_pos.copy()
							self.timers['tool use'].activate()
							self.direction = pygame.math.Vector2()
							self.frame_index = 0
					elif self._is_consumable(item):
						# Enter also eats food / drinks potions; RSHIFT keeps the same shortcut.
						if not self._use_tool_was_pressed:
							if self._consume_selected_food_or_potion():
								self.timers['interact'].activate()
					elif item == 'Bed' and not self._use_tool_was_pressed and not in_cave:
						# Bed renderer anchors its art by the rect center (not the feet).
						_bw = self.bed_surf.get_width()
						_bh = self.bed_surf.get_height()
						bed = PlaceableBed(
							pos = (self.target_pos[0] - _bw // 2, self.target_pos[1] - _bh // 2),
							surf = self.bed_surf,
							groups = [self.level_ref.all_sprites, self.collision_sprites, self.bed_sprites],
							player_add = self.level_ref.player_add)
						if getattr(self.level_ref, 'world_gen', None):
							bed.level = self.level_ref.world_gen.height_at(
								int(self.target_pos[0]) // TILE_SIZE,
								int(self.target_pos[1]) // TILE_SIZE)
						slot[1] -= 1
						if slot[1] <= 0:
							self.hotbar[self.hotbar_index] = None
					elif item == 'bridge' and not self._use_tool_was_pressed:
						# Placed on the water/lava tile under the crosshair; the level makes it walkable.
						level = self.level_ref
						if level is not None and level.place_bridge(
								self.target_pos):
							slot[1] -= 1
							if slot[1] <= 0:
								self.hotbar[self.hotbar_index] = None
						else:
							play_error()
							self._panel_error(
								'Aim at open lava to place a bridge.'
								if in_cave else
								'Aim at open water to place a bridge.')
					# seeds & water_bucket are handled by use_item (Shift)
					else:
						# Anything not a tool, consumable, bed or bridge: bare-hand punch.
						punch_target = self._punch_target()
						if punch_target is not None:
							level = self.level_ref
							blocked = (level is not None
							           and not can_store(
							               getattr(level, 'player_add', None),
							               getattr(punch_target, 'drop_items', lambda: [])()))
							if blocked:
								if not self._use_tool_was_pressed:
									play_error()
									level.show_inventory_full()
							else:
								self.timers['punch'].activate()
								self.timers['punch impact'].activate()
								self.direction = pygame.math.Vector2()
								self.frame_index = 0
				else:
					# Empty hand: sleep beside a placed bed, else punch only when a target exists.
					if self._try_sleep_near_bed():
						pass
					else:
						punch_target = self._punch_target()
						if punch_target is not None:
							level = self.level_ref
							blocked = (level is not None
							           and not can_store(
							               getattr(level, 'player_add', None),
							               getattr(punch_target, 'drop_items', lambda: [])()))
							if blocked:
								if not self._use_tool_was_pressed:
									play_error()
									level.show_inventory_full()
							else:
								self.timers['punch'].activate()
								self.timers['punch impact'].activate()
								self.direction = pygame.math.Vector2()
								self.frame_index = 0

			# RShift: plant / water / fill bucket / pick. Overworld: talk, forage, sleep, shop; cave: pots.
			use_item_pressed = input_manager.is_action_pressed_keys(keys, 'use_item')
			near_villager = None
			picked_decoration = False
			if use_item_pressed and not self._use_item_was_pressed and not in_cave:
				near_villager = self.level_ref.villager_near(self.rect.center)
				if near_villager is not None:
					self.direction = pygame.math.Vector2()
					self.level_ref.toggle_villager(near_villager.name)
					picked_decoration = True
				elif not self.timers['tool use'].active and not self.timers['water bucket'].active and not self.timers['punch'].active and not self.timers['interact'].active:
					slot = self.hotbar[self.hotbar_index]
					if slot and self._is_consumable(slot[0]):
						# RSHIFT drinks a potion or eats the selected food.
						if self._consume_selected_food_or_potion():
							self.timers['interact'].activate()
							picked_decoration = True
					if not slot and not picked_decoration:
						if self.level_ref.harvest_crop_at(self.target_pos):
							self.timers['interact'].activate()
							picked_decoration = True
						else:
							# Crop under the crosshair still growing: say so instead of doing nothing.
							gx = int(self.target_pos[0]) // TILE_SIZE
							gy = int(self.target_pos[1]) // TILE_SIZE
							plant = self.soil_layer.plant_at_tile(gx, gy)
							if plant is not None and not getattr(plant, 'harvestable', True):
								play_error()
								self.level_ref.show_crop_not_ready()
								picked_decoration = True
					if not picked_decoration:
						try:
							for bush in self.bush_sprites.sprites():
								if bush.rect.collidepoint(self.target_pos):
									bush.pick()
									picked_decoration = True
									break
							if not picked_decoration:
								for flower in self.flower_sprites.sprites():
									if flower.rect.collidepoint(self.target_pos):
										flower.damage()
										picked_decoration = True
										break
						except Exception as exc:  # keep input alive, never swallow silently
							print(f"[{self.__class__.__name__}] forage error: {exc!r}")
					# Sleep on RShift when a placed bed sits within one tile of the player.
					if not picked_decoration:
						hit_placed_bed = False
						px, py = self.rect.center
						try:
							for bed in self.bed_sprites.sprites():
								bx, by = bed.rect.center
								if ((bx - px) ** 2 + (by - py) ** 2
								    <= TILE_SIZE * TILE_SIZE):
									hit_placed_bed = True
									break
						except Exception as exc:  # keep input alive, never swallow silently
							print(f"[{self.__class__.__name__}] bed-check error: {exc!r}")
						if hit_placed_bed:
							self.level_ref.try_sleep()
							picked_decoration = True
						else:
							# Interaction sprites (shop, cave, bed interaction).
							try:
								collided_interaction_sprite = pygame.sprite.spritecollide(
									self, self.interaction, False)
							except Exception as exc:  # keep input alive, but say why once
								log_once('[Player] interaction collide error', exc)
								collided_interaction_sprite = []
							if collided_interaction_sprite:
								name = collided_interaction_sprite[0].name
								if name == 'VillageShop':
									self.toggle_shop()
									picked_decoration = True
								elif name == 'Bed':
									self.try_sleep()
									picked_decoration = True
								elif name == 'CaveEntrance':
									self.level_ref.request_cave_transition('cave')
									picked_decoration = True
								elif name == 'CaveExit':
									self.level_ref.request_cave_transition('overworld')
									picked_decoration = True
			# Cave: RShift picks pots (instant, no punch animation needed).
			if use_item_pressed and not self._use_item_was_pressed and in_cave and \
			   not self.timers['tool use'].active and not self.timers['water bucket'].active and not self.timers['punch'].active:
				slot = self.hotbar[self.hotbar_index]
				if slot and self._is_consumable(slot[0]):
					# RSHIFT drinks a potion or eats the selected food.
					if self._consume_selected_food_or_potion():
						self.timers['interact'].activate()
						picked_decoration = True
				if not picked_decoration:
					try:
						for sprite in self.tree_sprites.sprites():
							if getattr(sprite, 'allowed_tools', None) == ('punch',) and sprite.rect.collidepoint(self.target_pos):
								sprite.damage()
								picked_decoration = True
								break
					except Exception as exc:  # keep input alive, never swallow silently
						print(f"[{self.__class__.__name__}] pot-punch error: {exc!r}")
			if use_item_pressed and not self._use_item_was_pressed and near_villager is None and not picked_decoration and \
			   not self.timers['tool use'].active and not self.timers['water bucket'].active and not self.timers['punch'].active and \
			   not in_cave:
				slot = self.hotbar[self.hotbar_index]
				if slot:
					item, count = slot
					if item == 'water_bucket':
						if self.water_bucket_amount > 0 and self._can_water():
							self.selected_tool = 'water_bucket'
							self.timers['water bucket'].activate()
							self.direction = pygame.math.Vector2()
							self.frame_index = 0
						elif self.water_bucket_amount <= 0 and self.is_near_water():
							# play the fill animation; the timer callback fills the bucket
							self.selected_tool = 'water_bucket'
							self.timers['water bucket'].activate()
							self.direction = pygame.math.Vector2()
							self.frame_index = 0
						else:
							play_error()
							if self.water_bucket_amount <= 0:
								self._panel_error('Your bucket is empty - stand near water and press the use-item key to fill it.')
							else:
								self._panel_error('Water only tilled soil - use the hoe first, then water it.')
					elif item in self.seeds:
						if not self._can_plant():
							play_error()
							self._panel_error('Seeds need an empty tilled tile - hoe the ground first.')
						else:
							self.selected_seed = item
							if not self.timers['interact'].active:
								self.use_seed()
								self.timers['interact'].activate()
					elif item in SAPLING_ITEMS:
						if not self._can_plant_sapling():
							play_error()
							self._panel_error('This spot is blocked - find clear dry ground to plant the sapling.')
						else:
							self.selected_seed = None
							if not self.timers['interact'].active and self.use_sapling():
								self.timers['interact'].activate()
			self._use_item_was_pressed = use_item_pressed

			# number keys 1-9 select hotbar slot directly
			for i in range(9):
				if input_manager.is_action_pressed_keys(keys, f'hotbar_{i+1}') and not self.timers['tool use'].active and not self.timers['water bucket'].active and not self.timers['punch'].active:
					self.hotbar_index = i
					self._update_hotbar_selection()

			if input_manager.is_action_pressed_keys(keys, 'open_crafting') and not self.timers['tool use'].active:
				self.toggle_crafting()

			inventory_pressed = input_manager.is_action_pressed_keys(
				keys, 'open_inventory')
			if (inventory_pressed and not self._inventory_was_pressed
			    and not self.timers['tool use'].active):
				self.toggle_inventory()
			self._inventory_was_pressed = inventory_pressed

			self._use_tool_was_pressed = use_tool_pressed

	def _try_cave_transition(self):
		"""If the player is standing on this scene's cave trigger, request
		the scene swap (Enter at the doorway / exit lift). Returns True
		when the trigger fired so the caller can skip the tool swing."""
		scene = getattr(self.level_ref, 'scene', 'overworld')
		if scene == 'cave':
			target, want = 'overworld', 'CaveExit'
		else:
			target, want = 'cave', 'CaveEntrance'
		try:
			hits = pygame.sprite.spritecollide(self, self.interaction, False)
		except Exception as exc:  # keep the swing alive, but say why once
			log_once('[Player] cave-trigger collide error', exc)
			hits = []
		for hit in hits:
			if getattr(hit, 'name', None) == want:
				return self.level_ref.request_cave_transition(target)
		return False

	def _try_open_quests(self):
		"""Enter on the town-hall doorstep opens the quest board. Returns
		True when the panel opened so the caller can skip the tool swing."""
		if getattr(self.level_ref, 'scene', 'overworld') != 'overworld':
			return False
		try:
			hits = pygame.sprite.spritecollide(self, self.interaction, False)
		except Exception as exc:  # keep input alive, but say why once
			log_once('[Player] quest-trigger collide error', exc)
			hits = []
		for hit in hits:
			if getattr(hit, 'name', None) == 'TownHall':
				self.level_ref.toggle_quests()
				return True
		return False

	def _update_hotbar_selection(self):
		slot = self.hotbar[self.hotbar_index]
		if slot:
			item, count = slot
			if item in self.tools:
				self.selected_tool = item
				self.selected_seed = None
			elif item in self.seeds:
				self.selected_seed = item
			elif item in SAPLING_ITEMS:
				self.selected_seed = None

	def assign_to_hotbar(self, item, count=1, seed=False):
		if self.inventory.count(item) <= 0:
			return
		hotbar_count = sum(
			slot[1] for slot in self.inventory.slots[:HOTBAR_SIZE]
			if slot and slot[0] == item)
		if hotbar_count >= count:
			return
		move = min(count - hotbar_count, self.inventory.count(item))
		taken = self.inventory.remove_to_range(
			item, move, MAIN_START, SLOT_COUNT)
		remaining = self.inventory.add_to_range(
			item, taken, 0, HOTBAR_SIZE)
		if remaining > 0:
			self.inventory.add_to_range(
				item, remaining, MAIN_START, SLOT_COUNT)

	def remove_from_hotbar(self, index):
		slot = self.inventory.get_slot(index)
		if slot is None:
			return
		item, count = slot
		self.inventory.set_slot(index, None)
		remaining = self.inventory.add_to_range(
			item, count, MAIN_START, SLOT_COUNT)
		if remaining > 0:
			self.inventory.set_slot(index, [item, remaining])

	def set_hotbar_slot(self, index, item, count):
		self.inventory.set_slot(index, [item, count] if item else None)

	def get_status(self):
		# tool use
		if self.timers['tool use'].active:
			tool = self.selected_tool
			base = self.status.split('_')[0] if '_' not in self.status.replace('_idle','').replace('_hoe','').replace('_axe','').replace('_pickaxe','').replace('_punch','').replace('_water_bucket','') else self.status
			# Get direction prefix (up, down, left, right, up_left, etc.)
			for dir_name in ['up_left', 'up_right', 'down_left', 'down_right', 'up', 'down', 'left', 'right']:
				if self.status.startswith(dir_name):
					base = dir_name
					break
			self.status = base + '_' + tool
		if self.timers['water bucket'].active:
			for dir_name in ['up_left', 'up_right', 'down_left', 'down_right', 'up', 'down', 'left', 'right']:
				if self.status.startswith(dir_name):
					base = dir_name
					break
			self.status = base + '_water_bucket'
		# Punch: play the punch animation (empty hand).
		if self.timers['punch'].active:
			base = self.status.split('_')[0] if '_' not in self.status.replace('_idle','') else self.status.split('_idle')[0]
			for dir_name in ['up_left', 'up_right', 'down_left', 'down_right', 'up', 'down', 'left', 'right']:
				if self.status.startswith(dir_name):
					base = dir_name
					break
			self.status = base + '_punch'

	def update_timers(self):
		for timer in self.timers.values():
			timer.update()

	def _near_colliders(self):
		"""Solid sprites close enough to touch this frame's movement.
		Filtered once per tile position and reused for both axis passes.
		"""
		group = self.collision_sprites
		tile = (self.hitbox.centerx // TILE_SIZE,
		        self.hitbox.centery // TILE_SIZE)
		try:
			group_len = len(group)
		except TypeError:
			group_len = id(group)
		now = pygame.time.get_ticks()
		cache = self._collider_cache
		if (cache is not None and cache[0] == (id(group), tile, group_len)
				and now - cache[1] < 250):
			return cache[2]
		area = self.hitbox.inflate(TILE_SIZE * 2, TILE_SIZE * 2)
		near = []
		for sprite in group.sprites():
			hitbox = getattr(sprite, 'hitbox', None)
			if hitbox is not None and hitbox.colliderect(area):
				near.append(sprite)
		self._collider_cache = ((id(group), tile, group_len), now, near)
		return near

	def collision(self, direction):
		for _ in range(3):
			pushed = False
			for sprite in self._near_colliders():
				if hasattr(sprite, 'hitbox'):
					if sprite.hitbox.colliderect(self.hitbox):
						# A water tile's wall lifts once a bridge covers it; checked live each frame.
						if getattr(sprite, '_is_water_collider', False):
							level = getattr(self, 'level_ref', None)
							if level is not None and hasattr(level, 'is_bridged') \
							   and level.is_bridged(
							       sprite.hitbox.centerx // TILE_SIZE,
							       sprite.hitbox.centery // TILE_SIZE):
								continue
						if direction == 'horizontal':
							overlap_left = self.hitbox.right - sprite.hitbox.left
							overlap_right = sprite.hitbox.right - self.hitbox.left
							if overlap_left < overlap_right:
								self.hitbox.right = sprite.hitbox.left
							else:
								self.hitbox.left = sprite.hitbox.right
							self.rect.centerx = self.hitbox.centerx
							self.pos.x = self.hitbox.centerx

						if direction == 'vertical':
							overlap_top = self.hitbox.bottom - sprite.hitbox.top
							overlap_bottom = sprite.hitbox.bottom - self.hitbox.top
							if overlap_top < overlap_bottom:
								self.hitbox.bottom = sprite.hitbox.top
							else:
								self.hitbox.top = sprite.hitbox.bottom
							self.rect.centery = self.hitbox.centery
							self.pos.y = self.hitbox.centery
						pushed = True
			if not pushed:
				break

	def _elev_blocked(self, wx, wy):
		"""True when moving to (wx, wy) is illegal terrain: the overworld's
		water (lakes/rivers) or the cave's lava fill. In a FLAT world
		everything else is walkable."""
		wg = getattr(self.level_ref, 'world_gen', None) if getattr(self, 'level_ref', None) else None
		if wg is None:
			return False
		tx, ty = int(wx) // TILE_SIZE, int(wy) // TILE_SIZE
		if wg.is_water_at(tx, ty):
			level = getattr(self, 'level_ref', None)
			if level is not None and hasattr(level, 'is_bridged') \
			   and level.is_bridged(tx, ty):
				return False
			return True
		if wg.is_lava_at(tx, ty):
			return True
		return False

	def _bridge_step_ok(self, wx, wy):
		"""True when (wx, wy) is a legal COMBINED diagonal step onto, along or off
		a placed bridge - the intermediate tile of a stair-step bridge is open
		water, so both axes are allowed at once. Solid sprites still block.
		"""
		level = getattr(self, 'level_ref', None)
		if level is None or not hasattr(level, 'is_bridged'):
			return False
		wg = getattr(level, 'world_gen', None)
		if wg is None:
			return False
		tx, ty = int(wx) // TILE_SIZE, int(wy) // TILE_SIZE
		cur_tx = int(self.pos.x) // TILE_SIZE
		cur_ty = int(self.pos.y) // TILE_SIZE
		if (tx, ty) == (cur_tx, cur_ty):
			return False  # still on the same tile; use the normal path
		on_bridge = level.is_bridged(cur_tx, cur_ty)
		onto_bridge = level.is_bridged(tx, ty)
		if not (on_bridge or onto_bridge):
			return False  # no bridge involved; leave land movement alone
		if wg.is_lava_at(tx, ty) and not onto_bridge:
			return False
		if wg.is_water_at(tx, ty) and not onto_bridge:
			return False  # would step into open water/lava
		return True

	def move(self,dt):
		if hasattr(self, 'level_ref') and self.level_ref and getattr(self.level_ref, 'isometric_mode', False):
			self._move_isometric(dt)
		else:
			self._move_standard(dt)

	def _move_standard(self,dt):
		# normalizing a vector 
		if self.direction.magnitude() > 0:
			self.direction = self.direction.normalize()
		self.world_direction = self.direction.copy()

		# horizontal movement
		self.pos.x += self.direction.x * self.speed * dt
		self.hitbox.centerx = round(self.pos.x)
		self.rect.centerx = self.hitbox.centerx
		self.collision('horizontal')

		# vertical movement
		self.pos.y += self.direction.y * self.speed * dt
		self.hitbox.centery = round(self.pos.y)
		self.rect.centery = self.hitbox.centery
		self.collision('vertical')

	def _move_isometric(self, dt):
		if self.direction.magnitude() > 0:
			self.direction = self.direction.normalize()

		# Iso mapping: screen right = world (+x, -y), screen down = world (+x, +y).
		world_dx = (self.direction.x + self.direction.y) * 0.5
		world_dy = (self.direction.y - self.direction.x) * 0.5
		self.world_direction = pygame.math.Vector2(world_dx, world_dy)

		new_x = self.pos.x + world_dx * self.speed * dt
		new_y = self.pos.y + world_dy * self.speed * dt

		# Apply a diagonal step as one move so a stair-step bridge is not blocked.
		if world_dx != 0 and world_dy != 0 and self._bridge_step_ok(new_x, new_y):
			self.pos.x = new_x
			self.hitbox.centerx = round(self.pos.x)
			self.rect.centerx = self.hitbox.centerx
			self.collision('horizontal')
			self.pos.y = new_y
			self.hitbox.centery = round(self.pos.y)
			self.rect.centery = self.hitbox.centery
			self.collision('vertical')
			return

		# horizontal movement
		if not self._elev_blocked(new_x, self.pos.y):
			self.pos.x = new_x
		self.hitbox.centerx = round(self.pos.x)
		self.rect.centerx = self.hitbox.centerx
		self.collision('horizontal')

		# vertical movement
		if not self._elev_blocked(self.pos.x, new_y):
			self.pos.y = new_y
		self.hitbox.centery = round(self.pos.y)
		self.rect.centery = self.hitbox.centery
		self.collision('vertical')

	def update(self, dt):
		self.update_potion_effects()
		self.get_target_pos()
		self.input()
		self.get_status()
		self.update_timers()

		if not self.sleep:
			self.move(dt)
		self.animate(dt)
