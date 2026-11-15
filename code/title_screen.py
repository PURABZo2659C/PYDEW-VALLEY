import asyncio
import pygame, sys, os, math, random, webbrowser
import numpy as np
from pygame.constants import K_RETURN

from settings import asset_path, help_doc_path, ui_font, ui_scale


def _art_scale(base):
    """Scale factor for pixel art: an integer, so the pixels stay square.

    The interface grows with the screen, but pixel art only survives whole
    number steps - a 2.5x button would have uneven rows.
    """
    return max(1, int(round(base * ui_scale())))
from save_system import save_exists
from support import play_click, click_sound
from pause_menu import SettingsMenu
import input_manager

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class FloatingParticle:
    def __init__(self, sw, sh):
        self.sw = sw
        self.sh = sh
        self.reset()

    def reset(self):
        self.x = random.uniform(0, self.sw)
        self.y = random.uniform(0, self.sh * 0.7)
        self.size = random.uniform(1.5, 4)
        self.speed_x = random.uniform(-12, 12)
        self.speed_y = random.uniform(-8, 8)
        self.alpha = random.randint(100, 220)
        self.color_type = random.choice(['white', 'yellow', 'blue', 'pink'])
        self.life = 0
        self.max_life = random.uniform(3, 7)
        self.wobble_speed = random.uniform(1, 3)
        self.wobble_amp = random.uniform(5, 20)

    def update(self, dt):
        self.life += dt
        progress = self.life / self.max_life
        fade = math.sin(progress * math.pi)
        self.current_alpha = int(self.alpha * fade)
        self.x += self.speed_x * dt + math.sin(self.life * self.wobble_speed) * self.wobble_amp * dt
        self.y += self.speed_y * dt
        if self.life >= self.max_life or self.x < -20 or self.x > self.sw + 20 or self.y < -20:
            self.reset()

    def draw(self, surface):
        if self.current_alpha <= 0:
            return
        colors = {
            'white': (255, 255, 255, self.current_alpha),
            'yellow': (255, 255, 180, self.current_alpha),
            'blue': (180, 220, 255, self.current_alpha),
            'pink': (255, 200, 220, self.current_alpha),
        }
        s = pygame.Surface((int(self.size * 2), int(self.size * 2)), pygame.SRCALPHA)
        pygame.draw.circle(s, colors[self.color_type], (int(self.size), int(self.size)), int(self.size))
        surface.blit(s, (int(self.x - self.size), int(self.y - self.size)))


