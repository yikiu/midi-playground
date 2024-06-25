from utils import *
import pygame
from world import World
import random
from camera import Camera
from keystrokes import Keystrokes
from particle import Particle
from zipfile import ZipFile
import math


class Game:
    def __init__(self):
        self.active = False
        self.notes = []
        self.camera = Camera()
        self.world = World()
        self.safe_areas: list[pygame.Rect] = []
        self.camera_ctrl_text = get_font(24).render("Manual Camera Control Activated", True, (0, 255, 0))
        self.music_has_played = False
        self.offset_happened = False
        self.loading_text = get_font(24).render("Loading...", True, (255, 255, 255))
        self.keystrokes = Keystrokes()
        self.misses = 0
        self.mouse_down = False
        self.hitted_rectangles = []                           

    def start_song(self, screen: pygame.Surface):
        random.seed(Config.seed)

        # load song and notes
        with ZipFile(Config.current_song.fp) as zf:
            if Config.current_song.fp.lower().endswith(".osz"):
                # Config.music_offset = 0
                notes = read_osu_file(filedata=zf.read(Config.current_song.song_file_name))
            else:
                with zf.open(Config.current_song.song_file_name) as f:
                    notes = read_midi_file(file=f)
        notes = [note for note in notes]
        self.notes = notes

        # other settings

        self.world = World()
        self.music_has_played = False
        self.offset_happened = False
        self.camera.lock_type = CameraFollow(Config.camera_mode)
        screen.fill(get_colors()["background"])
        information_texts = [
            "Map loading stuck at some percentage? Try changing the \"Square speed\" in the config",
            "Also try changing the \"Change dir chance\" and the \"Bounce min spacing\"",
            "",
            "Too large maps will crash the program, so try with some smaller ones first",
            "",
            "Don't want to play the game? Turn on \"Theatre mode\" in the config",
            "",
            "Music off-sync? Change the \"Music offset\" in the settings"
        ]
        for index, info_text in enumerate(information_texts):
            rendered_text = get_font(24).render(info_text, True, get_colors()["hallway"])
            screen.blit(rendered_text, (50, 200 + 30 * index))
        pygame.display.flip()

        def update_loading_screen(message: str):
            screen.fill(get_colors()["background"], pygame.Rect(0, 0, Config.SCREEN_WIDTH, 100))
            screen.blit(get_font(60).render(message, True, get_colors()["hallway"]), (10, 10))
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return 1
            update_screen(Config.screen, Config.glsl_program, Config.render_object)

        try:
            self.safe_areas = self.world.gen_future_bounces(self.notes, update_loading_screen)
            self.safe_areas = fix_overlap(self.safe_areas, update_loading_screen)
        except UserCancelsLoadingError:
            return True
        except MapLoadingFailureError as e:
            return e.args[0] if len(e.args) else "Big error... can't load map :("
        self.world.start_time = get_current_time()
        self.world.square.dir = [0, 0]
        self.world.square.pos = self.world.future_bounces[0].square_pos

    def draw(self, screen: pygame.Surface, n_frames: int):
        colors = list(Config.color_themes.values())
        if not self.active:
            return

        if not self.music_has_played:
            if not self.offset_happened:
                for bnc_change in self.world.future_bounces:
                    bnc_change.time += Config.start_playing_delay / 1000
            self.offset_happened = True
            if self.world.time-Config.current_song.music_offset/1000 > Config.start_playing_delay/1000:
                self.music_has_played = True
                song_load_before = get_current_time()
                pygame.mixer.music.play()
                for bnc_change in self.world.future_bounces:
                    bnc_change.time += (get_current_time()-song_load_before)/1000

        screen_rect = screen.get_rect()

        # set world time
        self.world.update_time()

        # move camera (only works if not locked on square)
        self.camera.attempt_movement()

        # handle square bounces
        self.world.handle_bouncing(self.world.square)

        # move square
        self.world.square.reg_move()

        # square in center of camera if locked
        if self.camera.locked_on_square:
            self.camera.follow(self.world.square)

        # bounce anim
        sqrect = self.camera.offset(self.world.square.rect)
        if (self.world.time - 0.25) + Config.music_offset / 1000 < self.world.square.last_bounce_time:
            lerp = abs((self.world.time - 0.25 + Config.music_offset / 1000) - self.world.square.last_bounce_time) * 5
            lerp = lerp ** 2  # square it for better-looking interpolation
            if self.world.square.latest_bounce_direction:
                sqrect.inflate_ip((lerp * 5, -10 * lerp))
            else:
                sqrect.inflate_ip((-10 * lerp, lerp * 5))

        # safe areas
        total_rects = 0
        for safe_area in self.safe_areas:
            offsetted = self.camera.offset(safe_area)
            if screen_rect.colliderect(offsetted):
                total_rects += 1
                pygame.draw.rect(screen, get_colors()["hallway"], offsetted)

        # draw pegs
        for i, bounce_rect in enumerate(self.world.rectangles):
            offsetted = self.camera.offset(bounce_rect)

            if offsetted.colliderect(screen_rect):
                total_rects += 1
                if Config.do_color_bounce_pegs and self.world.collision_times[i] < (self.world.time * 1000 + Config.music_offset - Config.start_playing_delay)/1000:
                    pygame.draw.rect(screen, self.world.colors[i], offsetted)
                else:
                    pygame.draw.rect(screen, get_colors()["background"], offsetted)

        # particles
        # 这些是方框周围的点
        for particle in self.world.particles:
            pygame.draw.rect(screen, particle.color, self.camera.offset(particle.rect))
        for remove_particle in [particle for particle in self.world.particles if particle.age()]:
            self.world.particles.remove(remove_particle)

        # particle trail in game
        if Config.particle_trail:
            # every 2 frames add a particle
            if not self.world.square.died:
                if n_frames % 2 == 0:
                    square_center=self.world.square.pos
                    direction = [0, 0]
                    color=random.choice(colors)
                    new = Particle(square_center,direction, color=color,invert_color=True)
                    new.delta = [random.randint(-10, 10)/20, random.randint(-10, 10)/20]
                    self.world.particles.append(new)
                
        # scorekeeper drawing
        time_from_start = self.world.time-Config.start_playing_delay/1000+Config.music_offset/1000
        if not Config.theatre_mode:
            self.misses = self.world.scorekeeper.draw(screen, time_from_start if len(self.world.future_bounces) else -1, self.misses)

            # hit icons
            to_remove = []
            for hiticon in self.world.scorekeeper.hit_icons:
                if hiticon.draw(screen, self.camera):
                    to_remove.append(hiticon)
            for remove in to_remove:
                self.world.scorekeeper.hit_icons.remove(remove)

            if self.world.scorekeeper.hp <= 0 and not self.world.square.died:
                self.world.square.died = True
                self.world.square.dir = [0, 0]
                pygame.mixer.music.stop()
                play_sound("death.mp3", 0.5)
                self.world.future_bounces = []
                for _ in range(100):
                    self.world.particles.append(Particle(self.world.square.pos, [random.randint(-3, 3), random.randint(-3, 3)]))
            if self.world.square.died:
                self.world.scorekeeper.hp = 0

        # draw square
        self.world.square.draw(screen, sqrect)

        if not Config.theatre_mode:
            # keystrokes
            self.keystrokes.draw(screen)

            # countdown to start
            if time_from_start < 0:
                repr_time = f"{abs(int((time_from_start+0.065)*10)/10)}s"
                countdown_surface = get_font(36).render(repr_time, True, (255, 255, 255))
                screen.blit(countdown_surface, countdown_surface.get_rect(center=(Config.SCREEN_WIDTH / 2, Config.SCREEN_HEIGHT / 4)))
            elif time_from_start < 0.5:
                repr_zero = f"0.0s"
                countdown_surface = get_font(36).render(repr_zero, True, (255, 255, 255))
                countdown_surface.set_alpha((0.5-time_from_start)*2*255)
                screen.blit(countdown_surface, countdown_surface.get_rect(center=(Config.SCREEN_WIDTH / 2, Config.SCREEN_HEIGHT / 4)))

            # handle mouse clicks because self.handle_event doesn't get called for mouse clicks
            if pygame.mouse.get_pressed()[0] and not self.mouse_down:
                self.misses = self.world.handle_keypress(time_from_start, self.misses)
                self.mouse_down = True
            elif not pygame.mouse.get_pressed()[0]:
                self.mouse_down = False
            
            # draw accuracy
            # noinspection PyBroadException
            try:
                n_bounces = len(self.world.past_bounces)
                n_total_bounces = len(self.world.past_bounces)+len(self.world.future_bounces)
                if n_bounces > 0:
                    n_misses = self.misses
                    acc = round((n_bounces-n_misses)/n_bounces*100, 2)
                    acct = round((n_total_bounces-n_misses)/n_total_bounces*100, 2)
                    # clamp to 0-100
                    acc = max(0, min(100, acc))
                    acct = max(0, min(100, acct))
                    acc_text = get_font(24).render(f"Accuracy: {acc}%", True, (255, 255, 255))
                    acct_text = get_font(24).render(f"Total Accuracy: {acct}%", True, (255, 255, 255))
                    topleft1 = self.world.scorekeeper.life_bar_rect.move(0, 10).bottomleft
                    screen.blit(acc_text, acc_text.get_rect(topleft=topleft1))
                    screen.blit(acct_text, acct_text.get_rect(topleft=acc_text.get_rect(topleft=topleft1).move(0, 10).bottomleft))
            except ZeroDivisionError:
                pass
            except Exception:
                pass

            # failure message
            if self.world.square.died:
                # calculate accuracy
                n_bounces = len(self.world.past_bounces)
                n_total_bounces = len(self.world.past_bounces)+len(self.world.future_bounces)
                # clamp bounces to 1-infinity
                n_bounces = max(1, n_bounces)
                n_total_bounces = max(1, n_total_bounces)
                n_misses = self.misses

                acc = round((n_bounces-n_misses)/n_bounces*100, 2)
                acct = round((n_total_bounces-n_misses)/n_total_bounces*100, 2)

                # clamp to 0-100
                acc = max(0, min(100, acc))
                acct = max(0, min(100, acct))

                try_again_text = get_font(36).render("Press escape to go back.", True, (255, 255, 255))
                acc_text = get_font(36).render(f"Accuracy: {acc}%", True, (255, 255, 255))
                acct_text = get_font(36).render(f"Total Accuracy: {acct}%", True, (255, 255, 255))
                screen.blit(try_again_text, try_again_text.get_rect(center=(Config.SCREEN_WIDTH / 2, Config.SCREEN_HEIGHT / 4)))
                screen.blit(acc_text, acc_text.get_rect(center=(Config.SCREEN_WIDTH / 2, Config.SCREEN_HEIGHT / 4 + 50)))
                screen.blit(acct_text, acct_text.get_rect(center=(Config.SCREEN_WIDTH / 2, Config.SCREEN_HEIGHT / 4 + 100)))

        if not self.camera.locked_on_square:
            screen.blit(self.camera_ctrl_text, (10, 10))

    def handle_event(self, event: pygame.event.Event):
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return True
            if event.key == pygame.K_TAB:
                self.camera.locked_on_square = not self.camera.locked_on_square
            if not Config.theatre_mode:
                if self.camera.locked_on_square:
                    time_from_start = self.world.time-Config.start_playing_delay/1000+Config.music_offset/1000
                    if time_from_start < -0.2:
                        return
                    arrows_n_space = (pygame.K_SPACE, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN)

                    if 97+26 > event.key >= 97 or event.key in arrows_n_space:  # press a to z key or space or arrows
                        self.misses = self.world.handle_keypress(time_from_start, self.misses)
                   