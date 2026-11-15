import os
import sys
from pygame.math import Vector2

# A packaged build (PyInstaller) is "frozen": the assets live inside the
# bundle and sys._MEIPASS points at it.
FROZEN = getattr(sys, 'frozen', False)

if FROZEN:
	BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
	BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def asset_path(*parts):
	"""Read-only bundled resource (graphics, audio, font, data)."""
	return os.path.join(BASE_DIR, *parts)


# -- The interface font --
# Monocraft (Idrees Inc, SIL OFL 1.1) replaced Mojangles, which is Mojang's
# proprietary font and not licensed for redistribution. Monocraft is wider,
# so the sizes are scaled to keep the text the same width on screen.
UI_FONT = 'font/ui.ttf'
UI_FONT_SCALE = 22.0 / 28.0

# The interface was designed against a canvas this tall. The game opens
# full screen at the real desktop resolution, so on a bigger screen the
# whole UI scales by the same factor - the menus already fit themselves
# to the screen, and this keeps the text in step with them.
UI_REFERENCE_HEIGHT = 860

_ui_scale = 1.0


def set_ui_scale(value):
	"""Remember how much to scale the interface on this screen."""
	global _ui_scale
	_ui_scale = max(0.5, min(3.0, value))


def ui_scale():
	"""Interface scale factor for the current screen (1.0 = as designed)."""
	return _ui_scale


def ui_font(size, bold=False):
	"""The interface font, at a Mojangles-equivalent size.
	Monocraft is monospaced and wider, so the size is scaled to keep the
	text the same width on screen.
	"""
	import pygame
	font = pygame.font.Font(asset_path(UI_FONT),
	                         max(8, int(round(size * UI_FONT_SCALE * ui_scale()))))
	if bold:
		font.set_bold(True)
	return font


def user_data_dir():
	"""Writable folder for the save file, key bindings and volume.
	Running from source keeps the project's data/ folder; a packaged build
	writes next to the executable, the way Aseprite does.
	"""
	if not FROZEN:
		return asset_path('data')
	return os.path.dirname(os.path.abspath(sys.executable))


def user_data_path(*parts):
	"""Writable path inside user_data_dir()."""
	return os.path.join(user_data_dir(), *parts)


def ensure_user_data_dir():
	"""Create the writable folder if it does not exist yet."""
	directory = user_data_dir()
	try:
		os.makedirs(directory, exist_ok=True)
	except OSError:
		pass
	return directory


# -- The game always runs full screen --
# No settings file and no windowed mode: the game opens on the desktop,
# stretched to whatever resolution the screen has.
def app_version():
	"""The version of this build, from the bundled VERSION.txt."""
	try:
		with open(asset_path('VERSION.txt'), 'r', encoding='utf-8') as handle:
			return handle.read().strip() or 'unknown'
	except OSError:
		return 'dev'


def help_doc_path():
	"""Path to the in-game help page.
	A copy next to the executable is preferred; the bundled one is copied
	out, since a browser cannot open a onefile temp folder reliably.
	"""
	bundled = asset_path('PYDEW VALLEY DOCUMENTATION.html')
	beside = user_data_path('PYDEW VALLEY DOCUMENTATION.html')
	if os.path.exists(beside):
		return beside
	if not FROZEN:
		return bundled
	try:
		ensure_user_data_dir()
		import shutil
		shutil.copy2(bundled, beside)
	except OSError:
		pass
	return beside if os.path.exists(beside) else bundled

# The game runs full screen at the real desktop resolution, so there is
# no canvas size to hardcode - everything reads the live display surface.
TILE_SIZE = 128

# Isometric tile dimensions - 2:1 ratio for proper isometric projection
ISO_TILE_WIDTH = 128
ISO_TILE_HEIGHT = 64
ISO_SPRITE_HEIGHT = 64
WATER_SUNK_OFFSET = ISO_TILE_HEIGHT // 2

PLAYER_TOOL_OFFSET = {
	'left': Vector2(-50,40),
	'right': Vector2(50,40),
	'up': Vector2(0,-10),
	'down': Vector2(0,50),
	'up_left': Vector2(-50,10),
	'up_right': Vector2(50,10),
	'down_left': Vector2(-50,50),
	'down_right': Vector2(50,50),
}

