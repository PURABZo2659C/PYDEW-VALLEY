import pygame
from settings import *
from timer import Timer
from support import play_click
import input_manager

class Menu:
	def __init__(self, player, toggle_menu):

		# general setup
		self.player = player
		self.toggle_menu = toggle_menu
		self.display_surface = pygame.display.get_surface()
		self.font = ui_font(30)

		# options
		self.width = 400
		self.space = 10
		self.padding = 8

		# entries
		# Sell entries come first; sell_border marks the last one.
		self.options = list(SALE_PRICES.keys()) + list(PURCHASE_PRICES.keys())
		self.sell_border = len(SALE_PRICES) - 1
		self.setup()

		# movement
		self.index = 0
		# Rate-limits repeated navigation while a key is held.
		self.timer = Timer(200)

	def display_money(self):
		sw, sh = self.display_surface.get_size()
		text_surf = self.font.render(f'${self.player.money}', False, 'Black')
		text_rect = text_surf.get_rect(midbottom = (sw / 2, sh - 20))

		pygame.draw.rect(self.display_surface,'White',text_rect.inflate(10,10),0,4)
		self.display_surface.blit(text_surf,text_rect)

	def setup(self):
		sw, sh = self.display_surface.get_size()

		# create the text surfaces
		# Pre-render labels and measure the full menu height.
		self.text_surfs = []
		self.total_height = 0

		for item in self.options:
			text_surf = self.font.render(item_name(item), False, 'Black')
			self.text_surfs.append(text_surf)
			self.total_height += text_surf.get_height() + (self.padding * 2)

		self.total_height += (len(self.text_surfs) - 1) * self.space
		self.menu_top = sh / 2 - self.total_height / 2
		self.main_rect = pygame.Rect(sw / 2 - self.width / 2,self.menu_top,self.width,self.total_height)

		# buy / sell text surface
		self.buy_text = self.font.render('buy',False,'Black')
		self.sell_text =  self.font.render('sell',False,'Black')

	def input(self):
		keys = pygame.key.get_pressed()
		self.timer.update()

		if input_manager.is_action_pressed_keys(keys, 'pause'):
			play_click()
			self.toggle_menu()

		# Ignore repeats until the navigation timer expires.
		if not self.timer.active:
			if keys[pygame.K_UP] or input_manager.is_action_pressed_keys(keys, 'move_up'):
				self.index -= 1
				self.timer.activate()

			if keys[pygame.K_DOWN] or input_manager.is_action_pressed_keys(keys, 'move_down'):
				self.index += 1
				self.timer.activate()

			if keys[pygame.K_RETURN] or input_manager.is_action_pressed_keys(keys, 'use_tool'):
				self.timer.activate()
				play_click()

				# get item
				current_item = self.options[self.index]

				# sell
				if self.index <= self.sell_border:
					if self.player.inventory.remove(current_item, 1) == 1:
						self.player.money += SALE_PRICES.get(current_item, 0)

				# buy
				else:
					seed_price = PURCHASE_PRICES[current_item]
					if self.player.money >= seed_price:
						# A purchase is fresh loot: hotbar first (add_loot).
						if self.player.add_loot(current_item, 1) == 0:
							self.player.money -= seed_price
							self.player.assign_to_hotbar(current_item, 1)
						else:
							level = getattr(self.player, 'level_ref', None)
							if level is not None and hasattr(level, 'show_inventory_full'):
								level.show_inventory_full()

		# Wrap the selection at both ends.
		if self.index < 0:
			self.index = len(self.options) - 1
		if self.index > len(self.options) - 1:
			self.index = 0

	def show_entry(self, text_surf, amount, top, selected):

		# One row: name, owned count, and a sell/buy tag when selected.
		# background
		bg_rect = pygame.Rect(self.main_rect.left,top,self.width,text_surf.get_height() + (self.padding * 2))
		pygame.draw.rect(self.display_surface, 'White',bg_rect, 0, 4)

		# text
		text_rect = text_surf.get_rect(midleft = (self.main_rect.left + 20,bg_rect.centery))
		self.display_surface.blit(text_surf, text_rect)

		# amount
		amount_surf = self.font.render(str(amount), False, 'Black')
		amount_rect = amount_surf.get_rect(midright = (self.main_rect.right - 20,bg_rect.centery))
		self.display_surface.blit(amount_surf, amount_rect)

		# selected
		if selected:
			pygame.draw.rect(self.display_surface,'black',bg_rect,4,4)
			if self.index <= self.sell_border: # sell
				pos_rect = self.sell_text.get_rect(midleft = (self.main_rect.left + 150,bg_rect.centery))
				self.display_surface.blit(self.sell_text,pos_rect)
			else: # buy
				pos_rect = self.buy_text.get_rect(midleft = (self.main_rect.left + 150,bg_rect.centery))
				self.display_surface.blit(self.buy_text,pos_rect)

	def update(self):
		self.input()
		self.display_money()

		for text_index, text_surf in enumerate(self.text_surfs):
			top = self.main_rect.top + text_index * (text_surf.get_height() + (self.padding * 2) + self.space)
			item_key = self.options[text_index]
			amount = self.player.inventory.count(item_key)
			self.show_entry(text_surf, amount, top, self.index == text_index)