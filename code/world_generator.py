import pygame
import math
import glob
import os
import numpy as np
from settings import *
from sprites import (Tree, WildFlower, Generic, Water, WaterCollider, Rock,
                     Bush, GroundTile, Interaction)
from support import import_folder, visible_bottom_pad, clean_sprite_background, log_once
from collision import (structure_footprint, structure_blockers,
                       structure_outline_blockers, structure_front_tiles,
                       occluded_stand_tiles)
from random import Random, choice

# ---- CHUNK / TILE CONSTANTS ----
CHUNK_SIZE = 1024
CHUNK_RADIUS = 3
TILE = 128
TILES_PER_CHUNK = CHUNK_SIZE // TILE
EDGE_BLEND = 64

# ---- PERLIN NOISE IMPLEMENTATION ----

class PerlinNoise:
    """2D Perlin noise using gradient vectors and Hermite interpolation.
    Deterministic: same seed produces identical output everywhere."""

    def __init__(self, seed=0):
        rng = np.random.RandomState(seed)
        # Permutation table: shuffled 0-255 repeated
        p = np.arange(256, dtype=int)
        rng.shuffle(p)
        self.perm = np.concatenate([p, p])

        # Precomputed 2D Perlin gradient vectors (8 compass directions).
        self.grads = np.array([
            [1, 0], [-1, 0], [0, 1], [0, -1],
            [1, 1], [-1, 1], [1, -1], [-1, -1]
        ], dtype=float)
        self.grad_indices = rng.randint(0, 8, size=256)

    def _dot_grid_gradient(self, ix, iy, x, y):
        """Dot product of distance vector with gradient at grid point."""
        idx = self.perm[(self.perm[ix & 255] + iy) & 255] & 7
        gx, gy = self.grads[idx]
        dx, dy = x - ix, y - iy
        return dx * gx + dy * gy

    def _fade(self, t):
        """Hermite interpolation curve: 6t^5 - 15t^4 + 10t^3"""
        return t * t * t * (t * (t * 6 - 15) + 10)

    def noise(self, x, y):
        """Single-octave 2D Perlin noise. Returns value in approx [-1, 1]."""
        ix = int(math.floor(x))
        iy = int(math.floor(y))
        fx, fy = x - ix, y - iy

        u = self._fade(fx)
        v = self._fade(fy)

        n00 = self._dot_grid_gradient(ix, iy, x, y)
        n10 = self._dot_grid_gradient(ix + 1, iy, x, y)
        n01 = self._dot_grid_gradient(ix, iy + 1, x, y)
        n11 = self._dot_grid_gradient(ix + 1, iy + 1, x, y)

        nx0 = n00 + u * (n10 - n00)
        nx1 = n01 + u * (n11 - n01)
        return nx0 + v * (nx1 - nx0)

    def fractal(self, x, y, octaves=4, persistence=0.5, lacunarity=2.0, scale=1.0):
        """Multi-octave fractal Brownian motion (fBm).
        Returns value normalized to [0, 1]."""
        total = 0.0
        amplitude = 1.0
        frequency = scale
        max_amp = 0.0
        for i in range(octaves):
            total += amplitude * self.noise(x * frequency, y * frequency)
            max_amp += amplitude
            amplitude *= persistence
            frequency *= lacunarity
        return (total / max_amp + 1.0) * 0.5  # remap [-1,1] - [0,1]

    def noise_grid(self, x, y):
        """Vectorized ``noise`` for numpy coordinate arrays.
        Same arithmetic and operation order as the scalar path, so the values are
        bit-identical and existing saves keep their terrain.
        """
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        ix = np.floor(x).astype(np.int64)
        iy = np.floor(y).astype(np.int64)
        fx = x - ix
        fy = y - iy
        u = fx * fx * fx * (fx * (fx * 6 - 15) + 10)
        v = fy * fy * fy * (fy * (fy * 6 - 15) + 10)

        perm = self.perm
        gx_tab = np.ascontiguousarray(self.grads[:, 0])
        gy_tab = np.ascontiguousarray(self.grads[:, 1])

        def dot(ox, oy):
            idx = perm[(perm[ox & 255] + oy) & 255] & 7
            return (x - ox) * gx_tab[idx] + (y - oy) * gy_tab[idx]

        n00 = dot(ix, iy)
        n10 = dot(ix + 1, iy)
        n01 = dot(ix, iy + 1)
        n11 = dot(ix + 1, iy + 1)

        nx0 = n00 + u * (n10 - n00)
        nx1 = n01 + u * (n11 - n01)
        return nx0 + v * (nx1 - nx0)

    def fractal_grid(self, x, y, octaves=4, persistence=0.5,
                     lacunarity=2.0, scale=1.0):
        """Vectorized ``fractal`` over numpy coordinate arrays.
        All octaves are sampled in one noise_grid call and folded in the same
        order as the scalar loop, keeping values bit-identical.
        """
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        shape = x.shape
        amps = []
        xs = []
        ys = []
        amplitude = 1.0
        frequency = scale
        max_amp = 0.0
        for _ in range(octaves):
            amps.append(amplitude)
            xs.append((x * frequency).ravel())
            ys.append((y * frequency).ravel())
            max_amp += amplitude
            amplitude *= persistence
            frequency *= lacunarity
        n = self.noise_grid(np.concatenate(xs), np.concatenate(ys))
        step = x.size
        total = amps[0] * n[:step]
        for i in range(1, octaves):
            total = total + amps[i] * n[i * step:(i + 1) * step]
        return ((total / max_amp + 1.0) * 0.5).reshape(shape)


# ---- DETERMINISTIC WHITE NOISE ----

def white_noise(x, y, seed=0):
    """Deterministic white noise. Same (x,y,seed) always returns same [0,1] value.
    Used for small-scale visual variation, NOT terrain structure."""
    h = (x * 374761393 + y * 668265263 + seed * 1274126177) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h & 0xFFFF) / 0xFFFF


def white_noise_grid(x, y, seed=0):
    """Vectorized ``white_noise`` over numpy integer arrays.
    The 32-bit masks make the numpy arithmetic wrap exactly like the Python
    version, so values match bit for bit.
    """
    x = np.asarray(x, dtype=np.int64)
    y = np.asarray(y, dtype=np.int64)
    h = (x * 374761393 + y * 668265263 + seed * 1274126177) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h & 0xFFFF) / 0xFFFF


def _det_hash(*args):
    """Deterministic hash for arbitrary arguments."""
    h = 0
    for a in args:
        if isinstance(a, str):
            for c in a:
                h = (h * 31 + ord(c)) & 0xFFFFFFFF
        else:
            h = (h * 31 + (a & 0xFFFFFFFF)) & 0xFFFFFFFF
    return h


# ---- COORDINATE HELPERS ----

