import pygame, sys
from settings import *
from level import Level
from title_screen import TitleScreen
from save_system import load_save, delete_save

class Game:
	def __init__(self):
		pygame.init()
		# SCALED | FULLSCREEN stretches to the desktop without switching display modes.
		sw, sh = pygame.display.get_desktop_sizes()[0]
		self.screen = pygame.display.set_mode(
			(sw, sh), pygame.SCALED | pygame.FULLSCREEN)
		# Scale the interface to match: fonts grow with the fit-to-screen menus.
		set_ui_scale(self.screen.get_height() / float(UI_REFERENCE_HEIGHT))
		pygame.display.set_caption('PYDEW VALLEY')
		self.clock = pygame.time.Clock()

	def run_title(self):
		title = TitleScreen()
		return title.run()

	def run_level(self, choice):
		save_data = None
		if choice == 'NEW GAME':
			if not delete_save():
				# Another copy may hold the save open; carry on but say so.
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