# Auto-selector: the nearest breakable matching the selected tool is
# snapped to within SNAP_RANGE and a +-60 degree cone (SNAP_CONE_COS).
SNAP_RANGE = int(TILE_SIZE * 2.5)
SNAP_CONE_COS = 0.5


LAYERS = {
	'water': 0,
	'ground': 1,
	'soil': 2,
	'soil water': 3,
	'rain floor': 4,
	'house bottom': 5,
	'ground plant': 6,
	'main': 7,
	'house top': 8,
	'fruit': 9,
	'rain drops': 10,
}

# Fruit trees: chance a spawned tree is a fruit tree, and how many fruits
# it drops when felled (per-biome fruit art/item lives in BIOMES).
FRUIT_TREE_CHANCE = 0.25
APPLE_DROP_MIN = 1
APPLE_DROP_MAX = 3

# Natural-prop density: the chance that ONE open tile gets a prop of that
# kind. Every tile rolls its own noise, so the expected density is the same
# in every chunk. Pre-rejection: spacing rules turn some rolls down.
PROP_DENSITY = {
	'trees':   (0.050, 11),   # (chance per open tile, white-noise seed)
	'debris':  (0.014, 23),
	'rocks':   (0.007, 37),
	'bushes':  (0.027, 51),
	'flowers': (0.023, 67),
}
# How far the LOCAL average may bend around the mean above (0.35 =
# +-35%). That mild clumping reads as natural growth.
PROP_DENSITY_RELIEF = 0.35
# Feature size of that clumping band, in tiles (~8-tile blobs).
PROP_DENSITY_NOISE_SCALE = 0.125

# Berry bush: relative spawn weight among bushes (vs 100 for plain bushes)
# and how many berries it yields when cut down.
BERRY_BUSH_WEIGHT = 35
BERRY_DROP_MIN = 1
BERRY_DROP_MAX = 2

# ---- BIOMES: art pools + drops per biome ----
# Files resolve inside graphics/Biomes/<biome>/.
# debris: (file, hits_to_cut, wood_yield, spawn_weight)
# bushes: (file, drops, spawn_weight)  drops = [(item, min, max)]
# fruit_tree: (file, chance, drop_item) or None
# wood_item: inventory item dropped by that biome's trees/logs
# props: rare non-colliding standing decorations
# ground: ground-tile pool - numbered full-cube tiles, deco baked in
# ice_tile: frozen water surface tile, on interior water tiles only
BIOMES = {
	'Oak_Woods': {
		'trees': ['Oaktree_small.png', 'Oaktree_medium.png', 'Oaktree_large.png'],
		'fruit_tree': ('Oaktree_apple.png', FRUIT_TREE_CHANCE, 'apple'),
		'debris': [
			('Oaktree_log.png', 3, 2, 25),
			('OakStump_large.png', 3, 1, 35),
			('OakStump_medium.png', 2, 1, 40),
		],
		'bushes': [
			('Oak_bush.png', [('bush', 1, 1)], 100),
			('berry_bush.png', [('berry', BERRY_DROP_MIN, BERRY_DROP_MAX), ('bush', 1, 1)], BERRY_BUSH_WEIGHT),
		],
		'flowers': ['sunflower.png', 'flower.png', 'mushroom.png', 'mushrooms.png',
		            'yellow_flower.png', 'small_yellow_flower.png'],
		'ground': 'ground',
		'water_deco_glob': '*ater*ecoration*.png',
		'props': [],
		'wood_item': 'wood',
	},
	'Birch_Forest': {
		'trees': ['Birchtree_small.png', 'Birchtree_medium.png', 'Birchtree_large.png'],
		'fruit_tree': ('Birchtree_orange.png', FRUIT_TREE_CHANCE, 'orange'),
		'debris': [
			('Birchtree_log.png', 3, 2, 25),
			('BirchStump_large.png', 3, 1, 35),
			('BirchStump_medium.png', 2, 1, 40),
		],
		'bushes': [
			('Birch_bush.png', [('bush', 1, 1)], 100),
		],
		'flowers': ['Birch_flower1.png', 'Birch_flower2.png',
		            'purple_mushroom.png', 'purple_mushrooms.png'],
		'ground': 'ground',
		'water_deco_glob': '*ater*ecoration*.png',
		'props': [],
		'wood_item': 'birch_wood',
	},
	'Cherry_Blossom': {
		'trees': ['Cherrytree_small.png', 'Cherrytree_medium.png', 'Cherrytree_large.png'],
		'fruit_tree': ('Cherrytree_cherry.png', FRUIT_TREE_CHANCE, 'cherry'),
		'debris': [
			('Cherrytree_log.png', 3, 2, 25),
			('CherryStump_large.png', 3, 1, 35),
			('CherryStump_medium.png', 2, 1, 40),
		],
		'bushes': [
			('Cherry_bush1.png', [('bush', 1, 1)], 100),
			('Cherry_bush2.png', [('bush', 1, 1)], 100),
			('Cherry_bush3.png', [('bush', 1, 1)], 100),
			('Cherry_bush4.png', [('bush', 1, 1)], 100),
		],
		'flowers': ['Cherry_flower1.png', 'Cherry_flower2.png',
		            'pink_flower.png', 'small_pink_flower.png'],
		'ground': 'ground',
		'water_deco_glob': '*ater*ecoration*.png',
		'props': [],
		'wood_item': 'cherry_wood',
	},
	'Snowy_Pine': {
		'trees': ['Pinetree_small.png', 'Pinetree_medium.png', 'Pinetree_large.png'],
		'fruit_tree': None,
		'debris': [
			('Pinetree_log.png', 3, 2, 100),
		],
		'bushes': [
			('Pine_bush.png', [('bush', 1, 1)], 100),
		],
		'flowers': ['Snowy_flower1.png', 'Snowy_flower2.png', 'Snowy_flower3.png',
		            'Snowy_flower4.png', 'Snowy_flower5.png'],
		'ground': 'ground',
		'water_deco_glob': '*ater*ecoration*.png',
		'ice_tile': 'ice_tiles.png',
		'props': ['Snow_Man.png', 'CuteSnow_Man.png'],
		'wood_item': 'pine_wood',
	},
}