def grid_to_iso(gx, gy):
    """Convert grid coordinates to isometric screen coordinates"""
    x = (gx - gy) * (ISO_TILE_WIDTH // 2)
    y = (gx + gy) * (ISO_TILE_HEIGHT // 2)
    return x, y

def iso_to_grid(iso_x, iso_y):
    """Convert isometric screen coordinates back to grid coordinates"""
    gx = (iso_x / (ISO_TILE_WIDTH // 2) + iso_y / (ISO_TILE_HEIGHT // 2)) / 2
    gy = (iso_y / (ISO_TILE_HEIGHT // 2) - iso_x / (ISO_TILE_WIDTH // 2)) / 2
    return gx, gy

def world_to_grid(wx, wy):
    """Convert world pixel coordinates to grid coordinates"""
    return wx // TILE, wy // TILE

def grid_to_world(gx, gy):
    """Convert grid coordinates to world pixel coordinates"""
    return gx * TILE, gy * TILE


# ---- TERRAIN TYPE CONSTANTS ----

WATER_COLOR = (60, 130, 190)


_PATH_ART_CACHE = None


def _load_path_art():
    """Village path art pieces (graphics/world/Path*.png): slab runs along each
    grid axis, a 4-way cross and its four quarter slabs. None when any file
    is missing, so callers can fall back to procedural tiles.
    """
    global _PATH_ART_CACHE
    if _PATH_ART_CACHE is not None:
        return _PATH_ART_CACHE or None

    def _load(name):
        try:
            return pygame.image.load(
                asset_path('graphics', 'world', name)).convert_alpha()
        except (pygame.error, FileNotFoundError):
            return None

    art = {'x': _load('Path.png'), 'y': _load('Path1.png'),
           'cross': _load('Path_intersection.png'), 'quads': {}}
    if art['x'] is None or art['y'] is None or art['cross'] is None:
        _PATH_ART_CACHE = {}
        return None
    cross = art['cross']
    cw, ch = cross.get_size()
    mask = pygame.mask.from_surface(cross)
    seen = bytearray(cw * ch)
    for y0 in range(ch):
        for x0 in range(cw):
            start = y0 * cw + x0
            if seen[start] or not mask.get_at((x0, y0)):
                continue
            seen[start] = 1
            stack = [(x0, y0)]
            pts = []
            while stack:
                x, y = stack.pop()
                pts.append((x, y))
                i = y * cw + x
                if x > 0 and not seen[i - 1] and mask.get_at((x - 1, y)):
                    seen[i - 1] = 1
                    stack.append((x - 1, y))
                if x + 1 < cw and not seen[i + 1] and mask.get_at((x + 1, y)):
                    seen[i + 1] = 1
                    stack.append((x + 1, y))
                if y > 0 and not seen[i - cw] and mask.get_at((x, y - 1)):
                    seen[i - cw] = 1
                    stack.append((x, y - 1))
                if y + 1 < ch and not seen[i + cw] and mask.get_at((x, y + 1)):
                    seen[i + cw] = 1
                    stack.append((x, y + 1))
            xa = min(p[0] for p in pts)
            xb = max(p[0] for p in pts)
            ya = min(p[1] for p in pts)
            yb = max(p[1] for p in pts)
            slab = pygame.Surface((cw, ch), pygame.SRCALPHA)
            for x, y in pts:
                slab.set_at((x, y), cross.get_at((x, y)))
            cx = (xa + xb) // 2 - cw // 2
            cy = (ya + yb) // 2 - ch // 2
            if abs(cx) > abs(cy):
                key = 'E' if cx > 0 else 'W'
            else:
                key = 'S' if cy > 0 else 'N'
            art['quads'][key] = slab
    if len(art['quads']) != 4:
        art['quads'] = {}
    _PATH_ART_CACHE = art
    return art


# ---- WORLD GENERATOR ----

class WorldGenerator:
    def __init__(self, all_sprites, collision_sprites, tree_sprites, rock_sprites,
                 bush_sprites, flower_sprites, player_add, interaction_sprites=None,
                 seed=None):
        self.all_sprites = all_sprites
        self.collision_sprites = collision_sprites
        self.tree_sprites = tree_sprites
        self.rock_sprites = rock_sprites
        self.bush_sprites = bush_sprites
        self.flower_sprites = flower_sprites
        self.player_add = player_add
        # Cave-entrance trigger group; when given, entrances spawn per sector.
        self.interaction_sprites = interaction_sprites
        self._entrance_sector_cache = {}   # (sx, sy) -> (gx, gy) or None
        self._entrance_reserve_cache = {}  # (cx, cy) -> set of reserved tiles
        self.active_chunks = {}
        self._chunk_surfs = {}
        # Streaming chunk state [key, next_stage, sprites]; one stage runs per frame.
        self._staged_chunk = None
        # World seed: every decision is a pure function of it; None keeps the legacy.
        self.seed = WORLD_SEED if seed is None else seed
        # Felled natural trees stay felled and planted tiles stay planted; survives reset().
        self.removed_tree_ids = set()
        self.removed_debris_ids = set()
        self.removed_rock_ids = set()
        self.planted_tiles = set()
        # Nonce feeding the bush placement hash (rerolls every 5 days); trees never reroll.
        self.bush_refresh_nonce = 0
        self._bush_days = 0
        self.player = None

        # Level assigns the VillageGenerator here; it adds land/paths and reserves tiles.
        self.village_gen = None
        self._village_land = set()
        self._path_tiles = set()

        # Terrain cache: eliminates redundant Perlin evaluations
        self._terrain_cache = {}
        self._biome_cache = {}
        # Raw noise memos (pure per-tile); chunk gen prewarms blocks, readers just look up.
        self._lake_cache = {}
        self._river_cache = {}
        self._moisture_cache = {}
        self._detail_cache = {}
        # (cx, cy) -> placable-tile list, shared by all chunk placers
        self._non_water_cache = {}
        # (cx,cy) -> [(gx,gy,deco_surf)] water decos, deterministic via per-chunk rng.
        self._water_deco_cache = {}
        self._farm_patch_cache = {}  # (cx,cy) -> set of (tx, ty) farm-patched tiles
        # Tilled+watered tiles rendered via the farm-patch overlay pipeline.
        self._soil_water_cache = {}  # (cx,cy) -> {(tx,ty): surf}
        self._soilw_tile_map = {}    # (gx,gy) -> surf mirror, rebuilt on dirty
        self._soil_water_pool = None
        # Tile-keyed mirrors of the caches, rebuilt only on the dirty flag.
        self._wdeco_tile_map = {}
        self._patch_tile_map = {}
        self._ground_maps_dirty = True
        self._ground_pools = None
        # Surface -> minimal non-transparent src rect (diamond art is half-transparent).
        self._surf_bounds = {}

        # Create Perlin noise generators (different seeds for different layers)
        self.perlin_moisture = PerlinNoise(seed=self.seed)
        self.perlin_detail = PerlinNoise(seed=self.seed + 100)
        self.perlin_river = PerlinNoise(seed=self.seed + 200)
        self.perlin_object = PerlinNoise(seed=self.seed + 300)
        self.perlin_deco = PerlinNoise(seed=self.seed + 500)
        # Low-frequency blobs -> biome regions (Minecraft-style)
        self.perlin_biome = PerlinNoise(seed=self.seed + 600)
        # Lake basins: high band of a separate low-frequency noise.
        self.perlin_lake = PerlinNoise(seed=self.seed + 700)

        # Load sprite assets
        self._load_assets()

    def _load_assets(self):
        """Load sprite assets for every biome plus shared world art."""
        self.biome_assets = {name: self._load_biome_assets(name, cfg)
                             for name, cfg in BIOMES.items()}

        # Rock surfaces (shared across biomes)
        self.rock_surfs = []
        try:
            self.rock_surfs.append(pygame.image.load(asset_path('graphics', 'world', 'rocks.png')).convert_alpha())
        except Exception as exc:  # missing art: procedural fallback, but say why
            print(f"[WorldGen] rocks.png load failed, using procedural rock: {exc!r}")
            s = pygame.Surface((48, 48), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (150, 145, 135), (4, 4, 40, 40))
            self.rock_surfs.append(s)

        # Water frames (isometric)
        self.iso_water_frames = self._load_iso_water_frames()

        # The ONE cave-entry art (Cave_Entry.png), original size, shared by all doorways.
        self.entrance_surf = self._load_entrance_surf('Cave_Entry.png')
        # Authored doorway collision mask (Cave_collision.png): the source of truth.
        self.entrance_collision_surf = self._load_entrance_collision_surf(
            'Cave_collision.png')
        # Shared invisible surface for collision-only sprites (villages use one too).
        self._invisible = pygame.Surface((8, 8), pygame.SRCALPHA)
        # Outline blockers trace the authored mask exactly like village buildings:
        # thin 8px ground rows, projected once and reused by every doorway, with
        # the doorstep carved out so the entrance stays walkable.
        self._entrance_outline = []
        if self.entrance_collision_surf is not None:
            pad = (visible_bottom_pad(self.entrance_collision_surf)
                   + TILE_SIZE // 16)
            self._entrance_outline = structure_outline_blockers(
                self.entrance_collision_surf, pad, 0, 0,
                step=STRUCTURE_COLLISION_STEP,
                hole=pygame.Rect(-TILE_SIZE // 2, -TILE_SIZE // 2,
                                 TILE_SIZE, TILE_SIZE))
        # Missing-mask fallback only: whole-tile footprint + art occlusion.
        self._entrance_foot = (None if self._entrance_outline
                               else self._entrance_footprint_for(
                                   self.entrance_surf, self.entrance_surf))

        # Farm patch tile (lazy-loaded)
        self._farm_patch_iso = None

        # Village path slabs picked by angle; procedural dirt tiles as fallback.
        self.path_art = _load_path_art()
        self.path_surfs = [] if self.path_art else self._build_path_surfs()

    def _build_path_surfs(self):
        """Diamond dirt overlays for village paths: base fill, darker
        rim and deterministic pebble speckles, one set per world seed."""
        hw = ISO_TILE_WIDTH // 2
        hh = ISO_TILE_HEIGHT // 2
        pool = []
        for i in range(4):
            surf = pygame.Surface((ISO_TILE_WIDTH, ISO_TILE_HEIGHT),
                                  pygame.SRCALPHA)
            outer = [(hw, 0), (ISO_TILE_WIDTH, hh),
                     (hw, ISO_TILE_HEIGHT), (0, hh)]
            pygame.draw.polygon(surf, (150, 116, 76), outer)
            inner = [(hw, 4), (ISO_TILE_WIDTH - 6, hh),
                     (hw, ISO_TILE_HEIGHT - 4), (6, hh)]
            pygame.draw.polygon(surf, (176, 142, 96), inner)
            rng = Random(self.seed + 730 + i)
            placed = 0
            while placed < 24:
                rx = rng.randint(6, ISO_TILE_WIDTH - 6)
                ry = rng.randint(4, ISO_TILE_HEIGHT - 4)
                if abs(rx - hw) / hw + abs(ry - hh) / hh > 0.82:
                    continue
                placed += 1
                color = rng.choice(((158, 122, 82), (196, 165, 120),
                                    (166, 132, 88)))
                pygame.draw.circle(surf, color, (rx, ry), rng.randint(1, 3))
            pool.append(surf)
        return pool

    def _path_surf_at(self, gx, gy):
        """Variant pick for one path tile (stable per tile)."""
        pool = self.path_surfs
        if not pool:
            return None
        idx = int(white_noise(gx, gy, self.seed + 707) * len(pool))
        return pool[idx % len(pool)]

    def _path_pieces_at(self, gx, gy):
        """Overlay pieces for one village path tile, picked by the path's angle: the
        straight slab of its grid axis, quarter slabs for corners, the full cross
        where three or more route tiles meet.
        """
        paths = self._path_tiles
        nx = (gx - 1, gy) in paths
        px = (gx + 1, gy) in paths
        ny = (gx, gy - 1) in paths
        py = (gx, gy + 1) in paths
        art = self.path_art
        if art:
            if nx or px:
                if ny or py:
                    if nx + px + ny + py >= 3 or not art['quads']:
                        return (art['cross'],)
                    needed = set()
                    if nx:
                        needed.update(('N', 'W'))
                    if px:
                        needed.update(('E', 'S'))
                    if ny:
                        needed.update(('N', 'E'))
                    if py:
                        needed.update(('S', 'W'))
                    return tuple(art['quads'][k] for k in ('N', 'E', 'S', 'W')
                                 if k in needed)
                return (art['x'],)
            if ny or py:
                return (art['y'],)
        psurf = self._path_surf_at(gx, gy)
        return (psurf,) if psurf is not None else ()

    def _load_entrance_surf(self, name='Cave_Entry.png'):
        """Cave-entry art converted in place at its ORIGINAL size -
        no trim, no rescale."""
        try:
            return pygame.image.load(
                asset_path('graphics', 'Caves', name)).convert_alpha()
        except (pygame.error, FileNotFoundError):
            return None

    def _load_entrance_collision_surf(self, name='Cave_collision.png'):
        """Authored collision mask for the cave doorway, at its
        ORIGINAL size - no trim, no rescale."""
        try:
            s = pygame.image.load(
                asset_path('graphics', 'world', 'Collisions', name)).convert_alpha()
            clean_sprite_background(s)
            return s
        except (pygame.error, FileNotFoundError):
            return None

    def _entrance_footprint_for(self, surf, art=None):
        """Fallback for a missing collision mask: whole-tile footprint of
        the doorway UNION the tiles where the drawn art would paint over a
        standing player (collision.occluded_stand_tiles). The normal path
        uses the authored mask's outline instead.
        """
        foot = set()
        if surf is not None:
            pad = visible_bottom_pad(surf) + TILE_SIZE // 16
            foot |= structure_footprint(surf, pad, TILE_SIZE // 2,
                                        TILE_SIZE // 2)
        if art is not None:
            pad_art = visible_bottom_pad(art) + TILE_SIZE // 16
            for dx, dy in occluded_stand_tiles(art, pad_art):
                foot.add((dx, dy))
        return foot

    def _load_biome_assets(self, biome, cfg):
        """Load one biome's art pools from graphics/Biomes/<biome>/:
        trees, fruit tree, wood debris, bushes, flowers, ground-tile
        variants, water decos and rare props."""
        base = ('graphics', 'Biomes', biome)

        def load(name):
            if not name:
                return None
            try:
                return pygame.image.load(asset_path(*base, name)).convert_alpha()
            except Exception as exc:
                # Optional asset: a missing file just skips this entry.
                log_once(f'[WorldGen] optional asset {name!r} failed', exc)
                return None

        assets = {'name': biome, 'wood_item': cfg['wood_item']}

        # Tree surfaces
        trees = [s for s in (load(n) for n in cfg['trees']) if s]
        if not trees:
            s = pygame.Surface((64, 96), pygame.SRCALPHA)
            pygame.draw.rect(s, (80, 140, 60), (12, 0, 40, 96), 0, 8)
            trees = [s]
        assets['trees'] = trees

        # Fruit tree art, separate from trees; entry: (surf, chance, drop_item).
        fruit = cfg['fruit_tree']
        assets['fruit_tree'] = (load(fruit[0]), fruit[1], fruit[2]) if fruit else None

        # Wood debris entries: (surf, hits to cut, wood yield, foot_pad, spawn weight).
        assets['debris'] = []
        for name, health, wood_yield, weight in cfg['debris']:
            if weight <= 0:
                continue
            surf = load(name)
            if surf:
                assets['debris'].append(
                    (surf, health, wood_yield, visible_bottom_pad(surf), weight))

        # Flower/fungus surfaces paired with their item (the art file stem).
        assets['flowers'] = []
        for name in cfg['flowers']:
            surf = load(name)
            if surf:
                item = os.path.splitext(name)[0].lower()
                assets['flowers'].append((item, surf))
        if not assets['flowers']:
            for c in [(255, 220, 50), (220, 80, 80)]:
                s = pygame.Surface((24, 24), pygame.SRCALPHA)
                pygame.draw.circle(s, c, (12, 12), 10)
                assets['flowers'].append(('flower', s))

        # Bush options: (surf, drops, spawn weight)
        assets['bushes'] = []
        for i, (name, drops, weight) in enumerate(cfg['bushes']):
            surf = load(name)
            if surf is None and i == 0:
                try:
                    surf = pygame.image.load(
                        asset_path('graphics', 'overlay', 'bush.png')).convert_alpha()
                except Exception as exc:  # last-resort bush art; skip this entry
                    log_once('[WorldGen] overlay/bush.png load failed', exc)
                    surf = None
            if surf:
                assets['bushes'].append((surf, drops, weight))

        # Ground pool: full cube tiles from cfg['ground'] (folder or file); procedural fallback.
        assets['ground'] = []
        ground_path = asset_path(*base, cfg['ground'])
        if os.path.isdir(ground_path):
            def _variant_num(n):
                try:
                    return int(os.path.splitext(n)[0])
                except ValueError:
                    return 1 << 30
            names = sorted((n for n in os.listdir(ground_path)
                            if n.lower().endswith('.png')),
                           key=_variant_num)
            for name in names:
                try:
                    s = pygame.image.load(
                        os.path.join(ground_path, name)).convert_alpha()
                except Exception as exc:  # one bad variant file; keep the rest
                    log_once(f'[WorldGen] ground variant {name!r} failed', exc)
                    continue
                assets['ground'].append(
                    pygame.transform.scale(s, (ISO_TILE_WIDTH, ISO_TILE_WIDTH)))
        else:
            ground = load(cfg['ground'])
            if ground:
                assets['ground'].append(
                    pygame.transform.scale(ground, (ISO_TILE_WIDTH, ISO_TILE_WIDTH)))
        if not assets['ground']:
            g = pygame.Surface((ISO_TILE_WIDTH, ISO_TILE_WIDTH), pygame.SRCALPHA)
            self._draw_iso_tile(g, (145, 195, 75))
            assets['ground'].append(g)

        # Water deco sheets: horizontal 64x64-cell strips (lily pads, reeds, ice floes).
        assets['water_deco'] = []
        for path in sorted(glob.glob(asset_path(*base, cfg['water_deco_glob']))):
            try:
                wd = pygame.image.load(path).convert_alpha()
            except Exception as exc:  # one bad deco sheet; keep the rest
                log_once(f'[WorldGen] water deco {os.path.basename(path)!r} failed', exc)
                continue
            for r in range(max(1, wd.get_height() // 64)):
                for c in range(max(1, wd.get_width() // 64)):
                    try:
                        cell = wd.subsurface((c * 64, r * 64, 64, 64)).copy()
                    except Exception as exc:  # short last row/col; skip this cell
                        log_once('[WorldGen] water deco cell crop failed', exc)
                        continue
                    if cell.get_bounding_rect().width > 0:
                        assets['water_deco'].append(cell)

        # Frozen water surface, scaled to the water tile and never raised to ground level.
        assets['ice'] = None
        ice = load(cfg.get('ice_tile'))
        if ice:
            assets['ice'] = pygame.transform.scale(
                ice, (ISO_TILE_WIDTH, ISO_TILE_WIDTH))

        # Rare standing props (snowmen) - plain decor sprites, no drops
        assets['props'] = [s for s in (load(n) for n in cfg.get('props', ())) if s]

        return assets

    def _load_water(self):
        try:
            return pygame.image.load(asset_path('graphics', 'world', 'water', '0.png')).convert_alpha()
        except Exception as exc:  # missing art: flat fallback, but say why
            print(f"[WorldGen] water/0.png load failed, using flat water color: {exc!r}")
            s = pygame.Surface((TILE, TILE))
            s.fill(WATER_COLOR)
            return s

    def _load_iso_water_frames(self):
        """Load water frames scaled to isometric tile size."""
        frames = []
        for i in range(4):
            try:
                tile_path = asset_path('graphics', 'world', 'water', f'{i}.png')
                tile_surf = pygame.image.load(tile_path).convert_alpha()
                tile_surf = pygame.transform.scale(tile_surf, (ISO_TILE_WIDTH, ISO_TILE_WIDTH))
                frames.append(tile_surf)
            except Exception as exc:  # some frames are optional; keep the rest
                log_once('[WorldGen] water animation frame failed', exc)
                pass
        if not frames:
            water_surf = self._load_water()
            for i in range(4):
                frames.append(pygame.transform.scale(water_surf, (ISO_TILE_WIDTH, ISO_TILE_WIDTH)))
        return frames

    def _draw_iso_tile(self, surf, color):
        """Draw an isometric diamond tile."""
        cx = ISO_TILE_WIDTH // 2
        cy = ISO_TILE_HEIGHT // 2
        points = [
            (cx, 0),
            (ISO_TILE_WIDTH, cy),
            (cx, ISO_TILE_HEIGHT),
            (0, cy)
        ]
        pygame.draw.polygon(surf, color, points)

    # ---- FLAT TERRAIN (lakes + rivers; everything else is land) ----

    def _lake_at(self, gx, gy):
        """Blobby lake basins: the high tail of a low-frequency noise.
        Memoized per tile - this noise is sampled a dozen-plus times per visible
        tile, so without the cache every one of those re-ran the fractal.
        """
        key = (gx, gy)
        cache = self._lake_cache
        hit = cache.get(key)
        if hit is None:
            hit = self.perlin_lake.fractal(
                gx, gy,
                octaves=NOISE_OCTAVES,
                persistence=NOISE_PERSISTENCE,
                lacunarity=NOISE_LACUNARITY,
                scale=NOISE_SCALE_LAKE
            ) > LAKE_THRESHOLD
            cache[key] = hit
        return hit

    def _river_at(self, gx, gy):
        """Long winding rivers as contour bands of one low-frequency noise:
        |value - level| < half-width marks a river tile. Perlin contour lines read
        as connected meandering rivers. Memoized per tile like _lake_at.
        """
        key = (gx, gy)
        cache = self._river_cache
        hit = cache.get(key)
        if hit is None:
            value = self.perlin_river.fractal(
                gx, gy,
                octaves=4,
                persistence=NOISE_PERSISTENCE,
                lacunarity=NOISE_LACUNARITY,
                scale=RIVER_NOISE_SCALE
            )
            bank_dither = 0.7 + 0.6 * white_noise(gx, gy, seed=self.seed + 900)
            hit = False
            for level, half_w in RIVER_LEVELS:
                if abs(value - level) < half_w * bank_dither:
                    hit = True
                    break
            cache[key] = hit
        return hit

    def is_water_at(self, gx, gy):
        """Check if a grid position is water (lake basin or river)."""
        return self.get_terrain_type(gx, gy) == 'water'

    def height_at(self, gx, gy):
        """FLAT world: 0 = flat surface everywhere. Water is decided by
        is_water_at; kept for the shared movement/debug interface."""
        return 0

    def _moisture_at(self, gx, gy):
        """Large-scale moisture field, memoized per tile."""
        key = (gx, gy)
        cache = self._moisture_cache
        hit = cache.get(key)
        if hit is None:
            hit = self.perlin_moisture.fractal(
                gx, gy,
                octaves=NOISE_OCTAVES,
                persistence=NOISE_PERSISTENCE,
                lacunarity=NOISE_LACUNARITY,
                scale=NOISE_SCALE_MOISTURE
            )
            cache[key] = hit
        return hit

    def _detail_at(self, gx, gy):
        """Medium-scale detail field, memoized per tile."""
        key = (gx, gy)
        cache = self._detail_cache
        hit = cache.get(key)
        if hit is None:
            hit = self.perlin_detail.fractal(
                gx, gy,
                octaves=3,
                persistence=0.4,
                lacunarity=2.5,
                scale=NOISE_SCALE_DETAIL
            )
            cache[key] = hit
        return hit

    def _prewarm_water_rect(self, x0, y0, x1, y1):
        """Vectorized lake/river masks over an inclusive tile rect.
        Fills the caches for any tile still missing and returns (lake, river) as
        bool arrays indexed [gx - x0, gy - y0].
        """
        xs = np.arange(x0, x1 + 1, dtype=float)
        ys = np.arange(y0, y1 + 1, dtype=float)
        bgx, bgy = np.meshgrid(xs, ys, indexing='ij')

        lake = self.perlin_lake.fractal_grid(
            bgx, bgy,
            octaves=NOISE_OCTAVES,
            persistence=NOISE_PERSISTENCE,
            lacunarity=NOISE_LACUNARITY,
            scale=NOISE_SCALE_LAKE
        ) > LAKE_THRESHOLD

        river_value = self.perlin_river.fractal_grid(
            bgx, bgy,
            octaves=4,
            persistence=NOISE_PERSISTENCE,
            lacunarity=NOISE_LACUNARITY,
            scale=RIVER_NOISE_SCALE
        )
        bank_dither = 0.7 + 0.6 * white_noise_grid(
            bgx.astype(np.int64), bgy.astype(np.int64),
            seed=self.seed + 900)
        river = np.zeros(river_value.shape, dtype=bool)
        for level, half_w in RIVER_LEVELS:
            river |= np.abs(river_value - level) < half_w * bank_dither

        lake_cache = self._lake_cache
        river_cache = self._river_cache
        ix = bgx.ravel().astype(np.int64).tolist()
        iy = bgy.ravel().astype(np.int64).tolist()
        for (gx, gy), is_lake, is_river in zip(
                zip(ix, iy), lake.ravel().tolist(), river.ravel().tolist()):
            key = (gx, gy)
            if key not in lake_cache:
                lake_cache[key] = is_lake
            if key not in river_cache:
                river_cache[key] = is_river
        return lake, river

    def _prewarm_chunk_terrain(self, cx, cy):
        """Sample this chunk's noise fields with numpy, in one block.
        get_terrain_type reads lake/river noise up to two tiles away plus the
        tile's own moisture, so a cold chunk used to run ~1000 scalar Perlin
        fractals. The vectorized sampler produces bit-identical values.
        """
        span = TILES_PER_CHUNK
        margin = 3
        gx0 = cx * span
        gy0 = cy * span

        # Lake + river: chunk plus the shore-scan border.
        self._prewarm_water_rect(gx0 - margin, gy0 - margin,
                                 gx0 + span + margin - 1,
                                 gy0 + span + margin - 1)

        # Moisture + detail for the chunk plus a 1-tile border peek.
        xs = np.arange(gx0 - 1, gx0 + span + 1, dtype=float)
        ys = np.arange(gy0 - 1, gy0 + span + 1, dtype=float)
        bgx, bgy = np.meshgrid(xs, ys, indexing='ij')
        moisture = self.perlin_moisture.fractal_grid(
            bgx, bgy,
            octaves=NOISE_OCTAVES,
            persistence=NOISE_PERSISTENCE,
            lacunarity=NOISE_LACUNARITY,
            scale=NOISE_SCALE_MOISTURE
        )
        detail = self.perlin_detail.fractal_grid(
            bgx, bgy,
            octaves=3,
            persistence=0.4,
            lacunarity=2.5,
            scale=NOISE_SCALE_DETAIL
        )
        moisture_cache = self._moisture_cache
        detail_cache = self._detail_cache
        ix = bgx.ravel().astype(np.int64).tolist()
        iy = bgy.ravel().astype(np.int64).tolist()
        for (gx, gy), moist, det in zip(
                zip(ix, iy), moisture.ravel().tolist(), detail.ravel().tolist()):
            key = (gx, gy)
            if key not in moisture_cache:
                moisture_cache[key] = moist
            if key not in detail_cache:
                detail_cache[key] = det

        # Biome bands: biome_at's logic vectorized over the whole block at once.
        xs = np.arange(gx0 - 1, gx0 + span + 1, dtype=float)
        ys = np.arange(gy0 - 1, gy0 + span + 1, dtype=float)
        bgx, bgy = np.meshgrid(xs, ys, indexing='ij')
        v = self.perlin_biome.fractal_grid(
            bgx, bgy,
            octaves=3,
            persistence=NOISE_PERSISTENCE,
            lacunarity=NOISE_LACUNARITY,
            scale=NOISE_SCALE_BIOME
        )
        v = np.clip(0.5 + (v - 0.5) * BIOME_STRETCH, 0.0, 1.0)
        thresholds = np.array([thr for _, thr in BIOME_BANDS])
        names = [name for name, _ in BIOME_BANDS]
        idx = np.searchsorted(thresholds, v, side='right')
        idx = np.clip(idx, 0, len(thresholds) - 1)
        last = len(thresholds) - 1
        idx_m1 = np.maximum(idx - 1, 0)
        upper = ((thresholds[idx] - v) < BIOME_DITHER) & (idx < last)
        lower = ((~upper) & (idx > 0)
                 & ((v - thresholds[idx_m1]) < BIOME_DITHER))
        flat_x = bgx.astype(np.int64)
        flat_y = bgy.astype(np.int64)
        up_flip = upper & (white_noise_grid(
            flat_x, flat_y, seed=self.seed + 601) < 0.5)
        low_flip = lower & (white_noise_grid(
            flat_x, flat_y, seed=self.seed + 602) < 0.5)
        biome_idx = idx + up_flip.astype(np.int64) - low_flip.astype(np.int64)
        biome_names = np.array(names, dtype=object)[biome_idx]
        biome_cache = self._biome_cache
        ix = bgx.ravel().astype(np.int64).tolist()
        iy = bgy.ravel().astype(np.int64).tolist()
        for (gx, gy), biome in zip(zip(ix, iy),
                                   biome_names.ravel().tolist()):
            key = (gx, gy)
            if key not in biome_cache:
                biome_cache[key] = biome

    def get_terrain_type(self, gx, gy):
        """Determine terrain type using Perlin noise.
        Returns: 'water', 'wet_grass', 'grass', 'tall_grass', 'pebbles',
                 'flowers_yellow', 'flowers_blue', 'flowers_mixed'"""
        key = (gx, gy)
        if key in self._terrain_cache:
            return self._terrain_cache[key]

        # Village land forces dry grass; deliberately NOT cached so unload restores it.
        if self._village_land and key in self._village_land:
            return 'grass'

        # Lakes and rivers
        if self._lake_at(gx, gy) or self._river_at(gx, gy):
            self._terrain_cache[key] = 'water'
            return 'water'

        # Layer 1: Moisture (large scale) - controls wet vs dry
        moisture = self._moisture_at(gx, gy)

        # Layer 2: Detail (medium scale) - controls within-type variation
        detail = self._detail_at(gx, gy)

        # Wet grass: low-moisture land, widened into a damp ring near water.
        if moisture < WATER_THRESHOLD + WATER_TRANSITION:
            result = 'wet_grass'
        elif (moisture < WATER_THRESHOLD + WATER_TRANSITION + SHORE_WET_BOOST_ADJ
              and self._is_near_water(gx, gy, radius=1)):
            result = 'wet_grass'
        elif (moisture < WATER_THRESHOLD + WATER_TRANSITION + SHORE_WET_BOOST
              and self._is_near_water(gx, gy, radius=2)):
            result = 'wet_grass'
        # Dry land terrain types based on detail noise
        elif detail < 0.35:
            result = 'tall_grass'
        elif detail < 0.50:
            result = 'grass'
        elif detail < 0.60:
            result = 'pebbles'
        elif detail < 0.70:
            result = 'flowers_yellow'
        elif detail < 0.80:
            result = 'flowers_blue'
        else:
            result = 'flowers_mixed'

        self._terrain_cache[key] = result
        return result

    # ---- BIOME DETERMINATION (low-frequency Perlin blobs) ----

    def biome_at(self, gx, gy):
        """Minecraft-style biome for a tile: a separate low-frequency noise is mapped
        to BIOME_BANDS, giving large contiguous regions. Inside a thin band at
        each threshold the choice is dithered with white noise.
        """
        key = (gx, gy)
        if key in self._biome_cache:
            return self._biome_cache[key]

        v = self.perlin_biome.fractal(
            gx, gy,
            octaves=3,
            persistence=NOISE_PERSISTENCE,
            lacunarity=NOISE_LACUNARITY,
            scale=NOISE_SCALE_BIOME
        )
        # fBm clusters near 0.5 - stretch so the bands cover ~quartiles
        v = min(1.0, max(0.0, 0.5 + (v - 0.5) * BIOME_STRETCH))

        idx = 0
        for i, (name, threshold) in enumerate(BIOME_BANDS):
            if v < threshold:
                idx = i
                break
        else:
            idx = len(BIOME_BANDS) - 1
        biome = BIOME_BANDS[idx][0]

        # Border dither: near a threshold, flip bands with per-tile noise.
        if (BIOME_BANDS[idx][1] - v) < BIOME_DITHER and idx + 1 < len(BIOME_BANDS):
            if white_noise(gx, gy, seed=self.seed + 601) < 0.5:
                biome = BIOME_BANDS[idx + 1][0]
        elif idx > 0 and (v - BIOME_BANDS[idx - 1][1]) < BIOME_DITHER:
            if white_noise(gx, gy, seed=self.seed + 602) < 0.5:
                biome = BIOME_BANDS[idx - 1][0]

        self._biome_cache[key] = biome
        return biome

    def is_lava_at(self, gx, gy):
        """The overworld has no lava - the cave generator provides the
        cave's answer for shared movement rules."""
        return False

    def is_point_in_water(self, wx, wy):
        """Check if a world position is water (for collision)."""
        gx = int(wx) // TILE
        gy = int(wy) // TILE
        return self.is_water_at(gx, gy)

    # ---- VILLAGE HOOKS (registered by the VillageGenerator) ----

    def add_village_land(self, land_tiles, path_tiles):
        """Force dry flat grassland on these tiles and draw dirt-path
        overlays over these tiles until remove_village_land is called."""
        self._village_land.update(land_tiles)
        self._path_tiles.update(path_tiles)
        # Drop stale terrain answers or the land override would be masked.
        for key in land_tiles:
            self._terrain_cache.pop(key, None)
        for key in path_tiles:
            self._terrain_cache.pop(key, None)

    def remove_village_land(self, land_tiles, path_tiles):
        """Undo add_village_land (the terrain noise re-appears)."""
        self._village_land.difference_update(land_tiles)
        self._path_tiles.difference_update(path_tiles)
        # Pop defensively so the terrain below is recomputed.
        for key in land_tiles:
            self._terrain_cache.pop(key, None)

    def invalidate_chunks_in_rect(self, x0, y0, x1, y1):
        """Drop every active chunk overlapping this tile rect so it is
        re-generated on the next updates - with the current village
        overrides (land forced, props reserved) or without them."""
        for cx in range(x0 // TILES_PER_CHUNK, x1 // TILES_PER_CHUNK + 1):
            for cy in range(y0 // TILES_PER_CHUNK, y1 // TILES_PER_CHUNK + 1):
                key = (cx, cy)
                if key in self.active_chunks:
                    self._remove_chunk(key)
                    del self.active_chunks[key]
                    self._chunk_surfs.pop(key, None)
                    self._water_deco_cache.pop(key, None)
                    self._non_water_cache.pop(key, None)
                    self._ground_maps_dirty = True

    # ---- TILE SELECTION (Perlin structure + White noise variation) ----

    def _ground_variant(self, gx, gy, count):
        """Deterministic per-tile index into a biome's ground-tile pool.
        The last tile is the plain, deco-free one: it wins ~50% of tiles so the
        baked deco reads as a natural accent instead of uniform noise.
        """
        if count <= 1:
            return 0
        r = white_noise(gx, gy, seed=self.seed + 703)
        if r < 0.5:
            return count - 1
        return min(count - 2, int((r - 0.5) / 0.5 * (count - 1)))

    def _select_ground_tile(self, gx, gy):
        """Return one biome ground variant (or water tile for water terrain)."""
        terrain = self.get_terrain_type(gx, gy)
        if terrain == 'water':
            return self.iso_water_frames[0]
        pool = self.biome_assets[self.biome_at(gx, gy)]['ground']
        return pool[self._ground_variant(gx, gy, len(pool))]

    # ---- CHUNK SURFACE RENDERING (flat top-down fallback bake) ----

    def _make_chunk_surface(self, cx, cy, isometric=False, water_frame_idx=0):
        """Flat top-down chunk surface (non-isometric fallback bake)."""
        surf = pygame.Surface((CHUNK_SIZE, CHUNK_SIZE))
        surf.fill((145, 195, 75))

        for ty in range(TILES_PER_CHUNK):
            for tx in range(TILES_PER_CHUNK):
                gx = cx * TILES_PER_CHUNK + tx
                gy = cy * TILES_PER_CHUNK + ty

                terrain = self.get_terrain_type(gx, gy)
                if terrain == 'water':
                    water_surf = self._load_water()
                    surf.blit(water_surf, (tx * TILE, ty * TILE))
                else:
                    tile = self._select_ground_tile(gx, gy)
                    if tile:
                        surf.blit(tile, (tx * TILE, ty * TILE))

        return surf

    def _is_water_interior(self, gx, gy):
        """True when all 4 grid neighbors are also water.
        Water deco cells are 64px squares on a 128x64 diamond; their corners poke
        past the diamond, so only interior tiles can hold deco.
        """
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if not self.is_water_at(gx + dx, gy + dy):
                return False
        return True

    def _land_top_cube(self, biome, gidx):
        """The isometric ground cube for a tile.
        Picks a variant from the biome's ground pool (or a procedural diamond when
        the pool is empty) with the tile's depth key.
        """
        pool = self.biome_assets.get(biome, {}).get('ground')
        if not pool:
            return None
        return pool[gidx % len(pool)]

    def _precompute_water_decos(self, cx, cy):
        """Deterministic water-deco placement for a chunk (lily pads, reeds, ice
        floes). Uses the same per-chunk rng stream and tile order as the old
        chunk-surface bake, so placements are identical.
        """
        if not any(ba.get('water_deco') for ba in self.biome_assets.values()):
            return
        deco_rng = Random(_det_hash(cx, cy, 'water_deco'))
        entries = []
        tile_order = []
        for ty in range(TILES_PER_CHUNK):
            for tx in range(TILES_PER_CHUNK):
                tile_order.append((tx + ty, tx, ty))
        tile_order.sort()
        for _, tx, ty in tile_order:
            gx = cx * TILES_PER_CHUNK + tx
            gy = cy * TILES_PER_CHUNK + ty
            if self.get_terrain_type(gx, gy) != 'water':
                continue
            biome = self.biome_assets[self.biome_at(gx, gy)]
            water_deco = biome['water_deco']
            if water_deco and self._is_water_interior(gx, gy):
                chance = 0.05 if biome.get('ice') else 0.08
                if deco_rng.random() < chance:
                    entries.append((gx, gy, deco_rng.choice(water_deco)))
        self._water_deco_cache[(cx, cy)] = entries
        self._ground_maps_dirty = True

    def _content_bounds(self, surf):
        """Minimal src rect covering a ground surface's non-transparent
        pixels, cached per surface. Blitting with it skips transparent
        rows/cols (diamond art: ~50% of the box)."""
        b = self._surf_bounds.get(surf)
        if b is None:
            b = surf.get_bounding_rect()
            if b.w <= 0 or b.h <= 0:
                b = surf.get_rect()
            self._surf_bounds[surf] = b
        return b

    def iter_ground_entries(self, sw, sh, ox, oy):
        """Yield the ground pieces of a chunk, in painter order.
        Each entry is (gx, gy, surface, depth, rank, level, z). The cave has lava
        and no water decos, the overworld has farms, paths and water overlays.
        """
        half_w = ISO_TILE_WIDTH // 2   # 64
        half_h = ISO_TILE_HEIGHT // 2  # 32
        pad = ISO_TILE_WIDTH
        sunk = WATER_SUNK_OFFSET

        water_frame_idx = int(pygame.time.get_ticks() * 2 / 1000) % 4
        water_frame = self.iso_water_frames[water_frame_idx % len(self.iso_water_frames)]

        u0 = (ox - pad) // half_w
        u1 = (ox + sw + pad) // half_w
        v0 = (oy - pad) // half_h
        v1 = (oy + sh + pad) // half_h

        # Tile-keyed cache mirrors, rebuilt only on the dirty flag.
        if self._ground_maps_dirty:
            wdeco_tile_map = {}
            for entries in self._water_deco_cache.values():
                for gx, gy, dsurf in entries:
                    wdeco_tile_map[(gx, gy)] = dsurf
            patch_tile_map = set()
            for (cx, cy), tiles in self._farm_patch_cache.items():
                bx = cx * TILES_PER_CHUNK
                by = cy * TILES_PER_CHUNK
                for tx, ty in tiles:
                    patch_tile_map.add((bx + tx, by + ty))
            soilw_tile_map = {}
            for (cx, cy), tiles in self._soil_water_cache.items():
                bx = cx * TILES_PER_CHUNK
                by = cy * TILES_PER_CHUNK
                for (tx, ty), surf in tiles.items():
                    soilw_tile_map[(bx + tx, by + ty)] = surf
            self._wdeco_tile_map = wdeco_tile_map
            self._patch_tile_map = patch_tile_map
            self._soilw_tile_map = soilw_tile_map
            self._ground_maps_dirty = False
        wdeco_map = self._wdeco_tile_map
        patch_map = self._patch_tile_map
        soilw_map = self._soilw_tile_map

        # Ground-tile pools (variant cubes, deco baked into the art)
        gpools = self._ground_pools
        if gpools is None:
            gpools = {name: ba['ground'] for name, ba in self.biome_assets.items()}
            self._ground_pools = gpools
        patch_surf = self._farm_patch_iso
        patch_bounds = self._content_bounds(patch_surf) if patch_surf is not None else None

        terrain_at = self.get_terrain_type
        biome_at = self.biome_at
        land_top_cube = self._land_top_cube
        bounds = self._content_bounds
        water_bounds = bounds(water_frame)

        for v in range(v0, v1 + 1):
            # gx, gy are integers only where u and v share parity
            u = u0 + ((v - u0) & 1)
            for u2 in range(u, u1 + 1, 2):
                gx = (v + u2) // 2
                gy = (v - u2) // 2
                iso_x = u2 * half_w
                iso_y = v * half_h
                dx = iso_x - ox
                if dx <= -pad or dx >= sw:
                    continue
                dy = iso_y - oy

                ray = v * 128 + 128  # == tile-centre x + y in px

                if terrain_at(gx, gy) == 'water':
                    # Water diamond, art sunk 32px to read as a recessed plane.
                    if dy >= sh or dy + pad <= 0:
                        continue
                    yield (ray, 0.0, water_frame, dx, dy, water_bounds)
                    wd = wdeco_map.get((gx, gy))
                    if wd is not None:
                        yield (ray + OVERLAY_LIFT, 0.7, wd,
                               dx + half_w - wd.get_width() // 2,
                               dy + half_h - wd.get_height() // 2,
                               bounds(wd))
                    biome = self.biome_assets[biome_at(gx, gy)]
                    if biome.get('ice'):
                        ice = biome['ice']
                        yield (ray + OVERLAY_LIFT, 0.5, ice, dx, dy, bounds(ice))
                    continue

                if dy >= sh or dy + pad <= 0:
                    continue

                biome_name = biome_at(gx, gy)
                gpool = gpools[biome_name]
                if gpool:
                    # Ground art IS the tile now (full cube, no base to composite onto).
                    top_cube = land_top_cube(
                        biome_name, self._ground_variant(gx, gy, len(gpool)))
                    yield (ray, 0.0, top_cube, dx, dy, bounds(top_cube))

                # Village dirt path slabs: rank 1.5, above ground, below farm patches.
                if self._path_tiles and (gx, gy) in self._path_tiles:
                    for psurf in self._path_pieces_at(gx, gy):
                        yield (ray + OVERLAY_LIFT, 1.5, psurf,
                               dx, dy, bounds(psurf))

                if patch_bounds is not None and (gx, gy) in patch_map:
                    yield (ray + OVERLAY_LIFT, 2.0, patch_surf,
                           dx, dy, patch_bounds)

                if (gx, gy) in soilw_map:
                    soilw = soilw_map[(gx, gy)]
                    # Watered-soil blotch on the tile diamond, just above the patch (rank 2.05).
                    yield (ray + OVERLAY_LIFT, 2.05, soilw,
                           dx, dy, bounds(soilw))


    # ---- OBJECT PLACEMENT (noise-based natural clustering) ----

    def _is_near_water(self, gx, gy, radius=1):
        """Check if a grid position has lake/river water within radius tiles.
        Uses the raw water noises, NOT is_water_at/get_terrain_type - those route
        back into get_terrain_type's shore band.
        """
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if self._lake_at(gx + dx, gy + dy) or self._river_at(gx + dx, gy + dy):
                    return True
        return False

    # ---- CAVE ENTRANCES (jittered grid sampling with a dead zone) ----

    def _sector_entrance(self, sx, sy):
        """One deterministic entrance position per sector, inset from the
        sector borders by the dead zone (guarantees a minimum distance
        between neighbouring sectors' entrances). Doors sit on plain
        flat land; instead of random rolls this scans every dead-zone
        tile in stride order (coprime step decorrelates the visit
        order) with a cheap prefilter, first full-valid win.
        None if the sector holds no valid spot."""
        key = (sx, sy)
        if key in self._entrance_sector_cache:
            return self._entrance_sector_cache[key]

        margin = CAVE_ENTRANCE_DEAD_ZONE
        span = CAVE_SECTOR_SIZE - 2 * margin
        found = None
        if span > 0:
            gx0 = sx * CAVE_SECTOR_SIZE + margin
            gy0 = sy * CAVE_SECTOR_SIZE + margin
            # Vectorized lake/river prewarm over the scan (plus doorway footprint).
            self._prewarm_water_rect(gx0 - 2, gy0 - 2,
                                     gx0 + span + 1,
                                     gy0 + span + 2)
            total = span * span
            # Legacy WORLD_SEED keeps the original walk; fresh seeds rotate the stride start.
            start = (0 if self.seed == WORLD_SEED else
                     _det_hash(sx, sy, 'entrance', self.seed) % total)
            for i in range(total):
                k = (start + i * 17) % total
                gx = sx * CAVE_SECTOR_SIZE + margin + k % span
                gy = sy * CAVE_SECTOR_SIZE + margin + k // span
                if self._valid_entrance_tile(gx, gy):
                    found = (gx, gy)
                    break
        self._entrance_sector_cache[key] = found
        return found

    def _valid_entrance_tile(self, gx, gy):
        """A doorway on flat ground: the whole art footprint plus a clear
        approach must be dry land, so the portal never sits at a shore
        and the trigger is always reachable. Tiles inside a village
        site's reserved footprint are rejected so doorways never open
        inside a settlement."""
        for dx in range(-2, 3):
            for dy in range(-2, 4):
                # Raw water noise (exactly what get_terrain_type maps to 'water').
                if (self._lake_at(gx + dx, gy + dy)
                        or self._river_at(gx + dx, gy + dy)):
                    return False
        if self.village_gen is not None:
            for dx in range(-2, 3):
                for dy in range(-2, 4):
                    if self.village_gen.is_village_area_tile(gx + dx, gy + dy):
                        return False
        return True

    def _entrances_near_chunk(self, cx, cy):
        """Entrance positions from every sector overlapping the 3x3 chunks
        around (cx, cy) - covers both the chunk's own entrance and
        neighbours' footprints that spill into it."""
        tx0 = (cx - 1) * TILES_PER_CHUNK
        ty0 = (cy - 1) * TILES_PER_CHUNK
        tx1 = (cx + 2) * TILES_PER_CHUNK - 1
        ty1 = (cy + 2) * TILES_PER_CHUNK - 1
        sx0, sx1 = tx0 // CAVE_SECTOR_SIZE, tx1 // CAVE_SECTOR_SIZE
        sy0, sy1 = ty0 // CAVE_SECTOR_SIZE, ty1 // CAVE_SECTOR_SIZE
        out = []
        for sx in range(sx0, sx1 + 1):
            for sy in range(sy0, sy1 + 1):
                e = self._sector_entrance(sx, sy)
                if e:
                    out.append(e)
        return out

    def _reserved_tiles_for_chunk(self, cx, cy):
        """Tiles too close to any nearby cave entrance OR inside a
        village site - trees, rocks and other props must never spawn
        there."""
        if self.interaction_sprites is None and self.village_gen is None:
            return frozenset()
        key = (cx, cy)
        cached = self._entrance_reserve_cache.get(key)
        if cached is not None:
            return cached
        reserved = set()
        if self.interaction_sprites is not None:
            r = CAVE_ENTRANCE_RESERVE_RADIUS
            for gx, gy in self._entrances_near_chunk(cx, cy):
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        reserved.add((gx + dx, gy + dy))
        if self.village_gen is not None:
            reserved.update(self.village_gen.reserved_tiles_for_chunk(cx, cy))
        self._entrance_reserve_cache[key] = reserved
        return reserved

    def _place_cave_entrances(self, sprites, cx, cy):
        """Spawn the entrance that belongs to this chunk (its owning chunk
        only, so recycling a chunk deterministically recreates it)."""
        if self.interaction_sprites is None:
            return
        own = (cx, cy)
        for gx, gy in self._entrances_near_chunk(cx, cy):
            if (gx // TILES_PER_CHUNK, gy // TILES_PER_CHUNK) != own:
                continue
            # One sprite per doorway; the random Entry/Entry1 pick is gone.
            surf = self.entrance_surf
            if surf is None:
                continue
            # Rect centred on the door tile; z one below 'main' so the player draws in front.
            wx = gx * TILE + TILE // 2
            wy = gy * TILE + TILE // 2
            spr = Generic(
                pos=(wx - surf.get_width() // 2, wy - surf.get_height() // 2),
                surf=surf,
                groups=[self.all_sprites],
                z=LAYERS['rain floor'])
            # TILE_SIZE//4 world px deep == TILE_SIZE//16 screen px down
            spr.foot_pad = visible_bottom_pad(surf) + TILE_SIZE // 16
            # Anchor is the door tile; front_tiles are the walkable apron
            # tiles where the player should draw in front of the cave art.
            gtx, gty = gx, gy
            spr.front_tiles = {
                (gtx + dx, gty + dy)
                for dx, dy in structure_front_tiles(
                    surf, spr.foot_pad, door=(0, 0),
                    radius=STRUCTURE_FRONT_RADIUS)}
            sprites.append(spr)
            # Trigger covers the doorway's whole front apron; ENTER prompts only in front.
            trig = Interaction((wx - 320, wy - 192), (640, 448),
                               self.interaction_sprites, 'CaveEntrance')
            sprites.append(trig)
            self._add_entrance_blockers(sprites, wx, wy)

    def _add_entrance_blockers(self, sprites, wx, wy):
        """Wall off the rock's base with blockers traced from the authored
        collision mask (graphics/world/Collisions/Cave_collision.png) - the
        same 8px outline the village buildings use. The doorstep is carved
        out, so the front apron and the entrance stay walkable.

        A missing mask falls back to the old whole-tile footprint plus the
        art-occlusion tiles (see _entrance_footprint_for).
        """
        if self._entrance_outline:
            for rel in self._entrance_outline:
                block = rel.move(wx, wy)
                blocker = Generic(pos=block.topleft, surf=self._invisible,
                                  groups=[self.collision_sprites], z=0)
                blocker.hitbox = block
                sprites.append(blocker)
            return
        foot = self._entrance_foot
        has_surf = (self.entrance_collision_surf is not None
                    or self.entrance_surf is not None)
        if not foot or not has_surf:
            return
        gx = wx // TILE
        gy = wy // TILE
        tiles = {(x + gx, y + gy) for x, y in foot}
        invisible = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        for hitbox in structure_blockers(tiles):
            blocker = Generic(pos=hitbox.topleft, surf=invisible,
                              groups=[self.collision_sprites], z=0)
            blocker.hitbox = hitbox
            sprites.append(blocker)

    def _get_non_water_tiles(self, cx, cy):
        """Get list of non-water tile positions in a chunk (excludes tiles near water
        and tiles reserved for cave entrances). Memoized per chunk: every
        placer (trees, debris, rocks, bushes, flowers, props) races the
        same 24x24 scan - paying it six times was profiled at ~30% of
        chunk-gen time."""
        key = (cx, cy)
        cached = self._non_water_cache.get(key)
        if cached is not None:
            return list(cached)
        rng = Random(_det_hash(cx, cy, 'tilefilter'))
        reserved = self._reserved_tiles_for_chunk(cx, cy)
        tiles = []
        for ty in range(TILES_PER_CHUNK):
            for tx in range(TILES_PER_CHUNK):
                gx = cx * TILES_PER_CHUNK + tx
                gy = cy * TILES_PER_CHUNK + ty
                if (gx, gy) in reserved:
                    continue
                if self._is_near_water(gx, gy, radius=1):
                    continue
                wx = cx * CHUNK_SIZE + tx * TILE + TILE // 2
                wy = cy * CHUNK_SIZE + ty * TILE + TILE // 2
                tiles.append((tx, ty, wx, wy, gx, gy))
        rng.shuffle(tiles)
        self._non_water_cache[key] = list(tiles)
        return tiles

    def _place_water_colliders(self, sprites, cx, cy):
        """Create invisible collision rects for water tiles. The surface
        is never drawn (z <= LAYERS['water'] is skipped by the painter)
        and is shared: allocating a fresh SRCALPHA tile per water tile
        was dozens of small heap allocations per chunk."""
        for ty in range(TILES_PER_CHUNK):
            for tx in range(TILES_PER_CHUNK):
                gx = cx * TILES_PER_CHUNK + tx
                gy = cy * TILES_PER_CHUNK + ty
                if self.get_terrain_type(gx, gy) == 'water':
                    rect = pygame.Rect(
                        cx * CHUNK_SIZE + tx * TILE,
                        cy * CHUNK_SIZE + ty * TILE, TILE, TILE)
                    # Lets Player.collision() lift this wall once a bridge is placed.
                    water_sprite = WaterCollider(rect, [self.collision_sprites])
                    sprites.append(water_sprite)

    def _generate_chunk(self, cx, cy):
        """Generate all sprites for a chunk (synchronous path).

        Runtime streaming uses the same stages one per frame via
        _advance_staged_chunk; this full build is for flushes, loading
        and any caller that needs a finished chunk immediately.
        """
        sprites = []
        for stage in range(self._CHUNK_STAGES):
            self._generate_chunk_stage(sprites, cx, cy, stage)
        return sprites

    # Stage count sized so one stage per frame stays well under the frame budget.
    _CHUNK_STAGES = 5

    def _generate_chunk_stage(self, sprites, cx, cy, stage):
        """Run one slice of a chunk build, appending to `sprites`."""
        if stage == 0:
            # Vectorized noise prewarm first; then water walls and the cave doorway.
            self._prewarm_chunk_terrain(cx, cy)
            self._place_water_colliders(sprites, cx, cy)
            self._place_cave_entrances(sprites, cx, cy)
        elif stage == 1:
            # Shared per-chunk tile scan, reused by all placers and reserve lookups.
            self._get_non_water_tiles(cx, cy)
        elif stage == 2:
            self._place_trees(sprites, cx, cy)
        elif stage == 3:
            self._place_wood_debris(sprites, cx, cy)
            self._place_rocks(sprites, cx, cy)
            self._place_bushes(sprites, cx, cy)
            self._place_flowers(sprites, cx, cy)
            self._place_props(sprites, cx, cy)
        else:
            self._precompute_water_decos(cx, cy)

    def _start_staged_chunk(self, key):
        """Register a chunk and return its staged-build state."""
        cx, cy = key
        sprites = []
        # Registered now so _remove_chunk can clean a partially built chunk.
        self.active_chunks[key] = sprites
        self._staged_chunk = [key, 0, sprites]
        return self._staged_chunk

    def _advance_staged_chunk(self):
        """Run one build stage for the chunk currently being streamed."""
        state = self._staged_chunk
        key, stage, sprites = state
        cx, cy = key
        self._generate_chunk_stage(sprites, cx, cy, stage)
        stage += 1
        if stage >= self._CHUNK_STAGES:
            self._staged_chunk = None
        else:
            state[1] = stage

    def flush_chunks(self, player_pos, isometric=True):
        """Finish every needed chunk synchronously (teleports / loading).

        A teleport crosses several chunks in one frame: the normal staged
        fill would leave props and water colliders missing for seconds,
        so far jumps ask for the whole ring at once.
        """
        self.update(player_pos, isometric, staggered=False)

    def _prop_density(self, gx, gy, kind):
        """        Chance that a tile gets a natural prop of a given kind.

        Blends a low-frequency noise field with a per-tile roll, so props clump
        naturally instead of sprinkling evenly. The noise is sampled on the
        chunk's tile grid, so the answer only depends on the tile.
        """
        base, seed = PROP_DENSITY[kind]
        w = white_noise(gx, gy, seed)
        if w >= base * (1.0 + PROP_DENSITY_RELIEF):
            return False
        n = self.perlin_object.fractal(
            gx + seed, gy + seed,
            octaves=2, persistence=0.5, lacunarity=2.0,
            scale=PROP_DENSITY_NOISE_SCALE)
        return w < base * (1.0 - PROP_DENSITY_RELIEF
                           + 2.0 * PROP_DENSITY_RELIEF * n)

    def _place_trees(self, sprites, cx, cy):
        """Place trees at an even map-wide density, scattered by white
        noise with a little value-noise clumping (see _prop_density).
        Art, fruit tree and wood drop come from the tile's biome."""
        rng = Random(_det_hash(cx, cy, 'trees'))
        tiles = self._get_non_water_tiles(cx, cy)

        # Spacing constants; neighbour chunks checked too so canopies never overlap.
        SPACING = 180
        NEIGHBOUR_SPACING = 160

        def _too_close(wx, wy):
            for s in sprites:
                r = getattr(s, 'rect', None)
                if r is not None and (abs(r.centerx - wx) < SPACING
                                      and abs(r.centery - wy) < SPACING):
                    return True
            for t in self.tree_sprites:
                r = getattr(t, 'rect', None)
                if r is not None and (abs(r.centerx - wx) < NEIGHBOUR_SPACING
                                      and abs(r.centery - wy) < NEIGHBOUR_SPACING):
                    return True
            return False

        for i, (tx, ty, wx, wy, gx, gy) in enumerate(tiles):
            if not self._prop_density(gx, gy, 'trees'):
                continue
            # A planted tree owns this tile and its canopy space.
            if self._planted_near(gx, gy, 1):
                continue
            # Village layouts keep reserved tiles clear of natural trees.
            if getattr(self, 'village_gen', None) is not None and self.village_gen.is_reserved_tile(gx, gy):
                continue
            assets = self.biome_assets[self.biome_at(gx, gy)]
            # Spacing check (fits the widest canopy, incl. neighbour chunks)
            if _too_close(wx, wy):
                continue
            fruit = assets['fruit_tree']
            is_fruit = (fruit is not None and fruit[0] is not None and
                        rng.random() < fruit[1])
            if is_fruit:
                surf = fruit[0]
            else:
                idx = rng.randint(0, len(assets['trees']) - 1)
                surf = assets['trees'][idx]
            # Consume the rng draws even when skipped, keeping tree identity stable.
            tree_id = (cx, cy, i)
            if tree_id in self.removed_tree_ids:
                continue
            t = Tree(
                pos=(wx, wy),
                surf=surf,
                groups=[self.all_sprites, self.collision_sprites, self.tree_sprites],
                player_add=self.player_add,
                is_apple_tree=is_fruit,
                wood_yield=tree_wood_yield(surf.get_width()),
                wood_item=assets['wood_item'],
                fruit_item=fruit[2] if is_fruit else 'apple',
                tree_id=tree_id,
                sapling_item=BIOME_SAPLINGS.get(assets['name']),
                on_removed=self._mark_tree_removed)
            sprites.append(t)

    def _place_wood_debris(self, sprites, cx, cy):
        """Place cuttable log/stump debris (solid, yields wood when felled).

        Drawn from the same tile pool as trees at its own density and
        white-noise seed, so debris never correlates with trees, rocks
        or bushes. Debris art and wood drop come from the tile's biome.
        """
        rng = Random(_det_hash(cx, cy, 'wood_debris'))
        tiles = self._get_non_water_tiles(cx, cy)

        for i, (tx, ty, wx, wy, gx, gy) in enumerate(tiles):
            if not self._prop_density(gx, gy, 'debris'):
                continue
            if self._planted_near(gx, gy, 1):
                continue
            if getattr(self, 'village_gen', None) is not None and self.village_gen.is_reserved_tile(gx, gy):
                continue
            assets = self.biome_assets[self.biome_at(gx, gy)]
            pool = assets['debris']
            if not pool:
                continue
            weights = [entry[4] for entry in pool]
            pick = rng.choices(range(len(pool)), weights=weights, k=1)[0]
            surf, health, wood_yield, foot_pad, _weight = pool[pick]
            spacing = max(70, surf.get_width() // 2 + 40)
            if any(abs(s.rect.centerx - wx) < spacing and
                   abs(s.rect.centery - wy) < spacing for s in sprites):
                continue
            # Keep debris away from trees (incl. neighbour chunks) to avoid canopies.
            TREE_SPACING = 150
            if any(abs(t.rect.centerx - wx) < TREE_SPACING and
                   abs(t.rect.centery - wy) < TREE_SPACING
                   for t in self.tree_sprites):
                continue
            debris_id = (cx, cy, 'debris', i)
            if (debris_id in self.removed_debris_ids
                    or debris_id in self.removed_tree_ids):
                continue
            d = Tree(
                pos=(wx, wy),
                surf=surf,
                groups=[self.all_sprites, self.collision_sprites, self.tree_sprites],
                player_add=self.player_add,
                health=health,
                foot_pad=foot_pad,
                wood_yield=wood_yield,
                iso_anchor='center',
                wood_item=assets['wood_item'],
                tree_id=debris_id,
                on_removed=self._mark_debris_removed)
            sprites.append(d)

    def _place_rocks(self, sprites, cx, cy):
        """Place rocks at an even map-wide density (see _prop_density)."""
        if not self.rock_surfs:
            return
        rng = Random(_det_hash(cx, cy, 'rocks'))
        tiles = self._get_non_water_tiles(cx, cy)

        # Within-chunk + neighbour-chunk spacing so rocks never overlap borders.
        SPACING = 100

        def _too_close(wx, wy):
            for s in sprites:
                r = getattr(s, 'rect', None)
                if r is not None and (abs(r.centerx - wx) < SPACING
                                      and abs(r.centery - wy) < SPACING):
                    return True
            for rk in self.rock_sprites:
                r = getattr(rk, 'rect', None)
                if r is not None and (abs(r.centerx - wx) < SPACING
                                      and abs(r.centery - wy) < SPACING):
                    return True
            return False

        for i, (tx, ty, wx, wy, gx, gy) in enumerate(tiles):
            if not self._prop_density(gx, gy, 'rocks'):
                continue
            if self._planted_near(gx, gy):
                continue
            if getattr(self, 'village_gen', None) is not None and self.village_gen.is_reserved_tile(gx, gy):
                continue
            if _too_close(wx, wy):
                continue
            rock_id = (cx, cy, 'rock', i)
            if rock_id in self.removed_rock_ids:
                continue
            surf = rng.choice(self.rock_surfs)
            r = Rock(
                pos=(wx, wy),
                surf=surf,
                groups=[self.all_sprites, self.collision_sprites, self.rock_sprites],
                player_add=self.player_add,
                rock_id=rock_id,
                on_removed=self._mark_rock_removed)
            sprites.append(r)

    def _place_bushes(self, sprites, cx, cy):
        """Place bushes (plain + berry) at an even map-wide density
        (see _prop_density). Bush art/drops come from the tile's biome."""
        rng = Random(_det_hash(cx, cy, 'bushes', self.bush_refresh_nonce))
        tiles = self._get_non_water_tiles(cx, cy)

        for i, (tx, ty, wx, wy, gx, gy) in enumerate(tiles):
            if not self._prop_density(gx, gy, 'bushes'):
                continue
            if self._planted_near(gx, gy):
                continue
            if getattr(self, 'village_gen', None) is not None and self.village_gen.is_reserved_tile(gx, gy):
                continue
            options = self.biome_assets[self.biome_at(gx, gy)]['bushes']
            if not options:
                continue
            # Never spawn where a tree, log, rock or bush already sits.
            if any(s.rect.collidepoint(wx, wy)
                   or (abs(s.rect.centerx - wx) < 60
                       and abs(s.rect.centery - wy) < 60)
                   for s in sprites if hasattr(s, 'rect')):
                continue
            # Also avoid neighbour-chunk bushes and the player's spot.
            if any(abs(b.rect.centerx - wx) < 60
                   and abs(b.rect.centery - wy) < 60
                   for b in self.bush_sprites):
                continue
            if (self.player is not None
                    and self.player.rect.inflate(96, 96).collidepoint(wx, wy)):
                continue
            weights = [o[2] for o in options]
            pick = rng.choices(range(len(options)), weights=weights, k=1)[0]
            surf, drops, _w = options[pick]
            b = Bush(
                (wx, wy),
                surf,
                [self.all_sprites, self.collision_sprites, self.bush_sprites],
                self.player_add,
                drops=drops)
            sprites.append(b)

    def _place_flowers(self, sprites, cx, cy):
        """Place flowers at an even map-wide density (see _prop_density).
        Flower art comes from the tile's biome."""
        rng = Random(_det_hash(cx, cy, 'flowers'))
        tiles = self._get_non_water_tiles(cx, cy)

        for i, (tx, ty, wx, wy, gx, gy) in enumerate(tiles):
            if not self._prop_density(gx, gy, 'flowers'):
                continue
            if self._planted_near(gx, gy):
                continue
            if getattr(self, 'village_gen', None) is not None and self.village_gen.is_reserved_tile(gx, gy):
                continue
            pool = self.biome_assets[self.biome_at(gx, gy)]['flowers']
            if not pool:
                continue
            if any(abs(s.rect.centerx - wx) < 50 and abs(s.rect.centery - wy) < 50
                   for s in sprites if hasattr(s, 'rect')):
                continue
            item, base_surf = pool[rng.randint(0, len(pool) - 1)]
            scale = rng.uniform(0.7, 1.2)
            w, h = base_surf.get_size()
            # Nearest-neighbour avoids smoothscale's dark transparent-RGB fringe
            scaled = pygame.transform.scale(base_surf, (max(1, int(w * scale)), max(1, int(h * scale))))
            f = WildFlower((wx, wy), scaled, [self.all_sprites, self.collision_sprites, self.flower_sprites], self.collision_sprites, player_add=self.player_add, item=item)
            sprites.append(f)

    def _place_props(self, sprites, cx, cy):
        """Rare standing decorations (e.g. snowmen in Snowy_Pine).

        Non-colliding, no drops - pure decor. At most one per chunk, with
        a small deterministic chance, placed on a random non-water tile
        whose biome has props."""
        rng = Random(_det_hash(cx, cy, 'props'))
        if rng.random() >= 0.12:
            return
        tiles = self._get_non_water_tiles(cx, cy)
        rng.shuffle(tiles)
        for tx, ty, wx, wy, gx, gy in tiles:
            if self._planted_near(gx, gy):
                continue
            props = self.biome_assets[self.biome_at(gx, gy)]['props']
            if not props:
                continue
            if any(abs(s.rect.centerx - wx) < 70 and abs(s.rect.centery - wy) < 70
                   for s in sprites if hasattr(s, 'rect')):
                continue
            surf = props[rng.randint(0, len(props) - 1)]
            p = Generic(
                (wx - surf.get_width() // 2, wy - surf.get_height() // 2),
                surf,
                [self.all_sprites])
            sprites.append(p)
            return

    # ---- TREE PERSISTENCE ----

    def _planted_near(self, gx, gy, radius=0):
        """True when a planted tree owns this tile or a nearby tile."""
        if not self.planted_tiles:
            return False
        if (gx, gy) in self.planted_tiles:
            return True
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if (gx + dx, gy + dy) in self.planted_tiles:
                    return True
        return False

    def _mark_tree_removed(self, tree_id):
        """Tree callback: remember a felled natural tree across reloads."""
        if tree_id is not None:
            self.removed_tree_ids.add(tuple(tree_id))

    def _mark_debris_removed(self, debris_id):
        """Log/stump callback: felled debris stays gone across days."""
        if debris_id is not None:
            self.removed_debris_ids.add(tuple(debris_id))

    def _mark_rock_removed(self, rock_id):
        """Rock callback: mined natural rocks stay gone across days."""
        if rock_id is not None:
            self.removed_rock_ids.add(tuple(rock_id))

    def serialize_removed_trees(self):
        return [list(tree_id) for tree_id in sorted(self.removed_tree_ids)]

    def apply_removed_trees(self, ids):
        """Restore the felled-tree set and prune any already-generated
        copies (relevant when a save is applied after a chunk spawned)."""
        self.removed_tree_ids = {tuple(tree_id) for tree_id in ids or ()}
        for tree in list(self.tree_sprites.sprites()):
            if getattr(tree, 'tree_id', None) in self.removed_tree_ids:
                tree.kill()

    def serialize_removed_debris(self):
        return [list(i) for i in sorted(self.removed_debris_ids)]

    def serialize_removed_rocks(self):
        return [list(i) for i in sorted(self.removed_rock_ids)]

    def apply_removed_debris(self, ids):
        """Apply the list of debris the player removed back to the world.
        Felled trees and chopped debris must stay gone across a save/load, so
        the removed set is applied before the chunk is rebuilt.
        """
        self.removed_debris_ids = {tuple(i) for i in ids or ()}
        for tree in list(self.tree_sprites.sprites()):
            if getattr(tree, 'tree_id', None) in self.removed_debris_ids:
                tree.kill()

    def apply_removed_rocks(self, ids):
        self.removed_rock_ids = {tuple(i) for i in ids or ()}
        for rock in list(self.rock_sprites.sprites()):
            if getattr(rock, 'rock_id', None) in self.removed_rock_ids:
                rock.kill()

    def tree_surfs_for_sapling(self, item):
        """Growing stages for a sapling species: small then mature tree."""
        biome = SAPLING_BIOMES.get(item)
        trees = self.biome_assets.get(biome, {}).get('trees', [])
        if not trees:
            return ()
        if len(trees) == 1:
            return (trees[0],)
        return (trees[0], trees[1])

    def tree_surf_for_sapling(self, item):
        """Mature art for a sapling species (the medium tree variant)."""
        surfs = self.tree_surfs_for_sapling(item)
        return surfs[-1] if surfs else None

    # ---- CHUNK LIFECYCLE ----

    def _remove_chunk(self, key):
        """Remove all sprites belonging to a chunk."""
        staged = getattr(self, '_staged_chunk', None)
        if staged is not None and staged[0] == key:
            self._staged_chunk = None
        for sprite in self.active_chunks[key]:
            if sprite in self.all_sprites:
                self.all_sprites.remove(sprite)
            if hasattr(sprite, 'hitbox') and sprite in self.collision_sprites:
                self.collision_sprites.remove(sprite)
            if sprite in self.rock_sprites:
                self.rock_sprites.remove(sprite)
            if sprite in self.bush_sprites:
                self.bush_sprites.remove(sprite)
            if sprite in self.flower_sprites:
                self.flower_sprites.remove(sprite)
            sprite.kill()

    def draw_ground(self, display_surface, camera_offset, isometric=False):
        """Draw all active ground chunks."""
        sw, sh = display_surface.get_size()
        ox = int(camera_offset.x)
        oy = int(camera_offset.y)

        # Fill background
        display_surface.fill((0, 0, 0))

        # Water animation frame: ~2 fps (a change every 0.5s), calmer water.
        water_frame_idx = int(pygame.time.get_ticks() * 2 / 1000) % 4

        if not isometric:
            for key, chunk_surfs in self._chunk_surfs.items():
                cx, cy = key
                chunk_surf = chunk_surfs[min(water_frame_idx, len(chunk_surfs) - 1)]
                draw_x = cx * CHUNK_SIZE - ox
                draw_y = cy * CHUNK_SIZE - oy
                if (draw_x + chunk_surf.get_width() > 0 and draw_x < sw and
                    draw_y + chunk_surf.get_height() > 0 and draw_y < sh):
                    display_surface.blit(chunk_surf, (draw_x, draw_y))
            return

        # Isometric ground comes from iter_ground_entries; only the backdrop paints here.

    def update(self, player_pos, isometric=True, staggered=True):
        """Update chunks around the player. Runtime calls are staggered
        one build stage per frame; flushes load the whole ring at once."""
        pcx = int(player_pos.x // CHUNK_SIZE)
        pcy = int(player_pos.y // CHUNK_SIZE)
        needed = set()
        gen_radius = CHUNK_RADIUS + 1
        for dx in range(-gen_radius, gen_radius + 1):
            for dy in range(-gen_radius, gen_radius + 1):
                needed.add((pcx + dx, pcy + dy))

        # Remove distant chunks; farm/soil-water caches survive unload (player-owned).
        for key in [k for k in self.active_chunks if k not in needed]:
            self._remove_chunk(key)
            del self.active_chunks[key]
            self._chunk_surfs.pop(key, None)
            self._water_deco_cache.pop(key, None)
            self._non_water_cache.pop(key, None)
            self._ground_maps_dirty = True

        # A staged chunk cleaned up by _remove_chunk: just drop its state.
        if self._staged_chunk is not None:
            key = self._staged_chunk[0]
            if key not in needed or key not in self.active_chunks:
                self._staged_chunk = None

        missing = [k for k in sorted(
            needed, key=lambda k: (k[0] - pcx) ** 2 + (k[1] - pcy) ** 2)
            if k not in self.active_chunks]

        if not staggered:
            # Teleport/loading flush: build every missing chunk now, unstaged.
            self._staged_chunk = None
            for key in missing:
                cx, cy = key
                if not isometric:
                    # Flat mode: ground stays baked per chunk.
                    self._chunk_surfs[key] = [self._make_chunk_surface(cx, cy, False)]
                self.active_chunks[key] = self._generate_chunk(cx, cy)
        else:
            # One stage per frame; distance order keeps neighbour checks consistent.
            if self._staged_chunk is None and missing:
                self._start_staged_chunk(missing[0])
                if not isometric:
                    cx, cy = missing[0]
                    self._chunk_surfs[missing[0]] = [
                        self._make_chunk_surface(cx, cy, False)]
            if self._staged_chunk is not None:
                self._advance_staged_chunk()

        # Caches grow unbounded with play; they hold no live state, so clearing is safe.
        if len(self._lake_cache) > 400_000:
            self._lake_cache.clear()
        if len(self._river_cache) > 400_000:
            self._river_cache.clear()
        if len(self._terrain_cache) > 400_000:
            self._terrain_cache.clear()
        if len(self._biome_cache) > 400_000:
            self._biome_cache.clear()
        if len(self._moisture_cache) > 400_000:
            self._moisture_cache.clear()
        if len(self._detail_cache) > 400_000:
            self._detail_cache.clear()
        if len(self._non_water_cache) > 4_000:
            self._non_water_cache.clear()

    def init(self, player_pos, isometric=True):
        """Initialize world generation around the player."""
        self.active_chunks = {}
        self._staged_chunk = None
        self._chunk_surfs = {}
        self._water_deco_cache = {}
        self._farm_patch_cache = {}
        self._soil_water_cache = {}
        self._soilw_tile_map = {}
        self._soil_water_pool = None
        self._wdeco_tile_map = {}
        self._patch_tile_map = {}
        self._ground_maps_dirty = True
        self.update(player_pos, isometric)

    def tick_day(self):
        """Advance the bush refresh timer. Returns True on a refresh day."""
        self._bush_days += 1
        if self._bush_days < 5:
            return False
        self._bush_days = 0
        self.bush_refresh_nonce += 1
        return True

    def reset(self):
        """Reset the procedural world for a new day or a scene swap.
        Clears the noise and placement caches and re-seeds the props, but keeps
        the tree persistence state so felled trees stay felled.
        """
        for key in list(self.active_chunks.keys()):
            self._remove_chunk(key)
        self.active_chunks = {}
        self._staged_chunk = None
        self._chunk_surfs = {}
        self._terrain_cache = {}
        self._biome_cache = {}
        self._lake_cache = {}
        self._river_cache = {}
        self._moisture_cache = {}
        self._detail_cache = {}
        self._non_water_cache = {}
        self._water_deco_cache = {}
        self._soil_water_cache = {}
        self._soilw_tile_map = {}
        self._soil_water_pool = None
        self._wdeco_tile_map = {}
        self._patch_tile_map = {}
        self._ground_maps_dirty = True

    def set_farm_patch(self, world_x, world_y):
        """Track a farm patch tile so it renders on top of the ground."""
        cx = int(world_x // CHUNK_SIZE)
        cy = int(world_y // CHUNK_SIZE)
        key = (cx, cy)

        local_x = world_x - cx * CHUNK_SIZE
        local_y = world_y - cy * CHUNK_SIZE
        tx = int(local_x // TILE)
        ty = int(local_y // TILE)

        if tx < 0 or tx >= TILES_PER_CHUNK or ty < 0 or ty >= TILES_PER_CHUNK:
            return

        if key not in self._farm_patch_cache:
            self._farm_patch_cache[key] = set()
        self._farm_patch_cache[key].add((tx, ty))
        self._ground_maps_dirty = True

        # Preload the farm patch iso surface
        if self._farm_patch_iso is None:
            try:
                farm_patch = pygame.image.load(asset_path('graphics', 'world', 'farm_patch.png')).convert_alpha()
                # Authored like ground tiles: diamond face fills rows 0..64 of the 128x128 box.
                self._farm_patch_iso = pygame.transform.scale(
                    farm_patch, (ISO_TILE_WIDTH, ISO_TILE_WIDTH))
            except Exception as exc:  # missing art: patch fallback, but say why
                log_once('[WorldGen] farm_patch.png load failed', exc)
                self._farm_patch_iso = pygame.Surface(
                    (ISO_TILE_WIDTH, ISO_TILE_HEIGHT), pygame.SRCALPHA)
                self._farm_patch_iso.fill((120, 85, 50, 200))

    def clear_farm_patch(self, world_x, world_y):
        """Remove one farm-patch overlay tile (farmland expired)."""
        cx = int(world_x // CHUNK_SIZE)
        cy = int(world_y // CHUNK_SIZE)
        key = (cx, cy)
        tx = int((world_x - cx * CHUNK_SIZE) // TILE)
        ty = int((world_y - cy * CHUNK_SIZE) // TILE)
        tiles = self._farm_patch_cache.get(key)
        if tiles is None:
            return
        tiles.discard((tx, ty))
        if not tiles:
            self._farm_patch_cache.pop(key, None)
        self._ground_maps_dirty = True

    def _load_soil_water_pool(self):
        """Build the watered-soil overlay art pool.

        graphics/world/soil_water.png is authored like the other ground
        tiles: a 128x128 box whose diamond face fills rows 0..64, so it
        blits flush on the tile topleft exactly like the farm patch.
        """
        pool = []
        try:
            water = pygame.image.load(
                asset_path('graphics', 'world', 'soil_water.png')).convert_alpha()
            pool.append(pygame.transform.scale(
                water, (ISO_TILE_WIDTH, ISO_TILE_WIDTH)))
        except Exception as exc:  # missing art: overlay fallback, but say why
            log_once('[WorldGen] soil_water.png load failed', exc)
            fallback = pygame.Surface(
                (ISO_TILE_WIDTH, ISO_TILE_HEIGHT), pygame.SRCALPHA)
            pygame.draw.ellipse(
                fallback, (110, 150, 220, 190),
                (12, 4, ISO_TILE_WIDTH - 24, ISO_TILE_HEIGHT - 8))
            pool.append(fallback)
        return pool

    def set_soil_water(self, world_x, world_y, surf=None):
        """Mark a tilled tile as watered so the overlay draws above the
        farm patch, using the same per-chunk overlay mechanism."""
        cx = int(world_x // CHUNK_SIZE)
        cy = int(world_y // CHUNK_SIZE)
        key = (cx, cy)

        local_x = world_x - cx * CHUNK_SIZE
        local_y = world_y - cy * CHUNK_SIZE
        tx = int(local_x // TILE)
        ty = int(local_y // TILE)

        if tx < 0 or tx >= TILES_PER_CHUNK or ty < 0 or ty >= TILES_PER_CHUNK:
            return

        if self._soil_water_pool is None:
            self._soil_water_pool = self._load_soil_water_pool()
        if surf is None:
            surf = choice(self._soil_water_pool)

        tiles = self._soil_water_cache.setdefault(key, {})
        tiles[(tx, ty)] = surf
        self._ground_maps_dirty = True

    def clear_soil_water_at(self, world_x, world_y):
        """Remove one watered-soil overlay tile."""
        cx = int(world_x // CHUNK_SIZE)
        cy = int(world_y // CHUNK_SIZE)
        key = (cx, cy)
        tx = int((world_x - cx * CHUNK_SIZE) // TILE)
        ty = int((world_y - cy * CHUNK_SIZE) // TILE)
        tiles = self._soil_water_cache.get(key)
        if tiles is None:
            return
        tiles.pop((tx, ty), None)
        if not tiles:
            self._soil_water_cache.pop(key, None)
        self._ground_maps_dirty = True

    def clear_soil_water(self):
        """Remove every watered-soil overlay (dry weather / new day)."""
        self._soil_water_cache = {}
        self._soilw_tile_map = {}
        self._ground_maps_dirty = True
