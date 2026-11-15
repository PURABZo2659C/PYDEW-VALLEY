import os
import pygame
from settings import *
from support import import_folder
from sprites import Generic
from random import randint, choice

NIGHT_COLOR = (38, 101, 189)
DAY_COLOR = (255, 255, 255)

SEASON_TINTS = {
	0: (1.0, 1.0, 1.0),
	1: (1.0, 0.92, 0.82),
	2: (0.88, 0.82, 0.70),
	3: (0.82, 0.88, 1.0),
}

def lerp_color(a, b, t):
	t = max(0.0, min(1.0, t))
	return (
		int(a[0] + (b[0] - a[0]) * t),
		int(a[1] + (b[1] - a[1]) * t),
		int(a[2] + (b[2] - a[2]) * t),
	)

def get_sky_color(hour, minute):
	h = hour + minute / 60.0

	if 7 <= h < 17:
		return DAY_COLOR
	elif 17 <= h < 20:
		t = (h - 17) / 3.0
		return lerp_color(DAY_COLOR, NIGHT_COLOR, t)
	elif 5 <= h < 7:
		t = (h - 5) / 2.0
		return lerp_color(NIGHT_COLOR, DAY_COLOR, t)
	else:
		return NIGHT_COLOR

class Sky:
	def __init__(self, time_manager=None):
		self.display_surface = pygame.display.get_surface()
		self.full_surf = pygame.Surface(self.display_surface.get_size())
		self.start_color = list(DAY_COLOR)
		self.night = False
		self.time_manager = time_manager
		self._vision_patch = None
		self._vision_key = None

	def _get_vision_patch(self, base_color):
		radius = NIGHT_VISION_RADIUS
		key = (tuple(base_color), radius)
		if self._vision_key == key:
			return self._vision_patch
		patch = pygame.Surface((radius * 2, radius * 2))
		patch.fill(tuple(base_color))
		steps = 28
		for i in range(steps, 0, -1):
			t = i / steps
			amount = 1 - (i - 1) / max(1, steps - 1)
			color = lerp_color(base_color, (255, 255, 255), amount)
			pygame.draw.circle(
				patch, color, (radius, radius),
				max(1, int(radius * t)))
		self._vision_patch = patch
		self._vision_key = key
		return patch

	def display(self, dt, vision_center=None):
		sw, sh = self.display_surface.get_size()
		if not hasattr(self, 'full_surf') or self.full_surf.get_size() != (sw, sh):
			self.full_surf = pygame.Surface((sw, sh))

		if self.time_manager:
			target = get_sky_color(self.time_manager.hour, self.time_manager.minute)
			self.night = self.time_manager.is_night()
		else:
			target = DAY_COLOR

		for i in range(3):
			diff = target[i] - self.start_color[i]
			if abs(diff) < 3:
				self.start_color[i] = target[i]
			else:
				self.start_color[i] += diff * min(1.0, dt * 3)

		base_color = list(self.start_color)

		if self.time_manager:
			tint = SEASON_TINTS.get(self.time_manager.season_index, (1.0, 1.0, 1.0))
			base_color[0] = int(base_color[0] * tint[0])
			base_color[1] = int(base_color[1] * tint[1])
			base_color[2] = int(base_color[2] * tint[2])

		# A white grade is an identity multiply: skipping it leaves the
		# framebuffer untouched and saves a full-screen blit each frame.
		if tuple(base_color) == (255, 255, 255):
			return

		self.full_surf.fill(tuple(base_color))
		if vision_center is not None:
			patch = self._get_vision_patch(base_color)
			self.full_surf.blit(
				patch, patch.get_rect(center=vision_center))
		self.display_surface.blit(self.full_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

class Drop(Generic):
	def __init__(self, surf, pos, moving, groups, z,
			direction=(0.9, 1.1), speed_range=(700, 900),
			lifetime_range=(400, 500)):
		super().__init__(pos, surf, groups, z)
		self.lifetime = randint(*lifetime_range)
		self.start_time = pygame.time.get_ticks()
		self.moving = moving
		if self.moving:
			self.pos = pygame.math.Vector2(self.rect.topleft)
			self.direction = pygame.math.Vector2(*direction)
			self.speed = randint(*speed_range)

	def update(self, dt):
		if self.moving:
			self.pos += self.direction * self.speed * dt
			self.rect.topleft = (round(self.pos.x), round(self.pos.y))
		if pygame.time.get_ticks() - self.start_time >= self.lifetime:
			self.kill()

def _camera_spawn_pos(all_sprites):
	"""World-pixel point that projects onto the visible screen.
	The world is infinite, so a random screen point is inverted through the
	isometric projection instead of using a fixed box.
	"""
	cam = all_sprites
	cam_x = getattr(cam, 'cam_x', 0)
	cam_y = getattr(cam, 'cam_y', 0)
	surface = pygame.display.get_surface()
	sw = getattr(cam, 'screen_w', surface.get_width())
	sh = getattr(cam, 'screen_h', surface.get_height())
	if getattr(cam, 'isometric_mode', True):
		sx = randint(-100, sw + 100)
		sy = randint(-100, sh + 100)
		scr_x = sx + cam_x
		scr_y = sy + cam_y
		# Inverse of custom_draw's iso mapping:
		#   scr_x = (px - py) * 64 + 64,  scr_y = (px + py) * 32
		u = (scr_x - 64) / 64.0
		v = scr_y / 32.0
		px = (u + v) / 2.0
		py = (v - u) / 2.0
		return (px * 128, py * 128)
	return (cam_x + randint(-100, sw + 100),
			cam_y + randint(-100, sh + 100))

class Rain:
	def __init__(self, all_sprites):
		self.all_sprites = all_sprites
		self.rain_drops = import_folder(asset_path('graphics', 'rain', 'drops'))
		self.rain_floor = import_folder(asset_path('graphics', 'rain', 'floor'))

	def _spawn_pos(self):
		return _camera_spawn_pos(self.all_sprites)

	def create_floor(self):
		if not self.rain_floor:
			return
		Drop(
			surf=choice(self.rain_floor),
			pos=self._spawn_pos(),
			moving=False,
			groups=self.all_sprites,
			z=LAYERS['rain floor'])

	def create_drops(self):
		if not self.rain_drops:
			return
		Drop(
			surf=choice(self.rain_drops),
			pos=self._spawn_pos(),
			moving=True,
			groups=self.all_sprites,
			z=LAYERS['rain drops'])

	def update(self):
		self.create_floor()
		self.create_drops()

class Snow:
	"""Permanent snowfall for the snowy biome.
	Flakes spawn camera-relative so they always fill the screen, but fall
	slowly with a gentle leftward drift.
	"""

	def __init__(self, all_sprites, spawn_interval=0.05):
		self.all_sprites = all_sprites
		self.display_surface = pygame.display.get_surface()
		self.spawn_interval = spawn_interval
		self._spawn_timer = 0.0
		self._flakes = []
		self.frames = []
		path = asset_path('graphics', 'rain', 'snowflakes.png')
		if os.path.exists(path):
			sheet = pygame.image.load(path).convert_alpha()
			cell = 32
			cols = max(1, sheet.get_width() // cell)
			rows = max(1, sheet.get_height() // cell)
			for r in range(rows):
				for c in range(cols):
					frame = sheet.subsurface((c * cell, r * cell, cell, cell))
					self.frames.append(frame.copy())
		if not self.frames:
			flake = pygame.Surface((6, 6), pygame.SRCALPHA)
			pygame.draw.circle(flake, (255, 255, 255), (3, 3), 3)
			self.frames.append(flake)

	def _screen_pos(self, rect):
		cam = self.all_sprites
		cam_x = getattr(cam, 'cam_x', 0)
		cam_y = getattr(cam, 'cam_y', 0)
		if getattr(cam, 'isometric_mode', True):
			sx = (rect.centerx - rect.centery) / 2.0 + 64 - cam_x
			sy = (rect.centerx + rect.centery) / 4.0 - cam_y
		else:
			sx = rect.centerx - cam_x
			sy = rect.centery - cam_y
		return sx, sy

	def update(self, dt=1 / 60, spawning=True):
		cam = self.all_sprites
		sw = getattr(cam, 'screen_w', self.display_surface.get_width())
		sh = getattr(cam, 'screen_h', self.display_surface.get_height())
		# kill flakes that aged out or left the padded view (authoritative
		# even if the wall-clock lifetime and dt ever disagree)
		kept = []
		for f in self._flakes:
			if not f.alive():
				continue
			sx, sy = self._screen_pos(f.rect)
			if -150 <= sx <= sw + 150 and -150 <= sy <= sh + 150:
				kept.append(f)
			else:
				f.kill()
		self._flakes = kept

		if not spawning:
			return
		self._spawn_timer += dt
		if self._spawn_timer < self.spawn_interval:
			return
		self._spawn_timer = 0.0
		is_iso = getattr(cam, 'isometric_mode', True)
		# World motion projecting to a gentle leftward drift + slow fall:
		#   screen_vx = (vx - vy) / 2,  screen_vy = (vx + vy) / 4
		direction = (randint(60, 90) / 100.0, randint(90, 115) / 100.0)
		speed = randint(180, 260)
		if is_iso:
			screen_vx = (direction[0] - direction[1]) * speed / 2.0
			screen_vy = (direction[0] + direction[1]) * speed / 4.0
		else:
			screen_vx = direction[0] * speed
			screen_vy = direction[1] * speed
		pos = _camera_spawn_pos(cam)
		# spawn point in screen space (Drop rect is topleft=pos, 32x32)
		if is_iso:
			ssx = ((pos[0] + 16 - pos[1] - 16) / 2.0) + 64 - getattr(cam, 'cam_x', 0)
			ssy = ((pos[0] + 16 + pos[1] + 16) / 4.0) - getattr(cam, 'cam_y', 0)
		else:
			ssx = pos[0] + 16 - getattr(cam, 'cam_x', 0)
			ssy = pos[1] + 16 - getattr(cam, 'cam_y', 0)
		# live only until the flake would leave the (padded) screen box
		t_bottom = ((sh + 150) - ssy) / max(screen_vy, 1.0)
		if screen_vx < 0:
			t_side = (ssx + 150) / max(-screen_vx, 1.0)
		else:
			t_side = ((sw + 150) - ssx) / max(screen_vx, 1.0)
		lifetime = max(500, int(min(t_bottom, t_side) * 1000))
		flake = Drop(
			surf=choice(self.frames),
			pos=pos,
			moving=True,
			groups=self.all_sprites,
			z=LAYERS['rain drops'],
			direction=direction,
			speed_range=(speed, speed),
			lifetime_range=(lifetime, lifetime),
		)
		self._flakes.append(flake)
