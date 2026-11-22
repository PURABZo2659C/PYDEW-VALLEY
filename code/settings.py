import os
import re
import sys
from pygame.math import Vector2

# A PyInstaller build is "frozen": assets live in the bundle at sys._MEIPASS.
FROZEN = getattr(sys, 'frozen', False)

if FROZEN:
	BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
	BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def asset_path(*parts):
	"""Read-only bundled resource (graphics, audio, font, data)."""
	return os.path.join(BASE_DIR, *parts)


# -- The interface font --
# Monocraft (SIL OFL 1.1) replaced non-redistributable Mojangles; it is wider, so sizes scale.
UI_FONT = 'font/ui.ttf'
UI_FONT_SCALE = 22.0 / 28.0

# The UI was designed at this canvas height; everything scales by this factor on bigger screens.
UI_REFERENCE_HEIGHT = 860

_ui_scale = 1.0


def set_ui_scale(value):
	"""Remember how much to scale the interface on this screen."""
	global _ui_scale
	_ui_scale = max(0.5, min(3.0, value))


def ui_scale():
	"""Interface scale factor for the current screen (1.0 = as designed)."""
	return _ui_scale


# The in-game HUD sits a little larger than the menus. Fixed-pixel HUD
# pieces (hotbar, hearts, panels) multiply by this; font and icon sizes
# already follow the display, so they use hud_scale() below.
HUD_SCALE = 1.25


def hud_scale():
	"""Display scale for HUD fonts and icons (already display-relative)."""
	return ui_scale() * HUD_SCALE


# Centre-to-centre spacing of the stacked menu buttons (title and pause).
MENU_BUTTON_SPACING = 124


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


def init_audio():
	"""Start the mixer, falling back to SDL's dummy driver when the machine
	has no sound device (WSL, headless Linux, remote sessions). Sounds still
	load and play - they are just silent.
	"""
	import pygame
	try:
		pygame.mixer.init()
	except pygame.error:
		pass
	if pygame.mixer.get_init():
		return True
	# WSLg has PulseAudio, but a bare WSL shell does not export its address.
	server = '/mnt/wslg/PulseServer'
	if (sys.platform.startswith('linux') and not os.environ.get('PULSE_SERVER')
			and os.path.exists(server)):
		os.environ['PULSE_SERVER'] = 'unix:' + server
		try:
			pygame.mixer.init()
		except pygame.error:
			pass
		if pygame.mixer.get_init():
			return True
	if os.path.exists('/mnt/wslg'):
		print('[Audio] no sound device - in WSL run: sudo apt install libpulse0')
	else:
		print('[Audio] no sound device, continuing silently')
	os.environ['SDL_AUDIODRIVER'] = 'dummy'
	try:
		pygame.mixer.init()
	except pygame.error:
		return False
	return pygame.mixer.get_init() is not None


# -- The game always runs full screen --
# No settings file or windowed mode: opens on the desktop at its resolution.
def app_version():
	"""The version of this build, from the bundled VERSION.txt."""
	path = asset_path('VERSION.txt')
	if not os.path.exists(path) and not FROZEN:
		# Running from source: the version lives in the build tooling.
		path = os.path.join(BASE_DIR, 'APP', 'build', 'VERSION.txt')
	try:
		with open(path, 'r', encoding='utf-8') as handle:
			return handle.read().strip() or 'unknown'
	except OSError:
		return 'dev'


_HELP_VERSION = re.compile(r'(Pydew Valley \[v)[0-9][0-9.]*(\])')


def help_doc_path():
	"""Path to the in-game help page.
	Packaged builds copy and version-stamp the page beside the executable,
	except macOS app bundles, whose signed contents must not be modified.
	"""
	bundled = asset_path('PYDEW VALLEY DOCUMENTATION.html')
	if not FROZEN:
		return bundled
	if sys.platform == 'darwin':
		return bundled
	beside = user_data_path('PYDEW VALLEY DOCUMENTATION.html')
	try:
		with open(bundled, 'r', encoding='utf-8') as handle:
			html = handle.read()
		html = _HELP_VERSION.sub(
			lambda match: match.group(1) + app_version() + match.group(2), html)
		ensure_user_data_dir()
		with open(beside, 'w', encoding='utf-8') as handle:
			handle.write(html)
		return beside
	except OSError:
		return beside if os.path.exists(beside) else bundled

# Always full screen: no canvas to hardcode, everything reads the live display surface.
TILE_SIZE = 128

# Structure collision masks are projected onto the ground and quantised to
# this pixel grid: small enough to trace the authored outline, coarse enough
# to keep the collision group compact (one blocker sprite per run).
STRUCTURE_COLLISION_STEP = 8

# The game always runs full screen; there is no settings file.
def ini_bool(key, default=True):
	"""Always returns default since there is no settings file."""
	return default

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

# Auto-selector snaps to the nearest breakable within SNAP_RANGE and a +-60 cone.
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

# Fruit trees: spawn chance and fruit drops when felled (per-biome art/item in BIOMES).
FRUIT_TREE_CHANCE = 0.25
APPLE_DROP_MIN = 1
APPLE_DROP_MAX = 3

