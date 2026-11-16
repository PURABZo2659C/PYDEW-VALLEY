from settings import POTION_ITEMS, QUEST_STACK

MAX_STACK_SIZE = 64
HOTBAR_SIZE = 9
SLOT_COUNT = 36
MAIN_START = HOTBAR_SIZE

SEED_ITEMS = ('wheat_seed', 'tomato_seed')
SEED_CROP_TYPES = {
	'wheat_seed': 'wheat',
	'tomato_seed': 'tomato',
}
CROP_SEEDS = {crop: seed for seed, crop in SEED_CROP_TYPES.items()}
LEGACY_SEED_ALIASES = {
	'wheat': 'wheat_seed',
	'tomato': 'tomato_seed',
}

# Older saves stored 'Bread'; keys are lowercase now, normalised on load.
LEGACY_ITEM_ALIASES = {
	'Bread': 'bread',
}

UNSTACKABLE_ITEMS = {
	'hoe', 'axe', 'pickaxe', 'water_bucket', 'Bed', 'heart_of_valley',
	*POTION_ITEMS,
}


def stack_limit(item):
	return 1 if item in UNSTACKABLE_ITEMS else MAX_STACK_SIZE


def crop_type_for_seed(item):
	return SEED_CROP_TYPES.get(item)


class HotbarView:
	def __init__(self, inventory):
		self.inventory = inventory

	def __len__(self):
		return HOTBAR_SIZE

	def __getitem__(self, index):
		return self.inventory.slots[index]

	def __setitem__(self, index, value):
		self.inventory.set_slot(index, value)

	def __iter__(self):
		return iter(self.inventory.slots[:HOTBAR_SIZE])