# Flower / fungus pickups, keyed by their art file stem. Each type is its
# own inventory item so the icon matches the sprite that was picked.
FLOWER_ITEMS = [
	'flower', 'sunflower', 'yellow_flower', 'small_yellow_flower',
	'mushroom', 'mushrooms',
	'birch_flower1', 'birch_flower2', 'purple_mushroom', 'purple_mushrooms',
	'cherry_flower1', 'cherry_flower2', 'pink_flower', 'small_pink_flower',
	'snowy_flower1', 'snowy_flower2', 'snowy_flower3', 'snowy_flower4',
	'snowy_flower5',
]

# Low-frequency biome noise value -> biome bands (Minecraft-style blobs).
BIOME_BANDS = [
	('Oak_Woods', 0.25),
	('Birch_Forest', 0.50),
	('Cherry_Blossom', 0.75),
	('Snowy_Pine', 1.01),
]
# fBm output clusters near 0.5; stretching x4 before banding spreads the
# four biomes over roughly equal quartile-sized regions (clamped to 0..1).
BIOME_STRETCH = 4.0
# Dither band width at biome borders (speckled transition).
BIOME_DITHER = 0.02

# All wood flavours — crafting treats a 'wood' cost as this group.
WOOD_ITEMS = ('wood', 'birch_wood', 'cherry_wood', 'pine_wood')
POTION_ITEMS = ('health_potion', 'miner_potion',
                'night_vision_potion', 'speed_potion')
REFINED_ITEMS = ('coal', 'copper', 'iron', 'gold', 'amethyst',
                 'emerald', 'ruby', 'diamond')