# Chance one open tile gets a prop; per-tile noise keeps density even across chunks.
PROP_DENSITY = {
	'trees':   (0.050, 11),   # (chance per open tile, white-noise seed)
	'debris':  (0.014, 23),
	'rocks':   (0.007, 37),
	'bushes':  (0.027, 51),
	'flowers': (0.023, 67),
}
# How far the local average bends around the mean above (0.35 = +-35%).
PROP_DENSITY_RELIEF = 0.35
# Feature size of that clumping band, in tiles (~8-tile blobs).
PROP_DENSITY_NOISE_SCALE = 0.125

# Berry bush: spawn weight vs 100 for plain bushes, and berry yield when cut.
BERRY_BUSH_WEIGHT = 35
BERRY_DROP_MIN = 1
BERRY_DROP_MAX = 2

# ---- BIOMES: art pools + drops per biome ----
# Biome art pools and drops; files live in graphics/Biomes/<biome>/.
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

# Flower/fungus pickups keyed by art file stem; each type is its own item.
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
# fBm clusters near 0.5; x4 stretch spreads the four biomes into equal bands.
BIOME_STRETCH = 4.0
# Dither band width at biome borders (speckled transition).
BIOME_DITHER = 0.02

# All wood flavours - crafting treats a 'wood' cost as this group.
WOOD_ITEMS = ('wood', 'birch_wood', 'cherry_wood', 'pine_wood')
POTION_ITEMS = ('health_potion', 'miner_potion',
                'night_vision_potion', 'speed_potion')
REFINED_ITEMS = ('coal', 'copper', 'iron', 'gold', 'amethyst',
                 'emerald', 'ruby', 'diamond')

# Saplings: species -> biome tree art; felled trees drop theirs to replant.
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
# Trees mature after one in-game day; TREE_GROWTH_SECONDS is legacy save migration.
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

