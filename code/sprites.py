import math
import pygame
from settings import *
from random import randint, choice, random
from timer import Timer
from support import (
	visible_bottom_pad, play_click, play_error, iso_base_anchor, load_overlay_icons,
	load_sound as _load_sound_file,
)

# Shared decoded sounds: decoding per placement was a profiled hot spot.
_sound_cache = {}

def load_sound(name):
	snd = _sound_cache.get(name)
	if snd is None:
		snd = _load_sound_file(asset_path('audio', name))
		_sound_cache[name] = snd
	return snd


def can_store(player_add, items):
	"""True when every (item, count) pair still fits in the player's bag.
	Keeps a full bag from swallowing the source: a tree, rock, crop or bush
	stays standing until there is room for its loot.
	"""
	level = getattr(player_add, '__self__', None)
	if level is None or not hasattr(level, 'inventory_is_full'):
		return True
	for item, count in items:
		if item and count and count > 0 and level.inventory_is_full(item, count):
			return False
	return True


def notify_inventory_full(player_add):
	"""Show the 'Inventory Full!' popup for a sprite whose loot did not fit."""
	level = getattr(player_add, '__self__', None)
	if level is not None and hasattr(level, 'show_inventory_full'):
		level.show_inventory_full()


def teardown_solid(sprite):
	"""Detach a broken prop from every group and clear its collision box.
	Guarantees the sprite is gone from collision_sprites and that the
	leftover zero-sized hitbox can never overlap the player.
	"""
	# Iterate a copy: remove() mutates the group's list as we walk it.
	for group in list(sprite.groups()):
		group.remove(sprite)
	# Zero the hitbox so even a stale reference can never collide.
	sprite.hitbox = pygame.Rect(0, 0, 0, 0)
	sprite.alive = False
	# No-op now but kept so any future group still gets cleaned up.
	sprite.kill()

class Generic(pygame.sprite.Sprite):
	def __init__(self, pos, surf, groups, z = LAYERS['main']):
		super().__init__(groups)
		self.image = surf
		self.rect = self.image.get_rect(topleft = pos)
		self.z = z
		self.hitbox = self.rect.copy().inflate(-self.rect.width * 0.2, -self.rect.height * 0.75)
		# Flat world: sprites sit on the ground plane; kept for depth-sort.
		self.level = 0
		# Sole padding: the renderer lifts by this to seat art on the tile.
		self.foot_pad = 0

	def _rebuild_hitbox(self):
		self.hitbox = self.rect.copy().inflate(-self.rect.width * 0.2, -self.rect.height * 0.75)

class Interaction(Generic):
	def __init__(self, pos, size, groups, name):
		surf = pygame.Surface(size)
		super().__init__(pos, surf, groups)
		self.name = name

class WaterCollider(pygame.sprite.Sprite):
	"""Invisible water wall used by the chunk ring.
	Water tiles never draw a sprite, so this keeps only what collision
	reads: a rect/hitbox in the collision group.
	"""

	def __init__(self, rect, groups):
		super().__init__(groups)
		self.rect = rect
		self.hitbox = rect.copy()
		self.z = LAYERS['water']
		self._is_water_collider = True
		self.alive = True


class Water(Generic):
	def __init__(self, pos, frames, groups):

		#animation setup
		self.frames = frames
		self.frame_index = 0

		# sprite setup
		super().__init__(
				pos = pos, 
				surf = self.frames[self.frame_index], 
				groups = groups, 
				z = LAYERS['water']) 
		# Hitbox covers the water tile's world position for collision
		self.rect = self.image.get_rect(center = (pos[0], pos[1]))
		self.hitbox = self.rect.copy()

	def animate(self,dt):
		self.frame_index += 5 * dt
		if self.frame_index >= len(self.frames):
			self.frame_index = 0
		self.image = self.frames[int(self.frame_index)]

	def update(self,dt):
		self.animate(dt)