# Plantable saplings: species -> biome whose tree art it grows into.
# Felled trees drop their sapling, so trees only come back by replanting.
BIOME_SAPLINGS = {
	'Oak_Woods': 'oak_sapling',
	'Birch_Forest': 'birch_sapling',
	'Cherry_Blossom': 'cherry_sapling',
	'Snowy_Pine': 'pine_sapling',
}
SAPLING_BIOMES = {item: biome for biome, item in BIOME_SAPLINGS.items()}
SAPLING_ITEMS = tuple(SAPLING_BIOMES)
SAPLING_GROWTH_FOLDERS = {
	'oak_sapling': 'Oaktree',
	'birch_sapling': 'Birchtree',
	'cherry_sapling': 'Cherrytree',
	'pine_sapling': 'Pinetree',
}
# Planted trees mature after one in-game day. TREE_GROWTH_SECONDS is kept
# only to migrate saves written before growth switched to game time.
TREE_GROWTH_MINUTES = 24 * 60
TREE_STAGE_SECONDS = 20.0
TREE_GROWTH_SECONDS = TREE_STAGE_SECONDS * 3

# Wood dropped by a felled tree, based on the visible canopy width.
TREE_WOOD_DROPS = (
	(120, 2, 3),
	(160, 3, 4),
	(10 ** 9, 4, 5),
)


def tree_wood_yield(surf_width):
	for limit, low, high in TREE_WOOD_DROPS:
		if surf_width < limit:
			return (low, high)
	return TREE_WOOD_DROPS[-1][1:]

# Town-hall quests: deliver one full stack (64) of each item. Page one
# asks for saplings/seeds, page two for fruits and vegetables, page three
# for the eight refined ores.
QUEST_STACK = 64
TOWN_QUEST_PAGES = (
	(
		('birch_sapling', 'Birch Sapling', False),
		('cherry_sapling', 'Cherry Sapling', False),
		('oak_sapling', 'Oak Sapling', False),
		('pine_sapling', 'Pine Sapling', False),
		('tomato_seed', 'Tomato Seeds', True),
		('wheat_seed', 'Wheat Seeds', True),
	),
	(
		('apple', 'Apple', False),
		('berry', 'Berry', False),
		('cherry', 'Cherry', False),
		('orange', 'Orange', False),
		('tomato', 'Tomato', False),
		('wheat', 'Wheat', False),
	),
	(
		('coal', 'Coal', False),
		('copper', 'Copper', False),
		('iron', 'Iron', False),
		('gold', 'Gold', False),
		('amethyst', 'Amethyst', False),
		('emerald', 'Emerald', False),
		('ruby', 'Ruby', False),
		('diamond', 'Diamond', False),
	),
)

HEART_RECIPE = 'heart_of_valley'


def heart_recipe_unlocked(completed_quests):
	last_page = len(TOWN_QUEST_PAGES) - 1
	return all(f'{last_page}:{item}' in completed_quests
	           for item, _label, _seed in TOWN_QUEST_PAGES[last_page])


# Player-facing item names. Internal keys stay stable for saves/recipes.
ITEM_DISPLAY_NAMES = {
	'wood': 'Oak Wood',
	'health_potion': 'Health Potion',
	'miner_potion': 'Miner Potion',
	'night_vision_potion': 'Night Vision Potion',
	'speed_potion': 'Speed Potion',
	'heart_of_valley': 'Heart of the Valley',
	'wheat_seed': 'Wheat Seeds',
	'tomato_seed': 'Tomato Seeds',
}


def item_name(item):
	return ITEM_DISPLAY_NAMES.get(item, item.replace('_', ' ').title())

GROW_SPEED = {
	'wheat': 0.9,
	'tomato': 0.7,
}

# Harvested produce the player can eat. Wheat is a crafting grain.
EDIBLE_HEAL = {
	'apple': 10,
	'berry': 12,
	'cherry': 14,
	'orange': 16,
	'tomato': 20,
}
EDIBLE_ITEMS = tuple(EDIBLE_HEAL)

HARVEST_YIELD_MIN = 1
HARVEST_YIELD_MAX = 3

