import pygame
from settings import asset_path, ui_font, ui_scale

# Colors per message role.
COLORS = {
	'instruction': (86, 52, 24),
	'hint': (48, 92, 52),
	'error': (168, 34, 26),
}


class InstructionPanel:
	"""Top instruction bar, hidden by default.
	Three layers, highest first: toast (transient), hint (sticky),
	instruction (the tutorial step). The hint overrides the instruction.
	"""

	def __init__(self, display_surface):
		self.display_surface = display_surface
		self.font = ui_font(22)
		self.line_height = self.font.get_linesize()

		self.bg_raw = None
		try:
			self.bg_raw = pygame.image.load(
				asset_path('graphics', 'UI', 'Instruction_panel.png')
			).convert_alpha()
		except (pygame.error, FileNotFoundError):
			self.bg_raw = None

		self.instruction = None   # sticky tutorial step
		self.hint = None          # sticky contextual hint
		self.toast = None         # {'text', 'kind', 'remaining'}

		# geometry / animation: flush against the very top edge (no gap)
		scale = ui_scale()
		self.height = int(44 * scale)
		self.max_width_ratio = 0.52
		self.pad_x = int(28 * scale)
		self.pad_y = int(7 * scale)
		self.min_width = int(220 * scale)
		self._hidden_y = float(-(self.height + 20))
		self._shown_y = 0.0
		self._y = self._hidden_y
		self._target_y = self._hidden_y
		self._speed = 1600.0  # px / s

	# ------------------------------------------------------------------ API
	def set_instruction(self, text):
		"""Sticky tutorial step (None hides it)."""
		self.instruction = text or None

	def clear_instruction(self):
		self.instruction = None

	def set_hint(self, text):
		"""Sticky contextual hint (menus / interaction triggers). Overrides
		the tutorial instruction while set."""
		self.hint = text or None

	def clear_hint(self):
		self.hint = None

	def show_error(self, text, duration=3.0):
		"""Transient error toast (sound is played by the caller)."""
		self._set_toast(text, 'error', duration)

	def show_message(self, text, duration=6.0):
		"""Transient neutral toast (completion / info)."""
		self._set_toast(text, 'instruction', duration)

	def show_opening(self, text, duration=8.0):
		"""Neutral toast for the first thing a brand-new game has to say (the
		movement keys). Sticky: later neutral notes wait for it to fade, while
		errors still cut straight through.
		"""
		self._set_toast(text, 'instruction', duration, sticky=True)

	def clear(self):
		self.instruction = None
		self.hint = None
		self.toast = None

	def _set_toast(self, text, kind, duration, sticky=False):
		if not text:
			return
		# refresh an identical visible toast instead of stacking it
		if self.toast is not None and self.toast['text'] == text:
			self.toast['remaining'] = duration
			return
		# a sticky opening toast owns the bar until it expires
		if (self.toast is not None and self.toast.get('sticky')
			    and kind != 'error'):
			return
		self.toast = {
			'text': str(text),
			'kind': kind,
			'remaining': duration,
			'sticky': bool(sticky),
		}

	@property
	def opening_active(self):
		"""True while a sticky opening toast still owns the bar."""
		return bool(self.toast is not None and self.toast.get('sticky'))

	def _visible(self):
		# Highest layer wins: toast, then hint, then instruction.
		if self.toast is not None:
			return self.toast['text'], self.toast['kind']
		if self.hint is not None:
			return self.hint, 'hint'
		if self.instruction is not None:
			return self.instruction, 'instruction'
		return None, None

	# ------------------------------------------------------------------ loop
	def update(self, dt):
		# Count the toast down, then slide the panel toward its target.
		if self.toast is not None:
			self.toast['remaining'] -= dt
			if self.toast['remaining'] <= 0:
				self.toast = None

		text, _kind = self._visible()
		self._target_y = self._shown_y if text is not None else self._hidden_y
		delta = self._target_y - self._y
		step = self._speed * dt
		if abs(delta) <= step:
			self._y = self._target_y
		else:
			self._y += step if delta > 0 else -step

	def _wrap(self, text, max_width):
		# Greedy word wrap using the rendered text width.
		lines = []
		line = ''
		for word in text.split(' '):
			trial = word if not line else line + ' ' + word
			if not line or self.font.size(trial)[0] <= max_width:
				line = trial
			else:
				lines.append(line)
				line = word
		if line:
			lines.append(line)
		return lines or ['']

	def draw(self):
		text, kind = self._visible()
		if text is None:
			return
		sw, sh = self.display_surface.get_size()
		max_width = int(sw * self.max_width_ratio)

		# Size the panel to the text, then draw at the current slide position.
		lines = self._wrap(text, max_width - self.pad_x * 2)
		text_w = max(self.font.size(line)[0] for line in lines)
		panel_w = min(max_width, max(self.min_width, text_w + self.pad_x * 2))
		panel_h = self.line_height * len(lines) + self.pad_y * 2

		y = int(self._y)
		if y > sh:
			return

		if self.bg_raw:
			bg = pygame.transform.scale(self.bg_raw, (panel_w, panel_h))
		else:
			bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
			bg.fill((232, 207, 166, 240))
			pygame.draw.rect(bg, (144, 98, 93), bg.get_rect(), 2, 8)
		rect = bg.get_rect(midtop=(sw // 2, y))
		self.display_surface.blit(bg, rect)

		color = COLORS.get(kind, COLORS['instruction'])
		text_top = rect.top + self.pad_y
		for index, line in enumerate(lines):
			surf = self.font.render(line, False, color)
			self.display_surface.blit(
				surf, surf.get_rect(
					midtop=(rect.centerx,
					        text_top + index * self.line_height)))
