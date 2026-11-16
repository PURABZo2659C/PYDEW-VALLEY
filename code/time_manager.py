import pygame
from settings import *

class TimeManager:
	def __init__(self):
		self.minute = 0
		self.hour = DAY_START_HOUR
		self.day = 1
		self.season_index = 0
		self.year = 1
		# Real seconds accumulated toward the next 10-minute tick.
		self.elapsed = 0.0
		# Monotonic in-game minutes; saves and farmland/drop timers use it.
		self.total_minutes = self.hour * 60 + self.minute

	def update(self, dt):
		# One tick per SECONDS_PER_MINUTE of real time advances 10 game minutes.
		self.elapsed += dt
		if self.elapsed >= SECONDS_PER_MINUTE:
			self.elapsed -= SECONDS_PER_MINUTE
			self.minute += 10
			self.total_minutes += 10
			# Roll hour -> day -> season -> year in order.
			if self.minute >= 60:
				self.minute = 0
				self.hour += 1
				if self.hour >= 24:
					self.hour = 0
					self.day += 1
					if self.day > DAYS_PER_SEASON:
						self.day = 1
						self.season_index = (self.season_index + 1) % 4
						if self.season_index == 0:
							self.year += 1

	def sleep_to_morning(self):
		# Sleeping after morning starts the next day; before it stays today.
		current = self.hour * 60 + self.minute
		morning = DAY_START_HOUR * 60
		if current >= morning:
			self.total_minutes += 24 * 60 - current + morning
			self.day += 1
			if self.day > DAYS_PER_SEASON:
				self.day = 1
				self.season_index = (self.season_index + 1) % 4
				if self.season_index == 0:
					self.year += 1
		else:
			self.total_minutes += morning - current
		self.hour = DAY_START_HOUR
		self.minute = 0
		self.elapsed = 0.0

	def get_time_string(self):
		# 12-hour display; midnight is 12 AM.
		period = "AM" if self.hour < 12 else "PM"
		h = self.hour if self.hour <= 12 else self.hour - 12
		if h == 0:
			h = 12
		return f"{h}:{self.minute:02d} {period}"

	def get_season_name(self):
		return SEASONS[self.season_index]

	def is_night(self):
		return self.hour >= NIGHT_START_HOUR or self.hour < DAY_START_HOUR

	def get_day_progress(self):
		# Fraction of the 24-hour day elapsed.
		return (self.hour * 60 + self.minute) / (24 * 60)

	def get_season_color_tint(self):
		# Colour multipliers applied to the world per season.
		tints = {
			0: (1.0, 1.0, 1.0),
			1: (1.0, 0.95, 0.85),
			2: (0.9, 0.85, 0.7),
			3: (0.85, 0.9, 1.0),
		}
		return tints.get(self.season_index, (1.0, 1.0, 1.0))

	def get_time_of_day_factor(self):
		# 0 at night and 1 at midday; used to blend sky lighting.
		h = self.hour + self.minute / 60
		if 6 <= h < 12:
			return (h - 6) / 6
		elif 12 <= h < 17:
			return 1.0
		elif 17 <= h < 20:
			return 1.0 - (h - 17) / 3 * 0.5
		elif 20 <= h < 22:
			return 0.5 - (h - 20) / 2 * 0.5
		else:
			return 0.0