# Town-hall quests: one full stack (64) per item; pages ask saplings, produce, ores.
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
# Real seconds per 10 game minutes (1 day ~ 600s); elapsed time is subtracted, no drift.
# Do NOT change the rate: the potion timer and farmland decay tests are calibrated to it.
SECONDS_PER_MINUTE = 25 / 6
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
# Empty tilled tiles revert to grass after half an in-game day (~10 real min).
FARMLAND_EMPTY_MINUTES = MINUTES_PER_HOUR * (HOURS_PER_DAY // 2)
DAY_START_HOUR = 7
NIGHT_START_HOUR = 20
DAYS_PER_SEASON = 28
SEASONS = ['Spring', 'Summer', 'Fall', 'Winter']

# Potions tick on the REAL clock; saves store seconds left, so they freeze while off.
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
# Shore-bank bonus: two tiers - touching water gets the wider damp band, within 2 slimmer.
SHORE_WET_BOOST = 0.07
SHORE_WET_BOOST_ADJ = 0.12

# -- Flat terrain --
# Both maps are flat planes; overworld water is lakes + rivers, the cave a lava ocean.
# Rivers: |v - level| < half-width of low-frequency noise, dithered per tile.
RIVER_NOISE_SCALE = 0.006            # river field feature size (~170 tiles)
RIVER_LEVELS = (
	(0.50, 0.010),   # main stems
	(0.31, 0.008),   # second family (other contour lines)
	(0.69, 0.008),
)
# Lakes: high band of a separate lake noise -> blob basins.
NOISE_SCALE_LAKE = 0.008             # lake feature size (~125-tile blobs)
LAKE_THRESHOLD = 0.60
# Flat overlays lift above their tile's ground; must stay 0 < lift < 128 or ice overpaints.
OVERLAY_LIFT = 64
# Added to sprite depth keys; must clear OVERLAY_LIFT so sprites beat same-tile patches.
SPRITE_LIFT = 320
# Tiles around a doorway where the player draws in front of the structure's art.
# Render-only; collision is unchanged. Far behind the building keeps normal occlusion.
STRUCTURE_FRONT_RADIUS = 3

# Player stats

# ---- CAVE (separate world space) - also a FLAT plane ----
# Exit near top-left; everything not land is an endless lava ocean, no void.
CAVE_EXIT_TILE = (1, 0)
CAVE_EXIT_PAD_RADIUS = 3          # forced flat land around the exit platform
# Land where the fractal value sits in a band around 0.5; calibrated for ~50/50 land/lava.
CAVE_NOISE_SCALE = 0.05           # corridor feature size (~20-tile cycles)
CAVE_NOISE_OCTAVES = 4
# Entrances: jittered grid sampling, one per sector, inset by the dead zone.
CAVE_SECTOR_SIZE = 48             # tiles per sector
CAVE_ENTRANCE_DEAD_ZONE = 8       # min distance from a sector border
CAVE_ENTRANCE_RESERVE_RADIUS = 4  # no trees/rocks within this many tiles
CAVE_DARKNESS_ALPHA = 46          # ambient dim overlay while inside
# ---- Cave content: rocks, ore veins and decorations ----
# One prop max per land tile, deterministic per (tile, WORLD_SEED); ores rarer with depth.
# Rows: (item, exit weight, deep weight, rise depth, peak depth, hits, drop min, max).
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
# Some veins yield a refined good; CAVE_ORE_LOOT is the pool ore loot rolls from.
CAVE_ORE_DROPS = {'coal ore': 'coal', 'amethyst ore': 'amethyst'}
CAVE_ORE_LOOT = tuple(CAVE_ORE_DROPS.get(row[0], row[0]) for row in CAVE_ORES)
CAVE_CRATE_HEALTH = 3             # axe hits to cut a crate/shelf apart
CAVE_CRATE_ORE_CHANCE = 0.10      # loaded crates/shelves: extra random ore

# ---- VILLAGES (overworld settlements) ----
# Jittered grid like cave entrances: one site per sector, deterministic, nothing to save.
VILLAGE_SECTOR_SIZE = 160         # tiles per sector
VILLAGE_DEAD_ZONE = 24            # min distance from a sector border
VILLAGE_START_TILE = (12, 13)     # farm / TMX start - villages stay clear
VILLAGE_START_CLEARANCE = 44      # Chebyshev tiles from VILLAGE_START_TILE
# Streaming around the site centre (Chebyshev tiles)
VILLAGE_LOAD_DISTANCE = 30
VILLAGE_UNLOAD_DISTANCE = 40
# The core forces flat dry grassland while loaded (like the cave exit pad).
VILLAGE_LAND_MARGIN = 3
VILLAGE_RESERVE_MARGIN = 3
# Villager NPC behaviour
VILLAGER_SPEED = 105              # px/s wander speed
VILLAGER_IDLE_MIN = 1.2           # seconds standing still between walks
VILLAGER_IDLE_MAX = 3.4
VILLAGER_ACTIVE_START_HOUR = 6
VILLAGER_ACTIVE_END_HOUR = 20
# Plaza = the flattened dry centre; not rendered, only anchors the path starts.
VILLAGE_PLAZA = {
	'tiles': 2.0,                 # clear radius in map tiles
	'anchor': (1, 3),             # tile offset from the village centre
}
# Rows: (key, file, fallback width, anchor); footprints come from art_tiles(), front anchor+(1,1).
VILLAGE_BUILDINGS = (
	('town_hall', 'Town Hall.png', 4.3, (0, 0)),
	('bakery', 'Bakery.png', 3.3, (0, -6)),
	('smith', 'Blacksmith.png', 3.0, (7, -2)),
	('potion', 'Wizard.png', 3.0, (-7, -2)),
	('lumber', 'Lumber.png', 3.5, (7, 3)),
	('farmer', 'Farmer.png', 3.0, (0, 5)),
	('shop', 'Shop.png', 2.2, (-7, 3)),
)
# Tall props keep this many tiles clear of footprints so canopies miss roofs.
VILLAGE_BUILDING_CLEARANCE = 3
# Alternate building art used once the Heart of the Valley is placed.
VILLAGE_BUILDING_AFTER = {
	'town_hall': 'Town Hall_after.png',
}
# Jitter disabled so paths stay aligned with every door tile.
VILLAGE_ANCHOR_JITTER = 0
# Paths: (target offset, start offset, route); 'vh' walks the column first, 'hv' the row.
VILLAGE_PATHS = (
	((1, 1), (1, 6), 'vh'),       # town hall front (main square)
	((1, -5), (1, 6), 'vh'),      # bakery front (north approach)
	((8, -1), (1, 6), 'hv'),      # smith front (east approach)
	((-6, -1), (1, 6), 'hv'),     # potion front (west approach)
	((8, 4), (1, 6), 'hv'),       # lumber front (southeast approach)
	((1, 6), (1, 6), 'vh'),       # farmer front (south approach, main road)
	((-6, 4), (1, 6), 'hv'),      # shop front (southwest approach)
)
# Main road south out of the plaza: (x, y0, y1); starts at y=6 to clear the blocks.
VILLAGE_ROAD = (1, 6, 18)
# Villagers: (name, home key, wander zone); sprites in graphics/character/Villagers/<Name>/.
VILLAGERS = (
	('Baker', 'bakery', (-2, -8, 2, -4)),
	('Blacksmith', 'smith', (5, -4, 9, 0)),
	('Wizard', 'potion', (-9, -4, -5, 0)),
	('Farmer', 'farmer', (-2, 3, 2, 7)),
	('Woodcutter', 'lumber', (5, 1, 9, 5)),
)
# Range (world px) in which RSHIFT opens the nearest villager's menu.
VILLAGER_TALK_RADIUS = int(TILE_SIZE * 1.5)
# Trades per villager: 'sell'/'buy' for coins, 'barter' N for one, 'refine' costs then reward.
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
		# Buy-back below buy and shop prices so flipping seeds never turns a profit.
		'sell': (('wheat_seed', 2), ('tomato_seed', 4),
		         ('oak_sapling', 6), ('birch_sapling', 6),
		         ('cherry_sapling', 7), ('pine_sapling', 7)),
	},
}
