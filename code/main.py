import pygame, sys
from settings import *
from level import Level
from title_screen import TitleScreen
from save_system import load_save, delete_save

class Game:
	def __init__(self):
		pygame.init()
		# SCALED | FULLSCREEN is SDL's desktop-fullscreen path: the game
		# keeps its logical surface while SDL stretches it to the current
		# desktop resolution. SDL never switches the display mode, so
		# alt-tabbing cannot reflow other windows or leave the desktop
		# at a different resolution. (pygame.FULLSCREEN alone and the
		# pygame._sdl2 Window.set_fullscreen path both switched modes and
		# could crash in pygame.event.get().)
		#
		# PydewValley.ini can turn that off. fullscreen=0 gives a
		# resizable window instead, which is the way to play on a screen
		# smaller than 1525x860.
		if ini_bool('display.fullscreen', True) or ini_bool('fullscreen', True):
			self.screen = pygame.display.set_mode(
				(SCREEN_WIDTH, SCREEN_HEIGHT),
				pygame.SCALED | pygame.FULLSCREEN)
		else:
			self.screen = pygame.display.set_mode(
				(SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
		pygame.display.set_caption('PYDEW VALLEY')
		self.clock = pygame.time.Clock()

	def run_title(self):
		title = TitleScreen()
		return title.run()

	def run_level(self, choice):
		save_data = None
		if choice == 'NEW GAME':
			if not delete_save():
				# Another copy of the game may still be holding the save
				# file open. Carry on, but say so - otherwise CONTINUE
				# would bring back the world the player just left.
				print('[Main] could not delete the old save - '
					  'another copy of the game may be running')
		elif choice == 'CONTINUE':
			save_data = load_save()

		level = Level(save_data)

		while not level.quit_to_menu:
			events = pygame.event.get()
			for event in events:
				if event.type == pygame.QUIT:
					pygame.quit()
					sys.exit()
			dt = self.clock.tick(60) / 1000
			level.run(dt, events)
			pygame.display.update()

	def run(self):
		while True:
			choice = self.run_title()
			if choice == 'EXIT':
				break
			self.run_level(choice)
		pygame.quit()
		sys.exit()

if __name__ == '__main__':
	Game().run()