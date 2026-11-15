"""Interactive rows inside the F5 debug overlay.
DEMO is a pill switch; Rain and Season are combo boxes that drop their
list upward; Time and Player grid are text boxes with fixed punctuation.
"""

import pygame
from settings import SEASONS, TILE_SIZE, asset_path, ui_font

# palette (matches the F5 info box)
BOX_BG = (18, 18, 22, 235)
BOX_EDGE = (120, 120, 132)
DIM_EDGE = (70, 70, 78)
FOCUS_EDGE = (255, 255, 100)
LABEL_COL = (218, 218, 218)
DIM_COL = (150, 150, 160)
LIST_BG = (24, 24, 30, 245)
LIST_EDGE = (140, 140, 155)
ITEM_HOVER = (70, 70, 84)
ITEM_ON = (64, 122, 68)
# DEMO pill: wordless switch, green = ON, red = OFF
PILL_ON = (63, 191, 95)
PILL_OFF = (214, 69, 69)
PILL_KNOB = (242, 242, 245)
PILL_KNOB_EDGE = (24, 24, 28)

RAIN_OPTIONS = ((('False'), False), (('True'), True))
SEASON_OPTIONS = tuple((name, i) for i, name in enumerate(SEASONS))
TELEPORT_OPTIONS = (
	('Spawn', 'spawn'),
	('Village', 'village'),
	('Oak Woods', 'oak'),
	('Birch Forest', 'birch'),
	('Cherry Blossom', 'cherry'),
	('Snowy Pine', 'pine'),
	('Cave', 'cave'),
)

WIDGET_H = 20
ITEM_H = 22


