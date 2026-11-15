import os

import pygame
from settings import asset_path, app_version, ui_scale


class CreditsScreen:
	SCROLL_SPEED = 78
	START_DELAY = 0.5
	FINAL_FADE = 0.45
	HOLD_SECONDS = 3.0

	TEXT = (255, 245, 220)
	ACCENT = (255, 214, 122)
	TAGLINE = (255, 231, 159)
	OUTLINE = (38, 25, 16)

	INSPIRED_LOGOS = (
		'Minecraft.png',
		'Isocore.png',
		'Stardew Valley.png',
		'Mine Mogul.png',
	)

	def __init__(self, close_credits):
		self.display_surface = pygame.display.get_surface()
		self.close_credits = close_credits
		self.active = False
		self._font_cache = {}
		self._text_cache = {}
		self._tagline_cache = {}
		self._overlay = None
		self._layout_size = None
		self._content = None
		self._content_h = 0
		self._logo_center_y = 0
		self._phase = 'scroll'
		self._elapsed = 0.0
		self._final_elapsed = 0.0
		self._scroll_y = 0.0
		self._closed = False
		self._logo = self._load_logo()
		self._inspired = self._load_inspired()

	def _load_logo(self):
		try:
			return pygame.image.load(
				asset_path('graphics', 'world', 'logo.png')).convert_alpha()
		except (pygame.error, FileNotFoundError):
			return None

	def _load_inspired(self):
		logos = []
		for name in self.INSPIRED_LOGOS:
			try:
				surf = pygame.image.load(
					asset_path('graphics', 'world', name)).convert_alpha()
			except (pygame.error, FileNotFoundError):
				continue
			rect = surf.get_bounding_rect(10)
			if rect.w > 0 and rect.h > 0:
				surf = surf.subsurface(rect).copy()
			logos.append(surf)
		return logos

	def _scale(self):
		return max(0.55, ui_scale())

	def _font(self, size, bold=False):
		size = max(8, int(size))
		key = (size, bold)
		font = self._font_cache.get(key)
		if font is None:
			font = pygame.font.Font(
				asset_path('font', 'pixelFont-7-8x14-sproutLands.ttf'), size)
			font.set_bold(bold)
			self._font_cache[key] = font
		return font

	def _text(self, text, size, color, bold=False):
		key = (text, int(size), color, bold)
		surf = self._text_cache.get(key)
		if surf is None:
			surf = self._font(size, bold).render(text, False, color)
			self._text_cache[key] = surf
		return surf

	def _fit_text(self, text, size, color, max_width, bold=False):
		size = max(8, int(size))
		surf = self._text(text, size, color, bold)
		while surf.get_width() > max_width and size > 8:
			size -= 1
			surf = self._text(text, size, color, bold)
		return surf

	def _tagline_surface(self, text, size):
		pad = max(2, int(2 * self._scale()))
		key = (text, int(size), pad)
		surf = self._tagline_cache.get(key)
		if surf is not None:
			return surf
		font = self._font(size, True)
		fill = font.render(text, False, self.TAGLINE)
		outline = font.render(text, False, self.OUTLINE)
		surf = pygame.Surface(
			(fill.get_width() + pad * 2, fill.get_height() + pad * 2),
			pygame.SRCALPHA)
		for dx, dy in ((-pad, 0), (pad, 0), (0, -pad), (0, pad),
		               (-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad)):
			surf.blit(outline, (pad + dx, pad + dy))
		surf.blit(fill, (pad, pad))
		self._tagline_cache[key] = surf
		return surf

	def _build_layout(self):
		sw, sh = self.display_surface.get_size()
		scale = self._scale()
		content_w = max(280, min(int(sw * 0.84), int(880 * scale)))
		header_size = int(23 * scale)
		name_size = int(34 * scale)
		line_size = int(21 * scale)
		items = []
		cursor = 0
		self._logo_center_y = 0

		def add(surf, before=0, after=0):
			nonlocal cursor
			cursor += int(before)
			items.append((surf, cursor))
			cursor += surf.get_height() + int(after)

		logo_w = min(content_w, int(460 * scale))
		if self._logo is not None:
			logo_h = max(1, int(self._logo.get_height() * logo_w
			                   / self._logo.get_width()))
			logo = pygame.transform.smoothscale(self._logo, (logo_w, logo_h))
			add(logo, after=int(30 * scale))
			self._logo_center_y = logo_h // 2
		else:
			title = self._fit_text('PYDEW VALLEY', int(58 * scale), self.TEXT,
			                       content_w, bold=True)
			add(title, after=int(30 * scale))
			self._logo_center_y = title.get_height() // 2

		def header(text):
			add(self._fit_text(text, header_size, self.ACCENT, content_w,
			                   bold=True), before=int(12 * scale),
			    after=int(8 * scale))

		def name(text):
			add(self._fit_text(text, name_size, self.TEXT, content_w),
			    after=int(4 * scale))

		def line(text):
			add(self._fit_text(text, line_size, self.TEXT, content_w),
			    after=int(4 * scale))

		def divider():
			w = max(40, int(content_w * 0.45))
			h = max(2, int(2 * scale))
			bar = pygame.Surface((w, h), pygame.SRCALPHA)
			bar.fill((*self.ACCENT, 90))
			add(bar, before=int(15 * scale), after=int(10 * scale))

		def inspired_row():
			if not self._inspired:
				return
			gap = max(8, int(26 * scale))
			height = max(14, int(58 * scale))
			while height > 12:
				widths = [
					max(1, int(round(s.get_width() * height
					                 / max(1, s.get_height()))))
					for s in self._inspired
				]
				total = sum(widths) + gap * (len(widths) - 1)
				if total <= content_w:
					break
				height -= 2
			if total > content_w:
				factor = max(0.1, (content_w - gap * (len(widths) - 1))
				            / max(1, sum(widths)))
				widths = [max(1, int(round(w * factor))) for w in widths]
				total = sum(widths) + gap * (len(widths) - 1)
			row_h = max(
				max(1, int(round(s.get_height() * w / max(1, s.get_width()))))
				for s, w in zip(self._inspired, widths))
			row = pygame.Surface((total, row_h), pygame.SRCALPHA)
			x = 0
			for surf, width in zip(self._inspired, widths):
				logo_h = max(1, int(round(
					surf.get_height() * width / max(1, surf.get_width()))))
				logo = pygame.transform.smoothscale(surf, (width, logo_h))
				row.blit(logo, (x, (row_h - logo_h) // 2))
				x += width + gap
			add(row, before=int(8 * scale), after=int(12 * scale))

		header('CREATED BY')
		name('Purab H Patel')
		name('Adithya U Poojary')
		line('Version %s' % app_version())
		divider()
		header('BASED ON')
		line('"Creating a Stardew Valley-inspired game" — Clear Code')
		line('youtube.com/watch?v=T4IX36sP_0c')
		line('github.com/clear-code-projects/PyDew-Valley')
		line('The audio files and the starting TMX map come from there')
		divider()
		header('ART & UI')
		line('Cup Nooble — Sprout Lands Sprite / UI / Extra packs')
		line('Assets from Sprout Lands by Cup Nooble')
		line('pixelFont-7-8x14-sproutLands — Cup Nooble')
		line('Monocraft — interface font (Idrees Inc, OFL)')
		divider()
		header('MUSIC')
		# Only credit the tracks that are actually installed, so the
		# screen never names a track the build does not contain.
		for label, parts in (
			('Music by Yoiyami (CC0)', ('audio', 'Title_background.wav')),
			('"8bit attempt" — Daniel Stephens', ('audio', 'music.mp3')),
			('Menu track — see THIRD_PARTY_NOTICES.txt', ('audio', 'menu.mp3')),
		):
			if os.path.exists(asset_path(*parts)):
				line(label)
		divider()
		header('TOOLS')
		line('PyCharm')
		line('Aseprite')
		line('Tiled')
		divider()
		header('BUILT WITH')
		line('Python')
		line('Pygame')
		line('pytmx')
		line('NumPy')
		line('OpenCV')
		divider()
		header('INSPIRED BY')
		inspired_row()

		content_h = cursor + int(36 * scale)
		content = pygame.Surface((content_w, content_h), pygame.SRCALPHA)
		for surf, y in items:
			content.blit(surf, (content_w // 2 - surf.get_width() // 2, y))
		self._content = content
		self._content_h = content_h
		self._layout_size = (sw, sh)

	def _ensure_layout(self):
		if self._layout_size != self.display_surface.get_size():
			self._build_layout()

	def open(self):
		self._ensure_layout()
		sw, sh = self.display_surface.get_size()
		self._phase = 'scroll'
		self._elapsed = 0.0
		self._final_elapsed = 0.0
		self._scroll_y = sh * 0.40 - self._logo_center_y
		self._closed = False
		self.active = True

	def _close(self):
		if self._closed:
			return
		self._closed = True
		self.active = False
		if self.close_credits is not None:
			self.close_credits()

	def _input(self, events):
		for event in events:
			if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
				self._close()
				return

	def _advance(self, dt):
		scale = self._scale()
		if self._phase == 'scroll':
			self._elapsed += dt
			if self._elapsed >= self.START_DELAY:
				self._scroll_y -= self.SCROLL_SPEED * scale * dt
			end_y = -self._content_h - int(20 * scale)
			if self._scroll_y <= end_y:
				self._scroll_y = end_y
				self._phase = 'final'
				self._final_elapsed = 0.0
		else:
			self._final_elapsed += dt
			if self._final_elapsed >= self.FINAL_FADE + self.HOLD_SECONDS:
				self._close()

	def _draw_overlay(self, sw, sh):
		if self._overlay is None or self._overlay.get_size() != (sw, sh):
			self._overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
			self._overlay.fill((12, 9, 6, 225))
		self.display_surface.blit(self._overlay, (0, 0))

	def _draw_scroll(self, sw):
		x = sw // 2 - self._content.get_width() // 2
		self.display_surface.blit(self._content, (x, int(self._scroll_y)))

	def _draw_final(self, sw, sh):
		scale = self._scale()
		thanks = self._fit_text('Thanks for playing.', int(32 * scale),
		                        self.TEXT, int(sw * 0.80))
		tag_size = int(62 * scale)
		tag = self._tagline_surface('Explore beyond the Limits!', tag_size)
		max_tag_w = int(sw * 0.90)
		if tag.get_width() > max_tag_w:
			tag_size = max(8, int(tag_size * max_tag_w / tag.get_width()))
			tag = self._tagline_surface('Explore beyond the Limits!', tag_size)
		gap = int(30 * scale)
		group_h = thanks.get_height() + gap + tag.get_height()
		card = pygame.Surface((sw, group_h), pygame.SRCALPHA)
		card.blit(thanks, thanks.get_rect(midtop=(sw // 2, 0)))
		card.blit(tag, tag.get_rect(
			midtop=(sw // 2, thanks.get_height() + gap)))
		alpha = int(255 * min(1.0, self._final_elapsed / self.FINAL_FADE))
		card.set_alpha(alpha)
		top = max(int(sh * 0.12), (sh - group_h) // 2)
		self.display_surface.blit(card, (0, top))

	def _draw(self):
		sw, sh = self.display_surface.get_size()
		self._draw_overlay(sw, sh)
		if self._phase == 'scroll':
			self._draw_scroll(sw)
		else:
			self._draw_final(sw, sh)

	def update(self, events, dt):
		if not self.active:
			return
		self._input(events)
		if not self.active:
			return
		self._advance(dt)
		if not self.active:
			return
		self._draw()