class TitleScreen:
    BTN_START_Y = 450
    BTN_SPACING = 124

    def __init__(self):
        self.display_surface = pygame.display.get_surface()
        self.font = ui_font(80)
        self.option_font = ui_font(45)

        self.options = ['NEW GAME', 'CONTINUE', 'EXIT']
        self.selected = 0

        self.popup_active = False
        self.popup_confirm = False      # YES/NO overwrite confirmation
        self.popup_yes_rect = pygame.Rect(0, 0, 120, 50)
        self.popup_no_rect = pygame.Rect(0, 0, 120, 50)
        self.popup_font = ui_font(28)
        self.popup_ok_rect = pygame.Rect(0, 0, 160, 50)
        self.ok_button_img = None
        self._cached_popup_overlay = None
        self.popup_lines = ['No save file found!', 'Start a new game?']

        # corner buttons: SETTINGS at the top right, HELP right below it
        self.corner_font = ui_font(30)
        self.corner_images = self._load_corner_button_images()
        self.corner_hover = None
        self.settings_active = False
        self.settings_menu = None
        self.help_path = help_doc_path()

        self.time_val = 0
        sw, sh = self.get_size()

        self.particles = [FloatingParticle(sw, sh) for _ in range(30)]

        # logo replaces the text title
        try:
            self.logo = pygame.image.load(asset_path('graphics', 'world', 'logo.png')).convert_alpha()
        except (pygame.error, FileNotFoundError):
            self.logo = None

        # static fallback background (video used when available)
        try:
            self.menu_bg = pygame.image.load(asset_path('graphics', 'world', 'menu_background.jpg')).convert()
        except (pygame.error, FileNotFoundError):
            self.menu_bg = None

        # background video - OpenCV is optional, without it the title
        # screen falls back to its still background.
        self.video = None
        self._video_frame = None
        self._video_pos = 0.0
        self._video_fps = 30
        if _HAS_CV2:
            video_path = asset_path('graphics', 'world', 'Background.mp4')
            if os.path.exists(video_path):
                cap = cv2.VideoCapture(video_path)
                if cap.isOpened():
                    self.video = cap
                    self._video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
                    self._video_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

        # Menu music. First slot that exists wins:
        #   audio/Title_background.wav    - title theme by Yoiyami (CC0)
        #   graphics/world/background.mp3 - optional user track
        #   audio/menu.mp3                 - optional user track
        #   audio/music.mp3                - in-game track (fallback)
        # Only the CC0 title theme and the in-game track ship.
        self.menu_music = None
        music_path = None
        for candidate in (asset_path('audio', 'Title_background.wav'),
                          asset_path('graphics', 'world', 'background.mp3'),
                          asset_path('audio', 'menu.mp3'),
                          asset_path('audio', 'music.mp3')):
            if os.path.exists(candidate):
                music_path = candidate
                break
        if music_path:
            try:
                self.menu_music = pygame.mixer.Sound(music_path)
            except pygame.error:
                self.menu_music = None

        self.button_images = self._load_button_images()
        self._load_ok_button()

    def _load_button_images(self):
        try:
            img = pygame.image.load(asset_path('graphics', 'UI', 'blank_buttons.png')).convert_alpha()
            w, h = img.get_size()
            normal = img.subsurface((0, 0, w // 2, h))
            selected = img.subsurface((w // 2, 0, w // 2, h))
            scale = _art_scale(4)
            normal = pygame.transform.scale(normal, (normal.get_width() * scale, normal.get_height() * scale))
            selected = pygame.transform.scale(selected, (selected.get_width() * scale, selected.get_height() * scale))
            return {'normal': normal, 'selected': selected}
        except (pygame.error, FileNotFoundError):
            return None

    def _load_ok_button(self):
        try:
            img = pygame.image.load(asset_path('graphics', 'UI', 'blank_buttons.png')).convert_alpha()
            w, h = img.get_size()
            normal = img.subsurface((0, 0, w // 2, h))
            scale = _art_scale(2)
            self.ok_button_img = pygame.transform.scale(normal, (normal.get_width() * scale, normal.get_height() * scale))
        except (pygame.error, FileNotFoundError):
            self.ok_button_img = None

    def _load_corner_button_images(self):
        """Top-right SETTINGS / HELP buttons: their own two-state art
        from graphics/UI (left half = normal, right half = hover, the
        label is baked into the sprite)."""
        images = {}
        for name, stem in (('SETTINGS', 'setting.png'), ('HELP', 'Help.png')):
            try:
                raw = pygame.image.load(asset_path('graphics', 'UI', stem)).convert_alpha()
                w, h = raw.get_size()
                half = w // 2
                scale = _art_scale(3)  # 69x72 - compact enough to sit in the corner
                images[name] = {
                    'normal': pygame.transform.scale(
                        raw.subsurface((0, 0, half, h)), (half * scale, h * scale)),
                    'selected': pygame.transform.scale(
                        raw.subsurface((half, 0, w - half, h)), ((w - half) * scale, h * scale)),
                }
            except (pygame.error, FileNotFoundError):
                images[name] = None
        return images if any(images.values()) else None

    CORNER_RIGHT = 24
    CORNER_TOP = 20
    CORNER_GAP = 10

    def corner_rects(self, sw, sh):
        """SETTINGS on top, HELP stacked directly beneath it, top-right."""
        images = self.corner_images or {}
        size = next((images[name]['normal'].get_size()
                     for name in ('SETTINGS', 'HELP') if images.get(name)),
                    None)
        w, h = size if size else (192, 62)
        scale = ui_scale()
        right = int(self.CORNER_RIGHT * scale)
        top = int(self.CORNER_TOP * scale)
        gap = int(self.CORNER_GAP * scale)
        rects = {}
        y = top
        for name in ('SETTINGS', 'HELP'):
            rects[name] = pygame.Rect(sw - right - w, y, w, h)
            y += h + gap
        return rects

    # ── corner button actions ──────────────────────────────────────
    def open_settings(self):
        """Open the very same settings menu the pause screen uses."""
        sfx = click_sound()
        self.settings_menu = SettingsMenu(
            self.display_surface, self.close_settings,
            self.menu_music, [sfx] if sfx else [])
        self.settings_active = True

    def close_settings(self):
        self.settings_active = False

    def show_popup(self, lines):
        """Plain information popup (single OK button)."""
        self.popup_lines = list(lines)
        self.popup_confirm = False
        self.popup_active = True

    def close_confirm_popup(self):
        """NO / Esc on the new-game confirmation: keep the save and put
        the cursor on CONTINUE, which is the suggested path."""
        self.popup_active = False
        self.popup_confirm = False
        if save_exists():
            try:
                self.selected = self.options.index('CONTINUE')
            except ValueError:
                pass

    def open_help(self):
        """Open the controls / play-loop help page in the default browser."""
        if not os.path.exists(self.help_path):
            self.show_popup(['Help file not found!',
                             os.path.basename(self.help_path)])
            return
        try:
            uri = 'file:///' + os.path.abspath(self.help_path).replace('\\', '/')
            webbrowser.open(uri)
        except Exception as exc:  # no browser available: say so, don't crash
            self.show_popup(['Could not open help!', str(exc)[:60]])

    def get_size(self):
        return self.display_surface.get_size()

    def input(self):
        sw, sh = self.get_size()
        events = pygame.event.get()
        if self.settings_active and self.settings_menu:
            # the settings menu owns the screen while it is open
            # (its ESC / close button calls close_settings)
            self.settings_menu.input(events)
            return None
        corner = self.corner_rects(sw, sh)
        for event in events:
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if self.popup_active:
                if self.popup_confirm:
                    # Overwrite confirmation: only YES starts a fresh game
                    # (and deletes the old save); NO / Esc / Enter keeps it.
                    if event.type == pygame.KEYDOWN:
                        if (event.key in (pygame.K_RETURN, pygame.K_ESCAPE)
                                or input_manager.is_key_for_action(event.key, 'pause')):
                            play_click()
                            self.close_confirm_popup()
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        if self.popup_yes_rect.collidepoint(event.pos):
                            play_click()
                            self.popup_active = False
                            self.popup_confirm = False
                            return 'NEW GAME'
                        if self.popup_no_rect.collidepoint(event.pos):
                            play_click()
                            self.close_confirm_popup()
                    continue
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_RETURN, pygame.K_ESCAPE) or input_manager.is_key_for_action(event.key, 'interact') or input_manager.is_key_for_action(event.key, 'pause'):
                        play_click()
                        self.popup_active = False
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.popup_ok_rect.collidepoint(event.pos):
                        play_click()
                        self.popup_active = False
                continue

            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_UP, pygame.K_w) or input_manager.is_key_for_action(event.key, 'move_up'):
                    self.selected = (self.selected - 1) % len(self.options)
                if event.key in (pygame.K_DOWN, pygame.K_s) or input_manager.is_key_for_action(event.key, 'move_down'):
                    self.selected = (self.selected + 1) % len(self.options)
                if input_manager.is_key_for_action(event.key, 'interact') or event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    play_click()
                    return self.handle_choice(self.options[self.selected])
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for name, rect in corner.items():
                    if rect.collidepoint(event.pos):
                        play_click()
                        if name == 'SETTINGS':
                            self.open_settings()
                        else:
                            self.open_help()
                        return None
                for i, option in enumerate(self.options):
                    if self.button_images:
                        btn_img = self.button_images['normal']
                        btn_rect = btn_img.get_rect(center=(sw / 2, self.BTN_START_Y + i * self.BTN_SPACING))
                        if btn_rect.collidepoint(event.pos):
                            play_click()
                            return self.handle_choice(option)
                    else:
                        text_surf = self.option_font.render(option, False, 'White')
                        text_rect = text_surf.get_rect(center=(sw / 2, self.BTN_START_Y + i * self.BTN_SPACING))
                        if text_rect.collidepoint(event.pos):
                            play_click()
                            return self.handle_choice(option)
            if event.type == pygame.MOUSEMOTION:
                self.corner_hover = next(
                    (name for name, rect in corner.items()
                     if rect.collidepoint(event.pos)), None)
                for i, option in enumerate(self.options):
                    if self.button_images:
                        btn_img = self.button_images['normal']
                        btn_rect = btn_img.get_rect(center=(sw / 2, self.BTN_START_Y + i * self.BTN_SPACING))
                        if btn_rect.collidepoint(event.pos):
                            self.selected = i
                    else:
                        text_surf = self.option_font.render(option, False, 'White')
                        text_rect = text_surf.get_rect(center=(sw / 2, self.BTN_START_Y + i * self.BTN_SPACING))
                        if text_rect.collidepoint(event.pos):
                            self.selected = i
        return None

    def handle_choice(self, choice):
        if choice == 'NEW GAME' and save_exists():
            # Never wipe a save on a single click: ask first. YES starts fresh
            # (main deletes the old save), NO keeps it and points at CONTINUE.
            self.popup_lines = [
                'Saved game found!',
                'Starting a new game will permanently',
                'delete your old save.',
                'Choose NO to continue your old game.',
            ]
            self.popup_confirm = True
            self.popup_active = True
            return None
        if choice == 'CONTINUE' and not save_exists():
            self.show_popup(['No save file found!', 'Start a new game?'])
            return None
        return choice

    def draw_corner_buttons(self, surface, sw, sh):
        """SETTINGS (top) and HELP (below it) in the top-right corner."""
        images = self.corner_images or {}
        for name, rect in self.corner_rects(sw, sh).items():
            hovered = self.corner_hover == name
            art = images.get(name)
            if art:
                # label is baked into the sprite
                surface.blit(art['selected'] if hovered else art['normal'], rect)
                continue
            # art missing: plain button with the label drawn on top
            pygame.draw.rect(surface, (58, 90, 32) if hovered else (0, 0, 0), rect, 0, 10)
            pygame.draw.rect(surface, (90, 130, 60) if hovered else (120, 120, 120), rect, 2, 10)
            text = self.corner_font.render(name, False, '#FFD700' if hovered else '#FFFFFF')
            surface.blit(text, text.get_rect(center=rect.center))

    def draw_title(self, surface, sw, sh):
        if self.logo:
            # scale logo wide to fill most of the screen width
            max_w = int(sw * 0.95)
            max_h = 320
            lw, lh = self.logo.get_size()
            scale = min(max_w / lw, max_h / lh)
            if scale != 1.0:
                logo = pygame.transform.smoothscale(self.logo, (int(lw * scale), int(lh * scale)))
            else:
                logo = self.logo
            logo_rect = logo.get_rect(center=(sw / 2, 180))
            surface.blit(logo, logo_rect)
        else:
            title_text = self.font.render('PYDEW VALLEY', False, '#FFFFFF')
            title_rect = title_text.get_rect(center=(sw / 2, 170))
            surface.blit(title_text, title_rect)

    def draw_menu_options(self, surface, sw, sh):
        if self.popup_active:
            self.draw_popup(surface, sw, sh)
            return

        for i, option in enumerate(self.options):
            hover = i == self.selected

            if self.button_images:
                btn_img = self.button_images['selected'] if hover else self.button_images['normal']
                btn_rect = btn_img.get_rect(center=(sw / 2, self.BTN_START_Y + i * self.BTN_SPACING))
                surface.blit(btn_img, btn_rect)
                text_surf = self.option_font.render(option, False, '#5C3A1E')
                text_rect = text_surf.get_rect(center=btn_rect.center)
                surface.blit(text_surf, text_rect)
            else:
                color = '#FFD700' if hover else '#FFFFFF'
                text_surf = self.option_font.render(option, False, color)
                text_rect = text_surf.get_rect(center=(sw / 2, self.BTN_START_Y + i * self.BTN_SPACING))
                bg_rect = text_rect.inflate(60, 24)
                bg_color = (58, 90, 32) if hover else (0, 0, 0)
                pygame.draw.rect(surface, bg_color, bg_rect, 0, 10)
                surface.blit(text_surf, text_rect)

        hint = ui_font(20).render(
            'Use arrow keys to navigate, Enter to select', False, '#DDDDDD')
        hint_rect = hint.get_rect(center=(sw / 2, sh - 40))
        hint_bg = pygame.Surface((hint_rect.width + 20, hint_rect.height + 8), pygame.SRCALPHA)
        pygame.draw.rect(hint_bg, (0, 0, 0, 80), (0, 0, hint_rect.width + 20, hint_rect.height + 8), 0, 6)
        surface.blit(hint_bg, (hint_rect.x - 10, hint_rect.y - 4))
        surface.blit(hint, hint_rect)

    def draw_popup(self, surface, sw, sh):
        if self._cached_popup_overlay is None or self._cached_popup_overlay.get_size() != (sw, sh):
            self._cached_popup_overlay = pygame.Surface((sw, sh))
            self._cached_popup_overlay.set_alpha(180)
            self._cached_popup_overlay.fill('black')
        surface.blit(self._cached_popup_overlay, (0, 0))

        if self.popup_confirm:
            self._draw_confirm_popup(surface, sw, sh)
            return

        lines = [self.popup_font.render(text, False, 'White')
                 for text in self.popup_lines]
        rects = [line.get_rect(center=(sw / 2, sh / 2 - 50 + i * 40))
                 for i, line in enumerate(lines)]

        box_rect = rects[0].unionall(rects[1:]).inflate(60, 50) \
            if rects else pygame.Rect(sw / 2 - 120, sh / 2 - 90, 240, 120)
        pygame.draw.rect(surface, (40, 40, 40), box_rect, 0, 12)
        pygame.draw.rect(surface, (100, 100, 100), box_rect, 2, 12)

        for line, rect in zip(lines, rects):
            surface.blit(line, rect)

        self.popup_ok_rect.center = (sw / 2, sh / 2 + 60)
        if self.ok_button_img:
            ok_btn = self.ok_button_img.get_rect(center=(sw / 2, sh / 2 + 60))
            self.popup_ok_rect = ok_btn
            surface.blit(self.ok_button_img, ok_btn)
            ok_surf = self.popup_font.render('OK', False, '#5C3A1E')
            ok_rect = ok_surf.get_rect(center=ok_btn.center)
            surface.blit(ok_surf, ok_rect)
        else:
            pygame.draw.rect(surface, (58, 90, 32), self.popup_ok_rect, 0, 8)
            pygame.draw.rect(surface, (90, 130, 60), self.popup_ok_rect, 2, 8)
            ok_surf = self.popup_font.render('OK', False, 'White')
            ok_rect = ok_surf.get_rect(center=self.popup_ok_rect.center)
            surface.blit(ok_surf, ok_rect)

    def _draw_confirm_popup(self, surface, sw, sh):
        """New-game overwrite warning in the debug menu's YES/NO style."""
        lines = [self.popup_font.render(text, False, (240, 230, 200))
                 for text in self.popup_lines]
        scale = ui_scale()
        line_h = max(line.get_height() for line in lines) + 6
        btn_w, btn_h = int(120 * scale), int(50 * scale)
        gap = int(36 * scale)
        pad_x = int(44 * scale)
        box_w = max(int(560 * scale), max(line.get_width() for line in lines) + pad_x * 2)
        box_h = int(22 * scale) + line_h * len(lines) + int(18 * scale) + btn_h + int(20 * scale)
        box = pygame.Rect(0, 0, box_w, box_h)
        box.center = (sw // 2, sh // 2)

        pygame.draw.rect(surface, (34, 34, 40), box, 0, 12)
        pygame.draw.rect(surface, (180, 150, 70), box, 2, 12)

        y = box.y + 22
        for line in lines:
            surface.blit(line, line.get_rect(
                center=(box.centerx, y + line.get_height() // 2)))
            y += line_h

        btn_y = box.bottom - btn_h - 20
        yes = pygame.Rect(box.centerx - btn_w - gap // 2, btn_y,
                          btn_w, btn_h)
        no = pygame.Rect(box.centerx + gap // 2, btn_y, btn_w, btn_h)
        self.popup_yes_rect = yes
        self.popup_no_rect = no
        for rect, label, col in ((yes, 'YES', (63, 191, 95)),
                                 (no, 'NO', (214, 69, 69))):
            pygame.draw.rect(surface, col, rect, 0, 8)
            pygame.draw.rect(surface, (12, 12, 14), rect, 2, 8)
            text = self.popup_font.render(label, False, (20, 20, 20))
            surface.blit(text, text.get_rect(center=rect.center))

    def _advance_video(self, dt):
        """Read the next video frame sequentially (fast path, no seeking)."""
        if not self.video:
            return
        self._video_pos += dt
        frame_duration = 1.0 / self._video_fps
        if self._video_frame is not None and self._video_pos < frame_duration:
            return
        self._video_pos -= frame_duration
        ret, frame = self.video.read()
        if not ret:
            # loop: sequential re-open is cheaper than a seek on most codecs
            self.video.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.video.read()
            if not ret:
                return
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = np.transpose(frame, (1, 0, 2))
        self._video_frame = pygame.surfarray.make_surface(frame)

    def draw(self, dt):
        sw, sh = self.get_size()
        self.time_val += dt

        if self.video:
            self._advance_video(dt)
            if self._video_frame:
                bg = pygame.transform.scale(self._video_frame, (sw, sh))
                self.display_surface.blit(bg, (0, 0))
            elif self.menu_bg:
                bg = pygame.transform.scale(self.menu_bg, (sw, sh))
                self.display_surface.blit(bg, (0, 0))
            else:
                self.display_surface.fill((30, 30, 50))
        elif self.menu_bg:
            bg = pygame.transform.scale(self.menu_bg, (sw, sh))
            self.display_surface.blit(bg, (0, 0))
        else:
            self.display_surface.fill((30, 30, 50))

        for p in self.particles:
            p.update(dt)
            p.draw(self.display_surface)

        self.draw_title(self.display_surface, sw, sh)
        if self.settings_active and self.settings_menu:
            # settings owns the screen (its own dim overlay + panel)
            self.settings_menu.display()
            return
        self.draw_corner_buttons(self.display_surface, sw, sh)
        self.draw_menu_options(self.display_surface, sw, sh)

    async def run(self):
        clock = pygame.time.Clock()
        if self.menu_music:
            self.menu_music.play(loops=-1)
        try:
            while True:
                dt = clock.tick(60) / 1000
                result = self.input()
                if result:
                    return result
                self.draw(dt)
                pygame.display.update()
                # Hand control back to the event loop once per frame.
                await asyncio.sleep(0)
        finally:
            # QUIT calls pygame.quit() before sys.exit(), so the mixer may
            # already be down. Guard every teardown call.
            if self.menu_music is not None and pygame.mixer.get_init():
                self.menu_music.stop()
            if self.video is not None:
                try:
                    self.video.release()
                except Exception:
                    # Release is best-effort; a missing/closed decoder must
                    # not raise out of the shutdown path.
                    pass
