import json
import os
import pygame
from settings import user_data_path
from support import log_once

KEYBINDINGS_PATH = user_data_path('keybindings.json')

DEFAULT_BINDINGS = {
	'move_up': pygame.K_w,
	'move_down': pygame.K_s,
	'move_left': pygame.K_a,
	'move_right': pygame.K_d,
	'use_tool': pygame.K_RETURN,
	'use_item': pygame.K_RSHIFT,
	'interact': pygame.K_RSHIFT,
	'open_crafting': pygame.K_c,
	'open_inventory': pygame.K_e,
	'drop_item': pygame.K_q,
	'pause': pygame.K_ESCAPE,
	'hotbar_1': pygame.K_1,
	'hotbar_2': pygame.K_2,
	'hotbar_3': pygame.K_3,
	'hotbar_4': pygame.K_4,
	'hotbar_5': pygame.K_5,
	'hotbar_6': pygame.K_6,
	'hotbar_7': pygame.K_7,
	'hotbar_8': pygame.K_8,
	'hotbar_9': pygame.K_9,
}

# descriptive labels and categories for settings UI (Minecraft-style)
BINDING_INFO = {
	'move_up': ('MOVEMENT', 'Move Up'),
	'move_down': ('MOVEMENT', 'Move Down'),
	'move_left': ('MOVEMENT', 'Move Left'),
	'move_right': ('MOVEMENT', 'Move Right'),
	'use_tool': ('ACTIONS', 'Use Tool / Punch'),
	'use_item': ('ACTIONS', 'Plant / Water / Sleep'),
	'open_crafting': ('ACTIONS', 'Open Crafting Menu'),
	'open_inventory': ('ACTIONS', 'Open Inventory'),
	'drop_item': ('ACTIONS', 'Drop Held Item'),
	'hotbar_1': ('HOTBAR', 'Hotbar Slot 1'),
	'hotbar_2': ('HOTBAR', 'Hotbar Slot 2'),
	'hotbar_3': ('HOTBAR', 'Hotbar Slot 3'),
	'hotbar_4': ('HOTBAR', 'Hotbar Slot 4'),
	'hotbar_5': ('HOTBAR', 'Hotbar Slot 5'),
	'hotbar_6': ('HOTBAR', 'Hotbar Slot 6'),
	'hotbar_7': ('HOTBAR', 'Hotbar Slot 7'),
	'hotbar_8': ('HOTBAR', 'Hotbar Slot 8'),
	'hotbar_9': ('HOTBAR', 'Hotbar Slot 9'),
	'pause': ('MENU', 'Open Pause Menu'),
}

# Mouse bindings are NEGATIVE ints so they never collide with pygame key codes: -(event.button).
MOUSE_LEFT = -1
MOUSE_MIDDLE = -2
MOUSE_RIGHT = -3

_MOUSE_BUTTON_CODES = (MOUSE_LEFT, MOUSE_MIDDLE, MOUSE_RIGHT)
_MOUSE_BUTTON_LABELS = {
	MOUSE_LEFT: 'LEFT CLICK',
	MOUSE_MIDDLE: 'MIDDLE CLICK',
	MOUSE_RIGHT: 'RIGHT CLICK',
}

def is_mouse_binding(code):
	"""True when a stored binding code refers to a mouse button."""
	return isinstance(code, int) and code in _MOUSE_BUTTON_CODES

def mouse_button_code(event_button):
	"""Map a pygame MOUSEBUTTONDOWN button (1/2/3) to a binding code.
	Returns None for buttons that have no held state (the wheel)."""
	return -event_button if event_button in (1, 2, 3) else None

# current live bindings (mutable)
_bindings = dict(DEFAULT_BINDINGS)

