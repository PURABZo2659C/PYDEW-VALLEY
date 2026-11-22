import pygame
from settings import *
from support import play_click, play_error, load_overlay_icons
import input_manager
from inventory_model import HOTBAR_SIZE, MAIN_START, SLOT_COUNT, stack_limit


class InventoryMenu:
	def __init__(self, player, toggle_inventory):
		self.player = player
		self.toggle_inventory = toggle_inventory
		self.display_surface = pygame.display.get_surface()

		self.font = ui_font(20)
		self.tooltip_font = ui_font(16)

		# Preload every icon the menu may need.
		all_items = (list(player.inventory.unique_items()) + list(player.tools)
		             + list(player.seeds) + list(RECIPES.keys())
		             + list(POTION_ITEMS) + list(REFINED_ITEMS)
		             + list(SAPLING_ITEMS) + list(FLOWER_ITEMS)
		             + [HEART_RECIPE])
		self.item_icons = load_overlay_icons(all_items)
		self.seed_icons = load_overlay_icons(player.seeds)

		# Raw art is scaled once per screen size in recompute_layout.
		self.bg_raw = pygame.image.load(
			asset_path('graphics', 'UI', 'inventory.png')).convert_alpha()
		self.hb_raw = pygame.image.load(
			asset_path('graphics', 'UI', 'hotbar-2.png')).convert_alpha()
		self.close_raw = pygame.image.load(
			asset_path('graphics', 'UI', 'close.png')).convert_alpha()

		self.cols = 9
		self.rows = 3
		# cursor holds the stack under the mouse; hover_slot is the slot below it.
		self.cursor = None
		self.hover_slot = -1
		self._last_click_time = 0
		self._last_click_item = None
		self._last_click_slot = None
		self._error = None
		self._error_until = 0
		self._overlay = None
		self._last_size = None
		self.recompute_layout()

	def _ensure_layout(self):
		size = self.display_surface.get_size()
		if size != self._last_size:
			self.recompute_layout()

	def recompute_layout(self):
		# Fit the panel to 70% width / 75% height, then scale the slot grid with it.
		self._last_size = self.display_surface.get_size()
		sw, sh = self._last_size
		scale = min(sw * 0.7 / self.bg_raw.get_width(),
		            sh * 0.75 / self.bg_raw.get_height())
		self.scale = scale
		self.bg = pygame.transform.scale(
			self.bg_raw,
			(int(self.bg_raw.get_width() * scale),
			 int(self.bg_raw.get_height() * scale)))
		self.bg_rect = self.bg.get_rect(center=(sw // 2, sh // 2))
		self.hbar_img = pygame.transform.scale(
			self.hb_raw,
			(int(self.hb_raw.get_width() * scale),
			 int(self.hb_raw.get_height() * scale)))

		close_w = self.close_raw.get_width() // 2
		close_h = self.close_raw.get_height()
		close_scale = scale * 1.2
		self.close_normal = pygame.transform.scale(
			self.close_raw.subsurface((0, 0, close_w, close_h)),
			(int(close_w * close_scale), int(close_h * close_scale)))
		self.close_hovered = pygame.transform.scale(
			self.close_raw.subsurface((close_w, 0, close_w, close_h)),
			(int(close_w * close_scale), int(close_h * close_scale)))
		self.close_rect = self.close_normal.get_rect(
			topright=(self.bg_rect.right - 52, self.bg_rect.top - 2))

		# Slot centres in the unscaled inventory.png art.
		orig_slot_cx = [30, 78, 126, 174, 222, 270, 318, 366, 414]
		orig_slot_cy = [62, 118, 174]
		orig_slot_w = 37
		orig_slot_h = 36
		self.slot_rects = []
		for cy in orig_slot_cy:
			for cx in orig_slot_cx:
				rx = (cx - orig_slot_w // 2) * scale
				ry = (cy - orig_slot_h // 2) * scale
				self.slot_rects.append(pygame.Rect(
					self.bg_rect.left + rx, self.bg_rect.top + ry,
					orig_slot_w * scale, orig_slot_h * scale))

		hb_left = self.bg_rect.left + (30 - 26.5) * scale
		self.hbar_rect = self.hbar_img.get_rect(
			topleft=(hb_left, self.bg_rect.bottom + 10))
		# Hotbar slots use their own origin and pitch in hotbar-2.png.
		slot_cx0 = 26.5
		slot_cy = 27.5
		slot_pitch = 48
		slot_size = 40
		slot_isize = slot_size * scale
		self.hotbar_rects = []
		for i in range(HOTBAR_SIZE):
			cx = self.hbar_rect.left + slot_cx0 * scale + i * slot_pitch * scale
			cy = self.hbar_rect.top + slot_cy * scale
			self.hotbar_rects.append(pygame.Rect(
				cx - slot_isize / 2, cy - slot_isize / 2,
				slot_isize, slot_isize))

	def slot_icon(self, item):
		# Seeds have dedicated icons; other items resolve on first use.
		if item in self.player.seeds:
			icon = self.seed_icons.get(item)
			if icon is not None:
				return icon
		icon = self.item_icons.get(item)
		if icon is None:
			icon = load_overlay_icons([item]).get(item)
			self.item_icons[item] = icon
		return icon

	def _slot_index_at(self, pos):
		# Bag slots use model indices; hotbar slots use 0..HOTBAR_SIZE-1.
		for i, rect in enumerate(self.slot_rects):
			if rect.collidepoint(pos):
				return MAIN_START + i
		for i, rect in enumerate(self.hotbar_rects):
			if rect.collidepoint(pos):
				return i
		return None

	def _update_hover(self):
		self.hover_slot = self._slot_index_at(pygame.mouse.get_pos())

	def _show_error(self, text):
		self._error = text
		self._error_until = pygame.time.get_ticks() + 1600
		play_error()
		level = getattr(self.player, 'level_ref', None)
		panel = getattr(level, 'instruction_panel', None)
		if panel is not None:
			panel.show_error(text)

	def return_cursor(self):
		# Put the held stack back; refuse to close if the bag is full.
		if self.cursor is None:
			return True
		item, count = self.cursor
		remaining = self.player.inventory.add(
			item, count, hotbar_first=False)
		if remaining <= 0:
			self.cursor = None
			return True
		self.cursor = [item, remaining]
		self._show_error('Inventory full')
		return False

	def _close(self):
		if self.return_cursor():
			play_click()
			self.toggle_inventory()
			return True
		return False

	def _gather_to_cursor(self):
		# Double-click pulls matching stacks into the held stack.
		if self.cursor is None:
			return
		item, count = self.cursor
		space = stack_limit(item) - count
		if space <= 0:
			return
		gathered = self.player.inventory.gather(item, space)
		if gathered > 0:
			self.cursor[1] += gathered
			play_click()

	def _left_click(self, index):
		# Pick up, place, merge, or swap the held stack.
		inventory = self.player.inventory
		slot = inventory.get_slot(index)

		if self.cursor is None:
			if slot is None:
				return
			now = pygame.time.get_ticks()
			self.cursor = [slot[0], slot[1]]
			inventory.set_slot(index, None)
			self._last_click_time = now
			self._last_click_item = slot[0]
			self._last_click_slot = index
			play_click()
			return

		now = pygame.time.get_ticks()
		# Second click on the same slot within 280 ms gathers the rest.
		if (now - self._last_click_time < 280
		    and self._last_click_item == self.cursor[0]
		    and self._last_click_slot == index):
			self._gather_to_cursor()
			self._last_click_time = 0
			self._last_click_item = None
			self._last_click_slot = None
			return

		item, count = self.cursor
		if slot is None:
			move = min(count, stack_limit(item))
			inventory.set_slot(index, [item, move])
			count -= move
		elif slot[0] == item:
			space = stack_limit(item) - slot[1]
			move = min(count, space)
			slot[1] += move
			count -= move
		else:
			inventory.set_slot(index, [item, count])
			self.cursor = [slot[0], slot[1]]
			self._last_click_time = 0
			self._last_click_item = None
			self._last_click_slot = None
			play_click()
			return

		if count <= 0:
			self.cursor = None
		else:
			self.cursor = [item, count]
		self._last_click_time = 0
		self._last_click_item = None
		self._last_click_slot = None
		play_click()

	def _right_click(self, index):
		# Right click takes half a stack, or places one item.
		inventory = self.player.inventory
		slot = inventory.get_slot(index)

		if self.cursor is None:
			if slot is None:
				return
			take = max(1, (slot[1] + 1) // 2)
			self.cursor = [slot[0], take]
			slot[1] -= take
			if slot[1] <= 0:
				inventory.set_slot(index, None)
			play_click()
			return

		item, count = self.cursor
		if slot is None:
			inventory.set_slot(index, [item, 1])
			count -= 1
		elif slot[0] == item and slot[1] < stack_limit(item):
			slot[1] += 1
			count -= 1
		else:
			return

		if count <= 0:
			self.cursor = None
		else:
			self.cursor = [item, count]
		play_click()

	def _quick_move(self, index):
		# Shift+click moves a stack between bag and hotbar.
		if self.player.inventory.quick_move(index):
			play_click()
		else:
			play_error()

	def _swap_to_hotbar(self, index, hotbar_index):
		# Number keys swap the hovered slot with that hotbar slot.
		if self.cursor is not None:
			return
		if self.player.inventory.move_to_hotbar(index, hotbar_index):
			play_click()
			self.player._update_hotbar_selection()

	def input(self, events):
		self._ensure_layout()
		mouse_pos = pygame.mouse.get_pos()
		for event in events:
			if event.type == pygame.KEYDOWN:
				if (input_manager.is_key_for_action(event.key, 'open_inventory')
				    or event.key == pygame.K_ESCAPE
				    or input_manager.is_key_for_action(event.key, 'pause')):
					self._close()
					continue
				for number in range(1, 10):
					if input_manager.is_key_for_action(
						event.key, f'hotbar_{number}'):
						if self.hover_slot is not None:
							self._swap_to_hotbar(
								self.hover_slot, number - 1)
						break
			elif event.type == pygame.MOUSEBUTTONDOWN:
				if event.button == 1 and self.close_rect.collidepoint(event.pos):
					self._close()
					continue
				index = self._slot_index_at(event.pos)
				if index is None:
					if self.cursor is not None:
						self.return_cursor()
					continue
				if event.button == 1:
					# Shift+click quick-moves; plain click picks up or places.
					if pygame.key.get_mods() & pygame.KMOD_SHIFT:
						if self.cursor is None:
							self._quick_move(index)
					else:
						self._left_click(index)
				elif event.button == 3:
					self._right_click(index)

		self.hover_slot = self._slot_index_at(mouse_pos)

	def draw(self):
		# Dim the world, then draw panel, slots, cursor, tooltip, and errors.
		self._ensure_layout()
		sw, sh = self.display_surface.get_size()
		if self._overlay is None or self._overlay.get_size() != (sw, sh):
			self._overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
			self._overlay.fill((0, 0, 0, 140))
		self.display_surface.blit(self._overlay, (0, 0))
		self.display_surface.blit(self.bg, self.bg_rect)

		close_hovered = self.close_rect.collidepoint(pygame.mouse.get_pos())
		self.display_surface.blit(
			self.close_hovered if close_hovered else self.close_normal,
			self.close_rect)

		for i, rect in enumerate(self.slot_rects):
			index = MAIN_START + i
			if self.hover_slot == index:
				self._draw_highlight(rect)
			self._draw_slot(rect, self.player.inventory.get_slot(index))

		self.display_surface.blit(self.hbar_img, self.hbar_rect)
		for i, rect in enumerate(self.hotbar_rects):
			if self.hover_slot == i:
				self._draw_highlight(rect)
			self._draw_slot(rect, self.player.inventory.get_slot(i))

		self._draw_cursor()
		self._draw_tooltip()
		self._draw_error()

	def _draw_highlight(self, rect):
		surf = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
		surf.fill((255, 255, 255, 34))
		self.display_surface.blit(surf, rect)

	def _draw_slot(self, rect, slot):
		if not slot:
			return
		item, count = slot
		icon = self.slot_icon(item)
		if icon is not None:
			size = int(min(rect.w, rect.h) * 0.78)
			icon = pygame.transform.scale(icon, (size, size))
			self.display_surface.blit(
				icon, icon.get_rect(center=rect.center))
		if count > 1:
			self._draw_count(rect, count)

	def _draw_count(self, rect, count):
		surf = self.font.render(str(count), False, 'White')
		pos = (rect.right - 2, rect.bottom - 1)
		rect2 = surf.get_rect(bottomright=pos)
		pygame.draw.rect(
			self.display_surface, (0, 0, 0, 170),
			rect2.inflate(4, 2), 0, 3)
		self.display_surface.blit(surf, rect2)

	def _draw_cursor(self):
		if self.cursor is None:
			return
		mx, my = pygame.mouse.get_pos()
		item, count = self.cursor
		icon = self.slot_icon(item)
		if icon is not None:
			icon = pygame.transform.scale(icon, (40, 40))
			self.display_surface.blit(
				icon, icon.get_rect(center=(mx + 16, my + 16)))
		if count > 1:
			surf = self.font.render(str(count), False, 'White')
			rect = surf.get_rect(bottomright=(mx + 36, my + 38))
			pygame.draw.rect(
				self.display_surface, (0, 0, 0, 180),
				rect.inflate(4, 2), 0, 3)
			self.display_surface.blit(surf, rect)

	def _draw_tooltip(self):
		if self.cursor is not None or self.hover_slot is None:
			return
		slot = self.player.inventory.get_slot(self.hover_slot)
		if not slot:
			return
		text = item_name(slot[0])
		if slot[1] > 1:
			text = f'{text} x{slot[1]}'
		surf = self.tooltip_font.render(text, False, 'White')
		mx, my = pygame.mouse.get_pos()
		rect = surf.get_rect(topleft=(mx + 16, my + 16))
		sw, sh = self.display_surface.get_size()
		# Keep the tooltip inside the screen.
		rect.clamp_ip(pygame.Rect(8, 8, sw - 16, sh - 16))
		pygame.draw.rect(
			self.display_surface, (30, 25, 15),
			rect.inflate(10, 6), 0, 4)
		pygame.draw.rect(
			self.display_surface, (100, 80, 50),
			rect.inflate(10, 6), 2, 4)
		self.display_surface.blit(surf, rect)

	def _draw_error(self):
		if self._error is None or pygame.time.get_ticks() > self._error_until:
			return
		surf = self.font.render(self._error, False, '#FFB0A0')
		rect = surf.get_rect(
			center=(self.bg_rect.centerx, self.bg_rect.centery))
		pygame.draw.rect(
			self.display_surface, (70, 20, 20),
			rect.inflate(18, 10), 0, 5)
		self.display_surface.blit(surf, rect)

	def update(self, events):
		self.input(events)
		self.draw()
