import pygame 
import math
import os
from settings import *
import input_manager
import json
from player import Player
from overlay import Overlay
from sprites import Generic, Water, Interaction, Particle, Rock, PlaceableBed, PlaceableBridge, Tree, GrowingTree, break_flash
from support import *
from transition import Transition
from soil import SoilLayer
from sky import Rain, Sky, Snow, get_sky_color
from random import randint
from crafting import CraftingMenu
from villager_menu import VillagerMenu, ShopMenu
from inventory import InventoryMenu
from inventory_model import Inventory, LEGACY_SEED_ALIASES, CROP_SEEDS, HOTBAR_SIZE
from pause_menu import PauseMenu
from quest_menu import QuestMenu
from credits import CreditsScreen
from save_system import save_game
from time_manager import TimeManager
from world_generator import WorldGenerator, grid_to_iso, iso_to_grid, ISO_TILE_WIDTH, ISO_TILE_HEIGHT
from cave_generator import CaveGenerator
from village_generator import VillageGenerator
from instruction_panel import InstructionPanel
from debug_controls import DebugControls, WIDGET_H
from operator import itemgetter

_first = itemgetter(0)

# Onboarding flow: (step_id, template) per step; filled with live key bindings.
TUTORIAL_STEPS = (
	('punch_tree',
	 'Punch a tree by pressing {use_tool} to gather wood.'),
	('punch_rock',
	 'Punch a rock by pressing {use_tool} to mine stone.'),
	('open_inventory',
	 'Press {open_inventory} to open your inventory and rearrange items.'),
	('open_crafting',
	 'Press {open_crafting} to open the crafting menu.'),
	('craft_sticks',
	 'Craft sticks: open crafting, pick the Stick recipe, and click it.'),
	('craft_tool',
	 'Craft a tool: in crafting, make an axe or pickaxe from sticks and stone.'),
	('craft_bucket',
	 'Craft a water bucket from stone so you can water your crops.'),
	('planting',
	 'Till soil with the hoe, plant a seed, then water it with your bucket.'),
)

# One-time hints for the first hotbar selection; unlisted items stay generic.
SELECTION_HINTS = {
	'hoe': 'Hoe selected: press {use_tool} on grass to till soil for planting.',
	'axe': 'Axe selected: face a tree or bush and press {use_tool} to chop it.',
	'pickaxe': 'Pickaxe selected: face a rock or ore and press {use_tool} to mine it.',
	'water_bucket': 'Water bucket selected: fill it at water, then press '
	                'RSHIFT on tilled soil to water crops.',
	'bread': 'Bread selected: press {use_item} to eat it and restore energy.',
	'Bed': 'Bed selected: press {use_tool} to place it, then RSHIFT to sleep.',
	'bridge': 'Bridge selected: press {use_tool} on water or cave lava to '
	          'place it, then walk across.',
	'health_potion': 'Health potion selected: press {use_item} to drink it '
	                  'and restore your energy.',
	'miner_potion': 'Miner potion selected: press {use_item} to drink it - '
	                'your next swing finishes the job.',
	'night_vision_potion': 'Night vision potion selected: press {use_item} '
	                        'to drink it.',
	'speed_potion': 'Speed potion selected: press {use_item} to drink it '
	                'and move faster.',
}

# F5 DEMO test kit: tools + staples, 64-stacks of sellable/quest items.
DEMO_HOTBAR = (
	# 1st-4th slot: the four tools (stack 1), 5th slot: oak wood (64), rest empty
	('axe', 1), ('hoe', 1), ('pickaxe', 1), ('water_bucket', 1),
	('wood', 64),
	None, None, None, None,
)
DEMO_BAG = (
	# 1st quest page (6 items): saplings + seeds - 64 stacks
	('birch_sapling', 64), ('cherry_sapling', 64), ('oak_sapling', 64),
	('pine_sapling', 64), ('tomato_seed', 64), ('wheat_seed', 64),
	# 2nd quest page (6 items): fruits + vegetables - 64 stacks
	('apple', 64), ('berry', 64), ('cherry', 64), ('orange', 64),
	('tomato', 64), ('wheat', 64),
	# 3rd quest page (8 items): refined ores - 64 stacks
	('coal', 64), ('copper', 64), ('iron', 64), ('gold', 64),
	('amethyst', 64), ('emerald', 64), ('ruby', 64), ('diamond', 64),
	# Heart materials already at 64 above; potions stack 1 (unstackable)
	('health_potion', 1), ('miner_potion', 1),
	('night_vision_potion', 1), ('speed_potion', 1),
)

