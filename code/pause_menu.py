import pygame, sys
import input_manager
import json
from settings import *
from support import play_click, log_once


class SettingsMenu:
	def __init__(self, display_surface, close_callback, music_sound, sfx_sounds):
		self.display_surface = display_surface
		self.close_callback = close_callback
		self._cached_overlay = None

		self.music_sound = music_sound
		self.sfx_sounds = sfx_sounds
		self.music_volume, self.sfx_volume = self._load_volumes()
		if self.music_sound:
			self.music_sound.set_volume(self.music_volume)
		if self.sfx_sounds:
			for s in self.sfx_sounds:
				s.set_volume(self.sfx_volume)

		self.close_rect = pygame.Rect(0, 0, 0, 0)
		self._close_scaled = False
		self.close_normal = None
		self.close_hovered = None
		self.close_raw_size = (0, 0)

		# Tab system: 'audio' or 'controls'
		self.active_tab = 'audio'
		self.tab_rects = {}

		# Key rebinding state
		self._rebinding_action = None
		self._rebinding_wait = False
		self._pending_bindings = {}  # action -> new_key (unsaved)

		self._load_sprites()

	def _load_sprites(self):
		# close button
		try:
			close_raw = pygame.image.load(asset_path('graphics', 'UI', 'close.png')).convert_alpha()
			cw, ch = close_raw.get_size()
			half = cw // 2
			self.close_normal = close_raw.subsurface((0, 0, half, ch)).copy()
			self.close_hovered = close_raw.subsurface((half, 0, half, ch)).copy()
			self.close_raw_size = (half, ch)
		except (pygame.error, FileNotFoundError):
			pass

		# settings background
		try:
			self.settings_bg = pygame.image.load(asset_path('graphics', 'UI', 'settings.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.settings_bg = None

		# empty sound bar (293x99): 10 brown bars
		try:
			self.empty_bar_img = pygame.image.load(asset_path('graphics', 'UI', 'empty sound bar.png')).convert_alpha()
			self.empty_bar_w = self.empty_bar_img.get_width()
			self.empty_bar_h = self.empty_bar_img.get_height()
		except (pygame.error, FileNotFoundError):
			self.empty_bar_img = None
			self.empty_bar_w = 0
			self.empty_bar_h = 0

		# filled sound bar (292x99): 10 green bars
		try:
			self.filled_bar_img = pygame.image.load(asset_path('graphics', 'UI', 'Filled sound bar.png')).convert_alpha()
			self.filled_bar_w = self.filled_bar_img.get_width()
			self.filled_bar_h = self.filled_bar_img.get_height()
		except (pygame.error, FileNotFoundError):
			self.filled_bar_img = None
			self.filled_bar_w = 0
			self.filled_bar_h = 0

		# sound adjuster (55x118): draggable handle
		try:
			self.adjuster_img = pygame.image.load(asset_path('graphics', 'UI', 'sound adjuster.png')).convert_alpha()
			self.adjuster_w = self.adjuster_img.get_width()
			self.adjuster_h = self.adjuster_img.get_height()
		except (pygame.error, FileNotFoundError):
			self.adjuster_img = None
			self.adjuster_w = 0
			self.adjuster_h = 0

		# blank button sprite (192x31): left half = normal, right half = hover
		try:
			btn_raw = pygame.image.load(asset_path('graphics', 'UI', 'blank_buttons.png')).convert_alpha()
			bw, bh = btn_raw.get_size()
			half = bw // 2
			self.btn_normal = btn_raw.subsurface((0, 0, half, bh)).copy()
			self.btn_hovered = btn_raw.subsurface((half, 0, half, bh)).copy()
			self.btn_raw_size = (half, bh)
		except (pygame.error, FileNotFoundError):
			self.btn_normal = None
			self.btn_hovered = None
			self.btn_raw_size = (0, 0)

		# drag state
		self._dragging = None  # 'music' or 'sfx'

	def _apply_music_volume(self):
		if self.music_sound:
			self.music_sound.set_volume(self.music_volume)
		self._save_volumes()

	def _apply_sfx_volume(self):
		if self.sfx_sounds:
			for s in self.sfx_sounds:
				s.set_volume(self.sfx_volume)
		self._save_volumes()

	def _load_volumes(self):
		try:
			with open(VOLUME_SETTINGS_PATH, 'r') as f:
				data = json.load(f)
				return data.get('music', 0.5), data.get('sfx', 0.5)
		except (FileNotFoundError, json.JSONDecodeError):
			return 0.5, 0.5

	def _save_volumes(self):
		try:
			with open(VOLUME_SETTINGS_PATH, 'w') as f:
				json.dump({'music': self.music_volume, 'sfx': self.sfx_volume}, f)
		except IOError as exc:  # a lost volume setting must not crash; say why
			log_once('[PauseMenu] could not save volume settings', exc)

	def _start_rebind(self, action):
		self._rebinding_action = action
		self._rebinding_wait = True

	def _cancel_rebind(self):
		self._rebinding_action = None
		self._rebinding_wait = False

	def _cancel_all_rebinds(self):
		self._pending_bindings.clear()
		self._cancel_rebind()

	def _rebind_key(self, key):
		if key == pygame.K_ESCAPE:
			self._cancel_rebind()
			return
		# Check conflicts: current live bindings + pending changes
		for action, bound_key in input_manager._bindings.items():
			if action in self._pending_bindings:
				bound_key = self._pending_bindings[action]
			if bound_key == key and action != self._rebinding_action:
				return  # Key already in use
		# Store in pending, don't save yet
		self._pending_bindings[self._rebinding_action] = key
		self._cancel_rebind()

	def _save_keybindings(self):
		# Apply all pending changes
		for action, key in self._pending_bindings.items():
			input_manager._bindings[action] = key
		if self._pending_bindings:
			input_manager.save_bindings()
		self._pending_bindings.clear()

	def input(self, events):
		mx, my = pygame.mouse.get_pos()
		mouse_pressed = pygame.mouse.get_pressed()[0]

		for event in events:
			if event.type == pygame.QUIT:
				pygame.quit()
				sys.exit()
			if event.type == pygame.KEYDOWN:
				if event.key == pygame.K_ESCAPE or input_manager.is_key_for_action(event.key, 'pause'):
					play_click()
					if self._rebinding_action:
						self._cancel_rebind()
					else:
						self.close_callback()
					return
				# Handle key rebinding
				if self._rebinding_wait:
					self._rebind_key(event.key)
					return
			if event.type == pygame.MOUSEBUTTONDOWN:
				# While waiting for a rebind, a mouse button becomes the binding; close stays a cancel.
				if self._rebinding_wait and event.button in (1, 2, 3):
					code = input_manager.mouse_button_code(event.button)
					if code is not None and not self.close_rect.collidepoint(mx, my):
						play_click()
						self._rebind_key(code)
						return
				if event.button == 1:  # Left click
					if self.close_rect.collidepoint(mx, my):
						play_click()
						if self._rebinding_action:
							self._cancel_rebind()
						else:
							self.close_callback()
						return
					# Check if click is in content area
					if hasattr(self, '_content_rect') and self._content_rect and self._content_rect.collidepoint(mx, my):
						# Convert to content coordinates
						local_x = mx - self._content_rect.x
						local_y = my - self._content_rect.y + self._scroll_y
						
						# Volume bar dragging
						if hasattr(self, '_music_bar_rect') and self._music_bar_rect.collidepoint(local_x, local_y):
							self._dragging = 'music'
							return
						if hasattr(self, '_sfx_bar_rect') and self._sfx_bar_rect.collidepoint(local_x, local_y):
							self._dragging = 'sfx'
							return
						# Volume bar segment clicks (legacy)
						if hasattr(self, '_music_pill_rects'):
							for i, rect in enumerate(self._music_pill_rects):
								if rect.collidepoint(local_x, local_y):
									self.music_volume = (i + 1) / 10.0
									self._apply_music_volume()
									return
						if hasattr(self, '_sfx_pill_rects'):
							for i, rect in enumerate(self._sfx_pill_rects):
								if rect.collidepoint(local_x, local_y):
									self.sfx_volume = (i + 1) / 10.0
									self._apply_sfx_volume()
									return
						# Control rebinding
						if hasattr(self, '_control_rects'):
							for action, rect in self._control_rects.items():
								if rect.collidepoint(local_x, local_y):
									self._start_rebind(action)
									return
						# Save button
						if hasattr(self, '_save_rect') and self._save_rect.collidepoint(local_x, local_y):
							play_click()
							self._save_keybindings()
							return
						# Reset button
						if hasattr(self, '_reset_rect') and self._reset_rect.collidepoint(local_x, local_y):
							play_click()
							input_manager.reset_all_bindings()
							self._pending_bindings.clear()
							return
				elif event.button == 4:  # Mouse wheel up
					if hasattr(self, '_content_rect') and self._content_rect and self._content_rect.collidepoint(mx, my):
						self._scroll_y = max(0, self._scroll_y - 50)
						return
				elif event.button == 5:  # Mouse wheel down
					if hasattr(self, '_content_rect') and self._content_rect and self._content_rect.collidepoint(mx, my):
						max_scroll = max(0, getattr(self, '_content_height', 0) - self._content_rect.height)
						self._scroll_y = min(max_scroll, self._scroll_y + 50)
						return
			if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
				self._dragging = None

		# Handle dragging
		if self._dragging and mouse_pressed:
			# Convert mouse to content coordinates
			if hasattr(self, '_content_rect') and self._content_rect:
				local_x = mx - self._content_rect.x
				local_y = my - self._content_rect.y + self._scroll_y
				if self._dragging == 'music' and hasattr(self, '_music_bar_rect'):
					rect = self._music_bar_rect
					self.music_volume = max(0.0, min(1.0, (local_x - rect.x) / rect.width))
					self._apply_music_volume()
				elif self._dragging == 'sfx' and hasattr(self, '_sfx_bar_rect'):
					rect = self._sfx_bar_rect
					self.sfx_volume = max(0.0, min(1.0, (local_x - rect.x) / rect.width))
					self._apply_sfx_volume()

	def display(self):
		sw, sh = self.display_surface.get_size()

		if self._cached_overlay is None or self._cached_overlay.get_size() != (sw, sh):
			self._cached_overlay = pygame.Surface((sw, sh))
			self._cached_overlay.set_alpha(200)
			self._cached_overlay.fill((15, 20, 15))
		self.display_surface.blit(self._cached_overlay, (0, 0))

		# layout
		bg_w, bg_h = 635, 940
		if self.settings_bg:
			bg_w, bg_h = self.settings_bg.get_size()
		menu_w = 900
		scale = min(sw / menu_w, sh / (bg_h * (menu_w / bg_w)))
		box_w = int(menu_w * scale)
		box_h = int(bg_h * (menu_w / bg_w) * scale)
		max_h = int(sh * 0.92)
		if box_h > max_h:
			box_h = max_h
			box_w = int(box_h * (bg_w / bg_h))
		box_rect = pygame.Rect(0, 0, box_w, box_h)
		box_rect.center = (sw // 2, sh // 2)

		# draw background
		if self.settings_bg:
			scaled_bg = pygame.transform.smoothscale(self.settings_bg, (box_rect.width, box_rect.height))
			self.display_surface.blit(scaled_bg, box_rect)
		else:
			pygame.draw.rect(self.display_surface, (45, 32, 22), box_rect, 0, 12)
			pygame.draw.rect(self.display_surface, (120, 85, 45), box_rect, 3, 12)

		# Scrollable content area (no title)
		content_rect = pygame.Rect(
			box_rect.left + int(30 * scale),
			box_rect.top + int(200 * scale),
			box_rect.width - int(60 * scale),
			box_rect.height - int(300 * scale)
		)
		
		# Create content surface (will be scrolled)
		self._scroll_y = getattr(self, '_scroll_y', 0)
		
		# Draw content to a surface first to calculate height
		content_surf = pygame.Surface((content_rect.width, 2000), pygame.SRCALPHA)
		content_height = self._draw_content(content_surf, content_rect.width, scale)
		
		# Clamp scroll
		max_scroll = max(0, content_height - content_rect.height)
		self._scroll_y = max(0, min(self._scroll_y, max_scroll))
		
		# Blit visible portion
		visible_area = pygame.Rect(0, self._scroll_y, content_rect.width, content_rect.height)
		self.display_surface.blit(content_surf, content_rect, visible_area)
		
		# Scrollbar
		if content_height > content_rect.height:
			scrollbar_w = int(10 * scale)
			scrollbar_x = content_rect.right + int(5 * scale)
			scrollbar_h = content_rect.height
			thumb_h = max(int(30 * scale), int(scrollbar_h * content_rect.height / content_height))
			thumb_y = content_rect.top + int((self._scroll_y / max_scroll) * (scrollbar_h - thumb_h))
			
			# Track
			pygame.draw.rect(self.display_surface, (40, 30, 20), 
				pygame.Rect(scrollbar_x, content_rect.top, scrollbar_w, scrollbar_h), 0, 4)
			# Thumb
			pygame.draw.rect(self.display_surface, (120, 90, 60), 
				pygame.Rect(scrollbar_x, thumb_y, scrollbar_w, thumb_h), 0, 4)
		
		# Store for input handling
		self._content_rect = content_rect
		self._content_height = content_height

		# close button
		if self.close_normal:
			if not self._close_scaled:
				cw, ch = self.close_raw_size
				close_scale = scale * 3.5
				self.close_normal = pygame.transform.scale(self.close_normal, (int(cw * close_scale), int(ch * close_scale)))
				self.close_hovered = pygame.transform.scale(self.close_hovered, (int(cw * close_scale), int(ch * close_scale)))
				self._close_scaled = True
			close_img = self.close_hovered if self.close_rect.collidepoint(pygame.mouse.get_pos()) else self.close_normal
			self.close_rect = close_img.get_rect(topright=(box_rect.right - int(20 * scale), box_rect.top + int(30 * scale)))
			self.display_surface.blit(close_img, self.close_rect)

	def _pct_text(self, value, font, color):
		"""Render '100%' - the pixel font has no '%' glyph, so the sign
		is drawn by hand to keep the pixel look."""
		num = f'{int(round(value * 100))}'
		surf = font.render(num, False, color)
		w, h = surf.get_size()
		pct_w = max(8, int(h * 0.55))
		out = pygame.Surface((w + pct_w, h), pygame.SRCALPHA)
		out.blit(surf, (0, 0))
		dot = max(3, h // 6)
		margin = max(1, h // 14)
		left = w + max(1, h // 10)
		top = margin
		bottom = h - margin - dot
		right = w + pct_w - margin - dot
		# two pixel squares...
		pygame.draw.rect(out, color, pygame.Rect(left, top, dot, dot))
		pygame.draw.rect(out, color, pygame.Rect(right, bottom, dot, dot))
		# ...and a thick pixel slash from lower-left to upper-right.
		pygame.draw.line(out, color,
		                 (left, bottom + dot), (right + dot, top),
		                 max(2, h // 12))
		return out

	def _draw_volume_bar(self, row_rect, bar_size, font, label, volume,
	                     control_type, scale, target_surf=None):
		"""Draw one volume row with fixed columns so MUSIC and SFX are perfectly
		symmetrical: labels right-aligned, the percentage in a fixed right column,
		and the bar filling the whole space between them.
		"""
		if target_surf is None:
			target_surf = self.display_surface

		num_segments = 10
		filled_count = int(round(volume * 10))
		pad = max(4, int(12 * scale))
		gap = max(6, int(14 * scale))

		lab_surf = font.render(label, False, '#5C3A1E')
		pct_surf = self._pct_text(volume, font, '#5C3A1E')

		# Widest label + percentage reserve equal columns so both bars share the same edges.
		label_col = max(font.size('Music')[0], font.size('SFX')[0])
		pct_col = self._pct_text(1.0, font, '#5C3A1E').get_width()

		region_left = row_rect.left + pad + label_col + gap
		region_right = row_rect.right - pad - pct_col - gap
		region_w = max(60, region_right - region_left)

		display_bar_h = bar_size
		display_total_w = region_w
		display_pitch = max(1, display_total_w // num_segments)
		display_bar_w = max(1, int(display_pitch * 0.8))
		start_x = region_left
		bar_y = row_rect.centery - display_bar_h // 2
		bar_rect = pygame.Rect(start_x, bar_y, display_total_w,
		                       display_bar_h)

		target_surf.blit(lab_surf, lab_surf.get_rect(
			midright=(region_left - gap, row_rect.centery)))
		target_surf.blit(pct_surf, pct_surf.get_rect(
			midleft=(region_right + gap, row_rect.centery)))

		if self.empty_bar_img and self.filled_bar_img:
			# Stretch the 10-bar sprite across the full row width.
			empty_scaled = pygame.transform.scale(
				self.empty_bar_img, (display_total_w, display_bar_h))
			target_surf.blit(empty_scaled, bar_rect)

			if filled_count > 0:
				filled_src_w = max(1, int(self.filled_bar_w * volume))
				filled_sprite = self.filled_bar_img.subsurface(
					pygame.Rect(0, 0, filled_src_w,
					            self.filled_bar_h)).copy()
				filled_w = max(1, int(display_total_w * volume))
				filled_scaled = pygame.transform.scale(
					filled_sprite, (filled_w, display_bar_h))
				target_surf.blit(filled_scaled, bar_rect)

			pill_rects = []
			for i in range(num_segments):
				px = start_x + i * display_pitch
				pill_rects.append(pygame.Rect(
					px, bar_y, display_bar_w, display_bar_h))
		else:
			# Fallback: solid rects
			pygame.draw.rect(target_surf, (100, 85, 82), bar_rect)
			if filled_count > 0:
				filled_w = int(display_total_w * volume)
				pygame.draw.rect(target_surf, (192, 212, 112),
				                 (bar_rect.x, bar_rect.y, filled_w,
				                  display_bar_h))
			pill_rects = []
			for i in range(num_segments):
				px = start_x + i * display_pitch
				pill_rects.append(pygame.Rect(
					px, bar_y, display_bar_w, display_bar_h))

		if control_type == 'music':
			self._music_pill_rects = pill_rects
			self._music_bar_rect = bar_rect
		else:
			self._sfx_pill_rects = pill_rects
			self._sfx_bar_rect = bar_rect

		# Adjuster handle at the volume position, clamped inside the bar.
		if self.adjuster_img:
			adj_scale = display_bar_h * 1.4 / self.adjuster_h
			adj_w = max(1, int(self.adjuster_w * adj_scale))
			adj_h = max(1, int(self.adjuster_h * adj_scale))
			adj_x = start_x + int(display_total_w * volume) - adj_w // 2
			adj_x = max(start_x, min(
				adj_x, start_x + display_total_w - adj_w))
			adj_y = row_rect.centery - adj_h // 2
			adj_scaled = pygame.transform.scale(
				self.adjuster_img, (adj_w, adj_h))
			target_surf.blit(adj_scaled, (adj_x, adj_y))

	def _fit_font(self, text, max_w, size, min_size=10):
		"""Largest font size (at most `size`) whose rendering of `text`
		fits into `max_w` pixels wide."""
		size = max(min_size, int(size))
		while size > min_size:
			font = ui_font(size)
			if font.size(text)[0] <= max_w:
				return font
			size -= 1
		return ui_font(min_size)

	def _draw_content(self, surf, width, scale):
		"""Draw both audio and controls sections to a surface. Returns total height."""
		center_x = width // 2
		y = int(4 * scale)

		# ===== AUDIO SECTION =====
		section_font_size = max(14, int(56 * scale))
		bar_font_size = max(12, int(42 * scale))
		section_font = ui_font(section_font_size)
		bar_font = ui_font(bar_font_size)
		audio_surf = section_font.render('Audio', False, '#5C3A1E')
		audio_rect = audio_surf.get_rect(midtop=(center_x, y))
		surf.blit(audio_surf, audio_rect)
		# Underline
		pygame.draw.line(surf, '#5C3A1E',
			(audio_rect.left, audio_rect.bottom + int(3 * scale)),
			(audio_rect.right, audio_rect.bottom + int(3 * scale)), int(2 * scale))
		y = audio_rect.bottom + int(15 * scale)

		# Audio volume bars: taller rows with long, symmetric bars.
		bar_size = max(16, int(90 * scale))
		row_h = max(bar_size + int(28 * scale), int(150 * scale))
		row_pad = int(12 * scale)

		music_row = pygame.Rect(row_pad, y, width - row_pad * 2, row_h)
		self._draw_volume_bar(music_row, bar_size, bar_font, 'Music',
		                       self.music_volume, 'music', scale, surf)
		y += row_h

		sfx_row = pygame.Rect(row_pad, y, width - row_pad * 2, row_h)
		self._draw_volume_bar(sfx_row, bar_size, bar_font, 'SFX',
		                       self.sfx_volume, 'sfx', scale, surf)
		y += row_h

		# Divider
		y += int(7 * scale)
		divider_y = y
		pygame.draw.line(surf, (120, 90, 60), (int(50 * scale), divider_y), (width - int(50 * scale), divider_y), int(2 * scale))
		y += int(15 * scale)

		# ===== CONTROLS SECTION =====
		controls_surf = section_font.render('Controls', False, '#5C3A1E')
		controls_rect = controls_surf.get_rect(midtop=(center_x, y))
		surf.blit(controls_surf, controls_rect)
		# Underline
		pygame.draw.line(surf, '#5C3A1E', 
			(controls_rect.left, controls_rect.bottom + int(3 * scale)),
			(controls_rect.right, controls_rect.bottom + int(3 * scale)), int(2 * scale))
		y = controls_rect.bottom + int(15 * scale)

		# Keybindings list
		self._control_rects = {}
		actions = []
		for action, (category, description) in input_manager.BINDING_INFO.items():
			actions.append((action, description, category))
		
		# Control rows use the Biome font size; _fit_font shrinks long action names to fit.
		row_font_size = max(12, int(42 * scale))
		category_font_size = max(12, int(46 * scale))
		category_font = ui_font(category_font_size)
		font = ui_font(row_font_size)

		line_h = max(int(28 * scale), int(50 * scale))
		cat_spacing = int(6 * scale)
		row_left = int(18 * scale)
		row_right = int(18 * scale)
		inner_pad = int(14 * scale)
		gap = int(14 * scale)

		current_category = None
		for action, description, category in actions:
			# Category header
			if category != current_category:
				current_category = category
				y += cat_spacing
				cat_surf = category_font.render(category.upper(), False, '#5C3A1E')
				cat_rect = cat_surf.get_rect(topleft=(row_left, y))
				surf.blit(cat_surf, cat_rect)
				y += max(int(20 * scale), int(category_font_size * 1.15))

			# Key binding row
			row_rect = pygame.Rect(row_left, y, width - row_left - row_right, line_h)
			
			# Hover effect (adjusted for scroll)
			mouse_pos = pygame.mouse.get_pos()
			hovered = False
			if hasattr(self, '_content_rect') and self._content_rect:
				local_mouse = (mouse_pos[0] - self._content_rect.x, mouse_pos[1] - self._content_rect.y + self._scroll_y)
				hovered = row_rect.collidepoint(local_mouse) and self._rebinding_action is None
			
			# Background
			if self._rebinding_action == action:
				bg_color = (180, 140, 60)
			elif hovered:
				bg_color = (100, 80, 50)
			else:
				bg_color = (70, 55, 40)
			pygame.draw.rect(surf, bg_color, row_rect, 0, 6)
			pygame.draw.rect(surf, (160, 130, 100), row_rect, 2, 6)

			# Current key (right side)
			bound_key = self._pending_bindings.get(action, input_manager._bindings.get(action, pygame.K_UNKNOWN))
			key_name = input_manager.key_name(bound_key)
			if self._rebinding_action == action:
				key_name = '... PRESS KEY ...'
				key_color = '#FFD700'
			elif action in self._pending_bindings:
				key_color = '#88FF88'  # Green for pending change
			else:
				key_color = '#FFFFFF'
			key_surf = font.render(key_name, False, key_color)

			# Action name (left side) - shrunk so it never touches the key
			name_max_w = (row_rect.width - inner_pad * 2
			              - key_surf.get_width() - gap)
			name_font = self._fit_font(description, name_max_w,
			                           row_font_size)
			name_color = '#B68962' if self._rebinding_action != action else '#FFD700'
			name_surf = name_font.render(description, False, name_color)
			surf.blit(name_surf, name_surf.get_rect(
				midleft=(row_rect.left + inner_pad, row_rect.centery)))
			surf.blit(key_surf, key_surf.get_rect(
				midright=(row_rect.right - inner_pad, row_rect.centery)))

			# Store rect in content coordinates for click detection
			self._control_rects[action] = row_rect
			y += line_h + int(4 * scale)

		# NOTE: the read-only MOUSE section was removed; mouse buttons are rebindable keys now.

		# Buttons at bottom - Save and Reset side by side
		btn_font = ui_font(row_font_size)
		mouse_pos = pygame.mouse.get_pos()

		if hasattr(self, '_content_rect') and self._content_rect:
			local_mouse = (mouse_pos[0] - self._content_rect.x, mouse_pos[1] - self._content_rect.y + self._scroll_y)
		else:
			local_mouse = mouse_pos

		btn_pad_x = int(40 * scale)
		btn_draw_h = row_font_size + int(34 * scale)
		btn_gap = int(10 * scale)
		btn_start_y = y + int(15 * scale)

		def _draw_sprite_button(label, cx, cy):
			text_surf = btn_font.render(label, False, '#5C3A1E')
			tw = text_surf.get_width()
			btn_draw_w = tw + btn_pad_x * 2
			rect = pygame.Rect(cx - btn_draw_w // 2, cy, btn_draw_w, btn_draw_h)
			hovered = rect.collidepoint(local_mouse)

			if self.btn_normal and self.btn_hovered:
				btn_img = self.btn_hovered if hovered else self.btn_normal
				btn_img_scaled = pygame.transform.scale(btn_img, (btn_draw_w, btn_draw_h))
				surf.blit(btn_img_scaled, rect)
			else:
				bg = (80, 120, 60) if hovered else (60, 90, 40)
				pygame.draw.rect(surf, bg, rect, 0, 8)
				pygame.draw.rect(surf, (140, 180, 120), rect, 2, 8)

			color = '#FFD700' if hovered else '#5C3A1E'
			text_surf = btn_font.render(label, False, color)
			surf.blit(text_surf, text_surf.get_rect(center=rect.center))
			return rect

		# Save and Reset side by side, auto-sized to text
		save_surf = btn_font.render('Save', False, '#5C3A1E')
		reset_surf = btn_font.render('Reset Defaults', False, '#5C3A1E')
		save_w = save_surf.get_width() + btn_pad_x * 6
		reset_w = reset_surf.get_width() + btn_pad_x * 6
		total_w = save_w + btn_gap + reset_w
		save_cx = center_x - total_w // 2 + save_w // 2
		reset_cx = center_x + total_w // 2 - reset_w // 2

		self._save_rect = _draw_sprite_button('Save', save_cx, btn_start_y)
		self._reset_rect = _draw_sprite_button('Reset Defaults', reset_cx, btn_start_y)

		return btn_start_y + btn_draw_h + int(15 * scale)

	def update(self, events):
		self.input(events)
		self.display()


class PauseMenu:
	def __init__(self, display_surface, toggle_pause, level_ref):
		self.display_surface = display_surface
		self.toggle_pause = toggle_pause
		self.level_ref = level_ref
		self.font = ui_font(64)
		self.small_font = ui_font(45)

		self.options = ['Resume', 'Settings', 'Save + Quit']
		self.index = 0
		self.cooldown = 200
		self.last_key_time = 0
		self.option_rects = []

		self.settings_active = False
		self.settings_menu = None

		self.button_images = self._load_button_images()
		self._cached_overlay = None

	def close_settings(self):
		self.settings_active = False

	def _load_button_images(self):
		try:
			img = pygame.image.load(asset_path('graphics', 'UI', 'blank_buttons.png')).convert_alpha()
			w, h = img.get_size()
			normal = img.subsurface((0, 0, w // 2, h))
			selected = img.subsurface((w // 2, 0, w // 2, h))
			scale = 3
			normal = pygame.transform.scale(normal, (normal.get_width() * scale, normal.get_height() * scale))
			selected = pygame.transform.scale(selected, (selected.get_width() * scale, selected.get_height() * scale))
			return {'normal': normal, 'selected': selected}
		except (pygame.error, FileNotFoundError):
			return None

	def input(self):
		if self.settings_active:
			self.settings_menu.update()
			return

		keys = pygame.key.get_pressed()
		mouse = pygame.mouse.get_pressed()
		mouse_pos = pygame.mouse.get_pos()
		current_time = pygame.time.get_ticks()

		if current_time - self.last_key_time > self.cooldown:
			for i, rect in enumerate(self.option_rects):
				if rect.collidepoint(mouse_pos):
					self.index = i
					if mouse[0]:
						self.last_key_time = current_time
						self.confirm()
						return

		if current_time - self.last_key_time > self.cooldown:
			if keys[pygame.K_UP] or input_manager.is_action_pressed_keys(keys, 'move_up'):
				self.index = (self.index - 1) % len(self.options)
				self.last_key_time = current_time
			if keys[pygame.K_DOWN] or input_manager.is_action_pressed_keys(keys, 'move_down'):
				self.index = (self.index + 1) % len(self.options)
				self.last_key_time = current_time
			if keys[pygame.K_RETURN] or input_manager.is_action_pressed_keys(keys, 'interact'):
				self.last_key_time = current_time
				self.confirm()

	def confirm(self):
		play_click()
		choice = self.options[self.index]
		if choice == 'Resume':
			self.toggle_pause()
		elif choice == 'Settings':
			self.settings_active = True
			music = self.level_ref.music if hasattr(self.level_ref, 'music') else None
			sfx = [self.level_ref.success] if hasattr(self.level_ref, 'success') else []
			self.settings_menu = SettingsMenu(self.display_surface, self.close_settings, music, sfx)
		elif choice == 'Save + Quit':
			self.level_ref.save_and_quit()

	def display(self):
		if self.settings_active:
			self.settings_menu.update(self._events)
			return

		sw, sh = self.display_surface.get_size()
		if self._cached_overlay is None or self._cached_overlay.get_size() != (sw, sh):
			self._cached_overlay = pygame.Surface((sw, sh))
			self._cached_overlay.set_alpha(128)
			self._cached_overlay.fill('black')
		self.display_surface.blit(self._cached_overlay, (0, 0))

		title_surf = self.font.render('PAUSED', False, 'White')
		title_rect = title_surf.get_rect(center=(sw / 2, sh / 2 - 140))
		self.display_surface.blit(title_surf, title_rect)

		divider_y = title_rect.bottom + 10
		pygame.draw.line(self.display_surface, (100, 100, 100),
		                 (sw // 2 - 80, divider_y), (sw // 2 + 80, divider_y), 2)

		mouse_pos = pygame.mouse.get_pos()
		self.option_rects = []

		for i, option in enumerate(self.options):
			surf = self.small_font.render(option, False, 'White')
			rect = surf.get_rect(center=(sw / 2, sh / 2 - 40 + i * 70))
			self.option_rects.append(rect)

			selected = i == self.index
			hovered = rect.collidepoint(mouse_pos)

			if hovered:
				self.index = i

			if self.button_images:
				btn_img = self.button_images['selected'] if selected else self.button_images['normal']
				btn_rect = btn_img.get_rect(center=(sw / 2, sh / 2 - 40 + i * 70))
				self.display_surface.blit(btn_img, btn_rect)
				surf = self.small_font.render(option, False, '#5C3A1E')
				text_rect = surf.get_rect(center=btn_rect.center)
				self.display_surface.blit(surf, text_rect)
			else:
				bg_rect = rect.inflate(30, 10)
				if selected or hovered:
					btn_color = (58, 90, 32)
					border_color = (90, 130, 60)
					pygame.draw.rect(self.display_surface, btn_color, bg_rect, 0, 8)
					pygame.draw.rect(self.display_surface, border_color, bg_rect, 3, 8)

				color = '#FFD700' if selected else 'White'
				surf = self.small_font.render(option, False, color)
				self.display_surface.blit(surf, rect)

	def update(self, events):
		self._events = events
		if self.settings_active:
			self.settings_menu.update(events)
			return
		self.input()
		self.display()