SALE_PRICES = {
	'wood': 4,
	'birch_wood': 4,
	'cherry_wood': 4,
	'pine_wood': 4,
	'apple': 2,
	'orange': 4,
	'cherry': 4,
	'berry': 5,
	'wheat': 8,
	'tomato': 20,
	'rock': 6,
	'stick': 2,
	'flower': 3,
	'sunflower': 4,
	'yellow_flower': 3,
	'small_yellow_flower': 2,
	'mushroom': 4,
	'mushrooms': 5,
	'birch_flower1': 3,
	'birch_flower2': 3,
	'purple_mushroom': 5,
	'purple_mushrooms': 6,
	'cherry_flower1': 4,
	'cherry_flower2': 4,
	'pink_flower': 4,
	'small_pink_flower': 3,
	'snowy_flower1': 3,
	'snowy_flower2': 3,
	'snowy_flower3': 3,
	'snowy_flower4': 3,
	'snowy_flower5': 3,
	'water_bucket': 10,
	'bread': 15,
	'oak_sapling': 8,
	'birch_sapling': 8,
	'cherry_sapling': 8,
	'pine_sapling': 8,
}
PURCHASE_PRICES = {
	'wheat_seed': 3,
	'tomato_seed': 5,
}
# The village shop only buys foraged flowers/fungi.
SHOP_ITEMS = tuple(item for item in FLOWER_ITEMS if item in SALE_PRICES)

RECIPES = {
	'heart_of_valley': ({'iron': 5, 'gold': 5, 'ruby': 5,
	                     'emerald': 5, 'diamond': 5}, 1),
	'stick': ({'wood': 1}, 2),
	'axe': ({'stick': 2, 'rock': 3}, 1),
	'pickaxe': ({'stick': 2, 'rock': 3}, 1),
	'hoe': ({'stick': 2, 'rock': 2}, 1),
	'water_bucket': ({'rock': 3}, 1),
	'bridge': ({'wood': 4, 'stick': 2}, 1),
	'bread': ({'wheat': 3}, 1),
	'Bed': ({'bush': 3, 'wood': 3}, 1),
}

# Tools are ordinary inventory items; the hotbar uses these ids too.
TOOL_ITEMS = ('hoe', 'axe', 'pickaxe', 'water_bucket')

