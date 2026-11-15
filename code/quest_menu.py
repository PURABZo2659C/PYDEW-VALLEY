import math
import random
import pygame
from settings import *
from support import play_click, play_error, load_overlay_icons, log_once
import input_manager


class QuestMenu:
	"""Town-hall delivery board: six buttons per page, each asking for one
	full stack of an item. A successful delivery consumes the items and
	leaves the button pressed in as completed. Finishing page one reveals
	Next, which switches to the fruit delivery page."""

	PANEL_W, PANEL_H = 635, 469
	SLOT_W, SLOT_H = 130, 128
	GAP_X = 42
	GAP_X_TIGHT = 24
	X0 = (PANEL_W - (3 * SLOT_W + 2 * GAP_X)) // 2
	Y0 = 40
	Y0_TIGHT = 74

	TEXT = (92, 58, 30)
	HEART_SRC = pygame.Rect(225, 101, 184, 240)
	DROP_MS = 620
	FX_MS = 420

	def __init__(self, player, close_menu, on_heart_placed=None,
	             on_credits_replay=None):
		self.player = player
		self.close_menu = close_menu
		self.on_heart_placed = on_heart_placed
		self.on_credits_replay = on_credits_replay
		self.display_surface = pygame.display.get_surface()
		self._font_cache = {}
		self._text_cache = {}
		self._icon_cache = {}
		self._button_cache = {}
		self.scale = 1.0
		self.page = 0
		self.slot_rects = []
		self.next_rect = pygame.Rect(0, 0, 0, 0)
		self.ok_rect = pygame.Rect(0, 0, 0, 0)
		self.close_rect = pygame.Rect(0, 0, 0, 0)
		self.hover_index = -1
		self.index = -1
		self.error = None
		self._overlay = None
		self.heart_rect = pygame.Rect(0, 0, 0, 0)
		self._drop_start = None
		self._impact_start = None
		self._particles = []

		self.panel = self._load('Final_Quest_Panel.png')
		self.heart_panel = self._load('Final_Quest_Panel_heart.png')
		self.heart_after = self._load('Final_Quest_Panel_heart_after.png')
		self.quest_normal, self.quest_pressed = self._load_pair(
			'Quest_buttons.png', pygame.Surface.get_width)
		self.blank_normal, self.blank_hover = self._load_pair(
			'blank_buttons.png', pygame.Surface.get_width)
		self.close_normal, self.close_hovered = self._load_pair(
			'close.png', pygame.Surface.get_width)

		seed_items = [item for page in TOWN_QUEST_PAGES
		              for item, _label, seed in page if seed]
		crop_items = [item for page in TOWN_QUEST_PAGES
		              for item, _label, seed in page if not seed]
		self.seed_icons = load_overlay_icons(seed_items)
		self.crop_icons = load_overlay_icons(crop_items)
		self.heart_icon = load_overlay_icons([HEART_RECIPE]).get(HEART_RECIPE)
		try:
			self._impact_sound = pygame.mixer.Sound(
				asset_path('audio', 'success.wav'))
			self._impact_sound.set_volume(0.4)
		except Exception:
			self._impact_sound = None

	def _load(self, name):
		try:
			return pygame.image.load(
				asset_path('graphics', 'UI', name)).convert_alpha()
		except (pygame.error, FileNotFoundError):
			return None

	def _load_pair(self, name, _get_width):
		raw = self._load(name)
		if raw is None:
			return None, None
		half = raw.get_width() // 2
		return (raw.subsurface((0, 0, half, raw.get_height())).copy(),
		        raw.subsurface((half, 0, half, raw.get_height())).copy())

	def open(self):
		self.error = None
		self.hover_index = -1
		self.index = -1
		last_page = len(TOWN_QUEST_PAGES) - 1
		last_done = all(
			f'{last_page}:{item}' in self.player.completed_quests
			for item, _label, _seed in TOWN_QUEST_PAGES[last_page])
		self.page = len(TOWN_QUEST_PAGES) if last_done or self._heart_done() else 0
		self._drop_start = None
		self._impact_start = None
		self._particles = []
		if getattr(self.player, 'heart_placed', False) \
		   and not getattr(self.player, 'credits_seen', False) \
		   and self.on_heart_placed is not None:
			self.on_heart_placed()

	def _heart_page(self):
		return self.page >= len(TOWN_QUEST_PAGES)

	def _heart_done(self):
		"""The heart is terminal for the save: once placed or once the
		credits have been seen it can never be placed again."""
		return (bool(getattr(self.player, 'heart_placed', False))
		        or bool(getattr(self.player, 'credits_seen', False)))

	def _credits_locked(self):
		return (self._heart_page()
		        and getattr(self.player, 'heart_placed', False)
		        and not getattr(self.player, 'credits_seen', False))

	def _quests(self):
		if self._heart_page():
			return []
		return TOWN_QUEST_PAGES[self.page]

	def _quest_id(self, item):
		return f'{self.page}:{item}'

	def _font(self, size):
		size = max(8, int(size))
		font = self._font_cache.get(size)
		if font is None:
			font = ui_font(size)
			self._font_cache[size] = font
		return font

	def _text(self, text, base_size, color, factor=1.0):
		key = (text, base_size, color, round(factor, 3))
		surf = self._text_cache.get(key)
		if surf is None:
			surf = self._font(base_size).render(text, False, color)
			if factor < 0.999:
				surf = pygame.transform.scale(
					surf, (max(1, int(surf.get_width() * factor)),
					       max(1, int(surf.get_height() * factor))))
			self._text_cache[key] = surf
		return surf

	def _icon(self, item, seed, box):
		icons = self.seed_icons if seed else self.crop_icons
		surf = icons.get(item)
		if surf is None:
			return None
		key = (item, seed, box)
		scaled = self._icon_cache.get(key)
		if scaled is None:
			w, h = surf.get_size()
			factor = min(box / max(1, w), box / max(1, h))
			scaled = pygame.transform.scale(
				surf, (max(1, int(w * factor)), max(1, int(h * factor))))
			self._icon_cache[key] = scaled
		return scaled

	def _button(self, kind, size, bright=False):
		key = (kind, size, bright)
		img = self._button_cache.get(key)
		if img is None:
			source = {
				'quest': self.quest_normal,
				'quest_pressed': self.quest_pressed,
				'blank': self.blank_normal,
				'blank_hover': self.blank_hover,
			}.get(kind)
			if source is None:
				return None
			img = pygame.transform.scale(source, size)
			if bright:
				img = img.copy()
				img.fill((34, 34, 34, 0), special_flags=pygame.BLEND_RGBA_ADD)
			self._button_cache[key] = img
		return img

	def _have(self, item, seed):
		return self.player.inventory.count(item)

	def _take(self, item, amount, seed):
		self.player.inventory.remove(item, amount)

	def _page_complete(self):
		return all(self._quest_id(item) in self.player.completed_quests
		           for item, _, _ in self._quests())

	def _next_visible(self):
		# intermediate pages still offer Next; the final page auto-
		# advances to the heart panel instead of showing Next
		return (self.page < len(TOWN_QUEST_PAGES) - 1
		        and self._page_complete())

	def _activate(self, index):
		quests = self._quests()
		if not 0 <= index < len(quests):
			return
		item, label, seed = quests[index]
		quest_id = self._quest_id(item)
		if quest_id in self.player.completed_quests:
			play_click()
			return
		have = self._have(item, seed)
		if have < QUEST_STACK:
			play_error()
			if have <= 0:
				self.error = (f'Missing {label}!',
				              f'Gather {QUEST_STACK} to deliver.')
			else:
				self.error = (f'Not enough {label}!',
				              f'Need {QUEST_STACK}, you have {have}.')
			return
		self._take(item, QUEST_STACK, seed)
		self.player.completed_quests.add(quest_id)
		play_click()
		# completing the last quest on the last page drops straight
		# into the heart placing panel - no Next prompt needed
		if (self.page == len(TOWN_QUEST_PAGES) - 1
		        and self._page_complete()):
			# DEMO mode: once the town quests are done, stock the
			# materials to craft the Heart of the Valley so the player
			# can reach the heart panel without grinding ores again.
			level = getattr(self.player, 'level_ref', None)
			if getattr(level, 'debug_demo', False):
				cost = RECIPES[HEART_RECIPE][0]
				for item, count in cost.items():
					self.player.add_item(item, count)
			self._next()

	def _next(self):
		self.page += 1
		self.index = -1
		self.hover_index = -1
		self.error = None

	def _place_heart(self):
		if self._heart_done():
			if getattr(self.player, 'credits_seen', False) \
			   and self.on_credits_replay is not None:
				self.on_credits_replay()
			return
		if self._drop_start is not None:
			return
		if self._have(HEART_RECIPE, False) <= 0:
			play_error()
			self.error = ('The emblem is hollow!',
			              'Craft the Heart of the Valley first.')
			return
		self._take(HEART_RECIPE, 1, False)
		self.player.heart_placed = True
		self._drop_start = pygame.time.get_ticks()
		self._impact_start = None
		self._particles = []
		self.index = -1
		play_click()
		if self.on_heart_placed is not None:
			self.on_heart_placed()

	def _input(self, events):
		mx, my = pygame.mouse.get_pos()
		self.hover_index = -1
		heart_page = self._heart_page()
		locked = self._credits_locked()
		if self.error is None and not heart_page:
			for i, rect in enumerate(self.slot_rects):
				if rect.collidepoint(mx, my):
					self.hover_index = i
					break

		for event in events:
			if event.type == pygame.KEYDOWN:
				if self.error is not None:
					if event.key in (pygame.K_RETURN, pygame.K_ESCAPE,
					                 pygame.K_SPACE):
						play_click()
						self.error = None
					continue
				if event.key == pygame.K_ESCAPE or \
				   input_manager.is_key_for_action(event.key, 'pause'):
					if locked:
						continue
					play_click()
					self.close_menu()
					return
				if heart_page:
					if event.key in (pygame.K_RETURN, pygame.K_SPACE):
						self._place_heart()
					continue
				if event.key == pygame.K_LEFT:
					self.index = 0 if self.index < 0 else \
						(self.index - 1) % len(self._quests())
				elif event.key == pygame.K_RIGHT:
					self.index = 0 if self.index < 0 else \
						(self.index + 1) % len(self._quests())
				elif event.key == pygame.K_UP:
					if self.index < 0:
						self.index = 0
					elif self.index >= 3:
						self.index -= 3
				elif event.key == pygame.K_DOWN:
					if self.index < 0:
						self.index = 3
					elif self.index < 3:
						self.index += 3
				elif event.key == pygame.K_RETURN and self.index >= 0:
					self._activate(self.index)
			elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				if self.error is not None:
					if self.ok_rect.collidepoint(event.pos):
						play_click()
						self.error = None
					continue
				if not locked and self.close_rect.collidepoint(event.pos):
					play_click()
					self.close_menu()
					return
				if heart_page:
					if self.heart_rect.collidepoint(event.pos):
						self._place_heart()
					continue
				if self._next_visible() and \
				   self.next_rect.collidepoint(event.pos):
					play_click()
					self._next()
					continue
				for i, rect in enumerate(self.slot_rects):
					if rect.collidepoint(event.pos):
						self.index = i
						self._activate(i)
						break

	def _draw_text_button(self, rect, label, hovered):
		img = self._button('blank_hover' if hovered else 'blank', rect.size)
		if img is not None:
			self.display_surface.blit(img, rect)
		width, height = self._font(28).size(label)
		factor = min(1.0, (rect.w - 24) / max(1, width),
		             (rect.h - 8) / max(1, height))
		surf = self._text(label, 28, self.TEXT, factor)
		self.display_surface.blit(surf, surf.get_rect(center=rect.center))

	def _draw_slots(self, panel, sx):
		quests = self._quests()
		cols = 3 if len(quests) <= 6 else 4
		slot_w = int(self.SLOT_W * sx)
		slot_h = int(self.SLOT_H * sx)
		gap_x = int((self.GAP_X if cols == 3 else self.GAP_X_TIGHT) * sx)
		grid_w = cols * slot_w + (cols - 1) * gap_x
		x0 = panel.centerx - grid_w // 2
		y0 = panel.top + int((self.Y0 if cols == 3 else self.Y0_TIGHT) * sx)
		self.slot_rects = []
		mouse_pos = pygame.mouse.get_pos()
		label_base = self._font(28)
		widest = max(label_base.size(q[1])[0] for q in quests)
		label_scale = min(1.0, (slot_w - int(6 * sx)) / max(1, widest))
		text_h = int(label_base.get_height() * label_scale)
		label_gap = max(2, int(3 * sx))
		count_gap = max(1, int(sx))
		row_gap = max(8, int(22 * sx))
		row_step = slot_h + label_gap + 2 * text_h + count_gap + row_gap

		for i, (item, label, seed) in enumerate(quests):
			row, col = divmod(i, cols)
			rect = pygame.Rect(x0 + col * (slot_w + gap_x),
			                   y0 + row * row_step,
			                   slot_w, slot_h)
			self.slot_rects.append(rect)
			completed = self._quest_id(item) in self.player.completed_quests
			kind = 'quest_pressed' if completed else 'quest'
			hovered = rect.collidepoint(mouse_pos) or i == self.index
			img = self._button(kind, rect.size, bright=hovered)
			if img is not None:
				self.display_surface.blit(img, rect)
			else:
				pygame.draw.rect(self.display_surface, (220, 178, 128), rect,
				                 0, int(16 * sx))

			box = int(slot_h * 0.62)
			icon = self._icon(item, seed, box)
			if icon is not None:
				icon_rect = icon.get_rect(center=rect.center)
				self.display_surface.blit(icon, icon_rect)

			label_surf = self._text(label, 28, self.TEXT, label_scale)
			label_rect = label_surf.get_rect(
				midtop=(rect.centerx, rect.bottom + label_gap))
			self.display_surface.blit(label_surf, label_rect)

			if completed:
				status, color = 'DONE', (91, 140, 58)
			else:
				status = f'{self._have(item, seed)}/{QUEST_STACK}'
				color = self.TEXT
			status_surf = self._text(status, 28, color, label_scale)
			self.display_surface.blit(
				status_surf, status_surf.get_rect(
					midtop=(rect.centerx, label_rect.bottom + count_gap)))

		page_surf = self._text(
			f'{self.page + 1} / {len(TOWN_QUEST_PAGES)}', 28, self.TEXT)
		self.display_surface.blit(
			page_surf, page_surf.get_rect(
				midbottom=(panel.left + int(40 * sx),
				           panel.bottom - int(18 * sx))))

		if self._next_visible():
			btn_w = int(slot_w * 1.25)
			btn_h = int(btn_w * 31 / 96)
			self.next_rect = pygame.Rect(0, 0, btn_w, btn_h)
			self.next_rect.center = (panel.centerx,
			                         panel.bottom - int(44 * sx))
			hovered = self.next_rect.collidepoint(mouse_pos)
			self._draw_text_button(self.next_rect, 'NEXT', hovered)
		else:
			self.next_rect = pygame.Rect(0, 0, 0, 0)

	def _spawn_particles(self, center):
		self._particles = []
		now = pygame.time.get_ticks()
		scale = max(1.0, self.scale)
		colors = ((255, 226, 120), (255, 247, 200), (186, 230, 150))
		for i in range(22):
			angle = random.uniform(0, math.tau)
			speed = random.uniform(140, 520) * scale
			self._particles.append({
				'x': center[0],
				'y': center[1],
				'vx': math.cos(angle) * speed,
				'vy': math.sin(angle) * speed - 130 * scale,
				'born': now,
				'life': random.uniform(0.35, 0.6),
				'size': random.uniform(2, 5) * scale,
				'color': colors[i % len(colors)],
			})

	def _play_impact(self):
		if self._impact_sound is not None:
			try:
				self._impact_sound.play()
			except Exception as exc:  # missing/busy mixer; never break the quest UI
				log_once('[QuestMenu] impact sound failed', exc)

	def _draw_impact(self, sx, now, t):
		center = self.heart_rect.center
		alpha = int(210 * (1 - t))
		radius = int(self.heart_rect.w * (0.32 + 0.85 * t))
		width = max(2, int(9 * sx * (1 - t)))
		ring_size = max(4, radius * 2 + width * 2 + 4)
		ring = pygame.Surface((ring_size, ring_size), pygame.SRCALPHA)
		pygame.draw.circle(ring, (255, 226, 130, alpha),
		                   (ring_size // 2, ring_size // 2),
		                   radius, width)
		self.display_surface.blit(ring, ring.get_rect(center=center))

		for p in self._particles:
			age = max(0.0, (now - p['born']) / 1000)
			if age >= p['life']:
				continue
			fade = max(0.0, min(1.0, 1 - age / p['life']))
			x = p['x'] + p['vx'] * age
			y = p['y'] + p['vy'] * age + 700 * age * age
			r = max(1, int(p['size'] * fade))
			dot = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
			pygame.draw.circle(dot, (*p['color'], int(255 * fade)),
			                   (r, r), r)
			self.display_surface.blit(dot, dot.get_rect(center=(x, y)))

		if t < 0.45:
			flash = pygame.Surface(self.display_surface.get_size(),
			                       pygame.SRCALPHA)
			flash.fill((255, 255, 255, int(110 * (1 - t / 0.45))))
			self.display_surface.blit(flash, (0, 0))

	def _draw_heart(self, panel, sx, now):
		self.slot_rects = []
		self.next_rect = pygame.Rect(0, 0, 0, 0)
		self.heart_rect = pygame.Rect(
			panel.left + int(self.HEART_SRC.x * sx),
			panel.top + int(self.HEART_SRC.y * sx),
			max(1, int(self.HEART_SRC.w * sx)),
			max(1, int(self.HEART_SRC.h * sx)))

		placed = self._heart_done()
		owned = self._have(HEART_RECIPE, False) > 0
		hovered = self.heart_rect.collidepoint(pygame.mouse.get_pos())
		if not placed and owned and self.heart_icon is not None:
			alpha = 150 if hovered else int(50 + 18 * math.sin(now / 280))
			ghost = pygame.transform.smoothscale(
				self.heart_icon, self.heart_rect.size)
			ghost.set_alpha(max(30, min(200, alpha)))
			self.display_surface.blit(ghost, self.heart_rect)

		if not placed and self._drop_start is None:
			text = 'Check for new recipe in Crafting menu'
			width = self._font(28).size(text)[0]
			factor = min(1.0, (panel.w - int(60 * sx)) / max(1, width))
			text_surf = self._text(text, 28, self.TEXT, factor)
			text_rect = text_surf.get_rect(
				midtop=(panel.centerx, panel.top + int(378 * sx)))
			self.display_surface.blit(text_surf, text_rect)

			if owned:
				hint_surf = self._text(
					'Click the emblem to place it.', 28, (91, 140, 58))
				hint_rect = hint_surf.get_rect(
					midtop=(panel.centerx,
					        text_rect.bottom + max(4, int(8 * sx))))
				self.display_surface.blit(hint_surf, hint_rect)

		if self._drop_start is not None:
			elapsed = now - self._drop_start
			if elapsed >= self.DROP_MS:
				self._drop_start = None
				self._impact_start = now
				self._spawn_particles(self.heart_rect.center)
				self._play_impact()
			elif self.heart_icon is not None:
				t = elapsed / float(self.DROP_MS)
				ease = t * t * t
				factor = 2.15 + (1 - 2.15) * ease
				size = (max(1, int(self.heart_rect.w * factor)),
				        max(1, int(self.heart_rect.h * factor)))
				heart = pygame.transform.smoothscale(self.heart_icon, size)
				self.display_surface.blit(
					heart, heart.get_rect(center=self.heart_rect.center))

		if self._impact_start is not None:
			t = (now - self._impact_start) / float(self.FX_MS)
			if t >= 1:
				self._impact_start = None
				self._particles = []
			else:
				self._draw_impact(sx, now, t)

	def _draw_close(self, panel, sx):
		if self.close_normal is None or self._credits_locked():
			self.close_rect = pygame.Rect(0, 0, 0, 0)
			return
		size = (max(1, int(self.close_normal.get_width() * 1.8 * sx)),
		        max(1, int(self.close_normal.get_height() * 1.8 * sx)))
		normal = pygame.transform.scale(self.close_normal, size)
		hovered = pygame.transform.scale(self.close_hovered, size)
		self.close_rect = normal.get_rect(
			topright=(panel.right - int(23 * sx),
			          panel.top + int(20 * sx)))
		img = hovered if self.close_rect.collidepoint(pygame.mouse.get_pos()) \
			else normal
		self.display_surface.blit(img, self.close_rect)

	def _draw(self):
		sw, sh = self.display_surface.get_size()
		scale = max(0.55, min(sw * 0.74 / self.PANEL_W,
		                      sh * 0.84 / self.PANEL_H))
		sx = scale

		if self._overlay is None or self._overlay.get_size() != (sw, sh):
			self._overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
			self._overlay.fill((20, 15, 10, 170))
		self.display_surface.blit(self._overlay, (0, 0))

		panel = pygame.Rect(0, 0, int(self.PANEL_W * sx),
		                    int(self.PANEL_H * sx))
		panel.center = (sw // 2, sh // 2)
		sx = panel.w / float(self.PANEL_W)
		self.scale = sx
		now = pygame.time.get_ticks()
		heart_page = self._heart_page()

		if heart_page and self._impact_start is not None:
			shake_t = (now - self._impact_start) / 180.0
			if shake_t < 1:
				amp = (1 - shake_t) * 7 * sx
				panel = panel.move(int(math.sin(now * 0.09) * amp),
				                   int(math.cos(now * 0.13) * amp))

		dropping = (self._drop_start is not None
		            and now - self._drop_start < self.DROP_MS)
		art = self.panel
		if heart_page and self._heart_done() and not dropping:
			art = self.heart_after or self.panel
		elif heart_page:
			art = self.heart_panel or self.panel

		if art is not None:
			self.display_surface.blit(
				pygame.transform.scale(art, panel.size), panel)
		else:
			pygame.draw.rect(self.display_surface, (241, 212, 171), panel,
			                 0, int(14 * sx))
			pygame.draw.rect(self.display_surface, (203, 166, 123), panel,
			                 max(2, int(3 * sx)), int(14 * sx))

		if heart_page:
			self._draw_heart(panel, sx, now)
		else:
			self._draw_slots(panel, sx)
		self._draw_close(panel, sx)

		if self.error is not None:
			self._draw_error(sw, sh, sx)

	def _draw_error(self, sw, sh, sx):
		dim = pygame.Surface((sw, sh))
		dim.set_alpha(180)
		dim.fill('black')
		self.display_surface.blit(dim, (0, 0))

		title, detail = self.error
		title_width = self._font(36).size(title)[0]
		detail_width = self._font(30).size(detail)[0]
		title_factor = min(1.0, (sw * 0.8) / max(1, title_width))
		detail_factor = min(1.0, (sw * 0.8) / max(1, detail_width))
		title_surf = self._text(title, 36, 'White', title_factor)
		detail_surf = self._text(detail, 30, 'White', detail_factor)
		title_rect = title_surf.get_rect(center=(sw // 2, sh // 2 - 44))
		detail_rect = detail_surf.get_rect(center=(sw // 2, sh // 2 - 8))

		box_rect = title_rect.union(detail_rect).inflate(60, 50)
		pygame.draw.rect(self.display_surface, (40, 40, 40), box_rect, 0, 12)
		pygame.draw.rect(self.display_surface, (100, 100, 100), box_rect, 2, 12)

		self.display_surface.blit(title_surf, title_rect)
		self.display_surface.blit(detail_surf, detail_rect)

		ok_w = max(96, int(120 * sx))
		ok_h = max(31, int(ok_w * 31 / 96))
		self.ok_rect = pygame.Rect(0, 0, ok_w, ok_h)
		self.ok_rect.center = (sw // 2, box_rect.bottom + 40)
		hovered = self.ok_rect.collidepoint(pygame.mouse.get_pos())
		self._draw_text_button(self.ok_rect, 'OK', hovered)

	def update(self, events=None):
		if events is None:
			events = pygame.event.get()
		self._input(events)
		self._draw()