class WildFlower(Generic):
	def __init__(self, pos, surf, groups, collision_group=None, player_add=None, item='flower'):
		super().__init__(pos, surf, groups)
		self.rect = self.image.get_rect(center = pos)
		self.hitbox = self.rect.copy().inflate(-self.rect.width * 0.5, -self.rect.height * 0.6)
		self.collision_group = collision_group
		self.player_add = player_add
		self.item = item
		self.broken = False

	def damage(self, amount = 1):
		if not self.broken:
			# A full bag leaves the flower standing until its loot fits.
			if self.player_add and not can_store(
					self.player_add, [(self.item, 1)]):
				play_error()
				play_error(); notify_inventory_full(self.player_add)
				return
			self.broken = True
			if self.player_add:
				self.player_add(self.item)
			# Detach from every group; the flower no longer blocks movement.
			teardown_solid(self)

class Particle(Generic):
	def __init__(self, pos, surf, groups, z, duration = 200, source = None):
		super().__init__(pos, surf, groups, z)
		self.start_time = pygame.time.get_ticks()
		self.duration = duration

		# white surface 
		mask_surf = pygame.mask.from_surface(self.image)
		new_surf = mask_surf.to_surface()
		new_surf.set_colorkey((0,0,0))
		self.image = new_surf
		if source is not None:
			self._match_rendering(source)

	def _match_rendering(self, source):
		"""Draw this flash exactly where `source` stands.
		The painter places sprites from more than the topleft, so the source's
		render identity and rect are copied to land on the same pixels.
		"""
		self.rect = pygame.Rect(source.rect)
		self.level = getattr(source, 'level', 0)
		self.render_as_ground = getattr(source, 'render_as_ground', False)
		self.iso_anchor = getattr(source, 'iso_anchor', 'bottom')
		for attr in ('anchor_px', 'y_anchor_offset'):
			value = getattr(source, attr, None)
			if value is not None:
				setattr(self, attr, value)
		self.foot_pad = getattr(source, 'foot_pad', 0)

	def update(self,dt):
		current_time = pygame.time.get_ticks()
		if current_time - self.start_time > self.duration:
			self.kill()


def _drawable_group(sprite):
	"""The group level.custom_draw actually draws from (a CameraGroup).
	Registration order is not stable, so groups()[0] is often the collision
	group and a flash added there is never drawn.
	"""
	for group in sprite.groups():
		if callable(getattr(group, 'custom_draw', None)):
			return group
	return sprite.groups()[0] if sprite.groups() else []


def break_flash(sprite, z = LAYERS['fruit'], duration = 200, groups = None):
	"""White silhouette burst for a prop being chipped or broken.
	Drawn with the sprite's own render identity, so it sits on the prop, and
	added to the group the painter reads, so it is drawn at all.
	"""
	if groups is None:
		groups = _drawable_group(sprite)
	return Particle(
		pos = sprite.rect.topleft,
		surf = sprite.image,
		groups = groups,
		z = z,
		duration = duration,
		source = sprite)