# -- Time system --
# TimeManager.update() fires once SECONDS_PER_MINUTE of real time have
# passed and then advances the clock by 10 game minutes, so this value is
# really the interval per 10 game minutes:
#   25/6 real seconds -> 10 game minutes
#   25 real seconds   -> 1 game hour
#   1 game day (144 ticks) -> ~600 real seconds (~10 min)
# Elapsed time is subtracted, never reset, so no drift accumulates.
# Do NOT change the rate: the potion timer and the farmland decay tests
# are calibrated against it.
SECONDS_PER_MINUTE = 25 / 6
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
# Empty tilled tiles revert to grass after half an in-game day
# (12 game hours = 720 game minutes = 144 ticks x 25/6 s = ~10 real min).
FARMLAND_EMPTY_MINUTES = MINUTES_PER_HOUR * (HOURS_PER_DAY // 2)
DAY_START_HOUR = 7
NIGHT_START_HOUR = 20
DAYS_PER_SEASON = 28
SEASONS = ['Spring', 'Summer', 'Fall', 'Winter']

# Potions tick on the REAL clock: each lasts this many actual seconds.
# The save stores the seconds left, so a potion freezes while off.
POTION_EFFECT_DURATION_SECONDS = 5 * 60
SPEED_POTION_MULTIPLIER = 1.5
NIGHT_VISION_RADIUS = int(TILE_SIZE * 4.0)

KEYBINDINGS_PATH = user_data_path('keybindings.json')
VOLUME_SETTINGS_PATH = user_data_path('volume.json')

# World generation seed
WORLD_SEED = 12345

# Noise parameters
NOISE_SCALE_MOISTURE = 0.015
NOISE_SCALE_DETAIL = 0.04
NOISE_SCALE_WATER = 0.02
# Biome blobs: one full noise cycle spans ~1/NOISE_SCALE_BIOME tiles (~250).
NOISE_SCALE_BIOME = 0.004
NOISE_OCTAVES = 4
NOISE_PERSISTENCE = 0.5
NOISE_LACUNARITY = 2.0

# Terrain thresholds
WATER_THRESHOLD = 0.38
WATER_TRANSITION = 0.05
# Shore-bank bonus: land next to water reads as a damp river/lake bank.
# Two tiers - tiles touching water get the wider damp band, tiles within 2
# get a slimmer one.
SHORE_WET_BOOST = 0.07
SHORE_WET_BOOST_ADJ = 0.12

# -- Flat terrain --
# The overworld and the cave are FLAT planes (no elevation, no cliffs, no
# jumps). Water shapes the overworld: blob lakes + winding rivers; the cave
# keeps its lava ocean. Land is walkable in every direction.
# Rivers: contour bands of one low-frequency river noise. |v - level| <
# half-width (dithered per tile) marks a river tile.
RIVER_NOISE_SCALE = 0.006            # river field feature size (~170 tiles)
RIVER_LEVELS = (
	(0.50, 0.010),   # main stems
	(0.31, 0.008),   # second family (other contour lines)
	(0.69, 0.008),
)
# Lakes: high band of a separate lake noise -> blob basins.
NOISE_SCALE_LAKE = 0.008             # lake feature size (~125-tile blobs)
LAKE_THRESHOLD = 0.60
# Flat overlays (ice, water deco, farm soil) sit above their own tile's
# ground; the lift only breaks cross-tile ties. Constraint: 0 < lift < 128
# - a lift of 128 or more made ice paint over the tiles in front.
OVERLAY_LIFT = 64
# Sprites add this to their depth key. It must clear OVERLAY_LIFT so a
# same-tile farm patch sits below the sprite (rank 3.0 wins the tie).
SPRITE_LIFT = 320

# Player stats

# ---- CAVE (separate world space) - also a FLAT plane ----
# The cave exit sits near the top-left. Everything that is not land is full
# lava - an endless lava ocean, no black void.
CAVE_EXIT_TILE = (1, 0)
CAVE_EXIT_PAD_RADIUS = 3          # forced flat land around the exit platform
# Shape noise: land stays where the fractal value lies inside a band
# symmetric around 0.5, giving winding cave corridors. The band is
# calibrated from noise quantiles at init so land/lava splits ~50/50.
CAVE_NOISE_SCALE = 0.05           # corridor feature size (~20-tile cycles)
CAVE_NOISE_OCTAVES = 4
# Entrance placement: jittered grid sampling with a dead zone - one
# entrance per sector, inset from the borders so they keep a minimum
# distance from each other.
CAVE_SECTOR_SIZE = 48             # tiles per sector
CAVE_ENTRANCE_DEAD_ZONE = 8       # min distance from a sector border
CAVE_ENTRANCE_RESERVE_RADIUS = 4  # no trees/rocks within this many tiles
CAVE_DARKNESS_ALPHA = 46          # ambient dim overlay while inside
# ---- Cave content: rocks, ore veins and decorations ----
# One prop max per land tile, deterministic per (tile, WORLD_SEED).
# Ore TYPES get rarer with depth = tile distance from CAVE_EXIT_TILE.
# Each row: (item, weight at the exit, weight at full depth, depth where
# the weight starts rising, depth where it peaks, hits to mine, drop
# min, drop max).
# Near the lift only coal/copper spawn; iron fades in around depth 8,
# gold ~18, gems ~32 and ruby/diamond only past ~50.
CAVE_ORES = (
	('coal ore',     3.0, 2.4,   0,   0, 3, 1, 2),
	('copper ore',   2.6, 2.0,   0,   0, 3, 1, 2),
	('iron ore',     0.0, 2.2,   8,  28, 3, 1, 2),
	('gold ore',     0.0, 1.7,  18,  45, 4, 1, 2),
	('amethyst ore', 0.0, 1.0,  32,  70, 4, 1, 1),
	('emerald ore',  0.0, 0.9,  32,  70, 4, 1, 1),
	('ruby ore',     0.0, 0.7,  50,  95, 5, 1, 1),
	('diamond ore',  0.0, 0.6,  50,  95, 5, 1, 1),
)
CAVE_ORE_CHANCE = 0.030           # per land tile
CAVE_ROCK_CHANCE = 0.035          # per land tile (when no ore rolled)
CAVE_DECOR_CHANCE = 0.012         # per land tile (when no ore/rock rolled)
CAVE_PROP_RADIUS = 15             # tiles of props kept spawned around the player
CAVE_PROP_UNLOAD = 5              # extra rings before props despawn
# A few veins yield a refined good instead of the raw ore (coal reads
# better with the refined-fuel icon). CAVE_ORE_LOOT is the pool random
# ore loot rolls from.
CAVE_ORE_DROPS = {'coal ore': 'coal', 'amethyst ore': 'amethyst'}
CAVE_ORE_LOOT = tuple(CAVE_ORE_DROPS.get(row[0], row[0]) for row in CAVE_ORES)
CAVE_CRATE_HEALTH = 3             # axe hits to cut a crate/shelf apart
CAVE_CRATE_ORE_CHANCE = 0.10      # loaded crates/shelves: extra random ore

# ---- VILLAGES (overworld settlements) ----
# Same jittered-grid sampling as the cave entrances: one site per sector,
# inset from the borders so villages keep a minimum distance. Fully
# deterministic per (site tile, WORLD_SEED) - nothing to save.
VILLAGE_SECTOR_SIZE = 160         # tiles per sector
VILLAGE_DEAD_ZONE = 24            # min distance from a sector border
VILLAGE_START_TILE = (12, 13)     # farm / TMX start — villages stay clear
VILLAGE_START_CLEARANCE = 44      # Chebyshev tiles from VILLAGE_START_TILE
# Streaming around the site centre (Chebyshev tiles)
VILLAGE_LOAD_DISTANCE = 30
VILLAGE_UNLOAD_DISTANCE = 40
# The village core forces flat dry grassland while it is loaded (like the
# cave exit pad), so every site renders its layout the same way.
VILLAGE_LAND_MARGIN = 3
VILLAGE_RESERVE_MARGIN = 3
# Villager NPC behaviour
VILLAGER_SPEED = 105              # px/s wander speed
VILLAGER_IDLE_MIN = 1.2           # seconds standing still between walks
VILLAGER_IDLE_MAX = 3.4
VILLAGER_ACTIVE_START_HOUR = 6
VILLAGER_ACTIVE_END_HOUR = 20
# Plaza = the village green: the flattened dry centre the layout keeps
# clear. Not rendered - it only anchors the path starts.
VILLAGE_PLAZA = {
	'tiles': 2.0,                 # clear radius in map tiles
	'anchor': (1, 3),             # tile offset from the village centre
}
# Buildings laid out around the plaza. Rows: file, fallback width (tiles),
# anchor tile offset from the village centre. The width column is ONLY a
# fallback for a missing file: every footprint is measured from the art
# itself (art_tiles()). Art is bottom-anchored at the anchor tile; the
# walkable front is anchor+(1,1). The town hall sits at the centre, the
# other six homes ring it at an equal radius.
VILLAGE_BUILDINGS = (
	('town_hall', 'Town Hall.png', 4.3, (0, 0)),
	('bakery', 'Bakery.png', 3.3, (0, -6)),
	('smith', 'Blacksmith.png', 3.0, (7, -2)),
	('potion', 'Wizard.png', 3.0, (-7, -2)),
	('lumber', 'Lumber.png', 3.5, (7, 3)),
	('farmer', 'Farmer.png', 3.0, (0, 5)),
	('shop', 'Shop.png', 2.2, (-7, 3)),
)
# Tall props (trees, logs, rocks) keep this many tiles clear of every
# building footprint so canopies never draw over a roof or wall.
VILLAGE_BUILDING_CLEARANCE = 3
# Alternate building art used once the Heart of the Valley is placed.
VILLAGE_BUILDING_AFTER = {
	'town_hall': 'Town Hall_after.png',
}
# Jitter is disabled so the canonical path network stays perfectly
# aligned with every door tile. Variety comes from the natural props.
VILLAGE_ANCHOR_JITTER = 0
# Dirt paths: (target tile offset, start tile offset, route mode). The
# target is the building's front tile (anchor + (1,1)); the start sits
# outside the centre green on the side facing the building. 'vh' walks
# the column first, 'hv' the row first.
VILLAGE_PATHS = (
	((1, 1), (1, 6), 'vh'),       # town hall front (main square)
	((1, -5), (1, 6), 'vh'),      # bakery front (north approach)
	((8, -1), (1, 6), 'hv'),      # smith front (east approach)
	((-6, -1), (1, 6), 'hv'),     # potion front (west approach)
	((8, 4), (1, 6), 'hv'),       # lumber front (southeast approach)
	((1, 6), (1, 6), 'vh'),       # farmer front (south approach, main road)
	((-6, 4), (1, 6), 'hv'),      # shop front (southwest approach)
)
# Main road running south out of the plaza: (x, y0, y1). Starts at y=6
# so it clears the lumber/shop blocks (which end at relative y=5).
VILLAGE_ROAD = (1, 6, 18)
# Villagers: (name, home building key, wander zone (x0, y0, x1, y1) tile
# offsets from the village centre). Sprites live in
# graphics/character/Villagers/<Name>/{Down,Up,Left,Right}/.
VILLAGERS = (
	('Baker', 'bakery', (-2, -8, 2, -4)),
	('Blacksmith', 'smith', (5, -4, 9, 0)),
	('Wizard', 'potion', (-9, -4, -5, 0)),
	('Farmer', 'farmer', (-2, 3, 2, 7)),
	('Woodcutter', 'lumber', (5, 1, 9, 5)),
)
# Range (world px) in which RSHIFT opens the nearest villager's menu.
VILLAGER_TALK_RADIUS = int(TILE_SIZE * 1.5)
# Trade offers per villager (exact name from VILLAGERS).
#   'sell': player sells ONE unit for the coins shown.
#   'buy':  player buys ONE unit for the coins shown.
#   'barter': player gives N of the first item for ONE of the second.
#   'refine': alternating (item, amount) costs, then the reward.
VILLAGER_TRADES = {
	'Blacksmith': {
		'sell': (('coal', 2), ('copper', 5), ('iron', 9),
		         ('gold', 16), ('amethyst', 22), ('ruby', 26),
		         ('emerald', 30), ('diamond', 40),
		         ('hoe', 12), ('axe', 16), ('pickaxe', 16),
		         ('water_bucket', 14)),
		'buy': (('coal', 4), ('copper', 10), ('iron', 18),
		        ('gold', 32), ('amethyst', 44), ('ruby', 52),
		        ('emerald', 60), ('diamond', 80),
		        ('hoe', 24), ('axe', 32), ('pickaxe', 32),
		        ('water_bucket', 28)),
		'refine': (
			((('copper ore', 1), ('coal', 1)), 5, 'copper'),
			((('iron ore', 1), ('coal', 1)), 5, 'iron'),
			((('gold ore', 1), ('coal', 1)), 5, 'gold'),
			((('ruby ore', 1), ('coal', 1)), 5, 'ruby'),
			((('emerald ore', 1), ('coal', 1)), 5, 'emerald'),
			((('diamond ore', 1), ('coal', 1)), 5, 'diamond'),
		),
	},
	'Woodcutter': {
		'sell': (('wood', 3), ('birch_wood', 5),
		         ('cherry_wood', 10), ('pine_wood', 7)),
		'buy': (('wood', 5), ('birch_wood', 8),
		        ('cherry_wood', 15), ('pine_wood', 11)),
	},
	'Baker': {
		'sell': (('bread', 5), ('apple', 2), ('berry', 2),
		         ('wheat', 3), ('tomato', 3), ('cherry', 4),
		         ('orange', 5)),
		'buy': (('bread', 10), ('apple', 3), ('berry', 4),
		        ('wheat', 4), ('tomato', 5), ('cherry', 6),
		        ('orange', 7)),
	},
	'Wizard': {
		'barter': (
			((('ruby', 5),), 200, 'health_potion'),
			((('diamond', 5),), 200, 'miner_potion'),
			((('emerald', 5),), 200, 'night_vision_potion'),
			((('amethyst', 5),), 200, 'speed_potion'),
		),
	},
	'Farmer': {
		'buy': (('wheat_seed', 5), ('tomato_seed', 8),
		        ('oak_sapling', 12), ('birch_sapling', 12),
		        ('cherry_sapling', 15), ('pine_sapling', 15)),
		# Buy-back is always below the buy price above (so flipping seeds straight
		# back can never turn a profit) and below the general shop's sale price.
		'sell': (('wheat_seed', 2), ('tomato_seed', 4),
		         ('oak_sapling', 6), ('birch_sapling', 6),
		         ('cherry_sapling', 7), ('pine_sapling', 7)),
	},
}
