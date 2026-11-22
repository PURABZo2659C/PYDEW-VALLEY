import pygame
from settings import *
from timer import Timer
from support import play_click, load_overlay_icons
import input_manager

class CraftingMenu:
	def __init__(self, player, toggle_crafting):
		self.player = player
		self.toggle_crafting = toggle_crafting
		self.display_surface = pygame.display.get_surface()
		self.font = ui_font(28)
		self.small_font = ui_font(20)
		self.title_font = ui_font(52)
		self.count_font = ui_font(24)

		try:
			self.crafting_bg = pygame.image.load(asset_path('graphics', 'UI', 'crafting.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.crafting_bg = None
		try:
			self.recipe_entry_bg = pygame.image.load(asset_path('graphics', 'UI', 'craft block.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.recipe_entry_bg = None
		try:
			close_raw = pygame.image.load(asset_path('graphics', 'UI', 'close.png')).convert_alpha()
			cw, ch = close_raw.get_size()
			half = cw // 2
			self.close_normal = close_raw.subsurface((0, 0, half, ch)).copy()
			self.close_hovered = close_raw.subsurface((half, 0, half, ch)).copy()
			self.close_raw_size = (half, ch)
		except (pygame.error, FileNotFoundError):
			self.close_normal = None
			self.close_hovered = None
			self.close_raw_size = (0, 0)
		try:
			self.recipe_selector = pygame.image.load(asset_path('graphics', 'UI', 'recipe selector.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.recipe_selector = None

		self.recipes = list(RECIPES.keys())
		self.item_icons = load_overlay_icons(self.recipes)
		self.index = -1
		self.scroll_offset = 0
		self.visible_count = 5

		self.timer = Timer(50)
		self.slot_height = 90
		self.padding = 12

		self.entry_rects = []
		self.hover_index = -1
		self._cached_overlay = None
		self.close_rect = pygame.Rect(0, 0, 0, 0)
		self._close_scaled = False

	def _refresh_recipes(self):
		unlocked = heart_recipe_unlocked(
			getattr(self.player, 'completed_quests', ()))
		# The emblem is a one-off: hide it once crafted or placed so it cannot be made twice.
		heart_crafted = self.player.inventory.count(HEART_RECIPE) > 0
		heart_done = (heart_crafted
		              or getattr(self.player, 'heart_placed', False))
		recipes = [name for name in RECIPES
		           if name != HEART_RECIPE or (unlocked and not heart_done)]
		if recipes != self.recipes:
			self.recipes = recipes
			self.index = -1
			self.hover_index = -1
			self.scroll_offset = 0
		self._clamp_scroll()

	def _cost_items(self, item):
		return WOOD_ITEMS if item == 'wood' else (item,)

	def _total_item_count(self, item):
		return self.player.inventory.count_any(self._cost_items(item))

	def _consume_item(self, item, amount):
		self.player.inventory.remove_any(self._cost_items(item), amount)

	def can_craft(self, recipe_name):
		entry = RECIPES[recipe_name]
		materials = entry[0] if isinstance(entry, tuple) else entry
		for item, amount in materials.items():
			if self._total_item_count(item) < amount:
				return False
		return True

	def craft(self, recipe_name):
		if not self.can_craft(recipe_name):
			return
		entry = RECIPES[recipe_name]
		materials = entry[0] if isinstance(entry, tuple) else entry
		result_qty = entry[1] if isinstance(entry, tuple) else 1
		for item, amount in materials.items():
			self._consume_item(item, amount)
		result = recipe_name
		# Crafted output is fresh loot: hotbar first, spills into the bag (Player.add_loot).
		remaining = self.player.add_loot(result, result_qty)
		if remaining > 0:
			self.level_ref = getattr(self.player, 'level_ref', None)
			if self.level_ref is not None:
				if remaining == result_qty:
					self.level_ref.show_inventory_full()
				self.level_ref.drop_item(result, remaining)
		try:
			pygame.mixer.Sound(asset_path('audio', 'success.wav')).play()
		except Exception:  # fire-and-forget cue; a missing/busy mixer must not break crafting
			pass

	def craft_all(self, recipe_name):
		"""Craft as many as the materials allow (right-click)."""
		made = 0
		while self.can_craft(recipe_name):
			self.craft(recipe_name)
			made += 1
		return made

	def _clamp_scroll(self):
		max_offset = max(0, len(self.recipes) - self.visible_count)
		if self.scroll_offset > max_offset:
			self.scroll_offset = max_offset
		if self.scroll_offset < 0:
			self.scroll_offset = 0

	def input(self, events=None):
		self._refresh_recipes()
		self.timer.update()
		mx, my = pygame.mouse.get_pos()
		self.hover_index = -1
		for i, rect in enumerate(self.entry_rects):
			if rect.collidepoint(mx, my):
				self.hover_index = i
				break

		if events is None:
			events = pygame.event.get()
		for event in events:
			if event.type == pygame.KEYDOWN:
				if (event.key == pygame.K_ESCAPE
				    or input_manager.is_key_for_action(event.key, 'pause')
				    or input_manager.is_key_for_action(
					    event.key, 'open_crafting')):
					play_click()
					self.toggle_crafting()
					return
				elif self.timer.active:
					pass
				elif event.key == pygame.K_UP or input_manager.is_key_for_action(event.key, 'move_up'):
					if self.index > 0:
						self.index -= 1
					else:
						self.index = len(self.recipes) - 1
					if self.index < self.scroll_offset:
						self.scroll_offset = self.index
					if self.index >= self.scroll_offset + self.visible_count:
						self.scroll_offset = self.index - self.visible_count + 1
					self._clamp_scroll()
					self.timer.activate()
				elif event.key == pygame.K_DOWN or input_manager.is_key_for_action(event.key, 'move_down'):
					if self.index < len(self.recipes) - 1:
						self.index += 1
					else:
						self.index = 0
					if self.index < self.scroll_offset:
						self.scroll_offset = self.index
					if self.index >= self.scroll_offset + self.visible_count:
						self.scroll_offset = self.index - self.visible_count + 1
					self._clamp_scroll()
					self.timer.activate()
				elif (event.key == pygame.K_RETURN or input_manager.is_key_for_action(event.key, 'use_tool')) and self.index >= 0:
					recipe = self.recipes[self.index]
					if self.can_craft(recipe):
						play_click()
						self.craft(recipe)
						self.timer.activate()
			if event.type == pygame.MOUSEWHEEL:
				if not self.timer.active:
					self.scroll_offset -= event.y
					self._clamp_scroll()
					self.timer.activate()
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				if self.close_rect.collidepoint(mx, my):
					play_click()
					self.toggle_crafting()
					return
				elif not self.timer.active and self.hover_index >= 0:
					recipe = self.recipes[self.hover_index]
					if self.can_craft(recipe):
						play_click()
						self.craft(recipe)
						self.timer.activate()
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
				# Right-click crafts the recipe as many times as possible.
				if not self.timer.active and self.hover_index >= 0:
					recipe = self.recipes[self.hover_index]
					if self.can_craft(recipe):
						play_click()
						self.craft_all(recipe)
						self.timer.activate()

	def draw(self):
		self._refresh_recipes()
		sw, sh = self.display_surface.get_size()

		if self._cached_overlay is None or self._cached_overlay.get_size() != (sw, sh):
			self._cached_overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
			self._cached_overlay.fill((20, 15, 10, 170))
		self.display_surface.blit(self._cached_overlay, (0, 0))

		menu_w = 500
		scale = min(sw / menu_w, sh / (menu_w * 1.3))
		scaled_w = int(menu_w * scale)

		font_size = 28
		small_font_size = 28
		count_font_size = 28
		font = ui_font(font_size)
		small_font = ui_font(small_font_size)
		count_font = ui_font(count_font_size)

		clip_w = int(scaled_w * 0.90)
		entry_height = int(clip_w * 140 / 830)
		self.padding = int(6 * scale)
		self.visible_count = 5
		clip_h = self.visible_count * entry_height + (self.visible_count - 1) * self.padding
		top_margin = int(100 * scale)
		bottom_margin = int(40 * scale)
		scaled_h = top_margin + clip_h + bottom_margin

		if self.crafting_bg:
			scaled_bg = pygame.transform.smoothscale(self.crafting_bg, (scaled_w, scaled_h))
			menu_rect = scaled_bg.get_rect(center=(sw // 2, sh // 2))
			self.display_surface.blit(scaled_bg, menu_rect)
			clip_y = menu_rect.top + top_margin
		else:
			menu_rect = pygame.Rect((sw - scaled_w) // 2, (sh - scaled_h) // 2, scaled_w, scaled_h)
			pygame.draw.rect(self.display_surface, (45, 32, 22), menu_rect, 0, 12)
			pygame.draw.rect(self.display_surface, (120, 85, 45), menu_rect, 3, 12)
			title_font = ui_font(56)
			title_surf = title_font.render('CRAFTING', False, '#FFD700')
			title_rect = title_surf.get_rect(centerx=menu_rect.centerx, top=menu_rect.top + 14)
			self.display_surface.blit(title_surf, title_rect)
			clip_y = menu_rect.top + top_margin

		clip_x = menu_rect.centerx - clip_w // 2
		total_content_h = len(self.recipes) * (entry_height + self.padding) - self.padding
		scrollable = total_content_h > clip_h

		if scrollable:
			max_offset = max(0, len(self.recipes) - self.visible_count)
			self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
		else:
			self.scroll_offset = 0

		clip_rect = pygame.Rect(clip_x, clip_y, clip_w, clip_h)
		self.display_surface.set_clip(clip_rect.inflate(40, 40))

		y_start = clip_y - self.scroll_offset * (entry_height + self.padding)
		self.entry_rects = []

		for i, recipe_name in enumerate(self.recipes):
			entry_y = y_start + i * (entry_height + self.padding)
			entry_rect = pygame.Rect(clip_x, entry_y, clip_w, entry_height)
			self.entry_rects.append(entry_rect)

			if entry_rect.bottom < clip_y or entry_rect.top > clip_y + clip_h:
				continue

			affordable = self.can_craft(recipe_name)
			is_hovered = (i == self.hover_index)
			is_selected = (i == self.index and self.index >= 0)

			if self.recipe_entry_bg:
				orig_w, orig_h = self.recipe_entry_bg.get_size()
				entry_scale = entry_rect.w / orig_w
				img_w = entry_rect.w
				img_h = int(orig_h * entry_scale)
				scaled_entry = pygame.transform.smoothscale(self.recipe_entry_bg, (img_w, img_h))
				img_rect = scaled_entry.get_rect(center=entry_rect.center)
				self.display_surface.blit(scaled_entry, img_rect)
			else:
				if is_selected or is_hovered:
					pygame.draw.rect(self.display_surface, (70, 50, 25), entry_rect, 0, 8)
				else:
					pygame.draw.rect(self.display_surface, (55, 40, 28), entry_rect, 0, 8)

			if (is_selected or is_hovered) and self.recipe_selector:
				target = img_rect if self.recipe_entry_bg else entry_rect
				expanded = target.inflate(20, 20)
				sel_w, sel_h = self.recipe_selector.get_size()
				sel_scale = min(expanded.w / sel_w, expanded.h / sel_h)
				scaled_sel = pygame.transform.smoothscale(self.recipe_selector, (int(sel_w * sel_scale), int(sel_h * sel_scale)))
				sel_rect = scaled_sel.get_rect(center=expanded.center)
				self.display_surface.blit(scaled_sel, sel_rect)

			text_x = entry_rect.x + int(14 * scale)
			icon = self.item_icons.get(recipe_name)
			if icon:
				icon_size = int(entry_height * 0.62)
				scaled_icon = pygame.transform.smoothscale(
					icon, (icon_size, icon_size))
				icon_rect = scaled_icon.get_rect(
					midleft=(entry_rect.x + int(10 * scale),
					         entry_rect.centery))
				self.display_surface.blit(scaled_icon, icon_rect)
				text_x = icon_rect.right + int(10 * scale)

			name_color = '#FFFFFF' if affordable else '#666666'
			name_surf = font.render(item_name(recipe_name), False, name_color)
			self.display_surface.blit(name_surf, (text_x, entry_y + int(10 * scale)))

			entry = RECIPES[recipe_name]
			materials = entry[0] if isinstance(entry, tuple) else entry
			mat_parts = []
			for item, amount in materials.items():
				have = self._total_item_count(item)
				mat_parts.append(f'{have}/{amount} {item_name(item)}')
			mat_text = ' + '.join(mat_parts)
			mat_color = '#AAFFAA' if affordable else '#888888'
			wrapped = False
			label_reserve = int(64 * scale)
			available = (entry_rect.right - text_x - int(14 * scale)
			             - label_reserve)
			if small_font.size(mat_text)[0] > available:
				wrapped = True
				mat_factor = 0.72
				lines = []
				current = []
				for part in mat_parts:
					trial = ' + '.join(current + [part])
					if current and \
					   small_font.size(trial)[0] * mat_factor > available:
						lines.append(' + '.join(current))
						current = [part]
					else:
						current.append(part)
				if current:
					lines.append(' + '.join(current))
				line_step = max(18, int(18 * scale))
				for line_index, line in enumerate(lines):
					line_surf = small_font.render(line, False, mat_color)
					line_surf = pygame.transform.scale(
						line_surf,
						(max(1, int(line_surf.get_width() * mat_factor)),
						 max(1, int(line_surf.get_height() * mat_factor))))
					self.display_surface.blit(
						line_surf,
						(text_x, entry_y + int(40 * scale)
						 + line_index * line_step))
			else:
				mat_surf = small_font.render(mat_text, False, mat_color)
				self.display_surface.blit(mat_surf, (text_x, entry_y + int(42 * scale)))

			count = self._total_item_count(recipe_name)
			count_color = '#FFD700' if count > 0 else '#777777'
			count_surf = count_font.render(f'x{count}', False, count_color)
			self.display_surface.blit(count_surf, (entry_rect.right - count_surf.get_width() - int(14 * scale), entry_y + int(10 * scale)))

			if (is_hovered or is_selected) and not wrapped:
				if affordable:
					craft_label = small_font.render('Click to Craft', False, '#88FF88')
				else:
					craft_label = small_font.render('Missing materials', False, '#FF6666')
				self.display_surface.blit(craft_label, (entry_rect.right - craft_label.get_width() - int(14 * scale), entry_y + int(42 * scale)))

		self.display_surface.set_clip(None)

		if scrollable:
			bar_x = menu_rect.right - int(18 * scale)
			bar_w = int(8 * scale)
			pygame.draw.rect(self.display_surface, (30, 22, 14), (bar_x, clip_y, bar_w, clip_h), 0, bar_w // 2)
			handle_h = max(int(20 * scale), int(clip_h * self.visible_count / len(self.recipes)))
			handle_y = clip_y + int((clip_h - handle_h) * self.scroll_offset / max(1, len(self.recipes) - self.visible_count))
			pygame.draw.rect(self.display_surface, (140, 110, 60), (bar_x, handle_y, bar_w, handle_h), 0, bar_w // 2)

		if self.close_normal:
			if not self._close_scaled:
				cw, ch = self.close_raw_size
				close_scale = scale * 1.8
				self.close_normal = pygame.transform.scale(self.close_normal, (int(cw * close_scale), int(ch * close_scale)))
				self.close_hovered = pygame.transform.scale(self.close_hovered, (int(cw * close_scale), int(ch * close_scale)))
				self._close_scaled = True
			close_img = self.close_hovered if self.close_rect.collidepoint(pygame.mouse.get_pos()) else self.close_normal
			self.close_rect = close_img.get_rect(topright=(menu_rect.right - int(3 * scale) - 20, menu_rect.top + 20))
			self.display_surface.blit(close_img, self.close_rect)

	def update(self, events=None):
		self.draw()
		self.input(events)
