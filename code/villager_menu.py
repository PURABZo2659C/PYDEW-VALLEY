import pygame
from settings import *
from support import play_click, play_error, load_overlay_icons
from timer import Timer
import input_manager


class VillagerMenu:
	"""The villager trade panel: portrait, trade offers and coin count, with
	buy / sell / barter.
	"""

	def __init__(self, player, close_menu):
		self.player = player
		self.close_menu = close_menu
		self.display_surface = pygame.display.get_surface()
		self.font = ui_font(28)

		try:
			self.panel = pygame.image.load(
				asset_path('graphics', 'UI', 'Villagers.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.panel = None
		try:
			self.entry_bg = pygame.image.load(
				asset_path('graphics', 'UI', 'craft block.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.entry_bg = None
		try:
			self.selector = pygame.image.load(
				asset_path('graphics', 'UI', 'recipe selector.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.selector = None
		try:
			close_raw = pygame.image.load(
				asset_path('graphics', 'UI', 'close.png')).convert_alpha()
			cw, ch = close_raw.get_size()
			half = cw // 2
			self.close_normal = close_raw.subsurface((0, 0, half, ch)).copy()
			self.close_hovered = close_raw.subsurface(
				(half, 0, half, ch)).copy()
			self.close_raw_size = (half, ch)
		except (pygame.error, FileNotFoundError):
			self.close_normal = None
			self.close_hovered = None
			self.close_raw_size = (0, 0)

		# Currency icon next to every coin amount (matches the HUD's Currency.png).
		try:
			self.currency_icon = pygame.transform.smoothscale(
				pygame.image.load(
					asset_path('graphics', 'UI', 'Currency.png')
				).convert_alpha(), (22, 22))
		except (pygame.error, FileNotFoundError):
			self.currency_icon = None

		self.villager_name = ''
		self.rows = ()
		self.tabs = ('buy', 'sell')
		self._rows_by_tab = {'buy': (), 'sell': (), 'smelt': ()}
		self.active_tab = 'buy'
		self.tab_rects = {}
		self.item_icons = {}
		self._title_cache = (None, None)
		self._cached_overlay = None
		self.close_rect = pygame.Rect(0, 0, 0, 0)
		self._close_scaled = False
		self.entry_rects = []
		self.hover_index = -1
		self.scroll_offset = 0
		self.index = -1
		self.visible_count = 5
		self.timer = Timer(50)
		self._clip_rect = pygame.Rect(0, 0, 0, 0)

		# Baking reference: glyphs (109,36)-(526,125); underline (108,136,420,22) / (113,141,410,11).
		self._src_w, self._src_h = 635, 940
		self._glyph_x0, self._glyph_y0 = 109, 36
		self._glyph_x1, self._glyph_y1 = 526, 125
		self._title_color = (182, 137, 98)
		self._bars = (((108, 136, 420, 22), (196, 154, 108)),
		              ((113, 141, 410, 11), (209, 170, 124)))

	def open(self, name):
		self.villager_name = (name or '').upper()
		offers = VILLAGER_TRADES.get(name, {})
		if isinstance(offers, dict):
			sell = offers.get('sell', ())
			buy = offers.get('buy', ())
			barter = offers.get('barter', ())
			refine = offers.get('refine', ())
		else:
			sell, buy, barter, refine = offers, (), (), ()
		sell_rows = [('sell', item, price, None) for item, price in sell]
		buy_rows = [('buy', item, price, None) for item, price in buy]
		smelt_rows = []
		for entry in refine:
			costs, coin_cost, reward = entry
			smelt_rows.append(('refine', costs, coin_cost, reward))
		for entry in barter:
			costs, coin_cost, reward = entry
			buy_rows.append(('barter', costs, coin_cost, reward))
		tabs = ['buy', 'sell']
		if smelt_rows:
			tabs.append('smelt')
		self.tabs = tuple(tabs)
		self._rows_by_tab = {'buy': tuple(buy_rows),
		                     'sell': tuple(sell_rows),
		                     'smelt': tuple(smelt_rows)}
		self.active_tab = next(
			(tab for tab in self.tabs if self._rows_by_tab[tab]), 'buy')
		self.rows = self._rows_by_tab[self.active_tab]
		rows = buy_rows + sell_rows + smelt_rows
		icon_items = []
		for mode, item, price, reward in rows:
			icon_items.append(
				reward if mode in ('barter', 'refine') else item)
		self.item_icons = load_overlay_icons(icon_items)
		self.hover_index = -1
		self.scroll_offset = 0
		self.index = -1
		self.entry_rects = []
		self.tab_rects = {}
		self.timer.deactivate()
		self._title_cache = (None, None)

	def close(self):
		self.close_menu()

	def _seed_key(self, item):
		if item in getattr(self.player, 'seeds', ()):
			return item
		return None

	def _resolve_key(self, item):
		"""The key that stands for an offer in the offer list.
		Stable across a rebuild, so a click maps back to the right offer.
		"""
		key = self._seed_key(item) or item
		if self.player.inventory.count(key):
			return key
		for slot in self.player.inventory.slots:
			if slot and slot[0].lower() == key.lower():
				return slot[0]
		return key

	def _have(self, item):
		key = self._resolve_key(item)
		return self.player.inventory.count(key)

	def _take(self, item):
		key = self._resolve_key(item)
		return self.player.inventory.remove(key, 1) == 1

	def sell(self, item, price):
		if self._take(item):
			self.player.money += price
			play_click()
			return True
		play_error()
		return False

	def _show_inventory_full(self):
		"""Route the full-bag popup through to the level overlay."""
		level = getattr(self.player, 'level_ref', None)
		if level is not None and hasattr(level, 'show_inventory_full'):
			level.show_inventory_full()

	def buy(self, item, price):
		if self.player.money < price:
			play_error()
			return False
		seed = self._seed_key(item)
		key = seed or item
		# A purchase is fresh loot: hotbar first (Player.add_loot).
		if self.player.add_loot(key, 1) != 0:
			play_error()
			self._show_inventory_full()
			return False
		self.player.money -= price
		if seed or key in SAPLING_ITEMS or key in TOOL_ITEMS \
		   or key == 'bridge':
			assign = getattr(self.player, 'assign_to_hotbar', None)
			if callable(assign):
				assign(key, 1, seed=bool(seed))
		play_click()
		return True

	def barter(self, costs, coin_cost, reward_item):
		if coin_cost is not None and self.player.money < coin_cost:
			play_error()
			return False
		for cost_item, amount in costs:
			if self._have(cost_item) < amount:
				play_error()
				return False
		# Add the reward first: a full bag must not eat the gem/coin costs.
		if self.player.add_loot(reward_item, 1) != 0:
			play_error()
			self._show_inventory_full()
			return False
		if coin_cost is not None:
			self.player.money -= coin_cost
		for cost_item, amount in costs:
			self.player.inventory.remove(self._resolve_key(cost_item), amount)
		play_click()
		return True

	def sell_all(self, item, price):
		key = self._resolve_key(item)
		count = self.player.inventory.count(key)
		if count <= 0:
			play_error()
			return False
		self.player.inventory.remove(key, count)
		self.player.money += price * count
		play_click()
		return True

	def buy_all(self, item, price):
		bought = 0
		while self.player.money >= price:
			before = self.player.money
			if not self.buy(item, price):
				break
			bought += 1
			if self.player.money >= before:
				break
		return bought

	def barter_all(self, costs, coin_cost, reward_item):
		traded = 0
		while True:
			if coin_cost is not None and self.player.money < coin_cost:
				break
			if any(self._have(ci) < cn for ci, cn in costs):
				break
			if not self.barter(costs, coin_cost, reward_item):
				break
			traded += 1
		return traded

	def _scaled_rect(self, rect, menu_rect):
		sx = menu_rect.w / self._src_w
		sy = menu_rect.h / self._src_h
		x, y, w, h = rect
		return pygame.Rect(menu_rect.x + int(x * sx),
		                   menu_rect.y + int(y * sy),
		                   max(1, int(w * sx)), max(1, int(h * sy)))

	def _title_surface(self, target_h, max_w):
		key = (self.villager_name, target_h, max_w)
		if self._title_cache[0] == key:
			return self._title_cache[1]
		surf = None
		if self.villager_name:
			font = ui_font(max(10, int(target_h * 1.12)))
			raw = font.render(self.villager_name, False, self._title_color)
			ink = raw.get_bounding_rect(10)
			if ink.w > 0 and ink.h > 0:
				trimmed = raw.subsurface(ink).copy()
				scale = target_h / trimmed.get_height()
				size = (max(1, int(round(trimmed.get_width() * scale))),
				        max(1, int(round(trimmed.get_height() * scale))))
				surf = pygame.transform.scale(trimmed, size)
				if surf.get_width() > max_w:
					fit = max_w / surf.get_width()
					surf = pygame.transform.scale(
						surf, (max_w,
						       max(1, int(round(surf.get_height() * fit)))))
		self._title_cache = (key, surf)
		return surf

	def _clamp_scroll(self):
		max_offset = max(0, len(self.rows) - self.visible_count)
		self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

	def _switch_tab(self, tab):
		rows = self._rows_by_tab.get(tab, ())
		if tab == self.active_tab or not rows:
			return False
		self.active_tab = tab
		self.rows = rows
		self.hover_index = -1
		self.scroll_offset = 0
		self.index = -1
		self.entry_rects = []
		self.timer.activate()
		return True

	def _activate_row(self, index):
		if 0 <= index < len(self.rows):
			mode, item, price, reward = self.rows[index]
			if mode == 'sell':
				self.sell(item, price)
			elif mode == 'buy':
				self.buy(item, price)
			else:
				self.barter(item, price, reward)

	def _activate_row_all(self, index):
		"""Right-click: repeat the row's trade until it can no longer run."""
		if not (0 <= index < len(self.rows)):
			return
		mode, item, price, reward = self.rows[index]
		if mode == 'sell':
			self.sell_all(item, price)
		elif mode == 'buy':
			self.buy_all(item, price)
		else:
			self.barter_all(item, price, reward)

	def input(self, events=None):
		self.timer.update()
		mx, my = pygame.mouse.get_pos()
		self.hover_index = -1
		if self._clip_rect.collidepoint(mx, my):
			for i, rect in enumerate(self.entry_rects):
				if rect.collidepoint(mx, my):
					self.hover_index = i
					break

		if events is None:
			events = pygame.event.get()
		for event in events:
			if event.type == pygame.KEYDOWN:
				# Esc always closes the trade, even mid-trade.
				if (event.key == pygame.K_ESCAPE
				    or input_manager.is_key_for_action(event.key, 'pause')):
					play_click()
					self.close()
					return
				if self.timer.active or not self.rows:
					pass
				elif event.key == pygame.K_UP or input_manager.is_key_for_action(event.key, 'move_up'):
					if self.index > 0:
						self.index -= 1
					else:
						self.index = len(self.rows) - 1
					if self.index < self.scroll_offset:
						self.scroll_offset = self.index
					if self.index >= self.scroll_offset + self.visible_count:
						self.scroll_offset = self.index - self.visible_count + 1
					self._clamp_scroll()
					self.timer.activate()
				elif event.key == pygame.K_DOWN or input_manager.is_key_for_action(event.key, 'move_down'):
					if self.index < len(self.rows) - 1:
						self.index += 1
					else:
						self.index = 0
					if self.index < self.scroll_offset:
						self.scroll_offset = self.index
					if self.index >= self.scroll_offset + self.visible_count:
						self.scroll_offset = self.index - self.visible_count + 1
					self._clamp_scroll()
					self.timer.activate()
				elif (event.key == pygame.K_RETURN
				      or input_manager.is_key_for_action(event.key, 'use_tool')) \
						and self.index >= 0:
					self._activate_row(self.index)
					self.timer.activate()
			if event.type == pygame.MOUSEWHEEL:
				if not self.timer.active:
					self.scroll_offset -= event.y
					self._clamp_scroll()
					self.timer.activate()
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				if self.close_rect.collidepoint(mx, my):
					play_click()
					self.close()
					return
				for tab, rect in self.tab_rects.items():
					if rect.collidepoint(mx, my):
						if self._switch_tab(tab):
							play_click()
						return
				if not self.timer.active and self.hover_index >= 0:
					self._activate_row(self.hover_index)
					self.timer.activate()
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
				# Right-click repeats the trade as many times as possible.
				if not self.timer.active and self.hover_index >= 0:
					self._activate_row_all(self.hover_index)
					self.timer.activate()

	def draw(self):
		sw, sh = self.display_surface.get_size()

		if (self._cached_overlay is None
				or self._cached_overlay.get_size() != (sw, sh)):
			self._cached_overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
			self._cached_overlay.fill((20, 15, 10, 170))
		self.display_surface.blit(self._cached_overlay, (0, 0))

		menu_w = 500
		scale = min(sw / menu_w, sh / (menu_w * 1.3))
		scaled_w = int(menu_w * scale)

		clip_w = int(scaled_w * 0.90)
		entry_height = int(clip_w * 140 / 830)
		padding = int(6 * scale)
		clip_h = 5 * entry_height + 4 * padding
		top_margin = int(150 * scale)
		bottom_margin = int(40 * scale)
		scaled_h = top_margin + clip_h + bottom_margin

		if self.panel:
			scaled_bg = pygame.transform.smoothscale(
				self.panel, (scaled_w, scaled_h))
			menu_rect = scaled_bg.get_rect(center=(sw // 2, sh // 2))
			self.display_surface.blit(scaled_bg, menu_rect)
		else:
			menu_rect = pygame.Rect((sw - scaled_w) // 2,
			                        (sh - scaled_h) // 2,
			                        scaled_w, scaled_h)
			pygame.draw.rect(self.display_surface, (232, 207, 166),
			                 menu_rect, 0, 12)
			pygame.draw.rect(self.display_surface, (120, 85, 45),
			                 menu_rect, 3, 12)

		glyph_h = int((self._glyph_y1 - self._glyph_y0 + 1)
		              * menu_rect.h / self._src_h)
		max_w = int((self._glyph_x1 - self._glyph_x0 + 1)
		            * menu_rect.w / self._src_w)
		title = self._title_surface(glyph_h, max_w)
		if title:
			bottom = menu_rect.y + int(self._glyph_y1
			                           * menu_rect.h / self._src_h)
			rect = title.get_rect(midbottom=(menu_rect.centerx, bottom))
			self.display_surface.blit(title, rect)

		for bar_rect, color in self._bars:
			bar = self._scaled_rect(bar_rect, menu_rect)
			pygame.draw.rect(self.display_surface, color, bar, 0,
			                 bar.h // 2)

		clip_x = menu_rect.centerx - clip_w // 2
		clip_y = menu_rect.top + top_margin
		tab_h = int(34 * scale)
		tab_gap = int(8 * scale)
		tab_w = (clip_w - tab_gap * (len(self.tabs) - 1)) // len(self.tabs)
		tab_y = clip_y - tab_h - int(8 * scale)
		self.tab_rects = {}
		mouse_pos = pygame.mouse.get_pos()
		for i, tab in enumerate(self.tabs):
			tab_rect = pygame.Rect(clip_x + i * (tab_w + tab_gap),
			                       tab_y, tab_w, tab_h)
			self.tab_rects[tab] = tab_rect
			enabled = bool(self._rows_by_tab.get(tab))
			selected = tab == self.active_tab
			hovered = enabled and tab_rect.collidepoint(mouse_pos)
			if not enabled:
				bg, border, text_color = (210, 190, 158), (170, 145, 110), (150, 128, 100)
			elif selected:
				bg, border, text_color = (120, 85, 45), (80, 55, 25), '#FFF3D6'
			elif hovered:
				bg, border, text_color = (168, 125, 78), (100, 70, 35), '#FFF3D6'
			else:
				bg, border, text_color = (196, 154, 108), (120, 85, 45), '#5C3A1E'
			pygame.draw.rect(self.display_surface, bg, tab_rect, 0, 8)
			pygame.draw.rect(self.display_surface, border, tab_rect, 2, 8)
			label = self.font.render(tab.upper(), False, text_color)
			self.display_surface.blit(
				label, label.get_rect(center=tab_rect.center))
		step = entry_height + padding
		total_h = (len(self.rows) * step - padding) if self.rows else 0
		scrollable = total_h > clip_h
		if scrollable:
			self._clamp_scroll()
		else:
			self.scroll_offset = 0
		clip_rect = pygame.Rect(clip_x, clip_y, clip_w, clip_h)
		self._clip_rect = clip_rect
		self.display_surface.set_clip(clip_rect.inflate(40, 40))

		y_start = clip_y - self.scroll_offset * step
		self.entry_rects = []
		for i, (mode, item, price, reward) in enumerate(self.rows):
			entry_y = y_start + i * step
			entry_rect = pygame.Rect(clip_x, entry_y, clip_w, entry_height)
			self.entry_rects.append(entry_rect)
			if entry_rect.bottom < clip_y or entry_rect.top > clip_y + clip_h:
				continue

			if mode in ('barter', 'refine'):
				costs = item
				have = self._have(costs[0][0])
				can = (all(self._have(ci) >= cn for ci, cn in costs)
				       and (price is None or self.player.money >= price))
			else:
				have = self._have(item)
				if mode == 'sell':
					can = have > 0
				else:
					can = self.player.money >= price
			is_hovered = (i == self.hover_index)
			is_selected = (i == self.index and self.index >= 0)

			img_rect = entry_rect
			if self.entry_bg:
				orig_w, orig_h = self.entry_bg.get_size()
				entry_scale = entry_rect.w / orig_w
				img_h = int(orig_h * entry_scale)
				scaled_entry = pygame.transform.smoothscale(
					self.entry_bg, (entry_rect.w, img_h))
				img_rect = scaled_entry.get_rect(center=entry_rect.center)
				self.display_surface.blit(scaled_entry, img_rect)
			elif is_hovered or is_selected:
				pygame.draw.rect(self.display_surface, (70, 50, 25),
				                 entry_rect, 0, 8)
			else:
				pygame.draw.rect(self.display_surface, (55, 40, 28),
				                 entry_rect, 0, 8)

			if (is_hovered or is_selected) and self.selector:
				expanded = img_rect.inflate(20, 20)
				sel_w, sel_h = self.selector.get_size()
				sel_scale = min(expanded.w / sel_w, expanded.h / sel_h)
				scaled_sel = pygame.transform.smoothscale(
					self.selector,
					(int(sel_w * sel_scale), int(sel_h * sel_scale)))
				self.display_surface.blit(
					scaled_sel, scaled_sel.get_rect(center=expanded.center))

			label_item = reward if mode in ('barter', 'refine') else item
			text_x = entry_rect.x + int(14 * scale)
			icon = self.item_icons.get(label_item)
			if icon:
				icon_size = int(entry_height * 0.62)
				scaled_icon = pygame.transform.smoothscale(
					icon, (icon_size, icon_size))
				icon_rect = scaled_icon.get_rect(
					midleft=(entry_rect.x + int(10 * scale),
					         entry_rect.centery))
				self.display_surface.blit(scaled_icon, icon_rect)
				text_x = icon_rect.right + int(10 * scale)

			label = item_name(label_item)
			name_surf = self.font.render(
				label, False, '#FFFFFF' if can else '#666666')
			self.display_surface.blit(
				name_surf, (text_x, entry_y + int(10 * scale)))

			color = '#AAFFAA' if can else '#888888'
			price_x = text_x
			price_y = entry_y + int(42 * scale)
			if mode in ('sell', 'buy'):
				# "Buy for [coin] 4": label, coin, amount; the icon sits between, never after.
				label = 'Sell for' if mode == 'sell' else 'Buy for'
				label_surf = self.font.render(label, False, color)
				amount_surf = self.font.render(str(price), False, color)
				self.display_surface.blit(label_surf, (price_x, price_y))
				price_x += label_surf.get_width() + int(4 * scale)
				if self.currency_icon:
					ico = self.currency_icon
					self.display_surface.blit(
						ico, ico.get_rect(
							midleft=(price_x, price_y
							         + label_surf.get_height() // 2)))
					price_x += ico.get_width() + int(4 * scale)
				self.display_surface.blit(amount_surf, (price_x, price_y))
			else:
				# barter / refine rows are item costs, optionally plus a coin fee icon.
				price_text = ' + '.join(
					f'{amount} {item_name(cost)}'
					for cost, amount in item)
				price_surf = self.font.render(price_text, False, color)
				self.display_surface.blit(price_surf, (price_x, price_y))
				price_x += price_surf.get_width()
				if price is not None:
					if self.currency_icon:
						ico = self.currency_icon
						self.display_surface.blit(
							ico, ico.get_rect(
								midleft=(price_x, price_y
								         + price_surf.get_height() // 2)))
						price_x += ico.get_width() + int(4 * scale)
					amount_surf = self.font.render(str(price), False, color)
					self.display_surface.blit(amount_surf, (price_x, price_y))

			have_color = '#FFD700' if have > 0 else '#777777'
			have_surf = self.font.render(f'x{have}', False, have_color)
			self.display_surface.blit(
				have_surf, (entry_rect.right - have_surf.get_width()
				            - int(14 * scale), entry_y + int(10 * scale)))

			if is_hovered or is_selected:
				if mode == 'sell':
					text = 'Click to Sell' if can else 'Nothing to sell'
				elif mode == 'buy':
					text = 'Click to Buy' if can else "Can't afford"
				elif mode == 'refine':
					text = 'Click to Refine' if can else 'Missing materials'
				else:
					text = 'Click to Trade' if can else 'Missing materials'
				action = self.font.render(
					text, False, '#88FF88' if can else '#FF6666')
				self.display_surface.blit(
					action, (entry_rect.right - action.get_width()
					         - int(14 * scale), entry_y + int(42 * scale)))
		self.display_surface.set_clip(None)

		if scrollable:
			bar_x = menu_rect.right - int(18 * scale)
			bar_w = int(8 * scale)
			pygame.draw.rect(self.display_surface, (30, 22, 14),
			                 (bar_x, clip_y, bar_w, clip_h), 0, bar_w // 2)
			handle_h = max(int(20 * scale),
			               int(clip_h * self.visible_count / len(self.rows)))
			handle_y = clip_y + int((clip_h - handle_h) * self.scroll_offset
			                        / max(1, len(self.rows) - self.visible_count))
			pygame.draw.rect(self.display_surface, (140, 110, 60),
			                 (bar_x, handle_y, bar_w, handle_h), 0,
			                 bar_w // 2)

		money = self.font.render(f'{self.player.money}', False,
		                         (100, 70, 40))
		# Right-aligned: [icon][amount], no 'Coins' suffix.
		money_right = menu_rect.right - int(24 * scale)
		money_y = menu_rect.bottom - int(20 * scale)
		money_rect = money.get_rect(midright=(money_right, money_y))
		self.display_surface.blit(money, money_rect)
		if self.currency_icon:
			ico = self.currency_icon
			self.display_surface.blit(
				ico, ico.get_rect(
					midright=(money_rect.left - int(6 * scale), money_y)))

		if self.close_normal:
			if not self._close_scaled:
				cw, ch = self.close_raw_size
				close_scale = scale * 1.8
				self.close_normal = pygame.transform.scale(
					self.close_normal,
					(int(cw * close_scale), int(ch * close_scale)))
				self.close_hovered = pygame.transform.scale(
					self.close_hovered,
					(int(cw * close_scale), int(ch * close_scale)))
				self._close_scaled = True
			close_img = self.close_hovered if self.close_rect.collidepoint(
				pygame.mouse.get_pos()) else self.close_normal
			self.close_rect = close_img.get_rect(
				topright=(menu_rect.right - int(3 * scale) - 20,
				          menu_rect.top + 20))
			self.display_surface.blit(close_img, self.close_rect)

	def update(self, events=None):
		self.draw()
		self.input(events)


class ShopMenu(VillagerMenu):
	"""Village shop: sells the player's forage for coins."""

	def open(self):
		self.villager_name = 'SHOP'
		sell_rows = [
			('sell', item, SALE_PRICES[item], None)
			for item in SHOP_ITEMS
		]
		self.tabs = ('sell',)
		self._rows_by_tab = {
			'buy': (),
			'sell': tuple(sell_rows),
			'smelt': (),
		}
		self.active_tab = 'sell'
		self.rows = self._rows_by_tab['sell']
		self.item_icons = load_overlay_icons(
			row[1] for row in sell_rows)
		self.hover_index = -1
		self.scroll_offset = 0
		self.index = -1
		self.entry_rects = []
		self.tab_rects = {}
		self.timer.deactivate()
		self._title_cache = (None, None)
