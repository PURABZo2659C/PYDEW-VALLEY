import json
import os
import shutil
import time
from inventory_model import Inventory, LEGACY_SEED_ALIASES
from settings import TILE_SIZE, WORLD_SEED, user_data_path

SAVE_VERSION = 2
# The save lives beside the executable, so a portable copy carries its world along.
SAVE_PATH = user_data_path('save.json')


def _backup_path():
	return SAVE_PATH + '.bak'


def _migrate_completed_quests(quests):
	aliases = {
		'0:wheat': '0:wheat_seed',
		'0:tomato': '0:tomato_seed',
	}
	return [aliases.get(quest, quest) for quest in quests]


def _rename_item_keys(node, old, new):
	"""Rename an item id anywhere in a saved structure (dict keys, dict
	values and list entries) so older keeps keep their items."""
	if isinstance(node, dict):
		renamed = {}
		for key, value in node.items():
			renamed[new if key == old else key] = _rename_item_keys(
				value, old, new)
		return renamed
	if isinstance(node, list):
		return [_rename_item_keys(entry, old, new) for entry in node]
	if isinstance(node, str) and node == old:
		return new
	return node


def _migrate_save(data):
	if not isinstance(data, dict):
		return None
	player = data.get('player')
	if not isinstance(player, dict):
		return None

	version = data.get('version', 1)
	try:
		version = int(version)
	except (TypeError, ValueError):
		version = 1

	if 'inventory' not in player:
		inventory = Inventory.from_legacy(
			player.get('item_inventory'),
			player.get('seed_inventory'),
			player.get('hotbar'))
		player['inventory'] = inventory.to_data()
		player['completed_quests'] = _migrate_completed_quests(
			list(player.get('completed_quests', ())))
		selected_seed = player.get('selected_seed')
		player['selected_seed'] = LEGACY_SEED_ALIASES.get(
			selected_seed, selected_seed)
		for key in ('item_inventory', 'seed_inventory', 'hotbar'):
			player.pop(key, None)
	else:
		inventory = Inventory.from_data(player.get('inventory'))
		player['inventory'] = inventory.to_data()

	try:
		player['hotbar_index'] = min(
			8, max(0, int(player.get('hotbar_index', 0))))
	except (TypeError, ValueError):
		player['hotbar_index'] = 0

	player.setdefault('heart_placed', False)
	player.setdefault('credits_seen', False)
	player.setdefault('water_bucket_amount', 0)
	player.setdefault('selected_tool', 'hoe')
	player.setdefault('selected_seed', None)
	player.setdefault('potion_effects', {})
	player.setdefault('completed_quests', [])

	# 'Armor Potion' was rebranded as the Miner Potion (one-hit break).
	player = _rename_item_keys(player, 'armor_potion', 'miner_potion')
	data['player'] = player

	data['version'] = SAVE_VERSION
	return data


