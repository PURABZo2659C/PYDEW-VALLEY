import pygame, os
from settings import *
from support import load_overlay_icons

class Overlay:
	def __init__(self, player, time_manager=None):

		self.display_surface = pygame.display.get_surface()
		self.player = player
		self.time_manager = time_manager
		self.font = ui_font(28)
		self.font_size = 28
		self.small_font = ui_font(18)
		self.tiny_font = ui_font(14)

		all_items = (player.inventory.unique_items() + player.tools
		             + list(player.seeds) + list(RECIPES.keys())
		             + list(POTION_ITEMS) + list(REFINED_ITEMS)
		             + list(SAPLING_ITEMS) + list(FLOWER_ITEMS))
		self.item_icons = load_overlay_icons(all_items)
		self.seed_icons = load_overlay_icons(player.seeds)

		self.slot_size = 56
		self.slot_gap = 8

		ui_path = asset_path('graphics', 'UI')

		# Load decorative weather/time UI panel. The art pack has been
		# renamed over time, so accept both the old and current names.
		self.weather_ui_raw = None
		self.weather_icons_raw = None
		for name in ('Weather_UI_Free.png', 'Weather_UI.png'):
			path = os.path.join(ui_path, name)
			if os.path.exists(path):
				try:
					self.weather_ui_raw = pygame.image.load(path).convert_alpha()
					break
				except pygame.error:
					pass
		for name in ('Weather_Icons_smal_freel.png', 'Weather_Icons.png'):
			path = os.path.join(ui_path, name)
			if os.path.exists(path):
				try:
					self.weather_icons_raw = pygame.image.load(path).convert_alpha()
					break
				except pygame.error:
					pass
		try:
			arrow_raw = pygame.image.load(os.path.join(ui_path, 'arrow.png')).convert_alpha()
			aw, ah = arrow_raw.get_size()
			arrow_h = ah // 3
			self.arrow_icons = [
				arrow_raw.subsurface((0, 0, aw, arrow_h)),
				arrow_raw.subsurface((0, arrow_h, aw, arrow_h)),
				arrow_raw.subsurface((0, arrow_h * 2, aw, arrow_h)),
			]
		except (pygame.error, FileNotFoundError):
			self.arrow_icons = None
		try:
			heart_scale = 1.2
			full_raw = pygame.image.load(os.path.join(ui_path, 'full-hearts.png')).convert_alpha()
			half_raw = pygame.image.load(os.path.join(ui_path, 'half-hearts.png')).convert_alpha()
			empty_raw = pygame.image.load(os.path.join(ui_path, 'empty-hearts.png')).convert_alpha()
			sh_w = int(full_raw.get_width() * heart_scale)
			sh_h = int(full_raw.get_height() * heart_scale)
			self.heart_full = pygame.transform.smoothscale(full_raw, (sh_w, sh_h))
			self.heart_half = pygame.transform.smoothscale(half_raw, (sh_w, sh_h))
			self.heart_empty = pygame.transform.smoothscale(empty_raw, (sh_w, sh_h))
			self.heart_scaled_w = sh_w
			self.heart_scaled_h = sh_h
			self._hearts_cache = None
			self._hearts_cache_energy = -1
		except (pygame.error, FileNotFoundError):
			self.heart_full = None
			self.heart_half = None
			self.heart_empty = None
		try:
			self.hotbar_img = pygame.image.load(os.path.join(ui_path, 'hotbar.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.hotbar_img = None
		try:
			selector_raw = pygame.image.load(os.path.join(ui_path, 'selector.png')).convert_alpha()
			w, h = selector_raw.get_size()
			cw, ch = w // 2, h // 2
			self.selector_tl = selector_raw.subsurface((0, 0, cw, ch))
			self.selector_tr = selector_raw.subsurface((cw, 0, cw, ch))
			self.selector_bl = selector_raw.subsurface((0, ch, cw, ch))
			self.selector_br = selector_raw.subsurface((cw, ch, cw, ch))
		except (pygame.error, FileNotFoundError):
			self.selector_tl = self.selector_tr = self.selector_bl = self.selector_br = None

		try:
			potion_panel = pygame.image.load(os.path.join(ui_path, 'panel.png')).convert_alpha()
			self.potion_panel = pygame.transform.scale(
				potion_panel, (potion_panel.get_width() * 3, potion_panel.get_height() * 3))
		except (pygame.error, FileNotFoundError):
			self.potion_panel = None
		try:
			currency_raw = pygame.image.load(
				os.path.join(ui_path, 'Currency.png')).convert_alpha()
			self.currency_icon = pygame.transform.scale(currency_raw, (32, 32))
		except (pygame.error, FileNotFoundError):
			self.currency_icon = None
		self.potion_top = 63
		# Set by Level to the coordinates panel width so the timer cards
		# line up with it; None keeps the art's own size.
		self.potion_card_width = None
		self._potion_label_cache = {}

	def get_size(self):
		return self.display_surface.get_size()

	def make_tool_icon(self, tool):
		surf = pygame.Surface((48, 48), pygame.SRCALPHA)
		surf.fill((0, 0, 0, 0))
		pygame.draw.rect(surf, (180, 180, 180), (8, 8, 32, 32), 0, 6)
		return surf

	def slot_icon(self, item):
		# Wheat/tomato item keys are shared by crops and seed stacks; the
		# hotbar always holds seeds, so prefer the new seed art there.
		if item in self.player.seeds:
			return self.seed_icons.get(item) or self.item_icons.get(item)
		icon = self.item_icons.get(item)
		if icon is None:
			# Icons for items picked up after the overlay was built aren't
			# pre-loaded: resolve them on demand instead of drawing a dot.
			icon = load_overlay_icons([item]).get(item)
			self.item_icons[item] = icon
		return icon

	def make_seed_icon(self, seed):
		surf = pygame.Surface((48, 48), pygame.SRCALPHA)
		surf.fill((0, 0, 0, 0))
		colors = {'wheat': (210, 180, 60), 'tomato': (220, 60, 40)}
		color = colors.get(seed, (180, 180, 180))
		pygame.draw.ellipse(surf, color, (10, 10, 28, 28))
		pygame.draw.ellipse(surf, (255, 255, 255), (10, 10, 28, 28), 2)
		return surf

	def draw_bar(self, x, y, width, height, ratio, color):
		bg_rect = pygame.Rect(x, y, width, height)
		pygame.draw.rect(self.display_surface, (40, 40, 40), bg_rect, 0, 4)
		pygame.draw.rect(self.display_surface, (80, 80, 80), bg_rect, 2, 4)
		fill_w = int(width * max(0, min(1, ratio)))
		if fill_w > 0:
			fill_rect = pygame.Rect(x, y, fill_w, height)
			pygame.draw.rect(self.display_surface, color, fill_rect, 0, 4)

	def draw_night_vision(self, center):
		radius = NIGHT_VISION_RADIUS
		if getattr(self, '_night_glow_radius', None) != radius:
			self._night_glow_radius = radius
			self._night_glow = pygame.Surface((radius * 2, radius * 2))
			self._night_glow.fill((0, 0, 0))
			steps = 28
			for i in range(steps, 0, -1):
				t = i / steps
				fade = (1 - t) ** 2
				color = (int(115 * fade), int(110 * fade), int(95 * fade))
				pygame.draw.circle(
					self._night_glow, color, (radius, radius),
					max(1, int(radius * t)))
		rect = self._night_glow.get_rect(center=center)
		self.display_surface.blit(
			self._night_glow, rect, special_flags=pygame.BLEND_RGB_ADD)

	def draw_energy(self):
		if not self.heart_full:
			return
		sw, sh = self.get_size()
		energy = self.player.energy
		hearts = 10
		scaled_w = self.heart_scaled_w
		scaled_h = self.heart_scaled_h
		gap = -2
		total_w = hearts * scaled_w + (hearts - 1) * gap

		int_energy = int(round(energy))
		if self._hearts_cache_energy != int_energy:
			self._hearts_cache_energy = int_energy
			self._hearts_cache = pygame.Surface((total_w, scaled_h), pygame.SRCALPHA)
			for i in range(hearts):
				heart_energy = energy - i * 10
				if heart_energy >= 10:
					src = self.heart_full
				elif heart_energy >= 5:
					src = self.heart_half
				else:
					src = self.heart_empty
				slot_x = i * (scaled_w + gap)
				src_rect = src.get_rect(center=(slot_x + scaled_w // 2, scaled_h // 2))
				self._hearts_cache.blit(src, src_rect)

		hb_raw_w = int(438 * 1.4)
		hb_raw_h = int(83 * 1.4)
		hb_bottom = sh - 20
		hb_top = hb_bottom - hb_raw_h
		hb_left = (sw - hb_raw_w) // 2
		start_x = hb_left + 27
		start_y = hb_top + 8
		self.display_surface.blit(self._hearts_cache, (start_x, start_y))

	def _potion_label(self, text, max_w=None):
		"""Timer text for a potion card, shrunk only when it would not
		fit the panel's inner width."""
		key = (text, max_w)
		label = self._potion_label_cache.get(key)
		if label is None:
			width = self.font.size(text)[0]
			if max_w and width > max_w:
				size = max(14, int(self.font_size * max_w / width))
				font = ui_font(size)
				label = font.render(text, False, (92, 58, 30))
			else:
				label = self.font.render(text, False, (92, 58, 30))
			self._potion_label_cache[key] = label
		return label

	def draw_potion_effects(self):
		self.potion_card_rects = []
		if not self.time_manager:
			return
		# Potions count down in REAL seconds (Player.potion_remaining),
		# not on the accelerated game clock.
		effects = [effect for effect in
		           ('speed_potion', 'miner_potion', 'night_vision_potion')
		           if self.player.potion_remaining(effect) > 0]
		if not effects:
			return
		sw, sh = self.get_size()
		right = sw
		y = self.potion_top
		for effect in effects:
			remaining = int(self.player.potion_remaining(effect))
			mins = remaining // 60
			secs = remaining % 60
			label = f'{mins:02d}:{secs:02d}'
			card_size = self.potion_panel.get_size() if self.potion_panel else (165, 63)
			if self.potion_card_width:
				card_size = (self.potion_card_width, card_size[1])
			card = pygame.Rect(0, y, *card_size)
			card.right = right
			self.potion_card_rects.append(card)

			# The card is as wide as the coords panel above it, but the
			# panel art is only 165px, so anchor the art to the card's
			# RIGHT edge - the icon and timer then sit inside the art.
			if self.potion_panel:
				art = self.potion_panel.get_rect()
				art.right = card.right
				art.centery = card.centery
				self.display_surface.blit(self.potion_panel, art.topleft)
			else:
				art = card
				bg = pygame.Surface(card.size, pygame.SRCALPHA)
				bg.fill((231, 207, 162, 235))
				pygame.draw.rect(bg, (168, 119, 73), bg.get_rect(), 2, 8)
				self.display_surface.blit(bg, card.topleft)

			content_cy = card.centery + 3
			icon = self.item_icons.get(effect)
			icon_rect = None
			if icon:
				icon = pygame.transform.scale(icon, (32, 32))
				icon_rect = icon.get_rect(midright=(art.right - 12, content_cy))
				self.display_surface.blit(icon, icon_rect)
			# timer sits left of the icon, inside the panel art
			label_right = (icon_rect.left - 10 if icon_rect
			               else art.right - 14)
			max_w = max(24, art.width - 12 - 32 - 10 - 8)
			label_surf = self._potion_label(label, max_w)
			self.display_surface.blit(
				label_surf,
				label_surf.get_rect(midright=(label_right, content_cy)))
			y += card.height

	def draw_hotbar(self):
		hotbar = self.player.hotbar
		n = len(hotbar)
		sw, sh = self.get_size()

		hb_scale = 1.4

		if self.hotbar_img:
			raw_w, raw_h = self.hotbar_img.get_size()
			scaled_w, scaled_h = int(raw_w * hb_scale), int(raw_h * hb_scale)
			scaled_hb = pygame.transform.scale(self.hotbar_img, (scaled_w, scaled_h))
			hb_rect = scaled_hb.get_rect(midbottom=(sw // 2, sh - 20))
			self.display_surface.blit(scaled_hb, hb_rect)

			num_slots = 9
			slot_pitch = int(48 * hb_scale)
			slot_w = int(52 * hb_scale)
			slot_h = int(52 * hb_scale)
			slot_cx0 = int(26.5 * hb_scale)
			slot_cy = int(51.5 * hb_scale)

			if self.selector_tl:
				cw, ch = self.selector_tl.get_size()
				scale_w = (slot_w + 8) / (cw * 2)
				scale_h = (slot_h + 8) / (ch * 2)
				scale = min(scale_w, scale_h)
				self.sel_tl = pygame.transform.scale(self.selector_tl, (int(cw * scale), int(ch * scale)))
				self.sel_tr = pygame.transform.scale(self.selector_tr, (int(cw * scale), int(ch * scale)))
				self.sel_bl = pygame.transform.scale(self.selector_bl, (int(cw * scale), int(ch * scale)))
				self.sel_br = pygame.transform.scale(self.selector_br, (int(cw * scale), int(ch * scale)))
				sel_cw, sel_ch = self.sel_tl.get_size()

			for i in range(min(n, num_slots)):
				screen_cx = hb_rect.x + slot_cx0 + i * slot_pitch + 2
				screen_cy = hb_rect.y + slot_cy + 2
				slot = hotbar[i]
				if slot:
					item, count = slot
					icon = self.slot_icon(item)
					icon_size = int(32 * hb_scale)
					if icon:
						scaled = pygame.transform.scale(icon, (icon_size, icon_size))
						self.display_surface.blit(scaled, scaled.get_rect(center=(screen_cx, screen_cy)))
					elif item in self.player.tools:
						fallback = self.make_tool_icon(item)
						scaled = pygame.transform.scale(fallback, (icon_size, icon_size))
						self.display_surface.blit(scaled, scaled.get_rect(center=(screen_cx, screen_cy)))
					else:
						fallback = self.make_seed_icon(item)
						scaled = pygame.transform.scale(fallback, (icon_size, icon_size))
						self.display_surface.blit(scaled, scaled.get_rect(center=(screen_cx, screen_cy)))

					if item == 'water_bucket' and self.player.water_bucket_amount > 0:
						txt = str(self.player.water_bucket_amount)
						ts = self.tiny_font.render(txt, False, (100, 180, 255))
						tr = ts.get_rect(bottomright=(screen_cx + icon_size//2, screen_cy + icon_size//2))
						pygame.draw.rect(self.display_surface, (0, 0, 0), tr.inflate(4, 2), 0, 3)
						self.display_surface.blit(ts, tr)
					elif count > 1:
						ts = self.tiny_font.render(str(count), False, 'White')
						tr = ts.get_rect(bottomright=(screen_cx + icon_size//2, screen_cy + icon_size//2))
						pygame.draw.rect(self.display_surface, (0, 0, 0), tr.inflate(4, 2), 0, 3)
						self.display_surface.blit(ts, tr)

			if self.selector_tl and self.player.hotbar_index < num_slots:
				si = self.player.hotbar_index
				sel_left = hb_rect.x + slot_cx0 - slot_w / 2 + si * slot_pitch
				sel_right = sel_left + slot_w
				sel_top = hb_rect.y + slot_cy - slot_h / 2 + 1
				sel_bottom = sel_top + slot_h

				self.display_surface.blit(self.sel_tl, (sel_left, sel_top))
				self.display_surface.blit(self.sel_tr, (sel_right - sel_cw, sel_top))
				self.display_surface.blit(self.sel_bl, (sel_left, sel_bottom - sel_ch))
				self.display_surface.blit(self.sel_br, (sel_right - sel_cw, sel_bottom - sel_ch))
		else:
			total_w = n * self.slot_size + (n - 1) * self.slot_gap
			start_x = (sw - total_w) // 2
			bar_y = sh - self.slot_size - 30

			for i in range(n):
				x = start_x + i * (self.slot_size + self.slot_gap)
				rect = pygame.Rect(x, bar_y, self.slot_size, self.slot_size)
				is_selected = (i == self.player.hotbar_index)

				if is_selected:
					bg_color = (50, 100, 50)
					border_color = (100, 220, 100)
				else:
					bg_color = (50, 50, 60)
					border_color = (100, 100, 110)

				pygame.draw.rect(self.display_surface, bg_color, rect, 0, 8)
				pygame.draw.rect(self.display_surface, border_color, rect, 2, 8)

				key_num = str(i + 1)
				key_surf = self.tiny_font.render(key_num, False, (180, 180, 180))
				self.display_surface.blit(key_surf, (rect.x + 4, rect.y + 2))

				slot = hotbar[i]
				if slot:
					item, count = slot
					icon = self.slot_icon(item)
					if icon:
						icon_rect = icon.get_rect(center=rect.center)
						self.display_surface.blit(icon, icon_rect)
					elif item in self.player.tools:
						fallback = self.make_tool_icon(item)
						fallback_rect = fallback.get_rect(center=rect.center)
						self.display_surface.blit(fallback, fallback_rect)
					else:
						fallback = self.make_seed_icon(item)
						fallback_rect = fallback.get_rect(center=rect.center)
						self.display_surface.blit(fallback, fallback_rect)

					if item == 'water_bucket' and self.player.water_bucket_amount > 0:
						fill_text = str(self.player.water_bucket_amount)
						fill_surf = self.small_font.render(fill_text, False, (100, 180, 255))
						fill_rect = fill_surf.get_rect(bottomright=(rect.right - 3, rect.bottom - 2))
						bg = fill_rect.inflate(4, 2)
						pygame.draw.rect(self.display_surface, (0, 0, 0), bg, 0, 3)
						self.display_surface.blit(fill_surf, fill_rect)
					elif count > 1:
						count_surf = self.small_font.render(str(count), False, 'White')
						count_rect = count_surf.get_rect(bottomright=(rect.right - 3, rect.bottom - 2))
						bg = count_rect.inflate(4, 2)
						pygame.draw.rect(self.display_surface, (0, 0, 0), bg, 0, 3)
						self.display_surface.blit(count_surf, count_rect)

	def display(self, raining=False):
		sw, sh = self.get_size()

		# Single decorative weather/time UI at top-left
		if self.time_manager and self.weather_ui_raw:
			# Scale decorative UI to fit nicely
			ui_scale = min(sw * 0.15 / self.weather_ui_raw.get_width(), sh * 0.25 / self.weather_ui_raw.get_height())
			ui_scale = max(ui_scale, 1.0)
			ui_w = int(self.weather_ui_raw.get_width() * ui_scale)
			ui_h = int(self.weather_ui_raw.get_height() * ui_scale)
			weather_ui = pygame.transform.scale(self.weather_ui_raw, (ui_w, ui_h))
			ui_rect = weather_ui.get_rect(topleft=(10, 10))
			self.display_surface.blit(weather_ui, ui_rect)

			# Weather icon in the top square slot (bigger)
			if self.weather_icons_raw:
				icon_size = 32
				hour = self.time_manager.hour
				if 6 <= hour < 16:
					icon_row = 0
				elif 16 <= hour < 19:
					icon_row = 1
				else:
					icon_row = 2
				icon_col = 1 if raining else 0
				icon_surf = self.weather_icons_raw.subsurface(
					(icon_col * icon_size, icon_row * icon_size, icon_size, icon_size))
				icon_scaled = pygame.transform.scale(icon_surf, (112, 112))
				icon_rect = icon_scaled.get_rect(center=(ui_rect.left + ui_w * 0.28, ui_rect.top + ui_h * 0.31))
				self.display_surface.blit(icon_scaled, icon_rect)

				if self.arrow_icons:
					arrow_surf = self.arrow_icons[icon_row]
					arrow_scaled = pygame.transform.scale(arrow_surf, (24, 24))
					arrow_rect = arrow_scaled.get_rect(midleft=(icon_rect.right + 14, icon_rect.centery - 3))
					self.display_surface.blit(arrow_scaled, arrow_rect)

		# The weather art has two slots: a big square on top for the
		# weather icon and a lower bar for the coin counter.
		if self.time_manager and self.weather_ui_raw:
			# Lower slot of the art, in fractions of its size so the
			# geometry survives a resize.
			money_slot = pygame.Rect(
				ui_rect.left + int(ui_w * 0.026),
				ui_rect.top + int(ui_h * 0.613),
				int(ui_w * 0.717),
				int(ui_h * 0.330))
		else:
			money_slot = pygame.Rect(10, 170, 150, 40)

		# Money, left-and-centre aligned inside that slot; the font shrinks
		# so long numbers never spill out of the bar.
		if self.time_manager and self.weather_ui_raw:
			cy = money_slot.centery + max(2, int(ui_h * 0.025))
			mx = money_slot.left + 14
			if self.currency_icon:
				icon = pygame.transform.scale(self.currency_icon, (28, 28))
				icon_rect = icon.get_rect(midleft=(mx, cy))
				self.display_surface.blit(icon, icon_rect)
				mx = icon_rect.right + 6
			money_text = str(self.player.money)
			money_font = self.font
			text_w = money_font.size(money_text)[0]
			avail = money_slot.right - 6 - mx
			if text_w > avail and text_w > 0:
				# shrink to fit the bar rather than clip the number
				scale = max(0.55, avail / text_w)
				size = max(14, int(money_font.get_height() * scale))
				money_font = ui_font(size)
			money_surf = money_font.render(money_text, False, '#5C3A1E')
			self.display_surface.blit(
				money_surf, money_surf.get_rect(midleft=(mx, cy)))

		# Time panel: below the money bar, centred on it and a little
		# narrower than the weather card so the two never visually merge.
		time_str = (self.time_manager.get_time_string()
		            if self.time_manager else '')
		time_surf = self.font.render(time_str, False, '#5C3A1E')
		art_w, art_h = (self.potion_panel.get_size()
		                if self.potion_panel else (165, 63))
		panel_w = max(time_surf.get_width() + 30, int(art_w * 0.86))
		panel_h = max(int(panel_w * art_h / art_w),
		              time_surf.get_height() + 16)
		time_panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
		time_panel_rect.centerx = money_slot.centerx
		time_panel_rect.top = money_slot.bottom + 10
		# keep the clock on screen on short displays
		if time_panel_rect.bottom > sh - 4:
			time_panel_rect.bottom = sh - 4
		if self.potion_panel:
			panel = pygame.transform.scale(
				self.potion_panel, time_panel_rect.size)
			self.display_surface.blit(panel, time_panel_rect.topleft)
		else:
			panel = pygame.Surface(time_panel_rect.size, pygame.SRCALPHA)
			panel.fill((231, 207, 162, 235))
			pygame.draw.rect(panel, (168, 119, 73), panel.get_rect(), 2, 8)
			self.display_surface.blit(panel, time_panel_rect.topleft)

		self.display_surface.blit(
			time_surf, time_surf.get_rect(center=time_panel_rect.center))

		# hotbar
		self.draw_hotbar()
		self.draw_energy()
		self.draw_potion_effects()