# pretty names for pygame keys
_KEY_NAMES = {
	pygame.K_RETURN: 'ENTER',
	pygame.K_ESCAPE: 'ESC',
	pygame.K_UP: 'UP',
	pygame.K_DOWN: 'DOWN',
	pygame.K_LEFT: 'LEFT',
	pygame.K_RIGHT: 'RIGHT',
	pygame.K_PAGEUP: 'PAGE UP',
	pygame.K_PAGEDOWN: 'PAGE DOWN',
	pygame.K_TAB: 'TAB',
	pygame.K_LSHIFT: 'LSHIFT',
	pygame.K_RSHIFT: 'RSHIFT',
	pygame.K_LCTRL: 'LCTRL',
	pygame.K_RCTRL: 'RCTRL',
	pygame.K_LALT: 'LALT',
	pygame.K_RALT: 'RALT',
	pygame.K_BACKSPACE: 'BACKSPACE',
	pygame.K_CAPSLOCK: 'CAPS',
	pygame.K_SEMICOLON: ';',
	pygame.K_COMMA: ',',
	pygame.K_PERIOD: '.',
	pygame.K_SLASH: '/',
	pygame.K_BACKSLASH: '\\',
	pygame.K_LEFTBRACKET: '[',
	pygame.K_RIGHTBRACKET: ']',
	pygame.K_QUOTE: "'",
	pygame.K_MINUS: '-',
	pygame.K_EQUALS: '=',
	pygame.K_BACKQUOTE: '`',
}

def key_name(key_code):
	if is_mouse_binding(key_code):
		return _MOUSE_BUTTON_LABELS[key_code]
	if key_code in _KEY_NAMES:
		return _KEY_NAMES[key_code]
	try:
		name = pygame.key.name(key_code)
		return name.upper() if name else f'KEY {key_code}'
	except Exception:
		return f'KEY {key_code}'

def get_binding(action):
	return _bindings.get(action, DEFAULT_BINDINGS.get(action))

def get_bindings():
	return dict(_bindings)

def _mouse_pressed(code):
	"""True when the mouse button for a (negative) binding code is held."""
	try:
		return bool(pygame.mouse.get_pressed()[abs(code) - 1])
	except Exception:
		return False

def is_action_pressed(action):
	code = get_binding(action)
	if is_mouse_binding(code):
		return _mouse_pressed(code)
	keys = pygame.key.get_pressed()
	try:
		return bool(keys[code])
	except Exception:
		return False

def is_action_pressed_keys(keys, action):
	code = get_binding(action)
	if is_mouse_binding(code):
		return _mouse_pressed(code)
	try:
		return bool(keys[code])
	except Exception:
		return False

def is_key_for_action(key_code, action):
	return get_binding(action) == key_code

def is_any_hotbar_pressed():
	keys = pygame.key.get_pressed()
	for i in range(1, 10):
		code = get_binding(f'hotbar_{i}')
		if is_mouse_binding(code):
			if _mouse_pressed(code):
				return i - 1
			continue
		try:
			if keys[code]:
				return i - 1
		except Exception:
			continue
	return None

def has_conflict(key_code, exclude_action=None):
	conflicts = []
	for act, code in _bindings.items():
		if act == exclude_action:
			continue
		if code == key_code:
			conflicts.append(act)
	return conflicts

def set_binding(action, key_code):
	if action not in DEFAULT_BINDINGS:
		return False
	_bindings[action] = key_code
	save_bindings()
	return True

def reset_binding(action):
	if action in DEFAULT_BINDINGS:
		_bindings[action] = DEFAULT_BINDINGS[action]
		save_bindings()

def reset_all_bindings():
	global _bindings
	_bindings = dict(DEFAULT_BINDINGS)
	save_bindings()

def save_bindings():
	try:
		os.makedirs(os.path.dirname(KEYBINDINGS_PATH), exist_ok=True)
		with open(KEYBINDINGS_PATH, 'w') as f:
			json.dump(_bindings, f, indent=4)
	except Exception as exc:  # a lost rebind must not crash, but say so
		log_once('[Input] could not save keybindings', exc)

def load_bindings():
	global _bindings
	try:
		if os.path.exists(KEYBINDINGS_PATH):
			with open(KEYBINDINGS_PATH, 'r') as f:
				data = json.load(f)
			# migrate: only keep known actions, coerce to int
			loaded = {}
			for k, v in data.items():
				if k in DEFAULT_BINDINGS:
					try:
						loaded[k] = int(v)
					except Exception:
						continue
			# merge defaults for missing keys
			for k, v in DEFAULT_BINDINGS.items():
				if k not in loaded:
					loaded[k] = v
			_bindings = loaded
		else:
			_bindings = dict(DEFAULT_BINDINGS)
	except Exception:
		_bindings = dict(DEFAULT_BINDINGS)
	return dict(_bindings)

# auto-load on import
load_bindings()