class DebugControls:
	"""Editable rows living inside the F5 info box."""

	DROPDOWNS = ('rain', 'season', 'teleport')
	TEXTBOXES = ('time', 'grid')
	TOGGLES = ('demo',)

	def __init__(self):
		self.font = ui_font(18)
		self.demo_on = False
		self.open_menu = None
		self.menu_index = 0
		self.option_rects = []
		self.menu_rect = None
		self.focused = None
		self._fresh = False
		self.demo_confirm = False
		self.demo_confirm_rect = None
		self.demo_confirm_yes = None
		self.demo_confirm_no = None
		self.time_parts = ['', '']
		self.time_field = 0
		self.time_pm = False
		self.grid_parts = ['', '']
		self.grid_field = 0
		self.layout = {}
		self.teleport_choice = 'village'

	# ---- STATE ----
	@property
	def active(self):
		"""True while the panel owns the keyboard/mouse."""
		return self.focused is not None or self.open_menu is not None or self.demo_confirm

	@staticmethod
	def options(kind):
		if kind == 'rain':
			return RAIN_OPTIONS
		if kind == 'teleport':
			return TELEPORT_OPTIONS
		return SEASON_OPTIONS

	@staticmethod
	def _int(text, default=0):
		try:
			return int(text)
		except (TypeError, ValueError):
			return default

	def close(self, level):
		"""Commit any in-progress edit and drop every focus."""
		if self.focused:
			self._apply(level)
		self.focused = None
		self.open_menu = None

	# ---- SIZING ----
	def widget_width(self, kind, font):
		"""Width the closed widget needs for its widest possible value."""
		if kind == 'demo':
			return 46            # the pill switch
		if kind == 'time':
			return font.size(self.time_text(11, 50))[0] + 18
		if kind == 'grid':
			return font.size('(-9999, -9999)')[0] + 18
		return max(font.size(label)[0]
		           for label, _value in self.options(kind)) + 34

	@staticmethod
	def time_text(hour, minute):
		"""'hh:MM AM/PM' - the 12-hour reading the Time box shows, so
		the value never has to be decoded from a 24-hour number."""
		hour = int(hour)
		return (f"{(hour - 1) % 12 + 1:02d}:{int(minute):02d} "
		        f"{'PM' if hour >= 12 else 'AM'}")

	# ---- DRAW - closed widget (inside the info box) ----
	def segments(self, kind, fallback):
		"""[(text, is_editable), ...] to render inside a text box."""
		if kind == 'time' and self.focused == 'time':
			return [(self.time_parts[0].ljust(2, '_'), self.time_field == 0),
			        (':', False),
			        (self.time_parts[1].ljust(2, '_'), self.time_field == 1),
			        (' ', False),
			        ('PM' if self.time_pm else 'AM',
			         self.time_field == 2)]
		if kind == 'grid' and self.focused == 'grid':
			return [('(', False),
			        (self.grid_parts[0] or '_', self.grid_field == 0),
			        (', ', False),
			        (self.grid_parts[1] or '_', self.grid_field == 1),
			        (')', False)]
		return [(fallback, False)]

	def draw_widget(self, surface, kind, rect, fallback, font,
	                enabled=True):
		"""Draw one closed widget (DEMO pill / combo box / text box) and remember its
		rect so the next click can hit it. While DEMO is off the edit rows are
		drawn dimmed: they show their value but take no input.
		"""
		self.layout[kind] = rect
		if kind in self.TOGGLES:
			self._draw_pill(surface, rect, bool(fallback))
			return
		bg = pygame.Surface(rect.size, pygame.SRCALPHA)
		bg.fill(BOX_BG)
		surface.blit(bg, rect.topleft)
		lit = enabled and ((self.focused == kind)
		                   or (self.open_menu == kind))
		edge = FOCUS_EDGE if lit else (BOX_EDGE if enabled else DIM_EDGE)
		pygame.draw.rect(surface, edge, rect, 1, 6)

		cx = rect.x + 7
		cy = rect.centery - font.get_height() // 2 + 2
		text_col = LABEL_COL if enabled else DIM_COL
		if kind in self.DROPDOWNS:
			# combo: current value, arrow pinned to the right
			surf = font.render(str(fallback), True, text_col)
			surface.blit(surf, (cx, cy))
			ax, ay = rect.right - 13, rect.centery
			pygame.draw.polygon(surface,
			                    DIM_COL if enabled else DIM_EDGE,
			                    [(ax - 5, ay - 2), (ax + 5, ay - 2),
			                     (ax, ay + 5)])
			return
		# text box: fixed punctuation, editable digits in focus colour
		for text, editable in self.segments(kind, fallback):
			if not enabled:
				col = DIM_COL
			else:
				col = FOCUS_EDGE if (lit and editable) else LABEL_COL
			surf = font.render(text, True, col)
			surface.blit(surf, (cx, cy))
			cx += surf.get_width()

	def draw_demo_confirm(self, surface):
		"""Modal confirmation for turning DEMO on. DEMO is one-shot and
		cannot be turned off again, so the player is asked first."""
		if not self.demo_confirm:
			self.demo_confirm_rect = None
			self.demo_confirm_yes = None
			self.demo_confirm_no = None
			return
		sw, sh = surface.get_size()
		box = pygame.Rect(0, 0, int(sw * 0.52), int(sh * 0.20))
		box.center = (sw // 2, sh // 2)
		self.demo_confirm_rect = box
		# dim the world behind the dialog
		overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
		overlay.fill((0, 0, 0, 160))
		surface.blit(overlay, (0, 0))
		pygame.draw.rect(surface, (34, 34, 40), box, 0, 10)
		pygame.draw.rect(surface, (180, 150, 70), box, 2, 10)
		tfont = self.font
		lines = (
			'Enable DEMO mode?',
			'Once turned on, DEMO CANNOT be turned off.',
			'Confirm to continue.',
		)
		y = box.y + 16
		for line in lines:
			surf = tfont.render(line, True, (240, 230, 200))
			surface.blit(surf, (box.centerx - surf.get_width() // 2, y))
			y += surf.get_height() + 2
		# YES / NO buttons
		btn_w, btn_h = 90, 30
		gap = 28
		yes = pygame.Rect(box.centerx - btn_w - gap // 2, box.bottom - btn_h - 14,
		                  btn_w, btn_h)
		no = pygame.Rect(box.centerx + gap // 2, box.bottom - btn_h - 14,
		                 btn_w, btn_h)
		self.demo_confirm_yes = yes
		self.demo_confirm_no = no
		for rect, label, col in ((yes, 'YES', (63, 191, 95)),
		                          (no, 'NO', (214, 69, 69))):
			pygame.draw.rect(surface, col, rect, 0, 6)
			pygame.draw.rect(surface, (12, 12, 14), rect, 1, 6)
			s = tfont.render(label, True, (20, 20, 20))
			surface.blit(s, (rect.centerx - s.get_width() // 2,
			                 rect.centery - s.get_height() // 2))

	def _draw_pill(self, surface, rect, on):
		"""The DEMO switch: a wordless pill — green when ON, red when
		OFF — with a knob that slides to the active side, like the
		reference toggle. No ON/OFF text, the colour says it all."""
		r = rect.h // 2
		pygame.draw.rect(surface, PILL_ON if on else PILL_OFF,
		                 rect, 0, r)
		pygame.draw.rect(surface, (12, 12, 14), rect, 1, r)
		knob_r = r - 3
		kx = rect.right - knob_r - 3 if on else rect.left + knob_r + 3
		cy = rect.centery
		pygame.draw.circle(surface, PILL_KNOB_EDGE, (kx, cy), knob_r + 1)
		pygame.draw.circle(surface, PILL_KNOB, (kx, cy), knob_r)

	# ---- DRAW - open list (on top of everything) ----
	def draw_popup(self, surface, level):
		"""Draw the option list. It opens UPWARD, resting on top of its row - the
		info box hugs the bottom of the screen, so up is where the room is.
		Called at the very end of the frame so nothing paints over it.
		"""
		self.option_rects = []
		if not self.open_menu:
			self.menu_rect = None
			return
		anchor = self.layout.get(self.open_menu)
		if anchor is None:
			self.open_menu = None
			return

		opts = self.options(self.open_menu)
		width = max(self.font.size(label)[0]
		            for label, _v in opts) + 30
		height = len(opts) * ITEM_H + 8
		rect = pygame.Rect(anchor.left, anchor.top - 2 - height,
		                   width, height)
		# keep the list on screen (fall back to below the row only if
		# there is somehow no room above it)
		sw, sh = surface.get_size()
		if rect.top < 4:
			rect.top = anchor.bottom + 2
		if rect.bottom > sh - 4:
			rect.bottom = sh - 4
		if rect.right > sw - 4:
			rect.right = sw - 4
		if rect.left < 4:
			rect.left = 4
		self.menu_rect = rect

		bg = pygame.Surface(rect.size, pygame.SRCALPHA)
		bg.fill(LIST_BG)
		surface.blit(bg, rect.topleft)
		pygame.draw.rect(surface, LIST_EDGE, rect, 1, 6)

		current = self._current_value(level, self.open_menu)
		mouse = pygame.mouse.get_pos()
		for i, (label, value) in enumerate(opts):
			item = pygame.Rect(rect.x + 3, rect.y + 4 + i * ITEM_H,
			                  rect.w - 6, ITEM_H - 2)
			self.option_rects.append((item, self.open_menu, value))
			if value == current:
				pygame.draw.rect(surface, ITEM_ON, item, 0, 4)
			elif item.collidepoint(mouse):
				pygame.draw.rect(surface, ITEM_HOVER, item, 0, 4)
			surf = self.font.render(label, True, LABEL_COL)
			surface.blit(surf, (item.x + 8,
			                    item.centery - surf.get_height() // 2))

	def _current_value(self, level, kind):
		if kind == 'rain':
			return bool(getattr(level, 'raining', False))
		if kind == 'teleport':
			return self.teleport_choice
		return int(level.time_manager.season_index)

	# ---- INPUT ----
	def handle_events(self, level, events):
		"""Consume the clicks/keys that belong to the panel. Returns True
		when an event was taken (so the world must not also react)."""
		consumed = False
		if self.demo_confirm:
			# modal confirm: everything is eaten while it is open
			for event in events:
				if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
					if (self.demo_confirm_yes is not None
					        and self.demo_confirm_yes.collidepoint(event.pos)):
						self.demo_confirm = False
						level.set_debug_demo(True)
					elif (self.demo_confirm_no is not None
					        and self.demo_confirm_no.collidepoint(event.pos)):
						self.demo_confirm = False
					# clicking anywhere else cancels the dialog
					else:
						self.demo_confirm = False
					consumed = True
				elif event.type == pygame.KEYDOWN:
					if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
					                 pygame.K_y):
						self.demo_confirm = False
						level.set_debug_demo(True)
					else:
						self.demo_confirm = False
					consumed = True
			return consumed
		for event in events:
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				consumed = self._click(level, event.pos) or consumed
			elif event.type == pygame.KEYDOWN and self.active:
				self._key(level, event)
				consumed = True
		return consumed

	def _click(self, level, pos):
		# 0) the one-shot DEMO confirmation dialog eats every click
		if self.demo_confirm:
			if (self.demo_confirm_yes is not None
			        and self.demo_confirm_yes.collidepoint(pos)):
				self.demo_confirm = False
				level.set_debug_demo(True)
				return True
			if (self.demo_confirm_no is not None
			        and self.demo_confirm_no.collidepoint(pos)):
				self.demo_confirm = False
				return True
			# clicking anywhere else cancels the dialog
			self.demo_confirm = False
			return True
		# 1) an open list: pick an option, or close it
		if self.open_menu:
			for rect, kind, value in self.option_rects:
				if rect.collidepoint(pos):
					self._select(level, kind, value)
					self.open_menu = None
					return True
			anchor = self.layout.get(self.open_menu)
			self.open_menu = None
			if anchor is not None and anchor.collidepoint(pos):
				return True        # clicked the closed box again: toggle

		# 2) a focused text box loses focus on any other click
		if self.focused:
			self._apply(level)
			self.focused = None

		# 3) hit-test the widgets drawn inside the info box
		for kind, rect in self.layout.items():
			if not rect.collidepoint(pos):
				continue
			if kind in self.TOGGLES:
				self.focused = None
				self.open_menu = None
				if self.demo_on:
					# one-shot: once enabled it can never be turned off
					try:
						level.instruction_panel.show_error(
							'DEMO is already on and cannot be turned off.')
					except Exception:
						pass
					return True
				# ask before turning it on: it cannot be undone
				self.demo_confirm = True
				self._fresh = False
				# lay out the Yes/No buttons immediately so the confirm
				# can be accepted without waiting for a draw pass
				try:
					sw, sh = pygame.display.get_surface().get_size()
					box = pygame.Rect(0, 0, int(sw * 0.52),
					                 int(sh * 0.20))
					box.center = (sw // 2, sh // 2)
					btn_w, btn_h = 90, 30
					gap2 = 28
					self.demo_confirm_yes = pygame.Rect(
						box.centerx - btn_w - gap2 // 2,
						box.bottom - btn_h - 14, btn_w, btn_h)
					self.demo_confirm_no = pygame.Rect(
						box.centerx + gap2 // 2,
						box.bottom - btn_h - 14, btn_w, btn_h)
					self.demo_confirm_rect = box
				except Exception:
					pass
				return True
			if not self.demo_on:
				# edits wait for DEMO: swallow the click so the
				# world doesn't also react (no tool swing)
				return True
			if kind in self.DROPDOWNS:
				self.focused = None
				self.open_menu = kind
				self.menu_index = self._index_of(
					kind, self._current_value(level, kind))
				return True
			self.open_menu = None
			self.focused = kind
			self._fresh = True
			if kind == 'time':
				tm = level.time_manager
				hour = int(tm.hour)
				# read the clock back as a 12-hour value: the digits
				# and the AM/PM field together name the same instant
				self.time_parts = ['%02d' % (hour % 12 or 12),
				                   '%02d' % int(tm.minute)]
				self.time_pm = hour >= 12
				# Start in the field the click landed on, so the trailing AM / PM
				# word is directly toggleable instead of only reachable via Tab.
				if pos[0] >= rect.right - 32:
					self.time_field = 2
				else:
					self.time_field = 0
			else:
				p = level.player
				self.grid_parts = [str(p.rect.centerx // TILE_SIZE),
				                   str(p.rect.centery // TILE_SIZE)]
				self.grid_field = 0
			return True
		return False

	@staticmethod
	def _index_of(kind, value):
		for i, (_label, v) in enumerate(DebugControls.options(kind)):
			if v == value:
				return i
		return 0

	def _key(self, level, event):
		# dropdown open: navigate the list
		if self.open_menu and not self.focused:
			opts = self.options(self.open_menu)
			if event.key in (pygame.K_UP, pygame.K_KP_UP):
				self.menu_index = (self.menu_index - 1) % len(opts)
			elif event.key in (pygame.K_DOWN, pygame.K_KP_DOWN):
				self.menu_index = (self.menu_index + 1) % len(opts)
			elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
				self._select(level, self.open_menu,
				             opts[self.menu_index][1])
				self.open_menu = None
			elif event.key == pygame.K_ESCAPE:
				self.open_menu = None
			return

		if event.key in (pygame.K_ESCAPE, pygame.K_RETURN,
		                 pygame.K_KP_ENTER):
			self._apply(level)
			self.focused = None
			return

		parts, field = self._active()
		# the Time box carries a third field: its AM / PM suffix
		last_field = 2 if self.focused == 'time' else 1

		if event.key == pygame.K_TAB:
			shift = bool(event.mod & pygame.KMOD_SHIFT)
			step = -1 if shift else 1
			self._set_field((field + step) % (last_field + 1))
			return
		if event.key == pygame.K_LEFT:
			self._set_field(max(0, field - 1))
			return
		if event.key == pygame.K_RIGHT:
			self._set_field(min(last_field, field + 1))
			return

		if self.focused == 'time' and field == 2:
			self._key_meridiem(event)
			return

		if event.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
			self._fresh = False
			if parts[field]:
				parts[field] = parts[field][:-1]
			elif field == 1:
				self._set_field(0)   # back out of the second field
			return

		ch = getattr(event, 'unicode', '') or ''
		if self.focused == 'time':
			if ch not in '0123456789':
				return
		else:
			# The player grid takes a leading '-' in EITHER field: a freshly
			# focused field counts as empty, so '-9999' is as typeable as '9999'.
			typed = '' if self._fresh else parts[field]
			if ch == '-':
				if typed:
					return          # only a LEADING minus
			elif ch not in '0123456789':
				return
		if self._fresh:
			parts[field] = ''
			self._fresh = False
		if self.focused == 'time':
			max_len = 2
		else:
			# a sign counts as one of the four digits' worth of room
			max_len = 5 if parts[field].startswith('-') else 4
		if len(parts[field]) >= max_len:
			return
		parts[field] += ch

	def _key_meridiem(self, event):
		"""Third Time field: 'a' / 'p' pick AM / PM (any digit flips
		it), Backspace and the arrows hand focus back to the digits."""
		if event.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
			self._set_field(1)
			return
		ch = (getattr(event, 'unicode', '') or '').lower()
		if ch == 'a':
			self.time_pm = False
		elif ch == 'p':
			self.time_pm = True
		elif ch in '0123456789':
			self.time_pm = not self.time_pm

	def _active(self):
		if self.focused == 'time':
			return self.time_parts, self.time_field
		return self.grid_parts, self.grid_field

	def _set_field(self, index):
		if self.focused == 'time':
			self.time_field = index
		else:
			self.grid_field = index
		self._fresh = True

	# ---- APPLY ----
	def _select(self, level, kind, value):
		if kind == 'rain':
			level.raining = bool(value)
			# stick for a few in-game days instead of being re-rolled
			level.rain_days_left = 3 if value else 0
			level.soil_layer.raining = level.raining
		elif kind == 'teleport':
			self.teleport_choice = value
			try:
				level.teleport_to(value)
			except Exception as exc:
				try:
					print(f'[Debug] teleport failed: {exc!r}')
				except Exception:
					pass
		else:
			level.time_manager.season_index = int(value)

	def _apply(self, level):
		if self.focused == 'time':
			tm = level.time_manager
			# the box edits a 12-hour clock: the digits plus the
			# AM/PM field name one instant, so 07 PM lands at 19:00
			raw = self._int(self.time_parts[0], None)
			if raw is None:
				# an empty (or half-typed) hour keeps the current one
				h12 = tm.hour % 12 or 12
			else:
				h12 = max(0, min(12, raw)) or 12
			minute = self._int(self.time_parts[1], tm.minute)
			tm.hour = (h12 % 12) + (12 if self.time_pm else 0)
			# the clock ticks in 10-minute steps, so snap to it
			tm.minute = max(0, min(59, minute)) // 10 * 10
			tm.total_minutes = tm.hour * 60 + tm.minute
			tm.elapsed = 0.0
		elif self.focused == 'grid':
			if level.scene != 'overworld':
				return          # the cave has its own coordinate space
			gx = self._clamp(self._int(self.grid_parts[0], None))
			gy = self._clamp(self._int(self.grid_parts[1], None))
			if gx is None or gy is None:
				return
			player = level.player
			player.pos.update(gx * TILE_SIZE + TILE_SIZE // 2,
			                  gy * TILE_SIZE + TILE_SIZE // 2)
			player.rect.center = (round(player.pos.x), round(player.pos.y))
			player.hitbox.center = player.rect.center
			player.direction.update(0, 0)
			player.world_direction.update(0, 0)
			player.target_grid = None
			player.target_object = None

	@staticmethod
	def _clamp(value, default=None):
		if value is None:
			return default
		return max(-9999, min(9999, value))
