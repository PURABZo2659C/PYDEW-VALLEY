import pygame 

# Millisecond cooldown; optionally fires func when it expires.
class Timer:
	def __init__(self,duration,func = None):
		self.duration = duration
		self.func = func
		self.start_time = 0
		self.active = False

	def activate(self):
		# Start or restart the countdown.
		self.active = True
		self.start_time = pygame.time.get_ticks()

	def deactivate(self):
		self.active = False
		self.start_time = 0

	def update(self):
		current_time = pygame.time.get_ticks()
		# start_time == 0 means the timer was never activated.
		if current_time - self.start_time >= self.duration:
			if self.func and self.start_time != 0:
				self.func()
			self.deactivate()