def _build_save_data(level):
	player = level.player
	soil = level.soil_layer

	plants_data = []
	for plant in soil.plant_sprites.sprites():
		plants_data.append({
			'grid_x': plant.rect.centerx // TILE_SIZE,
			'grid_y': plant.rect.centery // TILE_SIZE,
			'plant_type': plant.plant_type,
			'age': plant.age,
		})

	ow = getattr(level, 'overworld_world_gen', None)
	removed_trees = ow.serialize_removed_trees() if ow else []
	removed_debris = ow.serialize_removed_debris() if ow else []
	removed_rocks = ow.serialize_removed_rocks() if ow else []
	planted_trees = (level.serialize_planted_trees()
	                 if hasattr(level, 'serialize_planted_trees') else [])
	bridges = (level.serialize_bridges()
	           if hasattr(level, 'serialize_bridges') else [])

	inventory = getattr(player, 'inventory', None)
	if inventory is None:
		inventory = Inventory.from_legacy(
			getattr(player, 'item_inventory', {}),
			getattr(player, 'seed_inventory', {}),
			getattr(player, 'hotbar', []))

	# DEMO ON: store the PRE-DEMO inventory snapshot so debug stock never overwrites real items.
	snap = getattr(level, '_demo_inv_snapshot', None)
	if snap is not None:
		inv_data = [[stack[0], int(stack[1])] if stack else None
		            for stack in snap]
	else:
		inv_data = inventory.to_data()

	return {
		'version': SAVE_VERSION,
		# World seed this save came from; pre-seed saves fall back to the legacy seed.
		'world_seed': int(getattr(level, 'world_seed', WORLD_SEED)),
		'player': {
			'pos': [player.pos.x, player.pos.y],
			'status': player.status,
			'frame_index': player.frame_index,
			'money': player.money,
			'energy': player.energy,
			'inventory': inv_data,
			'selected_tool': player.selected_tool,
			'selected_seed': player.selected_seed,
			'hotbar_index': player.hotbar_index,
			'water_bucket_amount': player.water_bucket_amount,
			# Seconds LEFT per effect, not absolute expiry: the countdown freezes while closed.
			'potion_effects': {
				effect: round(float(player.potion_remaining(effect)), 3)
				for effect in player.potion_effects
				if player.potion_remaining(effect) > 0
			},
			'completed_quests': sorted(getattr(player, 'completed_quests', ())),
			'heart_placed': bool(getattr(player, 'heart_placed', False)),
			'credits_seen': bool(getattr(player, 'credits_seen', False)),
		},
		'soil_grid': soil.grid,
		'farmland_timestamps': soil.serialize_tilled_at(),
		'plants': plants_data,
		'removed_trees': removed_trees,
		'removed_debris': removed_debris,
		'removed_rocks': removed_rocks,
		'planted_trees': planted_trees,
		'bridges': bridges,
		'raining': level.raining,
		'rain_days_left': level.rain_days_left,
		'sky_night': level.sky.night,
		'sky_color': level.sky.start_color,
		'time': {
			'hour': level.time_manager.hour,
			'minute': level.time_manager.minute,
			'day': level.time_manager.day,
			'season': level.time_manager.season_index,
			'year': level.time_manager.year,
			'total_minutes': level.time_manager.total_minutes,
		},
		# Tutorial step to resume at, so undone instructions come back after save/quit.
		'tutorial_step': int(getattr(level, 'tutorial_step', 0)),
		'scene': getattr(level, 'scene', 'overworld'),
		'return_pos': (list(level.return_pos)
		               if getattr(level, 'return_pos', None) else None),
		'return_level': getattr(level, 'return_level', 0),
	}


def save_game(level):
	try:
		data = _build_save_data(level)
		directory = os.path.dirname(SAVE_PATH)
		if directory:
			os.makedirs(directory, exist_ok=True)
		temp_path = SAVE_PATH + '.tmp'
		backup_path = _backup_path()
		with open(temp_path, 'w', encoding='utf-8') as handle:
			json.dump(data, handle, indent=4)
			handle.flush()
			os.fsync(handle.fileno())

		if os.path.exists(SAVE_PATH):
			backup_temp = backup_path + '.tmp'
			shutil.copy2(SAVE_PATH, backup_temp)
			os.replace(backup_temp, backup_path)

		os.replace(temp_path, SAVE_PATH)
		return True
	except (OSError, TypeError, ValueError):
		temp_path = SAVE_PATH + '.tmp'
		if os.path.exists(temp_path):
			try:
				os.remove(temp_path)
			except OSError:
				pass
		return False


def load_save():
	for path in (SAVE_PATH, _backup_path()):
		if not os.path.exists(path):
			continue
		try:
			with open(path, 'r', encoding='utf-8') as handle:
				data = json.load(handle)
		except (OSError, json.JSONDecodeError):
			continue
		migrated = _migrate_save(data)
		if migrated is not None:
			return migrated
	return None


def save_exists():
	return os.path.exists(SAVE_PATH)


def delete_save():
	"""Remove the save file and its backup.
	Another copy of the game can hold save.json open, and a failed delete
	would leave the old save behind. Retries a few times.
	"""
	for _attempt in range(5):
		for path in (SAVE_PATH, _backup_path(), SAVE_PATH + '.tmp'):
			if os.path.exists(path):
				try:
					os.remove(path)
				except OSError:
					pass
		if not (os.path.exists(SAVE_PATH) or os.path.exists(_backup_path())):
			return True
		time.sleep(0.2)
	return not (os.path.exists(SAVE_PATH) or os.path.exists(_backup_path()))