class Inventory:
	def __init__(self, slots=None):
		self.slots = [None] * SLOT_COUNT
		if slots:
			self.load(slots)

	@staticmethod
	def _normalize(stack):
		if not stack:
			return None
		try:
			item = stack[0]
			count = int(stack[1])
		except (TypeError, ValueError, IndexError):
			return None
		if not item or count <= 0:
			return None
		return [item, min(count, stack_limit(item))]

	def count(self, item):
		return sum(slot[1] for slot in self.slots
		           if slot and slot[0] == item)

	def count_any(self, items):
		return sum(self.count(item) for item in items)

	def unique_items(self):
		seen = []
		for slot in self.slots:
			if slot and slot[0] not in seen:
				seen.append(slot[0])
		return seen

	def has(self, item, amount=1):
		return self.count(item) >= amount

	def get_slot(self, index):
		if 0 <= index < SLOT_COUNT:
			return self.slots[index]
		return None

	def set_slot(self, index, stack):
		if not 0 <= index < SLOT_COUNT:
			return None
		normalized = self._normalize(stack)
		self.slots[index] = normalized
		return normalized

	def add_to_range(self, item, amount, start, end, merge_only=False):
		if not item or amount <= 0:
			return amount
		limit = stack_limit(item)
		remaining = int(amount)
		start = max(0, start)
		end = min(SLOT_COUNT, end)

		for i in range(start, end):
			if remaining <= 0:
				break
			slot = self.slots[i]
			if not slot or slot[0] != item:
				continue
			space = limit - slot[1]
			if space <= 0:
				continue
			move = min(space, remaining)
			slot[1] += move
			remaining -= move

		if merge_only:
			return remaining

		for i in range(start, end):
			if remaining <= 0:
				break
			if self.slots[i] is not None:
				continue
			move = min(limit, remaining)
			self.slots[i] = [item, move]
			remaining -= move
		return remaining

	def add(self, item, amount=1, hotbar_first=True):
		remaining = self.add_to_range(
			item, amount, 0, SLOT_COUNT, merge_only=True)
		if remaining <= 0:
			return 0
		if hotbar_first:
			remaining = self.add_to_range(
				item, remaining, 0, HOTBAR_SIZE)
			if remaining > 0:
				remaining = self.add_to_range(
					item, remaining, MAIN_START, SLOT_COUNT)
			return remaining
		remaining = self.add_to_range(
			item, remaining, MAIN_START, SLOT_COUNT)
		if remaining > 0:
			remaining = self.add_to_range(
				item, remaining, 0, HOTBAR_SIZE)
		return remaining

	def can_add(self, item, amount=1):
		"""True when `amount` more of `item` would fit in the bag.
		Used to refuse an action before its source is consumed.
		"""
		limit = stack_limit(item)
		remaining = int(amount)
		if remaining <= 0:
			return True
		for slot in self.slots:
			if slot and slot[0] == item:
				space = limit - slot[1]
				if space > 0:
					remaining -= space
					if remaining <= 0:
						return True
		empty = sum(1 for slot in self.slots if slot is None)
		return remaining <= empty * limit

	def has_room(self):
		"""True when at least one more item of any kind can be stored."""
		for slot in self.slots:
			if slot is None:
				return True
			if slot[1] < stack_limit(slot[0]):
				return True
		return False

	def ensure_count(self, item, target):
		missing = int(target) - self.count(item)
		if missing <= 0:
			return 0
		return self.add(item, missing, hotbar_first=False)

	def remove_to_range(self, item, amount, start, end):
		if not item or amount <= 0:
			return 0
		remaining = int(amount)
		removed = 0
		for i in range(start, end):
			if remaining <= 0:
				break
			slot = self.slots[i]
			if not slot or slot[0] != item:
				continue
			take = min(slot[1], remaining)
			slot[1] -= take
			remaining -= take
			removed += take
			if slot[1] <= 0:
				self.slots[i] = None
		return removed

	def remove(self, item, amount=1, hotbar_first=False):
		if hotbar_first:
			removed = self.remove_to_range(item, amount, 0, HOTBAR_SIZE)
			if removed < amount:
				removed += self.remove_to_range(
					item, amount - removed, MAIN_START, SLOT_COUNT)
			return removed
		removed = self.remove_to_range(item, amount, MAIN_START, SLOT_COUNT)
		if removed < amount:
			removed += self.remove_to_range(
				item, amount - removed, 0, HOTBAR_SIZE)
		return removed

	def remove_any(self, items, amount=1):
		remaining = int(amount)
		for item in items:
			if remaining <= 0:
				break
			remaining -= self.remove(item, remaining)
		return int(amount) - remaining

	def quick_move(self, index):
		if not 0 <= index < SLOT_COUNT:
			return False
		stack = self.slots[index]
		if not stack:
			return False
		item, count = stack
		if index < HOTBAR_SIZE:
			start, end = MAIN_START, SLOT_COUNT
		else:
			start, end = 0, HOTBAR_SIZE
		self.slots[index] = None
		remaining = self.add_to_range(item, count, start, end)
		if remaining > 0:
			self.slots[index] = [item, remaining]
		return remaining < count

	def swap(self, first, second):
		if first == second:
			return False
		if not (0 <= first < SLOT_COUNT and 0 <= second < SLOT_COUNT):
			return False
		self.slots[first], self.slots[second] = \
			self.slots[second], self.slots[first]
		return True

	def move_to_hotbar(self, index, hotbar_index):
		if not 0 <= index < SLOT_COUNT or not 0 <= hotbar_index < HOTBAR_SIZE:
			return False
		if index == hotbar_index:
			return False
		source = self.slots[index]
		target = self.slots[hotbar_index]
		if source is None:
			if target is None:
				return False
			self.swap(index, hotbar_index)
			return True
		item, count = source
		if target and target[0] == item:
			limit = stack_limit(item)
			space = limit - target[1]
			move = min(space, count)
			target[1] += move
			count -= move
			self.slots[index] = [item, count] if count > 0 else None
			return move > 0
		self.swap(index, hotbar_index)
		return True

	def gather(self, item, limit=MAX_STACK_SIZE):
		gathered = 0
		for i, slot in enumerate(self.slots):
			if gathered >= limit:
				break
			if not slot or slot[0] != item:
				continue
			take = min(slot[1], limit - gathered)
			slot[1] -= take
			gathered += take
			if slot[1] <= 0:
				self.slots[i] = None
		return gathered

	def load(self, slots):
		for index, raw in enumerate(list(slots)[:SLOT_COUNT]):
			if not raw:
				continue
			try:
				item = raw[0]
				count = int(raw[1])
			except (TypeError, ValueError, IndexError):
				continue
			if not item or count <= 0:
				continue
			item = LEGACY_ITEM_ALIASES.get(item, item)
			limit = stack_limit(item)
			placed = min(count, limit)
			self.slots[index] = [item, placed]
			overflow = count - placed
			if overflow > 0:
				self.add(item, overflow)

	def to_data(self):
		result = []
		for slot in self.slots:
			result.append([slot[0], int(slot[1])] if slot else None)
		return result

	@classmethod
	def from_data(cls, data):
		if isinstance(data, dict):
			data = data.get('slots')
		if not isinstance(data, (list, tuple)):
			return cls()
		return cls(data)

	@classmethod
	def from_legacy(cls, item_inventory=None, seed_inventory=None,
	                hotbar=None):
		inventory = cls()
		items = {
			str(key): int(value)
			for key, value in (item_inventory or {}).items()
			if value and int(value) > 0
		}
		seeds = {
			str(key): int(value)
			for key, value in (seed_inventory or {}).items()
			if value and int(value) > 0
		}
		legacy_hotbar = list(hotbar or [])

		for base, seed_item in LEGACY_SEED_ALIASES.items():
			crop_count = items.get(base, 0)
			seed_count = seeds.get(base, 0)
			if crop_count == seed_count and crop_count > QUEST_STACK:
				items[base] = QUEST_STACK
				seeds[base] = QUEST_STACK

		for index, raw in enumerate(legacy_hotbar[:HOTBAR_SIZE]):
			if not raw:
				continue
			try:
				item = raw[0]
				count = int(raw[1])
			except (TypeError, ValueError, IndexError):
				continue
			if not item or count <= 0:
				continue
			item = LEGACY_SEED_ALIASES.get(item, item)
			item = LEGACY_ITEM_ALIASES.get(item, item)
			limit = stack_limit(item)
			placed = min(count, limit)
			inventory.slots[index] = [item, placed]
			if count > placed:
				inventory.add(item, count - placed, hotbar_first=False)

		for item, count in items.items():
			inventory.add(LEGACY_ITEM_ALIASES.get(item, item), count,
			              hotbar_first=False)

		for seed, count in seeds.items():
			item = LEGACY_SEED_ALIASES.get(seed, seed)
			inventory.add(item, count, hotbar_first=False)
		return inventory