class DroppedItem(Generic):
	"""An item lying on the ground after Q (or an overflowing bag) let it go.
	It flies a short way in the facing direction, then floats until the bag
	has room. The lifetime is the FARMLAND clock.
	"""

	FLY_SPEED = 260.0       # px/s while it travels to its resting spot
	PICKUP_DELAY = 1.2      # seconds hands-off right after the throw
	BOB_LIFT = 7            # px the icon floats above its rest line

	def __init__(self, pos, item, count, groups, level_ref, throw=None):
		self.item = item
		self.count = int(count)
		self.level_ref = level_ref
		icon = load_overlay_icons([item]).get(item)
		if icon is None:
			icon = pygame.Surface((24, 24), pygame.SRCALPHA)
			pygame.draw.rect(icon, (180, 140, 80), icon.get_rect(), 0, 4)
		icon = pygame.transform.scale(icon, (28, 28))
		self.foot_pad = 0
		self.iso_anchor = 'center'
		jitter = (randint(-14, 14), randint(-10, 10))
		rest = (pos[0] + jitter[0], pos[1] + jitter[1])
		if throw:
			rest = (rest[0] + float(throw[0]), rest[1] + float(throw[1]))
			start = (pos[0] + jitter[0] // 2, pos[1] + jitter[1] // 2)
		else:
			start = rest
		super().__init__(
			pos=(start[0] - 14, start[1] - 14),
			surf=icon, groups=groups, z=LAYERS['main'])
		self.rect = self.image.get_rect(center=start)
		self.hitbox = self.rect.copy()
		self.mask = pygame.mask.from_surface(self.image)
		self.rest_pos = pygame.math.Vector2(rest)
		self._flying = bool(throw)
		self._phase = random() * math.tau
		self._age = 0.0
		self.y_anchor_offset = 0
		self._full_warned = 0
		# Game-clock expiry: a clock-less caller never expires.
		clock = getattr(level_ref, 'time_manager', None)
		self.dropped_at = (float(clock.total_minutes)
		                   if clock is not None else None)

	def _expire_check(self):
		if self.dropped_at is None:
			return False
		clock = getattr(self.level_ref, 'time_manager', None)
		if clock is None:
			return False
		return (float(clock.total_minutes) - self.dropped_at
		        >= FARMLAND_EMPTY_MINUTES)

	def _fly(self, dt):
		"""Travel from the throw to the resting spot."""
		if not self._flying:
			return
		delta = self.rest_pos - pygame.math.Vector2(self.rect.center)
		step = self.FLY_SPEED * max(0.0, float(dt))
		if delta.length() <= step:
			self.rect.center = (round(self.rest_pos.x),
			                    round(self.rest_pos.y))
			self._flying = False
		else:
			delta.scale_to_length(step)
			self.rect.center = (round(self.rect.centerx + delta.x),
			                    round(self.rect.centery + delta.y))
		self.hitbox = self.rect.copy()

	def update(self, dt):
		if self._expire_check():
			self.kill()
			return
		dt = max(0.0, float(dt))
		self._age += dt
		self._fly(dt)
		# Slow bob, phase-shifted per drop so piles never bob in lockstep.
		self._phase += dt * 3.0
		self.y_anchor_offset = -int(round(
			self.BOB_LIFT * 0.5 * (1.0 + math.sin(self._phase))))
		if self._age < self.PICKUP_DELAY:
			return
		now = pygame.time.get_ticks()
		player = getattr(self.level_ref, 'player', None)
		if player is None:
			return
		# Fast rect reject, then pixel-precise overlap for small items.
		if not player.hitbox.colliderect(self.rect):
			return
		player_mask = pygame.mask.from_surface(player.image)
		# overlap()'s offset: the other mask's origin relative to this one.
		offset = (player.rect.x - self.rect.x,
		          player.rect.y - self.rect.y)
		if not self.mask.overlap(player_mask, offset):
			return
		# A full inventory leaves the drop where it lies (Q's rule).
		remaining = player.add_loot(self.item, self.count)
		picked = self.count - remaining
		if picked > 0:
			play_click()
			self.count = remaining
		if remaining > 0 and now - self._full_warned > 1600:
			self._full_warned = now
			level = getattr(self, 'level_ref', None)
			if level is not None and hasattr(level, 'show_inventory_full'):
				level.show_inventory_full()
		if self.count <= 0:
			self.kill()

class Tree(Generic):
	def __init__(self, pos, surf, groups, player_add, is_apple_tree=False,
			health = 8, foot_pad = 24, wood_yield = 1, iso_anchor = 'bottom',
			wood_item = 'wood', fruit_item = 'apple', tree_id = None,
			sapling_item = None, on_removed = None):
		super().__init__(pos, surf, groups)
		self.rect = self.image.get_rect(center = pos)

		# Trunk hitbox: proportional so it stays correct if art changes.
		trunk_w = max(30, int(self.rect.width * 0.50))
		trunk_h = max(20, int(self.rect.height * 0.18))
		self.hitbox = self.rect.copy().inflate(
			trunk_w - self.rect.width,
			trunk_h - self.rect.height,
		)
		# Trees default to a 24px lift; stumps/logs pass visible_bottom_pad.
		self.foot_pad = foot_pad
		# 'bottom' = art bottom, 'center' = image center on the tile center.
		self.iso_anchor = iso_anchor

		# tree attributes
		self.health = health
		self.alive = True
		self.is_apple_tree = is_apple_tree
		if isinstance(wood_yield, (tuple, list)):
			low, high = wood_yield
			self.wood_drop = (max(0, int(low)), max(0, int(high)))
		else:
			self.wood_drop = (max(0, int(wood_yield)), max(0, int(wood_yield)))
		self.wood_yield = wood_yield
		self.wood_item = wood_item
		self.fruit_item = fruit_item
		self.sapling_item = sapling_item
		# Stable chunk id: felled trees stay gone across chunk reloads.
		self.tree_id = tree_id
		self.on_removed = on_removed

		self.player_add = player_add

		# sounds (cached module-level, see load_sound)
		self.axe_sound = load_sound('axe.mp3')

	def drop_items(self):
		"""[(item, count), ...] this tree yields when it is felled."""
		low, high = self.wood_drop
		items = [(self.wood_item, randint(low, high))]
		if self.is_apple_tree:
			items.append((self.fruit_item,
			              randint(APPLE_DROP_MIN, APPLE_DROP_MAX)))
		if self.sapling_item:
			items.append((self.sapling_item, 1))
		return items

	def damage(self, amount = 1):

		# damaging the tree
		self.health -= amount

		# play sound
		self.axe_sound.play()

		# Felled immediately, not on the next update() frame.
		self.check_death()

	def check_death(self):
		if self.health <= 0:
			items = self.drop_items()
			if not can_store(self.player_add, items):
				# Full bag: the tree stays standing until its loot fits.
				self.health = 1
				play_error(); notify_inventory_full(self.player_add)
				return
			break_flash(self, duration = 300)
			for item, count in items:
				for _ in range(count):
					self.player_add(item)
			if self.on_removed:
				self.on_removed(self.tree_id)
			# Clear collision so the felled tree no longer blocks movement.
			teardown_solid(self)

	def update(self,dt):
		if self.alive:
			self.check_death()

class GrowingTree(Generic):
	"""A planted sapling that swaps through its species' growth art.
	Each stage gets an equal slice of the growth time. Once grown, Level
	replaces this sprite with a regular Tree (solid, choppable).
	"""
	def __init__(self, pos, frames, groups, level_ref, record,
			elapsed = 0.0):
		self.frames = list(frames)
		super().__init__(pos, self.frames[0], groups, z = LAYERS['main'])
		self.base_pos = (pos[0], pos[1])
		self.level_ref = level_ref
		self.record = record
		self.duration = max(0.001, float(TREE_GROWTH_MINUTES))
		self.elapsed = max(0.0, min(float(elapsed), self.duration))
		self.last_minutes = self._now_minutes()
		self.rect = self.image.get_rect(center = self.base_pos)
		self.foot_pad = 24
		self.record['elapsed_minutes'] = self.elapsed
		self._apply_frame()

	def _now_minutes(self):
		time_manager = getattr(self.level_ref, 'time_manager', None)
		return float(getattr(time_manager, 'total_minutes',
		                     getattr(self, 'last_minutes', 0.0)))

	def _apply_frame(self):
		p = max(0.0, min(1.0, self.elapsed / self.duration))
		index = min(len(self.frames) - 1, int(p * len(self.frames)))
		surf = self.frames[index]
		if surf is None:
			return
		self.image = surf
		self.rect = self.image.get_rect(center = self.base_pos)
		self.foot_pad = 24

	def update(self,dt):
		now = self._now_minutes()
		if now > self.last_minutes:
			self.elapsed = min(
				self.duration, self.elapsed + (now - self.last_minutes))
			self.last_minutes = now
			self.record['elapsed_minutes'] = self.elapsed

		if self.elapsed >= self.duration:
			self._apply_frame()
			# Don't turn solid while the player stands on the tile.
			gx = int(self.base_pos[0]) // TILE_SIZE
			gy = int(self.base_pos[1]) // TILE_SIZE
			tile = pygame.Rect(gx * TILE_SIZE, gy * TILE_SIZE,
			                   TILE_SIZE, TILE_SIZE)
			if not self.level_ref.player.hitbox.colliderect(tile):
				self.level_ref.finish_growing_tree(self)
			return
		self._apply_frame()

class Rock(Generic):
	def __init__(self, pos, surf, groups, player_add, health = 6,
			drop_item = 'rock', rock_id = None, on_removed = None):
		super().__init__(pos, surf, groups)
		self.rect = self.image.get_rect(center = pos)
		self._rebuild_hitbox()
		self.foot_pad = 24
		self.health = health
		self.alive = True
		self.player_add = player_add
		self.drop_item = drop_item
		# Stable id keeps mined rocks gone; cave ores leave None (reroll).
		self.rock_id = rock_id
		self.on_removed = on_removed
		self.rock_sound = load_sound('axe.mp3')

	def damage(self, amount = 1):
		self.health -= amount
		self.rock_sound.play()
		break_flash(self)
		if self.health <= 0:
			items = self.drop_items()
			if not can_store(self.player_add, items):
				# Full bag: the rock stays until its loot fits.
				self.health = 1
				play_error(); notify_inventory_full(self.player_add)
				return
			self.alive = False
			self.break_drop(items)
			if self.on_removed:
				self.on_removed(self.rock_id)
			# Clear collision so the mined rock no longer blocks movement.
			teardown_solid(self)

	def drop_items(self):
		"""[(item, count), ...] this rock yields when it is mined."""
		return [(self.drop_item, 1)]

	def break_drop(self, items = None):
		if items is None:
			items = self.drop_items()
		for item, count in items:
			for _ in range(count):
				self.player_add(item)

	def update(self, dt):
		pass

class Ore(Rock):
	"""Cave ore vein: a rock that yields its ore item, tougher deposits
	may drop a small pile (1-2) of their item at once."""
	def __init__(self, pos, surf, groups, player_add, item, health = 6, drop = (1, 1)):
		super().__init__(pos, surf, groups, player_add, health = health, drop_item = item)
		self.drop = drop

	def drop_items(self):
		return [(self.drop_item, randint(self.drop[0], self.drop[1]))]

	def break_drop(self, items = None):
		super().break_drop(items)

class Crate(Generic):
	"""Cave crate / shelf: solid scenery the axe cuts apart. Always drops the
	oak wood item; loaded crates and shelves also roll a small chance for a
	random ore. `allowed_tools` keeps the pickaxe and bare fists off.
	"""
	allowed_tools = ('axe',)

	def __init__(self, pos, surf, groups, player_add, health = 3, loaded = False):
		super().__init__(pos, surf, groups, z = LAYERS['main'])
		self.rect = self.image.get_rect(center = pos)
		self._rebuild_hitbox()
		anchor = iso_base_anchor(surf)
		if anchor is not None:
			# Pin the base diamond center to the tile ('pixel' mode).
			self.iso_anchor = 'pixel'
			self.anchor_px = anchor
			self.foot_pad = surf.get_height() - anchor[1]
		else:
			self.foot_pad = visible_bottom_pad(surf) + TILE_SIZE // 16
		self.health = health
		self.alive = True
		self.player_add = player_add
		self.loaded = loaded
		self.hit_sound = load_sound('axe.mp3')

	def _play_hit(self):
		self.hit_sound.play()

	def damage(self, amount = 1):
		self.health -= amount
		self._play_hit()
		break_flash(self)
		if self.health <= 0:
			items = self.drop_items()
			if not can_store(self.player_add, items):
				# Full bag: the crate stays until its loot fits.
				self.health = 1
				play_error(); notify_inventory_full(self.player_add)
				return
			self.alive = False
			self.break_drop(items)
			# Clear collision so the broken crate no longer blocks movement.
			teardown_solid(self)

	def drop_items(self):
		"""[(item, count), ...] this crate yields when it is cut apart."""
		items = [('wood', 1)]
		if self.loaded and random() < CAVE_CRATE_ORE_CHANCE:
			items.append((choice(CAVE_ORE_LOOT), 1))
		return items

	def break_drop(self, items = None):
		if items is None:
			items = self.drop_items()
		for item, count in items:
			for _ in range(count):
				self.player_add(item)

class Pot(Crate):
	"""Cave pot: punched to pick it up — one hit, no loot."""
	allowed_tools = ('punch',)

	def __init__(self, pos, surf, groups, player_add):
		super().__init__(pos, surf, groups, player_add, health = 1)

	def _play_hit(self):
		play_click()

	def drop_items(self):
		return []

	def break_drop(self, items = None):
		pass

class GroundTile(Generic):
	def __init__(self, pos, surf, groups, tile_type='grass'):
		super().__init__(pos, surf, groups, z=LAYERS['ground'])
		self.tile_type = tile_type

class Bush(Generic):
	def __init__(self, pos, surf, groups, player_add, drops = None):
		super().__init__(pos, surf, groups)
		self.rect = self.image.get_rect(center = pos)
		self._rebuild_hitbox()
		self.foot_pad = 24
		self.health = 3
		self.alive = True
		self.player_add = player_add
		# [(item, min, max), ...]; berry bushes also drop the bush itself.
		self.drops = drops if drops is not None else [('bush', 1, 1)]
		self.hoe_sound = load_sound('hoe.wav')
		# Bushes are foraged with RShift (pick), never broken by tools.
		self.allowed_tools = ()

	def damage(self, amount = 1):
		# Tools cannot damage a bush; only RShift pick() harvests it.
		play_error()
		return

	def drop_items(self):
		"""[(item, count), ...] this bush yields when it is foraged."""
		return [(item, randint(drop_min, drop_max))
		        for item, drop_min, drop_max in self.drops]

	def pick(self):
		if not self.alive:
			return
		items = self.drop_items()
		if not can_store(self.player_add, items):
			# Full bag: the bush stays so its berries are not lost.
			play_error()
			play_error(); notify_inventory_full(self.player_add)
			return
		self.alive = False
		for item, count in items:
			for _ in range(count):
				self.player_add(item)
		# Detach from every group; the bush no longer blocks movement.
		teardown_solid(self)

	def update(self, dt):
		pass

class PlaceableBed(Generic):
	def __init__(self, pos, surf, groups, player_add):
		super().__init__(pos, surf, groups)
		# Image center anchors on the tile diamond center.
		self.iso_anchor = 'center'
		self.foot_pad = visible_bottom_pad(self.image)
		# Solid hitbox so the player cannot walk through the bed.
		self.hitbox = self.rect.copy().inflate(-10, -10)
		self.health = 3
		self.alive = True
		self.player_add = player_add
		self.axe_sound = load_sound('axe.mp3')

	def damage(self, amount = 1):
		if self.health - amount <= 0:
			# A full bag means no break sound or animation at all.
			if not can_store(self.player_add, [('Bed', 1)]):
				play_error(); notify_inventory_full(self.player_add)
				return
		self.health -= amount
		self.axe_sound.play()
		break_flash(self)
		if self.health <= 0:
			self.alive = False
			self.player_add('Bed')
			# Clear collision so the broken bed no longer blocks movement.
			teardown_solid(self)

	def update(self, dt):
		pass

class PlaceableBridge(Generic):
	"""A walkable wooden deck placed on a water or cave-lava tile.
	The art is pre-cut to the bare deck diamond, so a placed bridge IS a
	tile. Three axe hits chop it apart and the plank goes back in the bag.
	"""
	render_as_ground = True
	# Only an axe takes a deck apart; punches/pickaxes ignore it.
	allowed_tools = ('axe',)

	def __init__(self, pos, surf, groups, level_ref = None, tile = None,
			scene = 'overworld', player_add = None):
		super().__init__(pos, surf, groups, z = LAYERS['ground'])
		self.iso_anchor = 'center'
		self.hitbox = pygame.Rect(0, 0, 0, 0)
		self.level_ref = level_ref
		# World tile the deck covers; needed to un-walk it on break.
		self.tile = tile
		# Which world's bridge set owns this deck (overworld / cave).
		self.scene = scene
		self.player_add = player_add
		self.health = 3
		self.alive = True
		self.axe_sound = load_sound('axe.mp3')

	def damage(self, amount = 1):
		if not self.alive:
			return
		# The finishing hit needs a free bag slot for the plank.
		if self.health - amount <= 0:
			if not can_store(self.player_add, [('bridge', 1)]):
				play_error(); notify_inventory_full(self.player_add)
				return
		self.health -= amount
		self.axe_sound.play()
		break_flash(self)
		if self.health <= 0:
			self.alive = False
			if self.player_add:
				self.player_add('bridge')
			level = self.level_ref
			if level is not None and self.tile is not None \
			   and hasattr(level, 'break_bridge'):
				level.break_bridge(*self.tile, self.scene)
			# kill() drops it from all_sprites, which the ground pass draws.
			self.kill()

	def update(self, dt):
		pass