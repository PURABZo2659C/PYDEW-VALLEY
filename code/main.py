import asyncio
import pygame, sys
from settings import *
from level import Level
from title_screen import TitleScreen
from save_system import load_save, delete_save

class Game:
	def __init__(self):
		pygame.init()
		# Full screen at the real desktop resolution: the canvas is the
		# screen itself, so the pixel art is drawn 1:1 and stays crisp.
		# SCALED keeps SDL from switching the display mode, so alt-tabbing
		# cannot reflow other windows or leave the desktop at a different
		# resolution (plain FULLSCREEN does switch modes and caused the
		# tab-glitch).
		sw, sh = pygame.display.get_desktop_sizes()[0]
		self.screen = pygame.display.set_mode(
			(sw, sh), pygame.SCALED | pygame.FULLSCREEN)
		# Scale the interface to match: the menus fit themselves to the
		# screen, and the fonts have to grow with them.
		set_ui_scale(self.screen.get_height() / float(UI_REFERENCE_HEIGHT))
		pygame.display.set_caption('PYDEW VALLEY')
		self.clock = pygame.time.Clock()

	async def run_title(self):
		title = TitleScreen()
		return await title.run()

	async def run_level(self, choice):
		save_data = None
		if choice == 'NEW GAME':
			if not delete_save():
				# Another copy of the game may still hold the save file open. Carry
				# on, but say so - otherwise CONTINUE would bring back the old world.
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
			# Hand control back to the event loop once per frame.
			await asyncio.sleep(0)

	async def run(self):
		while True:
			choice = await self.run_title()
			if choice == 'EXIT':
				break
			await self.run_level(choice)
		pygame.quit()
		sys.exit()

if __name__ == '__main__':
	# The loop runs on asyncio so the event loop gets a turn every frame.
	asyncio.run(Game().run())