class Level:
	def __init__(self, save_data=None):

		# get the display surface
		self.display_surface = pygame.display.get_surface()
		
		# Isometric mode flag
		self.isometric_mode = True

		# -- world seed --
		# New games roll a fresh seed; saves carry their own, else WORLD_SEED.
		if save_data is not None:
			stored = save_data.get('world_seed')
			self.world_seed = stored if isinstance(stored, int) else WORLD_SEED
		else:
			env_seed = os.environ.get('PYDEW_WORLD_SEED')
			try:
				self.world_seed = (int(env_seed) if env_seed is not None
				                   else randint(1, 2 ** 31 - 1))
			except ValueError:
				self.world_seed = randint(1, 2 ** 31 - 1)

		# groups
		self.all_sprites = CameraGroup()
		self.collision_sprites = pygame.sprite.Group()
		self.tree_sprites = pygame.sprite.Group()
		self.flower_sprites = pygame.sprite.Group()
		self.rock_sprites = pygame.sprite.Group()
		self.bush_sprites = pygame.sprite.Group()
		self.flower_sprites = pygame.sprite.Group()
		self.bed_sprites = pygame.sprite.Group()
		self.bridge_sprites = pygame.sprite.Group()
		self._bridged_tiles = set()
		self.interaction_sprites = pygame.sprite.Group()

		try:
			# Full slab art drawn in the ground pass at tile depth, so it sits flush.
			self.bridge_surf = pygame.image.load(
				asset_path('graphics', 'world', 'Bridge.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.bridge_surf = None

		self.soil_layer = SoilLayer(self.all_sprites, self.collision_sprites)

		# time
		self.time_manager = TimeManager()
		self.soil_layer.time_manager = self.time_manager

		# -- cave world space (swapped in/out through the sleep Transition) --
		# Two group sets coexist: the inactive scene freezes in its own groups.
		self.scene = 'overworld'
		self.return_pos = None          # overworld entrance to return to
		self.return_level = 0
		self._transition_pending = False
		self._pending_scene = None
		self._pending_restore_pos = None
		self._cave_dark = None
		self.cave_sprites = CameraGroup()
		self.cave_sprites.isometric_mode = True
		self.cave_collision = pygame.sprite.Group()
		self.cave_interaction = pygame.sprite.Group()
		# cave_prop_sprites: rocks/ores (pickaxe); cave_decor_sprites: breakables.
		self.cave_prop_sprites = pygame.sprite.Group()
		self.cave_decor_sprites = pygame.sprite.Group()
		self.cave_stub_sprites = pygame.sprite.Group()
		# Cave decks are per-visit: never written to the save.
		self.cave_bridge_sprites = pygame.sprite.Group()
		self._cave_bridged_tiles = set()
		self.cave_gen = CaveGenerator(
			self.cave_sprites, self.cave_collision,
			self.cave_interaction, self.player_add,
			prop_sprites = self.cave_prop_sprites,
			decor_sprites = self.cave_decor_sprites,
			seed = self.world_seed)
		self.cave_sprites.world_gen = self.cave_gen
		self._setup_cave_exit()

		self.setup()
		# stable overworld references for swapping back
		self.overworld_camera = self.all_sprites
		self.overworld_world_gen = self.world_gen

		# Planted trees live outside chunk gen: they persist across scene swaps.
		self.sapling_surfs = load_overlay_icons(SAPLING_ITEMS)
		self.growth_frames = {}
		for item, folder in SAPLING_GROWTH_FOLDERS.items():
			frames = import_folder(asset_path('graphics', 'Growing', folder))
			if frames:
				self.growth_frames[item] = frames
		self.planted_trees = []
		self.planted_tiles = set()

		self.overlay = Overlay(self.player, self.time_manager)
		self.instruction_panel = InstructionPanel(self.display_surface)
		self.transition = Transition(self.reset, self.player)

		# sky
		self.rain = Rain(self.all_sprites)
		self.snow = Snow(self.all_sprites)
		self.raining = False
		self.rain_days_left = 0
		self.soil_layer.raining = self.raining
		self.sky = Sky(self.time_manager)

		# shop
		self.shop_menu = ShopMenu(self.player, self.toggle_shop)
		self.shop_active = False

		# crafting
		self.crafting_menu = CraftingMenu(self.player, self.toggle_crafting)
		self.crafting_active = False

		# villager trading
		self.villager_menu = VillagerMenu(self.player, self.toggle_villager)
		self.villager_active = False

		# inventory
		self.inventory_menu = InventoryMenu(self.player, self.toggle_inventory)
		self.inventory_active = False

		# town hall quest board
		self.quest_menu = QuestMenu(
			self.player, self.toggle_quests, self.on_heart_placed,
			self.replay_credits)
		self.quest_active = False
		self.credits = None
		self.credits_active = False
		self._credits_at = None

		# pause menu
		self.pause_menu = PauseMenu(self.display_surface, self.toggle_pause, self)
		self.pause_active = False
		self._pause_consumed = False
		self.menu_btn_font = ui_font(28 * HUD_SCALE)
		self.menu_btn_cooldown = 300
		self.menu_btn_last = 0
		self.menu_btn_hover = False
		self.quit_to_menu = False
		self.menu_btn_img = self._load_menu_button()

		hud = HUD_SCALE
		self.coords_font = ui_font(28 * HUD_SCALE)
		self.coords_top = 0
		# The panel follows the current readings (see _coords_layout);
		# this is only the initial size before the first frame is drawn.
		self.coords_panel_raw = None
		self.coords_panel_img = None
		self._coords_panel_cache = None
		self._coords_slices = None
		base_w = int(165 * hud)
		base_h = int(63 * hud)
		try:
			self.coords_panel_raw = pygame.image.load(
				asset_path('graphics', 'UI', 'panel.png')).convert_alpha()
			self._coords_slices = horizontal_slice_bounds(self.coords_panel_raw)
			base_w = max(base_w, int(self.coords_panel_raw.get_width() * 3 * hud))
			base_h = int(self.coords_panel_raw.get_height() * 3 * hud)
			self._stretch_coords_panel((base_w, base_h))
		except (pygame.error, FileNotFoundError) as exc:  # optional panel; say why
			print(f"[Level] UI/panel.png load failed, drawing plain coords panel: {exc!r}")
		# remembered for the no-art fallback in _draw_coordinates
		self.coords_base_size = (base_w, base_h)
		self.coords_panel_size = (base_w, base_h)
		self.coords_panel_rect = pygame.Rect(
			self.display_surface.get_width() - base_w, self.coords_top, base_w, base_h)
		if self.menu_btn_img:
			self.menu_button_rect = self.menu_btn_img.get_rect(
				midright=(self.coords_panel_rect.left - int(8 * hud),
				          self.coords_panel_rect.centery))
		else:
			self.menu_button_rect = pygame.Rect(0, 0, int(95 * hud), int(40 * hud))
			self.menu_button_rect.midright = (
				self.coords_panel_rect.left - int(8 * hud),
				self.coords_panel_rect.centery)
		self.overlay.potion_top = self.coords_top + base_h
		# potion timer cards share this column and the panel's width
		self.overlay.potion_card_width = base_w

		self.block_font = ui_font(36)

		# debug overlay (F5) + its control panel (rain/season/time/coords)
		self.debug_mode = False
		self._debug_key_time = 0
		self.debug_controls = DebugControls()
		# Inventory snapshot taken when DEMO went on (None off); saves keep real items.
		self._demo_inv_snapshot = None

		# camera mode (F3 toggle) - hides UI/player/selector, auto-screenshots clean game view
		self.camera_mode = False
		self._camera_key_time = 0
		self._camera_shot_pending = False

		if save_data:
			self.apply_save_data(save_data)

		music_vol, sfx_vol = self._load_volumes()
		# music
		self.success = load_sound(asset_path('audio', 'success.wav'))
		self.success.set_volume(sfx_vol * 0.3)
		self.music = load_sound(asset_path('audio', 'music.mp3'))
		self.music.set_volume(music_vol)
		self.music.play(loops = -1)

		# Tutorial: new games start at 0; saves resume or rebuild their step.
		self.tutorial_step = self._resume_tutorial_step(save_data)
		self.tutorial_enabled = self.tutorial_step < len(TUTORIAL_STEPS)
		self._tutorial_hooks = {
			'wood': self.player.inventory.count_any(WOOD_ITEMS),
			'rock': self.player.inventory.count('rock'),
			'stick': self.player.inventory.count('stick'),
			'axe': self.player.inventory.count('axe'),
			'pickaxe': self.player.inventory.count('pickaxe'),
			'bucket': self.player.inventory.count('water_bucket'),
		}
		# New-game movement toast rides the sticky layer above the tutorial step.
		if save_data is None:
			self.instruction_panel.show_opening(
				f'Move with {self._movement_keys()} to walk around '
				'the valley.', duration=8)

		# Hint state: last hotbar item, categories explained, end-game note flags.
		self._last_selected_item = None
		self._selection_hints_shown = set()
		self._heart_hint_shown = False
		self._all_quests_hint_shown = False

	def _load_volumes(self):
		try:
			with open(VOLUME_SETTINGS_PATH, 'r') as f:
				data = json.load(f)
				return data.get('music', 0.5), data.get('sfx', 0.5)
		except (FileNotFoundError, json.JSONDecodeError):
			return 0.5, 0.5

	def _load_menu_button(self):
		try:
			img = pygame.image.load(asset_path('graphics', 'UI', 'menu.png')).convert_alpha()
			w, h = img.get_size()
			normal = img.subsurface((0, 0, w // 2, h))
			hovered = img.subsurface((w // 2, 0, w // 2, h))
			scale = 2 * HUD_SCALE
			self.menu_btn_normal = pygame.transform.scale(
				normal, (int(normal.get_width() * scale),
				         int(normal.get_height() * scale)))
			self.menu_btn_hovered = pygame.transform.scale(
				hovered, (int(hovered.get_width() * scale),
				          int(hovered.get_height() * scale)))
			return self.menu_btn_normal
		except (pygame.error, FileNotFoundError):
			return None

	def teleport_to(self, kind):
		"""Debug Teleport: move the player to the nearest matching spot (village /
		one biome region / cave entrance). Already inside the chosen kind? It
		picks the next nearest instead of staying still.
		"""
		from settings import (VILLAGE_SECTOR_SIZE, CAVE_SECTOR_SIZE,
		                      TILE_SIZE)
		if self.scene == 'cave' and kind != 'cave':
			return False
		player = self.player
		cur_gx = player.rect.centerx // TILE_SIZE
		cur_gy = player.rect.centery // TILE_SIZE
		cands = []
		wg = self.world_gen
		if kind == 'spawn':
			target = None
			if not wg.is_water_at(0, 0):
				target = (0, 0)
			else:
				found = None
				for r in range(1, 120):
					for dx in range(-r, r + 1):
						for dy in range(-r, r + 1):
							if max(abs(dx), abs(dy)) != r:
								continue
							gx, gy = dx, dy
							try:
								if not wg.is_water_at(gx, gy):
									found = (gx, gy)
							except Exception:
								pass
							if found is not None:
								break
						if found is not None:
							break
					if found is not None:
						break
				target = found
			if target is None:
				return False
			cands = [target]
		elif kind == 'village':
			vg = self.village_gen
			sx0 = cur_gx // VILLAGE_SECTOR_SIZE
			sy0 = cur_gy // VILLAGE_SECTOR_SIZE
			for sx in range(sx0 - 3, sx0 + 4):
				for sy in range(sy0 - 3, sy0 + 4):
					spec = vg._sector_village(sx, sy)
					if spec:
						cx, cy = spec['center']
						cands.append((cx + 1, cy + 3))
		elif kind == 'cave':
			sec = CAVE_SECTOR_SIZE
			sx0 = cur_gx // sec
			sy0 = cur_gy // sec
			for sx in range(sx0 - 4, sx0 + 5):
				for sy in range(sy0 - 4, sy0 + 5):
					try:
						spot = wg._sector_entrance(sx, sy)
					except Exception:
						spot = None
					if spot:
						cands.append(spot)
		else:
			bmap = {'oak': 'Oak_Woods', 'birch': 'Birch_Forest',
			        'cherry': 'Cherry_Blossom', 'pine': 'Snowy_Pine'}
			target = bmap.get(kind)
			if target is None:
				return False
			have = 0
			r = 0
			MAXR = 700
			while r < MAXR and have < 6:
				for dx in range(-r, r + 1):
					for dy in range(-r, r + 1):
						if max(abs(dx), abs(dy)) != r:
							continue
						gx, gy = cur_gx + dx, cur_gy + dy
						try:
							if (wg.biome_at(gx, gy) == target
									and not wg.is_water_at(gx, gy)):
								cands.append((gx, gy))
								have += 1
								if have >= 6:
									break
						except Exception:
							pass
					if have >= 6:
						break
				r += 1
		if not cands:
			return False
		seen = set()
		uniq = []
		for t in cands:
			if t not in seen:
				seen.add(t)
				uniq.append(t)
		uniq.sort(key=lambda t: (t[0]-cur_gx)**2 + (t[1]-cur_gy)**2)
		chosen = None
		for t in uniq:
			d2 = (t[0]-cur_gx)**2 + (t[1]-cur_gy)**2
			if d2 > 16*16:
				chosen = t
				break
		if chosen is None:
			chosen = uniq[1] if len(uniq) > 1 else uniq[0]
		gx, gy = chosen
		player.direction.update(0, 0)
		player.world_direction.update(0, 0)
		player.pos.update(gx * TILE_SIZE + TILE_SIZE // 2,
		                  gy * TILE_SIZE + TILE_SIZE // 2)
		player.rect.center = (round(player.pos.x), round(player.pos.y))
		player.hitbox.center = player.rect.center
		player.target_grid = None
		player.target_object = None
		# A teleport crosses chunks at once; flush the ring now, villages first.
		if self.scene == 'overworld':
			try:
				if self.village_gen is not None:
					self.village_gen.update(player.pos)
				wg.flush_chunks(player.pos, self.isometric_mode)
			except Exception as exc:
				print(f"[Level] teleport chunk flush failed: {exc!r}")
		return True

	def _stretch_coords_panel(self, size):
		"""Widen the panel at a fixed height without distorting it.

		Uses the shared horizontal 9-slice: both end caps keep their
		normal size and only the flat middle stretches, so the art looks
		the same however long the readings get.
		"""
		if self.coords_panel_img is not None and self._coords_panel_cache == size:
			return self.coords_panel_img
		self.coords_panel_img = stretch_horizontal(
			self.coords_panel_raw, size, self._coords_slices)
		self._coords_panel_cache = size
		return self.coords_panel_img

	def _coords_layout(self, x_text, y_text):
		"""Panel size and text centres for the current readings: the art
		grows with the text, with a fixed margin so the digits stay clear
		of the rounded ends."""
		x_w = self.coords_font.size(x_text)[0]
		y_w = self.coords_font.size(y_text)[0]
		pad = int(24 * HUD_SCALE)
		gap = int(20 * HUD_SCALE)
		base_w, base_h = getattr(self, 'coords_base_size', (165, 63))
		width = max(base_w, pad * 2 + x_w + y_w + gap)
		# Centre the pair; the fixed margins are the minimum on each side.
		content = x_w + gap + y_w
		start = (width - content) // 2
		return width, base_h, start + x_w // 2, start + x_w + gap + y_w // 2

	def _draw_coordinates(self):
		sw, sh = self.display_surface.get_size()
		x = self.player.rect.centerx // TILE_SIZE
		y = self.player.rect.centery // TILE_SIZE
		x_text, y_text = f'X: {x}', f'Y: {y}'
		panel_w, panel_h, x_cx, y_cx = self._coords_layout(x_text, y_text)

		if self.coords_panel_raw:
			self._stretch_coords_panel((panel_w, panel_h))
			rect = self.coords_panel_img.get_rect(
				topright=(sw, self.coords_top))
			self.display_surface.blit(self.coords_panel_img, rect)
		else:
			rect = pygame.Rect(sw - panel_w, self.coords_top,
			                   panel_w, panel_h)
			pygame.draw.rect(self.display_surface, (231, 207, 162), rect, 0, 8)
			pygame.draw.rect(self.display_surface, (168, 119, 73), rect, 3, 8)
		self.coords_panel_rect = rect
		self.coords_panel_size = (panel_w, panel_h)
		# potion cards share the coords column, so keep them aligned
		self.overlay.potion_card_width = panel_w

		cy = rect.centery + int(3 * HUD_SCALE)
		self._blit_coords_text(x_text, (rect.left + x_cx, cy))
		self._blit_coords_text(y_text, (rect.left + y_cx, cy))

	def _blit_coords_text(self, text, center):
		surf = self.coords_font.render(text, False, (92, 58, 30))
		self.display_surface.blit(surf, surf.get_rect(center=center))

	def setup(self):
		tmx_data = load_map(asset_path('data', 'map.tmx'))

		# Player 
		for obj in tmx_data.get_layer_by_name('Player'):
			if obj.name == 'Start':
				self.player = Player(
					pos = (obj.x,obj.y), 
					group = self.all_sprites, 
					collision_sprites = self.collision_sprites,
					tree_sprites = self.tree_sprites,
					rock_sprites = self.rock_sprites,
					bush_sprites = self.bush_sprites,
					flower_sprites = self.flower_sprites,
					bed_sprites = self.bed_sprites,
					interaction = self.interaction_sprites,
					soil_layer = self.soil_layer,
					toggle_shop = self.toggle_shop,
					try_sleep = self.try_sleep,
					toggle_crafting = self.toggle_crafting,
					toggle_inventory = self.toggle_inventory,
					level = self)
			
			if obj.name == 'Bed':
				Interaction((obj.x,obj.y), (obj.width,obj.height), self.interaction_sprites, obj.name)

		# world generator; cave entrances land in interaction_sprites
		self.world_gen = WorldGenerator(self.all_sprites, self.collision_sprites, self.tree_sprites, self.rock_sprites, self.bush_sprites, self.flower_sprites, self.player_add, interaction_sprites = self.interaction_sprites, seed = self.world_seed)
		self.world_gen.player = self.player
		self.all_sprites.world_gen = self.world_gen
		self.all_sprites.isometric_mode = self.isometric_mode
		self.soil_layer.world_gen = self.world_gen

		# Villages stream around the player; set the reference before chunk gen.
		self.village_gen = VillageGenerator(
			self.all_sprites, self.collision_sprites,
			self.interaction_sprites, self.world_gen, self.time_manager,
			seed = self.world_seed)
		self.world_gen.village_gen = self.village_gen

		# Ensure player spawns on dry land
		self._safe_spawn()

		# Build the opening chunk ring at once; streaming is one step per frame.
		self.world_gen.flush_chunks(self.player.pos, self.isometric_mode)

	def inventory_is_full(self, item=None, count=1):
		"""True when the bag cannot take `count` more of `item`.
		With no item given, reports whether the bag is full for anything at all.
		"""
		inv = self.player.inventory
		if item is None:
			return not inv.has_room()
		return not inv.can_add(item, count)

	def player_add(self,item):
		# Loot lands in the hotbar first (Player.add_loot); overflow hits the bag.
		if self.player.add_loot(item, 1) == 0:
			self.success.play()
			return True
		play_error()
		self.show_inventory_full()
		return False

	def _give_item(self, item, count=1):
		remaining = self.player.add_loot(item, count)
		if remaining:
			if remaining == count:
				# nothing fit in the bag: tell the player why
				self.show_inventory_full()
			self.drop_item(item, remaining)

	def drop_item(self, item, count=1, throw=None):
		"""Leave `count` of `item` floating on the ground in front of
		the player (``throw`` = world-px direction to toss it in)."""
		count = int(count)
		if count <= 0:
			return
		from sprites import DroppedItem
		DroppedItem(
			pos=self.player.rect.center,
			item=item,
			count=count,
			groups=self.all_sprites,
			level_ref=self,
			throw=throw)

	def is_planted_tile(self, gx, gy):
		return (gx, gy) in self.planted_tiles

	# -- bridges -----------------------------------------------------
	def _bridge_tiles(self, scene=None):
		"""The walkable-tile set for a scene (defaults to the active one)."""
		scene = self.scene if scene is None else scene
		if scene == 'cave':
			return self._cave_bridged_tiles
		return self._bridged_tiles

	def _spawn_bridge(self, gx, gy, scene=None):
		"""Create the bridge sprite for one tile and remember the tile
		as walkable. Returns the sprite (or None if art is missing)."""
		if self.bridge_surf is None:
			return None
		scene = self.scene if scene is None else scene
		key = (int(gx), int(gy))
		tiles = self._bridge_tiles(scene)
		if key in tiles:
			return None
		px = key[0] * TILE_SIZE + TILE_SIZE // 2
		py = key[1] * TILE_SIZE + TILE_SIZE // 2
		w, h = self.bridge_surf.get_size()
		if scene == 'cave':
			groups = [self.cave_sprites, self.cave_bridge_sprites]
		else:
			groups = [self.overworld_camera, self.bridge_sprites]
		bridge = PlaceableBridge(
			pos=(px - w // 2, py - h // 2),
			surf=self.bridge_surf,
			groups=groups,
			level_ref=self,
			tile=key,
			scene=scene,
			player_add=self.player_add)
		tiles.add(key)
		return bridge

	def place_bridge(self, target_pos):
		"""Place a bridge on the water (overworld) or lava (cave) tile
		under the cursor. The item is only consumed by the caller when
		this returns True."""
		if self.bridge_surf is None or self.scene not in ('overworld', 'cave'):
			return False
		wg = getattr(self, 'world_gen', None)
		if wg is None:
			return False
		gx = int(target_pos[0]) // TILE_SIZE
		gy = int(target_pos[1]) // TILE_SIZE
		if (gx, gy) in self._bridge_tiles():
			return False
		if not wg.is_water_at(gx, gy):
			return False
		return self._spawn_bridge(gx, gy) is not None

	def is_bridged(self, gx, gy):
		"""True when a bridge makes this water/lava tile walkable."""
		if self.scene not in ('overworld', 'cave'):
			return False
		return (int(gx), int(gy)) in self._bridge_tiles()

	def break_bridge(self, gx, gy, scene=None):
		"""A deck was chopped apart: its tile is open water/lava again.
		Dropping the tile from the scene's set re-arms the collider and keeps the
		deck out of the saved bridge list, so the break persists.
		"""
		self._bridge_tiles(scene).discard((int(gx), int(gy)))

	def _clear_cave_bridges(self, refund=False):
		"""Remove every cave deck. Called when the cave is entered/left:
		each cave visit starts fresh, so decks never persist in a save."""
		bridges = list(self.cave_bridge_sprites)
		if not bridges:
			self._cave_bridged_tiles.clear()
			return
		for bridge in bridges:
			bridge.kill()
		self.cave_bridge_sprites.empty()
		self._cave_bridged_tiles.clear()
		if refund:
			# Refund the planks; leftovers drop at the overworld return spot.
			self._give_item('bridge', len(bridges))

	def serialize_bridges(self):
		return [[gx, gy] for gx, gy in sorted(self._bridged_tiles)]

	def restore_bridges(self, entries):
		if not isinstance(entries, (list, tuple)):
			return
		for entry in entries:
			try:
				gx, gy = int(entry[0]), int(entry[1])
			except (TypeError, ValueError, IndexError):
				continue
			self._spawn_bridge(gx, gy, 'overworld')

	def can_plant_sapling_at(self, gx, gy):
		"""Saplings need a free dry overworld tile: no collision sprite,
		village reserve, cave trigger, tilled soil or existing planting."""
		if self.scene != 'overworld':
			return False
		wg = self.overworld_world_gen
		if wg.is_water_at(gx, gy):
			return False
		if (gx, gy) in self.planted_tiles:
			return False
		if self.village_gen.is_reserved_tile(gx, gy):
			return False
		cell = self.soil_layer._cell(gx, gy)
		if cell is not None and ('X' in cell or 'P' in cell):
			return False
		tile = pygame.Rect(gx * TILE_SIZE, gy * TILE_SIZE,
		                   TILE_SIZE, TILE_SIZE)
		for sprite in self.collision_sprites.sprites():
			hitbox = getattr(sprite, 'hitbox', None) or sprite.rect
			if hitbox.colliderect(tile):
				return False
		for sprite in self.interaction_sprites.sprites():
			if sprite.rect.colliderect(tile):
				return False
		return True

	def plant_sapling(self, item, pos):
		"""Plant a sapling item at a target world position. Returns True
		when a growing-tree sprite was created."""
		if item not in SAPLING_ITEMS:
			return False
		gx = int(pos[0]) // TILE_SIZE
		gy = int(pos[1]) // TILE_SIZE
		if not self.can_plant_sapling_at(gx, gy):
			return False
		record = {
			'x': gx * TILE_SIZE + TILE_SIZE // 2,
			'y': gy * TILE_SIZE + TILE_SIZE // 2,
			'sapling': item,
			'elapsed_minutes': 0.0,
		}
		self.planted_trees.append(record)
		self.planted_tiles.add((gx, gy))
		self.overworld_world_gen.planted_tiles.add((gx, gy))
		self._spawn_growing_tree(record, 0.0)
		try:
			self.soil_layer.plant_sound.play()
		except Exception as exc:  # a dead sound must not block planting
			log_once('[Level] plant sound error', exc)
		return True

	def _spawn_growing_tree(self, record, elapsed):
		pos = (record['x'], record['y'])
		frames = list(self.growth_frames.get(record['sapling'], ()))
		if not frames:
			mature = self.overworld_world_gen.tree_surf_for_sapling(
				record['sapling'])
			sapling = self.sapling_surfs.get(record['sapling'])
			frames = [s for s in (sapling, mature) if s]
		if not frames:
			placeholder = pygame.Surface((48, 48), pygame.SRCALPHA)
			pygame.draw.ellipse(placeholder, (90, 160, 70),
			                    (8, 16, 32, 28))
			frames = [placeholder]
		grower = GrowingTree(
			pos, frames, [self.overworld_camera], self, record, elapsed)
		record['grower'] = grower

	def finish_growing_tree(self, grower):
		record = grower.record
		grower.kill()
		record.pop('grower', None)
		record['elapsed_minutes'] = TREE_GROWTH_MINUTES
		self._spawn_planted_tree(record)

	def _spawn_planted_tree(self, record):
		frames = self.growth_frames.get(record['sapling'], ())
		surf = frames[-1] if frames else \
			self.overworld_world_gen.tree_surf_for_sapling(record['sapling'])
		if surf is None:
			return
		biome = SAPLING_BIOMES.get(record['sapling'])
		wood_item = BIOMES.get(biome, {}).get('wood_item', 'wood')
		tree = Tree(
			pos=(record['x'], record['y']),
			surf=surf,
			groups=[self.overworld_camera, self.collision_sprites,
			        self.tree_sprites],
			player_add=self.player_add,
			wood_yield=tree_wood_yield(surf.get_width()),
			wood_item=wood_item,
			sapling_item=record['sapling'],
			on_removed=lambda _tree_id, rec=record:
				self._forget_planted_tree(rec))
		record['tree'] = tree

	def _forget_planted_tree(self, record):
		# Chopped planted tree: drop its record; Tree.check_death dropped the sapling.
		if record in self.planted_trees:
			self.planted_trees.remove(record)
		gx = int(record['x']) // TILE_SIZE
		gy = int(record['y']) // TILE_SIZE
		self.planted_tiles.discard((gx, gy))
		self.overworld_world_gen.planted_tiles.discard((gx, gy))
		record.pop('grower', None)
		record.pop('tree', None)

	def serialize_planted_trees(self):
		out = []
		for record in self.planted_trees:
			out.append({
				'x': record['x'],
				'y': record['y'],
				'sapling': record['sapling'],
				'elapsed_minutes': round(
					float(record.get('elapsed_minutes', 0.0)), 3),
			})
		return out

	def restore_planted_trees(self, entries):
		for entry in entries or ():
			item = entry.get('sapling')
			if item not in SAPLING_ITEMS:
				continue
			try:
				x = float(entry['x'])
				y = float(entry['y'])
				if 'elapsed_minutes' in entry:
					elapsed = float(entry['elapsed_minutes'])
				else:
					# Pre-game-time saves stored real seconds.
					elapsed = (float(entry.get('elapsed', 0.0))
					           / max(0.001, TREE_GROWTH_SECONDS)
					           * TREE_GROWTH_MINUTES)
			except (KeyError, TypeError, ValueError):
				continue
			gx = int(x) // TILE_SIZE
			gy = int(y) // TILE_SIZE
			record = {'x': x, 'y': y, 'sapling': item,
			          'elapsed_minutes': max(0.0, elapsed)}
			self.planted_trees.append(record)
			self.planted_tiles.add((gx, gy))
			self.overworld_world_gen.planted_tiles.add((gx, gy))
			if elapsed >= TREE_GROWTH_MINUTES:
				record['elapsed_minutes'] = TREE_GROWTH_MINUTES
				self._spawn_planted_tree(record)
			else:
				self._spawn_growing_tree(record, elapsed)

	def _safe_spawn(self):
		"""If the TMX spawn point is on water, find the nearest dry tile and move the player."""
		gx = int(self.player.pos.x) // TILE_SIZE
		gy = int(self.player.pos.y) // TILE_SIZE

		if not self.world_gen.is_water_at(gx, gy):
			return

		# Spiral search outward from spawn for nearest dry land
		for radius in range(1, 50):
			found = None
			for dx in range(-radius, radius + 1):
				for dy in (-radius, radius):
					if not self.world_gen.is_water_at(gx + dx, gy + dy):
						found = (gx + dx, gy + dy)
						break
				if found:
					break
			if not found:
				for dy in range(-radius, radius + 1):
					for dx in (-radius, radius):
						if not self.world_gen.is_water_at(gx + dx, gy + dy):
							found = (gx + dx, gy + dy)
							break
					if found:
						break
			if found:
				new_wx = found[0] * TILE_SIZE + TILE_SIZE // 2
				new_wy = found[1] * TILE_SIZE + TILE_SIZE // 2
				self.player.pos = pygame.math.Vector2(new_wx, new_wy)
				self.player.rect.center = (new_wx, new_wy)
				self.player.hitbox.center = (new_wx, new_wy)
				return

	def toggle_shop(self):
		if self.shop_active:
			self.shop_active = False
		else:
			self.shop_menu.open()
			self.shop_active = True

	# ---- CAVE WORLD SPACE ----

	def _setup_cave_exit(self):
		"""Lift platform back to the surface - native-size art bottom-anchored
		slightly below the CAVE_EXIT_TILE so the platform face sits on the pad
		diamond, walled off by its own collision bands.
		"""
		try:
			surf = pygame.image.load(asset_path('graphics', 'Caves', 'Cave_Exit.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			surf = None

		gx, gy = CAVE_EXIT_TILE
		if surf is not None:
			wx = gx * TILE_SIZE + TILE_SIZE // 2
			wy = gy * TILE_SIZE + TILE_SIZE // 2
			# Rect centred on the pad tile for depth sort; z below 'main' keeps the player in front.
			platform = Generic(
				pos = (wx - surf.get_width() // 2, wy - surf.get_height() // 2),
				surf = surf,
				groups = [self.cave_sprites],
				z = LAYERS['rain floor'])
			# TILE_SIZE//4 world px deep == TILE_SIZE//16 screen px down
			platform.foot_pad = visible_bottom_pad(surf) + TILE_SIZE // 16
			# occlusion_bands walls lift overdraw; the pad tile stays walkable.
			for x0, y0, w, h in occlusion_bands(surf, platform.foot_pad):
				blocker = Generic(
					pos = (wx + x0, wy + y0),
					surf = pygame.Surface((2, 2), pygame.SRCALPHA),
					groups = [self.cave_collision],
					z = 0)
				blocker.hitbox = pygame.Rect(wx + x0, wy + y0, w, h)
		# Trigger: 3x3 tiles around the lift so ENTER shows within one tile of it.
		Interaction((gx * TILE_SIZE - TILE_SIZE, gy * TILE_SIZE - TILE_SIZE),
		            (TILE_SIZE * 3, TILE_SIZE * 3),
		            self.cave_interaction, 'CaveExit')

	def request_cave_transition(self, target_scene, restore_pos=None):
		"""Fade to black with the existing sleep Transition, then swap
		scenes at full black (the callback slot is borrowed exactly like
		bed sleep uses it). Returns False if nothing happened."""
		if self._transition_pending or self.player.sleep:
			return False
		if target_scene == self.scene:
			return False
		self._transition_pending = True
		self._pending_scene = target_scene
		self._pending_restore_pos = restore_pos
		if target_scene == 'cave':
			# remember which overworld entrance we came through
			self.return_pos = (self.player.pos.x, self.player.pos.y)
		self.transition.reset = self._do_pending_swap
		self.player.direction = pygame.math.Vector2()
		base = 'down'
		for name in ('up_left', 'up_right', 'down_left', 'down_right',
		             'up', 'down', 'left', 'right'):
			if self.player.status.startswith(name):
				base = name
				break
		self.player.status = base + '_idle'
		self.player.sleep = True
		return True

	def _do_pending_swap(self):
		"""Transition callback — runs at full black, then the fade back in
		unlocks the player (Transition also re-activates the interact
		timer, debouncing the trigger we are standing on)."""
		self.transition.reset = self.reset  # bed sleep keeps working
		scene = self._pending_scene
		restore = self._pending_restore_pos
		self._pending_scene = None
		self._pending_restore_pos = None
		self._transition_pending = False
		if scene:
			self._swap_scene(scene, restore)

	def _swap_scene(self, scene, restore_pos=None):
		"""Point the active camera group / world generator / player group
		references at the target scene. The inactive scene's sprites stay
		exactly where they are (frozen), so returning restores everything."""
		player = self.player
		if scene == 'cave':
			# Every cave visit is a fresh run: props reroll and old decks clear.
			self._clear_cave_bridges()
			self.cave_gen.reset_props()
			if restore_pos is not None:
				px, py = restore_pos
			else:
				# spawn on the cave exit platform at the top-left
				gx, gy = CAVE_EXIT_TILE
				px = gx * TILE_SIZE + TILE_SIZE // 2
				py = gy * TILE_SIZE + TILE_SIZE // 2
			player.pos = pygame.math.Vector2(px, py)
			player.rect.center = (round(px), round(py))
			player.hitbox.center = player.rect.center

			self.scene = 'cave'
			self.world_gen = self.cave_gen
			self.all_sprites = self.cave_sprites
			if player not in self.cave_sprites:
				self.cave_sprites.add(player)
			player.collision_sprites = self.cave_collision
			player.interaction = self.cave_interaction
			# rock_sprites: ores (pickaxe); tree_sprites: breakable decor (axe/punch).
			player.rock_sprites = self.cave_prop_sprites
			player.tree_sprites = self.cave_decor_sprites
			player.bush_sprites = self.cave_stub_sprites
			player.flower_sprites = self.cave_stub_sprites
			player.bed_sprites = self.cave_stub_sprites
			# axe-breakable cave decks
			player.bridge_sprites = self.cave_bridge_sprites
		else:
			if restore_pos is not None:
				px, py = restore_pos
			elif self.return_pos is not None:
				px, py = self.return_pos
			else:
				px, py = 1561, 1772  # TMX start (defensive fallback)
			# stand one tile in front of the doorway, not on its trigger
			py += TILE_SIZE
			player.pos = pygame.math.Vector2(px, py)
			player.rect.center = (round(px), round(py))
			player.hitbox.center = player.rect.center

			self.scene = 'overworld'
			self.world_gen = self.overworld_world_gen
			self.all_sprites = self.overworld_camera
			self.cave_sprites.remove(player)
			player.collision_sprites = self.collision_sprites
			player.interaction = self.interaction_sprites
			player.tree_sprites = self.tree_sprites
			player.rock_sprites = self.rock_sprites
			player.bush_sprites = self.bush_sprites
			player.flower_sprites = self.flower_sprites
			player.bed_sprites = self.bed_sprites
			player.bridge_sprites = self.bridge_sprites
			# Leaving the cave removes its decks and returns the planks.
			self._clear_cave_bridges(refund=True)

		player.direction = pygame.math.Vector2()

	def _display_cave_darkness(self):
		"""Constant ambient dim inside the cave (drawn under the HUD)."""
		sw, sh = self.display_surface.get_size()
		if self._cave_dark is None or self._cave_dark.get_size() != (sw, sh):
			self._cave_dark = pygame.Surface((sw, sh))
			self._cave_dark.fill((0, 0, 0))
			self._cave_dark.set_alpha(CAVE_DARKNESS_ALPHA)
		self.display_surface.blit(self._cave_dark, (0, 0))

	def _player_screen_center(self):
		cam = self.all_sprites
		if self.isometric_mode:
			px = self.player.rect.centerx / TILE_SIZE
			py = self.player.rect.centery / TILE_SIZE
			x = ((px - py) * (ISO_TILE_WIDTH // 2) + 64
			     - getattr(cam, 'cam_x', 0))
			y = ((px + py) * (ISO_TILE_HEIGHT // 2)
			     - getattr(cam, 'cam_y', 0) - 38)
		else:
			offset = getattr(cam, 'offset', pygame.math.Vector2())
			x = self.player.rect.centerx - offset.x
			y = self.player.rect.centery - offset.y - 38
		return round(x), round(y)

	def _has_night_vision(self):
		return (self.player.has_potion_effect('night_vision_potion')
		        and (self.time_manager.is_night() or self.scene == 'cave'))

	def _night_vision_center(self):
		if not self._has_night_vision():
			return None
		return self._player_screen_center()

	def _display_night_vision(self):
		if self.scene != 'cave' or not self._has_night_vision():
			return
		self.overlay.draw_night_vision(self._player_screen_center())

	def _save_camera_screenshot(self):
		"""Save a clean game-only screenshot (no UI, player or selector)."""
		import os
		from datetime import datetime
		shot_dir = user_data_path('Shots')
		os.makedirs(shot_dir, exist_ok=True)
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
		path = os.path.join(shot_dir, f'camera_{timestamp}.png')
		pygame.image.save(self.display_surface, path)

	def _refresh_hint(self):
		"""Resolve the sticky hint layer each frame.
		Menu hint wins, then a nearby interaction trigger, else the layer is
		cleared so the tutorial can show.
		"""
		if self.player.sleep:
			self.instruction_panel.clear_hint()
			return

		# The hint bar does not need 60 Hz: refresh at most ~16x/s.
		now = pygame.time.get_ticks()
		sig = (self.pause_active, self.shop_active, self.crafting_active,
		       self.inventory_active, self.villager_active, self.quest_active,
		       self.scene, self.player.sleep)
		if (sig == getattr(self, '_hint_sig', None)
				and now - getattr(self, '_hint_ms', 0) < 60):
			return
		self._hint_sig = sig
		self._hint_ms = now

		hint = None
		if self.pause_active:
			hint = 'Resume to return to the valley.'
		elif self.shop_active:
			hint = ('Shop: LEFT-CLICK sells or buys one item, '
			        'RIGHT-CLICK trades a full stack.')
		elif self.crafting_active:
			hint = 'Crafting: LEFT-CLICK crafts one, RIGHT-CLICK crafts all.'
		elif self.villager_active:
			hint = 'Trading: LEFT-CLICK trades one, RIGHT-CLICK trades all.'
		elif self.inventory_active:
			hint = ('Inventory: LEFT-CLICK picks a stack, RIGHT-CLICK splits, '
			        'SHIFT+CLICK quick-moves, 1-9 sets a hotbar slot.')
		elif self.quest_active:
			# Once the heart is placed the board has nothing left to ask for.
			if not getattr(self.player, 'heart_placed', False):
				hint = 'Quest board: deliver the listed items to complete quests.'
		elif self.scene == 'cave':
			hits = pygame.sprite.spritecollide(
				self.player, self.cave_interaction, False)
			if any(getattr(s, 'name', None) == 'CaveExit' for s in hits):
				hint = 'Press ENTER to ride the lift back to the surface.'
			if hint is None:
				hint = self._near_object_hint('cave')
		else:
			hits = pygame.sprite.spritecollide(
				self.player, self.interaction_sprites, False)
			names = {getattr(s, 'name', None) for s in hits}
			use_key = input_manager.key_name(
				input_manager.get_binding('use_tool'))
			interact_key = input_manager.key_name(
				input_manager.get_binding('use_item'))
			if 'CaveEntrance' in names:
				hint = f'Press {use_key} to enter the cave.'
			elif 'TownHall' in names:
				hint = f'Press {use_key} to open the quest board.'
			elif 'VillageShop' in names:
				hint = f'Press {interact_key} to browse the shop.'
			if hint is None:
				hint = self._near_object_hint('overworld')

		self.instruction_panel.set_hint(hint)

	def _near_object_hint(self, scene):
		"""Contextual hint for whatever interactable sits under the
		player's crosshair or right next to them (villager, bush, flower,
		crop, bed, cave pot). Returns None when nothing is in range."""
		player = self.player
		use_key = input_manager.key_name(
			input_manager.get_binding('use_item'))

		if scene == 'overworld':
			# a villager close enough to talk beats everything else
			npc = self.villager_near(player.rect.center)
			if npc is not None:
				name = getattr(npc, 'name', None) or 'a villager'
				return f'{name} is nearby - press {use_key} to talk and trade.'

		target = getattr(player, 'target_pos', None)
		if target is not None:
			if scene == 'cave':
				try:
					for sprite in player.tree_sprites.sprites():
						if getattr(sprite, 'allowed_tools', None) == ('punch',) \
							   and sprite.alive \
							   and sprite.rect.collidepoint(target):
							return (f'A pot sits under the cursor - press '
							        f'{use_key} to smash it.')
				except Exception as exc:  # hint only; never spam, but surface it
					log_once('[Level] pot-hint error', exc)
				return None

			# crop under the cursor: ready to pick or still growing?
			try:
				plant = self.soil_layer.plant_at_tile(
					int(target[0]) // TILE_SIZE, int(target[1]) // TILE_SIZE)
			except Exception as exc:  # hint only; never spam, but surface it
				log_once('[Level] crop-hint error', exc)
				plant = None
			if plant is not None:
				if getattr(plant, 'harvestable', False):
					return (f'A ripe crop is under the cursor - press '
					        f'{use_key} to harvest it.')
				return 'This crop is still growing - check back later.'

			# berry bush / wild flower under the cursor
			try:
				for bush in player.bush_sprites.sprites():
					if bush.alive and bush.rect.collidepoint(target):
						return f'A berry bush is under the cursor - press {use_key} to pick it.'
				for flower in player.flower_sprites.sprites():
					if not getattr(flower, 'broken', False) \
						   and flower.rect.collidepoint(target):
						return f'A flower is under the cursor - press {use_key} to pick it.'
			except Exception as exc:  # hint only; never spam, but surface it
				log_once('[Level] bush/flower-hint error', exc)

		# a placed bed right next to you can be slept in
		px, py = player.rect.center
		try:
			for bed in player.bed_sprites.sprites():
				bx, by = bed.rect.center
				if ((bx - px) ** 2 + (by - py) ** 2
				    <= TILE_SIZE * TILE_SIZE):
					return f'A bed is right beside you - press {use_key} to sleep.'
		except Exception as exc:  # hint only; never spam, but surface it
			log_once('[Level] bed-hint error', exc)
		return None

	def _update_selection_hint(self):
		"""One-time hint when the player selects a new hotbar item."""
		player = self.player
		if not 0 <= player.hotbar_index < len(player.hotbar):
			return
		slot = player.hotbar[player.hotbar_index]
		item = slot[0] if slot else None
		if item == self._last_selected_item:
			return
		# Leave the selection unrecorded while the opening toast owns the bar.
		if self.instruction_panel.opening_active:
			return
		self._last_selected_item = item
		if item is None or self.credits_active:
			return
		template = SELECTION_HINTS.get(item)
		if template is None:
			if item in getattr(player, 'seeds', ()):
				template = ('Seeds selected: press RSHIFT on tilled soil '
				            'to plant them.')
			elif item in SAPLING_ITEMS:
				template = ('Sapling selected: press RSHIFT on clear ground '
				            'to plant the tree.')
			elif item in EDIBLE_ITEMS:
				template = ('{name} selected: press {use_item} to eat it '
				            'and restore energy.')
		if template is None:
			return
		# each item (or item category) is explained only the first time
		category = ('seed' if item in getattr(player, 'seeds', ()) else
		            'sapling' if item in SAPLING_ITEMS else
		            'food' if item in EDIBLE_ITEMS else item)
		if category in self._selection_hints_shown:
			return
		self._selection_hints_shown.add(category)
		use_key = input_manager.key_name(
			input_manager.get_binding('use_tool'))
		use_item_key = input_manager.key_name(
			input_manager.get_binding('use_item'))
		self.instruction_panel.show_message(
			template.format(use_tool=use_key, use_item=use_item_key,
			                name=item_name(item)),
			duration=5)

	def _update_quest_progress_hint(self):
		"""Heart-recipe hint once every town quest is done, then a final
		'valley restored' note once the heart has been placed."""
		player = self.player
		if (not self._heart_hint_shown
			    and heart_recipe_unlocked(
				    getattr(player, 'completed_quests', ()))
			    and not getattr(player, 'heart_placed', False)):
			self._heart_hint_shown = True
			self.instruction_panel.show_message(
				'All town quests are complete! Craft the Heart of the Valley '
				'in crafting, then place it on the quest board.', duration=10)
		if (not self._all_quests_hint_shown
			    and getattr(player, 'heart_placed', False)):
			self._all_quests_hint_shown = True
			self.instruction_panel.show_message(
				'All quests complete! The Heart of the Valley is placed and '
				'the valley is restored.', duration=10)

	def toggle_crafting(self):
		self.crafting_active = not self.crafting_active
		self._refresh_hint()

	def villager_near(self, pos):
		if self.scene != 'overworld':
			return None
		return self.village_gen.npc_near(pos, VILLAGER_TALK_RADIUS)

	def toggle_villager(self, name=None):
		if self.villager_active:
			self.villager_active = False
			self._refresh_hint()
			return
		if name and self.village_gen.is_trading_time():
			self.villager_menu.open(name)
			self.villager_active = True
			self._refresh_hint()

	def toggle_inventory(self):
		self.inventory_active = not self.inventory_active
		if not self.inventory_active:
			self.inventory_menu.return_cursor()
		self._refresh_hint()

	def toggle_quests(self):
		self.quest_active = not self.quest_active
		if self.quest_active:
			self.quest_menu.open()
		self._refresh_hint()

	def on_heart_placed(self):
		self.village_gen.set_heart_placed(True)
		self.schedule_credits()

	def schedule_credits(self):
		if getattr(self.player, 'credits_seen', False):
			return
		if self.credits_active or self._credits_at is not None:
			return
		self._credits_at = pygame.time.get_ticks() + 3000

	def update_credits_timer(self):
		if getattr(self.player, 'credits_seen', False):
			self._credits_at = None
			return
		if self._credits_at is not None \
		   and pygame.time.get_ticks() >= self._credits_at:
			self.start_credits()

	def replay_credits(self):
		if self.credits_active:
			return
		self.start_credits(force=True)

	def start_credits(self, force=False):
		self._credits_at = None
		if self.credits_active:
			return
		if not force and getattr(self.player, 'credits_seen', False):
			return
		self.quest_active = False
		self.pause_active = False
		self.shop_active = False
		self.crafting_active = False
		self.villager_active = False
		if self.inventory_active:
			self.inventory_menu.return_cursor()
		self.inventory_active = False
		self.player.credits_seen = True
		if self.credits is None:
			self.credits = CreditsScreen(self.end_credits)
		self.credits.open()
		self.credits_active = True
		save_game(self)

	def end_credits(self):
		self.credits_active = False
		self.player.credits_seen = True
		save_game(self)

	def toggle_pause(self):

		self.pause_active = not self.pause_active

	def try_sleep(self):
		h = self.time_manager.hour
		# Sleep allowed 8PM-6AM only; the F5 DEMO switch lifts the gate.
		sleep_ok = (h >= 20 or h < 6) or self.debug_demo
		if sleep_ok:
			self.player.direction = pygame.math.Vector2()
			self.player.status = 'left_idle'
			self.player.sleep = True
		else:
			self.instruction_panel.show_error(
				'You can only sleep at night(8PM-6AM)!')
			play_error()

	def force_sleep(self):
		self.player.direction = pygame.math.Vector2()
		self.player.status = 'left_idle'
		self.player.sleep = True

	def show_crop_not_ready(self):
		"""The player picked a crop that has not grown yet (error)."""
		self.crop_not_ready = True
		self.instruction_panel.show_error(
			'That crop is not ready to harvest yet.')

	def show_inventory_full(self):
		"""An item could not be added because every slot is taken (error)."""
		self.instruction_panel.show_error(
			'Inventory full! Sell, eat, or plant items to free space.')

	def _resume_tutorial_step(self, save_data):
		"""Tutorial step a loaded game resumes at (0 for a brand-new game).
		Current saves store the exact step; older ones are reconstructed from
		evidence - the highest proven step + 1.
		"""
		if not save_data:
			return 0
		stored = save_data.get('tutorial_step')
		if isinstance(stored, int):
			return max(0, min(stored, len(TUTORIAL_STEPS)))

		# End-game proof beats item evidence: an old save with credits/heart counts.
		pd = save_data.get('player') or {}
		if pd.get('credits_seen') or pd.get('heart_placed'):
			return len(TUTORIAL_STEPS)

		inv = self.player.inventory
		proven = []
		if inv.count_any(WOOD_ITEMS) > 0:
			proven.append(0)                       # punch_tree
		if inv.count('rock') > 0:
			proven.append(1)                       # punch_rock
		if inv.count('stick') > 0:
			proven.append(4)                       # craft_sticks
		if inv.count('axe') > 0 or inv.count('pickaxe') > 0:
			proven.append(5)                       # craft_tool
		if inv.count('water_bucket') > 0:
			proven.append(6)                       # craft_bucket
		if self._farm_evidence():
			proven.append(7)                       # planting
		if not proven:
			return 0
		return min(max(proven) + 1, len(TUTORIAL_STEPS))

	def _farm_evidence(self):
		"""True when the restored save shows farming work: a live plant or
		tilled / watered soil (the planting step's own condition)."""
		if len(self.soil_layer.plant_sprites) > 0:
			return True
		grid = getattr(self.soil_layer, 'grid', None)
		if grid:
			for row in grid:
				for cell in row:
					if cell and ('X' in cell or 'W' in cell or 'P' in cell):
						return True
		return False

	def _tutorial_keys(self):
		return {
			'use_tool': input_manager.key_name(
				input_manager.get_binding('use_tool')),
			'open_inventory': input_manager.key_name(
				input_manager.get_binding('open_inventory')),
			'open_crafting': input_manager.key_name(
				input_manager.get_binding('open_crafting')),
		}

	def _movement_keys(self):
		"""'W / A / S / D' built from the LIVE bindings, so rebinding
		the movement (or another keyboard layout) keeps the onboarding
		honest instead of hard-coding the letters."""
		return ' / '.join(
			input_manager.key_name(input_manager.get_binding(action))
			for action in ('move_up', 'move_left', 'move_down',
			               'move_right'))

	def _update_tutorial(self):
		"""Advance through TUTORIAL_STEPS as the player performs each action.
		The current step is kept in the panel's sticky instruction layer, so it
		stays until replaced; the hint layer (menus / triggers) overrides it."""
		if not self.tutorial_enabled or self.credits_active:
			return
		if self.tutorial_step >= len(TUTORIAL_STEPS):
			self.tutorial_enabled = False
			self.instruction_panel.clear_instruction()
			self.instruction_panel.show_message(
				'Basics complete! Explore, trade, and take on town quests.')
			return

		h = self._tutorial_hooks
		step_id, template = TUTORIAL_STEPS[self.tutorial_step]
		done = False
		inv = self.player.inventory
		if step_id == 'punch_tree':
			done = inv.count_any(WOOD_ITEMS) > h['wood']
		elif step_id == 'punch_rock':
			done = inv.count('rock') > h['rock']
		elif step_id == 'open_inventory':
			done = self.inventory_active
		elif step_id == 'open_crafting':
			done = self.crafting_active
		elif step_id == 'craft_sticks':
			done = inv.count('stick') > h['stick']
		elif step_id == 'craft_tool':
			done = (inv.count('axe') > h['axe']
			        or inv.count('pickaxe') > h['pickaxe'])
		elif step_id == 'craft_bucket':
			done = inv.count('water_bucket') > h['bucket']
		elif step_id == 'planting':
			done = len(self.soil_layer.plant_sprites) > 0

		if done:
			self.tutorial_step += 1
			return

		# Until a seed is owned, prompt to find the village, not to plant.
		has_seed = (inv.count('tomato_seed') > 0 or inv.count('wheat_seed') > 0)
		if step_id == 'planting' and not has_seed:
			msg = ('Find the village and buy seeds from the farmer '
			       '- the farmer sells wheat and tomato seeds.')
			self.instruction_panel.set_instruction(msg)
		else:
			# Keep the current step's text in the sticky instruction layer.
			self.instruction_panel.set_instruction(
				template.format(**self._tutorial_keys()))

	def save_and_quit(self):
		if self.inventory_active:
			if not self.inventory_menu.return_cursor():
				play_error()
				return False
		self.inventory_active = False
		self.quest_active = False
		self.shop_active = False
		self.crafting_active = False
		self.villager_active = False
		self.pause_active = False
		# Collect cave decks before saving so the planks reach the stored inventory.
		if self.scene == 'cave':
			self._clear_cave_bridges(refund=True)
		if not save_game(self):
			self.instruction_panel.show_error(
				'Save failed! Your progress was not saved.')
			play_error()
			return False
		if hasattr(self, 'music') and self.music:
			self.music.stop()
		self.quit_to_menu = True
		return True

	def apply_save_data(self, data):
		pd = data['player']
		self.player.pos = pygame.math.Vector2(pd['pos'][0], pd['pos'][1])
		self.player.rect.center = (pd['pos'][0], pd['pos'][1])
		self.player.hitbox.center = self.player.rect.center
		self.player.status = pd['status']
		self.player.frame_index = pd['frame_index']
		self.player.money = pd['money']
		self.player.energy = pd.get('energy', 100)
		if 'inventory' in pd:
			self.player.inventory = Inventory.from_data(pd['inventory'])
		else:
			self.player.inventory = Inventory.from_legacy(
				pd.get('item_inventory'), pd.get('seed_inventory'),
				pd.get('hotbar'))
		self.player.completed_quests = set(pd.get('completed_quests', ()))
		self.player.heart_placed = bool(pd.get('heart_placed', False))
		self.player.credits_seen = bool(pd.get('credits_seen', False))
		self.village_gen.set_heart_placed(self.player.heart_placed)
		if self.player.heart_placed and not self.player.credits_seen:
			self.schedule_credits()
		# The DEMO-only auto-stocked kit lives in set_debug_demo, not here.
		self.player.selected_tool = pd.get('selected_tool', 'hoe')
		selected_seed = pd.get('selected_seed')
		self.player.selected_seed = LEGACY_SEED_ALIASES.get(
			selected_seed, selected_seed)
		self.player._update_hotbar_selection()
		try:
			self.player.hotbar_index = min(
				8, max(0, int(pd.get('hotbar_index', 0))))
		except (TypeError, ValueError):
			self.player.hotbar_index = 0
		self.player.water_bucket_amount = pd.get('water_bucket_amount', 0)

		soil = self.soil_layer
		soil.grid = data['soil_grid']
		soil.create_soil_tiles()
		soil.create_hit_rects()

		# Rebuild garden overlays; the save stores the soil grid, not the caches.
		ow = getattr(self, 'overworld_world_gen', None)
		if ow is not None:
			for g_row, row in enumerate(soil.grid):
				for g_col, cell in enumerate(row):
					if 'X' not in cell:
						continue
					x = (g_col + soil._grid_ox) * TILE_SIZE
					y = (g_row + soil._grid_oy) * TILE_SIZE
					ow.set_farm_patch(x, y)
					if 'W' in cell:
						ow.set_soil_water(x, y)

		for row in soil.grid:
			for cell in row:
				while 'P' in cell:
					cell.remove('P')
		for pinfo in data['plants']:
			gx, gy = pinfo['grid_x'], pinfo['grid_y']
			cell = soil._cell(gx, gy)
			cell.append('P')
			soil_sprite = soil.ensure_plant_anchor(gx, gy)
			from soil import Plant
			plant = Plant(
				pinfo['plant_type'],
				[self.all_sprites, soil.plant_sprites,
				 self.collision_sprites],
				soil_sprite, soil.check_watered)
			plant.age = pinfo['age']
			plant.image = plant.frames[int(plant.age)]
			plant.rect = plant.image.get_rect(
				midbottom=plant.soil.rect.midbottom
				+ pygame.math.Vector2(0, plant.y_offset))
			if int(plant.age) > 0:
				plant.z = LAYERS['main']
				plant.hitbox = plant.rect.copy().inflate(
					-26, -plant.rect.height * 0.4)
			if plant.age >= plant.max_age:
				plant.harvestable = True

		self.raining = data.get('raining', False)
		self.rain_days_left = data.get('rain_days_left', 0)
		self.soil_layer.raining = self.raining
		self.sky.start_color = data['sky_color']
		self.sky.night = data['sky_night']

		if 'time' in data:
			t = data['time']
			self.time_manager.hour = t.get('hour', DAY_START_HOUR)
			self.time_manager.minute = t.get('minute', 0)
			self.time_manager.day = t.get('day', 1)
			self.time_manager.season_index = t.get('season', 0)
			self.time_manager.year = t.get('year', 1)
			self.time_manager.total_minutes = t.get(
				'total_minutes',
				self.time_manager.hour * 60 + self.time_manager.minute)

		soil.time_manager = self.time_manager
		soil.restore_tilled_at(
			data.get('farmland_timestamps'),
			self.time_manager.total_minutes)

		# Saves carry seconds LEFT per potion; older ones an absolute expiry.
		self.player.restore_potion_effects(pd.get('potion_effects', {}))
		self.player.update_potion_effects()

		# Apply felled-tree and planted-tree records to the overworld generators.
		ow = getattr(self, 'overworld_world_gen', None)
		if ow is not None:
			ow.apply_removed_trees(data.get('removed_trees', []))
			ow.apply_removed_debris(data.get('removed_debris', []))
			ow.apply_removed_rocks(data.get('removed_rocks', []))
		self.restore_planted_trees(data.get('planted_trees', []))
		self.restore_bridges(data.get('bridges', []))

		# scene (absent in old saves -> overworld)
		rp = data.get('return_pos')
		if rp:
			self.return_pos = (rp[0], rp[1])
		self.return_level = data.get('return_level', 0)
		if data.get('scene', 'overworld') == 'cave':
			self._swap_scene('cave', restore_pos = (pd['pos'][0], pd['pos'][1]))

	def reset(self):
		# plants
		self.soil_layer.update_plants()

		# Reset the world FIRST: it wipes the soil-water cache re-watering needs.
		if hasattr(self, 'world_gen'):
			self.world_gen.reset()

		# soil
		self.soil_layer.remove_water()

		if self.rain_days_left > 0:
			self.rain_days_left -= 1
			self.raining = self.rain_days_left > 0
		else:
			self.raining = randint(0,10) > 7
			if self.raining:
				self.rain_days_left = randint(1, 3)
		self.soil_layer.raining = self.raining
		if self.raining:
			self.soil_layer.water_all()

		# villages: unload (deterministic sites stream back in)
		self.village_gen.reset()

		# sky
		self.sky.start_color = list(get_sky_color(DAY_START_HOUR, 0))
		self.sky.night = False

		# advance time
		self.time_manager.sleep_to_morning()
		# Bushes reroll every 5 days; trees/logs/rocks keep their layout.
		if self.overworld_world_gen.tick_day():
			for bush in list(self.bush_sprites.sprites()):
				bush.kill()
		self.soil_layer.update_farmland(self.time_manager.total_minutes)
		self.player.update_potion_effects()

		try:
			save_game(self)
		except Exception as exc:  # auto-save must never crash the loop
			print(f"[Level] auto-save failed: {exc!r}")

	def harvest_crop_at(self, target_pos):
		plant = self.soil_layer.harvestable_plant_at(target_pos)
		if plant is None:
			return False
		crop = plant.plant_type
		seed = CROP_SEEDS.get(crop)
		# Full bag must not swallow the crop: check room before pulling the plant.
		amount = randint(HARVEST_YIELD_MIN, HARVEST_YIELD_MAX)
		if self.inventory_is_full(crop, amount) or (
				seed and self.inventory_is_full(seed, 1)):
			play_error()
			self.show_inventory_full()
			return False
		self.soil_layer.remove_plant(plant)
		self._give_item(crop, amount)
		if seed:
			self._give_item(seed, 1)
		break_flash(plant, z=LAYERS['main'], groups=self.all_sprites)
		try:
			self.soil_layer.plant_sound.play()
		except Exception as exc:  # a dead sound must not block harvesting
			log_once('[Level] harvest sound error', exc)
		return True

	def run(self,dt, events):

		if self.quit_to_menu:
			return

		# FPS tracker for debug overlay
		if dt > 0:
			self._last_fps = 1.0 / dt

		# custom_draw's ground pass paints the backdrop; no extra fill here.
		self.all_sprites.custom_draw(self.player, self.debug_mode, getattr(self, '_last_fps', 0), self.time_manager, self.raining, hide_player=self.camera_mode, debug_controls=self.debug_controls)
		if self.scene == 'cave':
			self._display_cave_darkness()

		self.update_credits_timer()
		if self.credits_active:
			self.credits.update(events, dt)
			if self.credits_active:
				return
			if any(e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE
			       for e in events):
				# The Esc that closed the credits must not also open the pause menu.
				self._pause_consumed = True
				self._pause_key_time = pygame.time.get_ticks()
			return

		# Camera mode shot: right after the world draw, before any UI.
		if self.camera_mode:
			if self._camera_shot_pending:
				self._camera_shot_pending = False
				self._save_camera_screenshot()
				self.camera_mode = False
		else:
			self.overlay.display(self.raining)

		# coordinates + menu button
		sw, sh = self.display_surface.get_size()
		if not self.camera_mode:
			self._draw_coordinates()
			if self.menu_btn_img:
				self.menu_button_rect = self.menu_btn_img.get_rect(
					midright=(self.coords_panel_rect.left - int(8 * HUD_SCALE),
					          self.coords_panel_rect.centery))
				self.menu_btn_hover = self.menu_button_rect.collidepoint(pygame.mouse.get_pos())
				btn_img = self.menu_btn_hovered if self.menu_btn_hover else self.menu_btn_normal
				self.display_surface.blit(btn_img, self.menu_button_rect)
			else:
				hud = HUD_SCALE
				self.menu_button_rect = pygame.Rect(0, 0, int(95 * hud), int(40 * hud))
				self.menu_button_rect.midright = (
					self.coords_panel_rect.left - int(8 * hud),
					self.coords_panel_rect.centery)
				self.menu_btn_hover = self.menu_button_rect.collidepoint(pygame.mouse.get_pos())
				btn_color = '#6a6a6a' if self.menu_btn_hover else '#4a4a4a'
				pygame.draw.rect(self.display_surface, btn_color, self.menu_button_rect, 0, 6)
				btn_surf = self.menu_btn_font.render('MENU', False, 'White')
				btn_rect = btn_surf.get_rect(center=self.menu_button_rect.center)
				self.display_surface.blit(btn_surf, btn_rect)

		now = pygame.time.get_ticks()
		if not self.camera_mode and pygame.mouse.get_pressed()[0] and now - self.menu_btn_last > self.menu_btn_cooldown:
			if self.menu_btn_hover:
				play_click()
				self.menu_btn_last = now
				self.toggle_pause()

		keys = pygame.key.get_pressed()
		pause_held = (keys[pygame.K_ESCAPE]
		              or input_manager.is_action_pressed_keys(keys, 'pause'))
		pause_key_event = any(
			e.type == pygame.KEYDOWN
			and (e.key == pygame.K_ESCAPE
			     or input_manager.is_key_for_action(e.key, 'pause'))
			for e in events)

		# Esc (or the pause key) also closes the pause menu. Settings
		# sits on top of it and handles Esc itself first.
		if (pause_key_event and self.pause_active
				and not getattr(self.pause_menu, 'settings_active', False)):
			play_click()
			self.toggle_pause()
			self._pause_consumed = True
			self._pause_key_time = pygame.time.get_ticks()

		if self._pause_consumed:
			if not pause_held:
				self._pause_consumed = False
		elif not self.pause_active and not self.shop_active and not self.crafting_active and not self.inventory_active and not self.villager_active and not self.quest_active and not getattr(self.debug_controls, 'active', False):
			if input_manager.is_action_pressed_keys(keys, 'pause'):
				# debounce via cooldown
				now2 = pygame.time.get_ticks()
				if now2 - getattr(self, '_pause_key_time', 0) > 300:
					self._pause_key_time = now2
					self.toggle_pause()

			# F5 toggles debug overlay
			if keys[pygame.K_F5]:
				now2 = pygame.time.get_ticks()
				if now2 - self._debug_key_time > 300:
					self._debug_key_time = now2
					self.debug_mode = not self.debug_mode

		menus_open = any((
			self.pause_active, self.shop_active, self.crafting_active,
			self.inventory_active, self.villager_active, self.quest_active,
			self.credits_active,
		))
		if not menus_open:
			for event in events:
				# Q: throw the held slot's item on the ground
				if (event.type == pygame.KEYDOWN
				    and input_manager.is_key_for_action(
					    event.key, 'drop_item')):
					self.player.drop_selected()
					continue
				if event.type != pygame.MOUSEWHEEL or not event.y:
					continue
				direction = -1 if event.y > 0 else 1
				self.player.hotbar_index = (
					self.player.hotbar_index + direction) % 9
				self.player._update_hotbar_selection()

		# F3 camera mode: hides UI/player/selector, saves a clean screenshot.
		if keys[pygame.K_F3]:
			now2 = pygame.time.get_ticks()
			if now2 - self._camera_key_time > 300:
				self._camera_key_time = now2
				self.camera_mode = not self.camera_mode
				if self.camera_mode:
					self._camera_shot_pending = True

		menus_before = (self.pause_active, self.shop_active,
		                self.crafting_active, self.inventory_active,
		                self.villager_active, self.quest_active)
		if self.pause_active:
			self.pause_menu.update(events)
		elif self.shop_active:
			self.shop_menu.update(events)
		elif self.crafting_active:
			self.crafting_menu.update(events)
		elif self.villager_active:
			self.villager_menu.update(events)
		elif self.inventory_active:
			self.inventory_menu.update(events)
		elif self.quest_active:
			self.quest_menu.update(events)
		else:
			# Time stands still in the cave (no day rollover underground).
			if not self.player.sleep and self.scene == 'overworld':
				self.time_manager.update(dt)

			self.all_sprites.update(dt)
			# Villages stream before the chunk ring so reserved land exists first.
			if self.scene == 'overworld':
				self.village_gen.update(self.player.pos)
			self.world_gen.update(self.player.pos, self.isometric_mode)

			# Overworld-only: farming, weather and sky tint are meaningless in the cave.
			if self.scene == 'overworld':
				self.soil_layer.update_farmland(
					self.time_manager.total_minutes)

				# weather
				if self.raining:
					self.rain.update()

				# permanent snowfall in the snowy biome (prune always runs)
				if self.world_gen:
					pgx = self.player.rect.centerx // TILE_SIZE
					pgy = self.player.rect.centery // TILE_SIZE
					in_snow = self.world_gen.biome_at(pgx, pgy) == 'Snowy_Pine'
					self.snow.update(dt, spawning=in_snow)

				self.sky.display(dt, self._night_vision_center())

			self._display_night_vision()

			# transition overlay
			if self.player.sleep:
				self.transition.play()

		# A menu closed by this frame's input must not let the same Esc
		# press fall through and toggle the pause menu too.
		menus_after = (self.pause_active, self.shop_active,
		               self.crafting_active, self.inventory_active,
		               self.villager_active, self.quest_active)
		if any(before and not after for before, after in zip(
				menus_before, menus_after)):
			if pause_held or pause_key_event:
				self._pause_consumed = True
				self._pause_key_time = pygame.time.get_ticks()

		# Instruction panel draws last, on top of world, HUD and menus.
		if not self.camera_mode:
			if not (self.inventory_active or self.crafting_active
				    or self.shop_active or self.villager_active
				    or self.quest_active or self.pause_active):
				self._update_selection_hint()
				self._update_quest_progress_hint()
			self._refresh_hint()
			self._update_tutorial()
			self.instruction_panel.update(dt)
			# Keep the bar clear of the weather panel and top-right buttons.
			weather = getattr(self.overlay, 'weather_rect', None)
			hud = HUD_SCALE
			self.instruction_panel.left_limit = (
				weather.right + int(8 * hud) if weather else 0)
			self.instruction_panel.right_limit = (
				self.menu_button_rect.left - int(8 * hud))
			self.instruction_panel.draw()

		# F5 info box: Rain/Season combos, Time/Player text boxes, above the HUD.
		self._update_debug_controls(events)

	def _update_debug_controls(self, events):
		"""Drive the editable rows of the F5 info box and keep the
		player locked whenever one of them owns the keyboard."""
		ctl = getattr(self, 'debug_controls', None)
		if ctl is None:
			return
		menus_open = any((
			self.pause_active, self.shop_active, self.crafting_active,
			self.inventory_active, self.villager_active,
			self.quest_active, self.credits_active,
		))
		active = (self.debug_mode and not self.camera_mode
		          and self.isometric_mode and not menus_open)
		if not active:
			if ctl.active:
				ctl.close(self)
			ctl.layout = {}
			ctl.menu_rect = None
			self.player.input_locked = False
			return
		ctl.handle_events(self, events)
		self.player.input_locked = ctl.active
		ctl.draw_popup(self.display_surface, self)
		ctl.draw_demo_confirm(self.display_surface)

	@property
	def debug_demo(self):
		"""True while the F5 DEMO switch is on (edits + test kit)."""
		return bool(getattr(self.debug_controls, 'demo_on', False))

	def set_debug_demo(self, on):
		"""Flip the DEMO switch in the F5 info box.
		ON snapshots the inventory, then replaces it with the test kit. OFF puts
		the snapshot back, so the real items are never destroyed.
		"""
		on = bool(on)
		ctl = self.debug_controls
		if on == bool(ctl.demo_on):
			return
		ctl.demo_on = on
		inv = self.player.inventory
		if on:
			self._demo_inv_snapshot = inv.to_data()
			inv.slots[:] = [None] * len(inv.slots)
			for i, stack in enumerate(DEMO_HOTBAR[:HOTBAR_SIZE]):
				inv.set_slot(i, None if stack is None else list(stack))
			for i, stack in enumerate(DEMO_BAG):
				inv.set_slot(HOTBAR_SIZE + i, list(stack))
			self.player.hotbar_index = 0
			self.player._update_hotbar_selection()
		else:
			snap = self._demo_inv_snapshot
			self._demo_inv_snapshot = None
			if snap is not None:
				inv.slots[:] = [None] * len(inv.slots)
				inv.load(snap)

class CameraGroup(pygame.sprite.Group):
	def __init__(self):
		super().__init__()
		self.display_surface = pygame.display.get_surface()
		self.offset = pygame.math.Vector2()
		self.world_gen = None
		self.isometric_mode = True

		# animated tile selector (replaces the old white polygon outline)
		try:
			self._selector_img = pygame.image.load(
				asset_path('graphics', 'UI', 'Tile_selector.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self._selector_img = None

		# "Ready to harvest" bubble + crop icons shown above mature crops.
		try:
			self._crop_notify_img = pygame.image.load(
				asset_path('graphics', 'UI', 'Crop_notify.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self._crop_notify_img = None
		self._crop_notify_scaled = None
		self._crop_icons = load_overlay_icons(('wheat', 'tomato'))
		self._crop_icon_scaled = {}

		# Per-pixel-alpha blits are ~3x slower; colorkey each ground surface once.
		self._keyed_surf_cache = {}
		
		# Screen dimensions
		sw, sh = self.display_surface.get_size()
		self.screen_w = sw
		self.screen_h = sh
		
		# Camera position (top-left of viewport in screen space)
		self.cam_x = 0
		self.cam_y = 0
		
		# Box camera dead zone: the camera scrolls only when the player exits it.
		box_w = sw // 3
		box_h = sh // 3
		self.dead_zone = pygame.Rect(
			(sw - box_w) // 2,  # left
			(sh - box_h) // 2,  # top
			box_w,              # width
			box_h               # height
		)
		
		# World bounds in screen-space (set after world is generated)
		self.world_bounds = pygame.Rect(-5000, -5000, 10000, 10000)

	def set_world_bounds(self, min_x, min_y, max_x, max_y):
		self.world_bounds = pygame.Rect(min_x, min_y, max_x - min_x, max_y - min_y)

	def update_camera(self, player):
		"""Update camera to follow player with box dead zone"""
		if self.isometric_mode:
			# World pos to iso screen space; +64 x lands feet on the tile centre.
			px = player.rect.centerx / 128.0
			py = player.rect.centery / 128.0
			screen_x = (px - py) * 64 + 64
			screen_y = (px + py) * 32
		else:
			screen_x = player.rect.centerx
			screen_y = player.rect.centery
		
		# Player position relative to camera
		rel_x = screen_x - self.cam_x
		rel_y = screen_y - self.cam_y
		
		# Scroll left/right if player exits dead zone horizontally
		if rel_x < self.dead_zone.left:
			self.cam_x = screen_x - self.dead_zone.left
		elif rel_x > self.dead_zone.right:
			self.cam_x = screen_x - self.dead_zone.right
		
		# Scroll up/down if player exits dead zone vertically
		if rel_y < self.dead_zone.top:
			self.cam_y = screen_y - self.dead_zone.top
		elif rel_y > self.dead_zone.bottom:
			self.cam_y = screen_y - self.dead_zone.bottom
		
		# No world-bounds clamp: infinite terrain; a fixed rect froze the camera.
		
		# Quantize the camera once per frame so all painters share one offset.
		self.cam_x = int(self.cam_x)
		self.cam_y = int(self.cam_y)

		# Set offset for ground rendering
		self.offset.x = self.cam_x
		self.offset.y = self.cam_y

	def _ground_surface(self, surf):
		"""Colorkey copy of a fully opaque/transparent ground surface.
		Per-pixel-alpha blits are ~3x slower, and every ground art asset is
		pixel art, so the chroma-key copy draws the same pixels cheaper.
		"""
		cached = self._keyed_surf_cache.get(surf)
		if cached is not None:
			return cached
		cached = surf
		if surf.get_flags() & pygame.SRCALPHA:
			try:
				import numpy as np
				alpha = pygame.surfarray.array_alpha(surf)
				if not ((alpha != 0) & (alpha != 255)).any():
					rgb = pygame.surfarray.array3d(surf)
					opaque = alpha != 0
					key = None
					for candidate in ((255, 0, 255), (0, 255, 0),
							(0, 0, 255), (255, 255, 0), (0, 255, 255)):
						hit = ((rgb[:, :, 0] == candidate[0])
						       & (rgb[:, :, 1] == candidate[1])
						       & (rgb[:, :, 2] == candidate[2])
						       & opaque).any()
						if not hit:
							key = candidate
							break
					if key is not None:
						copy = pygame.Surface(surf.get_size()).convert()
						copy.fill(key)
						copy.blit(surf, (0, 0))
						copy.set_colorkey(key)
						cached = copy
			except Exception:
				cached = surf
		self._keyed_surf_cache[surf] = cached
		return cached

	def _selector_surface(self, target_grid):
		"""Build the animated selector surface for a target tile.
		Returns (surface, rect) with rect in screen space, or (None, None).
		"""
		gx, gy = target_grid
		iso_x = (gx - gy) * (ISO_TILE_WIDTH // 2)
		iso_y = (gx + gy) * (ISO_TILE_HEIGHT // 2)
		screen_x = round(iso_x - self.cam_x)
		screen_y = round(iso_y - self.cam_y)
		cx = screen_x + ISO_TILE_WIDTH // 2
		cy = screen_y + ISO_TILE_HEIGHT // 2

		if self._selector_img:
			# pulse between 0.90 and 1.00 around the tile centre
			t = pygame.time.get_ticks() / 1000.0
			scale = 0.95 + 0.05 * math.sin(t * 4.0)
			w = max(1, int(ISO_TILE_WIDTH * scale))
			h = max(1, int(ISO_TILE_HEIGHT * scale))
			sel = pygame.transform.smoothscale(self._selector_img, (w, h))
			return sel, sel.get_rect(center=(cx, cy))

		# fallback: white diamond outline
		hw = ISO_TILE_WIDTH // 2
		hh = ISO_TILE_HEIGHT // 2
		points = [
			(screen_x + hw, screen_y),
			(screen_x + ISO_TILE_WIDTH, screen_y + hh),
			(screen_x + hw, screen_y + ISO_TILE_HEIGHT),
			(screen_x, screen_y + hh),
		]
		min_x = min(p[0] for p in points)
		min_y = min(p[1] for p in points)
		max_x = max(p[0] for p in points)
		max_y = max(p[1] for p in points)
		surf = pygame.Surface((max_x - min_x, max_y - min_y), pygame.SRCALPHA)
		local = [(p[0] - min_x, p[1] - min_y) for p in points]
		pygame.draw.polygon(surf, (255, 255, 255), local, 3)
		return surf, surf.get_rect(topleft=(min_x, min_y))

	def _draw_crop_notifies(self):
		"""Bob a Crop_notify bubble + crop icon above every mature crop."""
		if self._crop_notify_img is None:
			return
		if self._crop_notify_scaled is None:
			self._crop_notify_scaled = pygame.transform.scale(
				self._crop_notify_img, (36, 44))
		notify = self._crop_notify_scaled
		ticks = pygame.time.get_ticks()
		sw, sh = self.display_surface.get_size()
		for sprite in self.sprites():
			if not getattr(sprite, 'harvestable', False):
				continue
			crop = getattr(sprite, 'plant_type', None)
			if not crop:
				continue
			phase = (ticks / 380.0
			         + (sprite.rect.centerx + sprite.rect.centery) * 0.01)
			bob = int(round(math.sin(phase) * 4))
			if self.isometric_mode:
				sx = sprite.rect.centerx / 128.0
				sy = sprite.rect.centery / 128.0
				iso_x = (sx - sy) * 64 + 64
				iso_y = (sx + sy) * 32
				top = (iso_y - self.cam_y
				       - sprite.image.get_height() // 2
				       + getattr(sprite, 'y_anchor_offset', 0))
				draw_x = round(iso_x - self.cam_x)
				draw_y = round(top) - notify.get_height() // 2 - bob
			else:
				draw_x = sprite.rect.centerx - self.offset.x
				draw_y = (sprite.rect.top - self.offset.y
				          - notify.get_height() - bob)
			rect = notify.get_rect(center=(draw_x, draw_y))
			if rect.right < 0 or rect.left > sw or rect.bottom < 0 or rect.top > sh:
				continue
			self.display_surface.blit(notify, rect)
			icon = self._crop_icons.get(crop)
			if icon is not None:
				scaled = self._crop_icon_scaled.get(crop)
				if scaled is None:
					scaled = pygame.transform.scale(icon, (20, 20))
					self._crop_icon_scaled[crop] = scaled
				self.display_surface.blit(
					scaled, scaled.get_rect(center=(rect.centerx,
					                                rect.centery - 2)))

	def custom_draw(self, player, debug_mode=False, fps=0, time_manager=None, raining=False, hide_player=False, debug_controls=None):
		# Store for use in debug overlay below
		self.debug_mode = debug_mode
		self._last_fps = fps
		self._debug_time_manager = time_manager
		self._debug_raining = raining
		# Update camera position
		self.update_camera(player)

		# Draw ground chunks
		if self.world_gen:
			self.world_gen.draw_ground(self.display_surface, self.offset, self.isometric_mode)

		# Painter's key (depth, rank, -level, z): depth = x+y px, rank 0..2 ground, 3 sprites.
		draw_list = []

		if self.isometric_mode and self.world_gen:
			sw, sh = self.display_surface.get_size()
			ox = int(self.cam_x)
			oy = int(self.cam_y)
			for gdepth, grank, gsurf, gdx, gdy, garea in self.world_gen.iter_ground_entries(
					sw, sh, ox, oy):
				draw_list.append(((gdepth, grank, 0, 0),
					(True, self._ground_surface(gsurf),
					 int(gdx) + garea.x, int(gdy) + garea.y, garea)))

			# Tile selector: target tile depth, rank 2.5 (above overlays, below sprites).
			if not hide_player and hasattr(player, 'target_grid') and player.target_grid:
				sel_surf, sel_rect = self._selector_surface(player.target_grid)
				if sel_surf is not None:
					depth = ((player.target_grid[0] + player.target_grid[1])
						* ISO_TILE_WIDTH + ISO_TILE_WIDTH + OVERLAY_LIFT)
					draw_list.append(((depth, 2.5, 0, 0),
						(True, sel_surf, sel_rect.x, sel_rect.y,
						 sel_surf.get_rect())))

		sw, sh = self.display_surface.get_size()
		for sprite in self.sprites():
			if sprite.z <= LAYERS['water']:
				continue  # Water is drawn on the ground tiles themselves
			if sprite.z not in LAYERS.values():
				continue
			if hide_player and sprite is player:
				continue
			# Bridges are ground: terrain pass at their tile depth so they sit flush.
			if self.isometric_mode and getattr(
					sprite, 'render_as_ground', False):
				gx = sprite.rect.centerx // ISO_TILE_WIDTH
				gy = sprite.rect.centery // ISO_TILE_WIDTH
				iso_x = (gx - gy) * (ISO_TILE_WIDTH // 2)
				iso_y = (gx + gy) * (ISO_TILE_HEIGHT // 2)
				src = sprite.image.get_bounding_rect()
				ray = (gx + gy + 1) * ISO_TILE_WIDTH
				draw_list.append(((ray + OVERLAY_LIFT, 1.6, 0, 0),
				                  (True, self._ground_surface(sprite.image),
				                   round(iso_x - self.cam_x),
				                   round(iso_y - self.cam_y), src)))
				continue
			lvl = getattr(sprite, 'level', 0)
			img = sprite.image
			iw, ih = img.get_size()
			if self.isometric_mode:
				sx = sprite.rect.centerx / 128.0
				sy = sprite.rect.centery / 128.0
				# +64 x: feet land on the tile diamond centre, not the left vertex.
				iso_x = (sx - sy) * 64 + 64
				iso_y = (sx + sy) * 32
				mode = getattr(sprite, 'iso_anchor', 'bottom')
				if mode == 'pixel':
					# Pin the art's base diamond centre to the tile (uncentred crates).
					ax, ay = sprite.anchor_px
					draw_x = round(iso_x - self.cam_x - ax)
					draw_y = round(iso_y - self.cam_y - ay)
				elif mode == 'center':
					draw_x = round(iso_x - self.cam_x - iw // 2)
					draw_y = round(iso_y - self.cam_y - ih // 2)
					draw_y += getattr(sprite, 'y_anchor_offset', 0)
				else:
					draw_x = round(iso_x - self.cam_x - iw // 2)
					draw_y = round(iso_y - self.cam_y - ih)
					# Lift by sole padding so the visible art bottom sits on the tile centre.
					draw_y += getattr(sprite, 'foot_pad', 0)
				# Skip off-screen props before the sort; the chunk ring holds thousands.
				if (draw_x >= sw or draw_y >= sh
						or draw_x + iw <= 0 or draw_y + ih <= 0):
					continue
				# Floor depth at the sprite's own tile centre so that tile cannot overdraw.
				own_tile = ((sprite.rect.centerx // ISO_TILE_WIDTH
					+ sprite.rect.centery // ISO_TILE_WIDTH)
					* ISO_TILE_WIDTH + ISO_TILE_WIDTH)
				depth = max(sprite.rect.centerx + sprite.rect.centery,
					own_tile)
				# SPRITE_LIFT: stay above flat overlays (OVERLAY_LIFT); see settings.py.
				depth += SPRITE_LIFT
				# Front-bias: when the player stands on a structure's front
				# tiles (doorstep / apron), lower the structure's depth so the
				# player draws in front of the facade. Only tiles within
				# STRUCTURE_FRONT_RADIUS of the door get this priority, so
				# walking round the back keeps normal occlusion.
				if getattr(sprite, 'front_tiles', None):
					p_tile = (player.rect.centerx // ISO_TILE_WIDTH,
					          player.rect.centery // ISO_TILE_WIDTH)
					if p_tile in sprite.front_tiles:
						p_own = ((player.rect.centerx // ISO_TILE_WIDTH
							+ player.rect.centery // ISO_TILE_WIDTH)
							* ISO_TILE_WIDTH + ISO_TILE_WIDTH)
						p_depth = max(player.rect.centerx + player.rect.centery,
							p_own) + SPRITE_LIFT
						if depth >= p_depth:
							depth = p_depth - 1
				sort_key = (depth, 3.0, -lvl, sprite.z)
			else:
				draw_x = sprite.rect.left - int(self.offset.x)
				draw_y = sprite.rect.top - int(self.offset.y)
				if (draw_x >= sw or draw_y >= sh
						or draw_x + iw <= 0 or draw_y + ih <= 0):
					continue
				sort_key = (sprite.rect.centery, -lvl, sprite.z)
			draw_list.append((sort_key, (False, self._ground_surface(img), draw_x, draw_y, None)))

		draw_list.sort(key=_first)

		# Draw back-to-front, batching consecutive ground pieces into blits().
		batch = []
		for _, payload in draw_list:
			is_ground, obj, draw_x, draw_y, src_area = payload
			if is_ground:
				batch.append((obj, (draw_x, draw_y), src_area))
				continue
			if batch:
				self.display_surface.blits(batch, doreturn=False)
				batch = []
			self.display_surface.blit(obj, (draw_x, draw_y))
		if batch:
			self.display_surface.blits(batch, doreturn=False)

		# Mature-crop notifications float above the crop art.
		self._draw_crop_notifies()

		# DEBUG OVERLAY - toggle with F5
		if self.debug_mode and self.isometric_mode and not hide_player:
			hw = ISO_TILE_WIDTH // 2
			hh = ISO_TILE_HEIGHT // 2
			# Interface font; the 4pt gap marks big lines (no bold face).
			font = ui_font(18)
			font_big = ui_font(22)

			pgx = player.rect.centerx // TILE_SIZE
			pgy = player.rect.centery // TILE_SIZE

			# green outline on PLAYER's own tile
			p_iso_x = (pgx - pgy) * hw
			p_iso_y = (pgx + pgy) * hh
			p_scr_x = round(p_iso_x - self.cam_x)
			p_scr_y = round(p_iso_y - self.cam_y)
			p_points = [
				(p_scr_x + hw, p_scr_y),
				(p_scr_x + ISO_TILE_WIDTH, p_scr_y + hh),
				(p_scr_x + hw, p_scr_y + ISO_TILE_HEIGHT),
				(p_scr_x, p_scr_y + hh),
			]
			pygame.draw.polygon(self.display_surface, (0, 255, 0), p_points, 2)

			# red dot on player body center + line to target
			ppx = player.rect.centerx / 128.0
			ppy = player.rect.centery / 128.0
			px_iso_x = (ppx - ppy) * hw + hw
			px_iso_y = (ppx + ppy) * hh
			px_sx = round(px_iso_x - self.cam_x)
			px_sy = round(px_iso_y - self.cam_y - 24 - 41)
			pygame.draw.circle(self.display_surface, (255, 0, 0), (px_sx, px_sy), 5)

			tgx, tgy = pgx, pgy
			if hasattr(player, 'target_grid') and player.target_grid:
				tgx, tgy = player.target_grid
				t_iso_x = (tgx - tgy) * hw
				t_iso_y = (tgx + tgy) * hh
				tgt_cx = round(t_iso_x - self.cam_x) + hw
				tgt_cy = round(t_iso_y - self.cam_y) + hh
				pygame.draw.line(self.display_surface, (255, 0, 0), (px_sx, px_sy), (tgt_cx, tgt_cy), 2)

			# Compute target tile diagnostic info
			terrain_str = '?'
			cell_str = '?'
			block_str = ''
			if self.world_gen:
				terrain_str = self.world_gen.get_terrain_type(tgx, tgy)
				if terrain_str == 'water':
					block_str = 'WATER'
				elif terrain_str == 'lava':
					block_str = 'LAVA'
			if hasattr(player, 'soil_layer') and player.soil_layer:
				if player.soil_layer._has_cell(tgx, tgy):
					cell = player.soil_layer._cell(tgx, tgy)
					cell_str = repr(cell) if cell else '[]'
					if 'X' in cell:
						block_str = 'HOED'
				else:
					cell_str = 'OOB'
					block_str = 'OOB'

			# F3-style debug panel (bottom-right): Rain/Season combos, Time/Player boxes.
			sw, sh = self.display_surface.get_size()
			ctl = debug_controls
			tm_dbg = self._debug_time_manager
			lines = [
				("Pydew Valley  [v%s]" % app_version(), (255, 255, 100), None),
				("DEMO:", (255, 255, 100), 'demo'),
				("", None, None),
				(f"FPS: {int(self._last_fps)}", (200, 200, 200), None),
				("", None, None),
				("Player grid:", (100, 255, 100), 'grid'),
				(f"Player world: ({player.rect.centerx}, {player.rect.centery})", (100, 255, 100), None),
				(f"Player iso:   ({ppx:.2f}, {ppy:.2f})", (100, 200, 100), None),
				("", None, None),
				(f"Target grid:  ({tgx}, {tgy})", (100, 180, 255), None),
				(f"Offset:       ({tgx-pgx}, {tgy-pgy})", (100, 180, 255), None),
				("", None, None),
				(f"Terrain: {terrain_str}", (255, 180, 100), None),
				(f"Cell:    {cell_str}", (255, 180, 100), None),
				(f"Block:   {block_str if block_str else 'NONE'}", (255, 80, 80) if block_str else (100, 255, 100), None),
				(f"Biome:   {self.world_gen.biome_at(tgx, tgy) if self.world_gen else '?'}", (100, 255, 255), None),
				(f"Snap:    {type(player.target_object).__name__ if getattr(player, 'target_object', None) else 'NONE'}", (255, 100, 255), None),
				("", None, None),
				(f"Status: {player.status}", (255, 200, 100), None),
				(f"Dir:    ({player.direction.x:.2f}, {player.direction.y:.2f})", (255, 200, 100), None),
				(f"World:  ({player.world_direction.x:.2f}, {player.world_direction.y:.2f})", (255, 200, 100), None),
				("", None, None),
				("Time:", (200, 200, 255), 'time'),
				(f"Camera: ({self.cam_x:.0f}, {self.cam_y:.0f})", (200, 200, 255), None),
				("Rain:", (200, 200, 255), 'rain'),
				("Season:", (200, 200, 255), 'season'),
("Teleport:", (200, 200, 255), 'teleport'),
			]

			# values the widgets show (a focused box replaces its own)
			values = {
				'grid': f"({pgx}, {pgy})",
				# Time row reads as a 12-hour clock, like the focused box.
				'time': (ctl.time_text(tm_dbg.hour, tm_dbg.minute)
				         if (tm_dbg and ctl) else "--:-- --"),
				'rain': str(bool(self._debug_raining)),
				'season': (tm_dbg.get_season_name() if tm_dbg else "?"),
'teleport': str(getattr(ctl, 'teleport_choice', 'village')) if ctl else 'village',
				'demo': bool(getattr(ctl, 'demo_on', False)),
			}

			# width follows the widest row: label + widget, or text
			line_h = int(21 * ui_scale())
			panel_w = int(240 * ui_scale())
			for text, _color, kind in lines:
				if not text:
					continue
				if kind and ctl is not None:
					w = (12 + font.size(text)[0] + 6
					     + ctl.widget_width(kind, font) + 12)
				else:
					w = font.size(text)[0] + 24
				panel_w = max(panel_w, w)

			panel_h = len(lines) * line_h + 16
			panel_x = sw - panel_w - 4
			panel_y = sh - panel_h - 4
			# (no slide: the combo list opens UPWARD, never off the bottom)
			bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
			bg.fill((0, 0, 0, 160))
			self.display_surface.blit(bg, (panel_x, panel_y))

			if ctl is not None:
				ctl.layout = {}   # rebuilt every frame the box is drawn

			y_off = panel_y + 8
			for text, color, kind in lines:
				if text:
					label_x = panel_x + 12
					surf = font.render(text, True, color)
					self.display_surface.blit(surf, (label_x, y_off))
					if kind:
						if ctl is None:
							plain = font.render(
								f"{text} {values[kind]}", True, color)
							self.display_surface.blit(plain,
								(label_x, y_off))
						else:
							ww = ctl.widget_width(kind, font)
							ctl.draw_widget(
								self.display_surface, kind,
								pygame.Rect(label_x + surf.get_width() + 6,
								            y_off - 1, ww, WIDGET_H),
								values[kind], font,
								enabled=bool(ctl.demo_on))
				y_off += line_h
