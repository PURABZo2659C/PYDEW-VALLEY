"""Structure collision system.
Whole-tile blockers built from a structure's opaque art pixels, so the
player stops exactly at the visible outline (river-bank rule).
"""

from support import ground_footprint_tiles, tile_runs

import pygame


def structure_footprint(surf, foot_pad, wx, wy, min_frac=0.125):
    """The whole ground tiles this bottom-anchored structure covers.
    min_frac drops only true slivers, so doorsteps and paths stay free.
    """
    return ground_footprint_tiles(surf, foot_pad, wx, wy, min_frac=min_frac)


def structure_blockers(foot, tile=None):
    """Merge footprint tiles into one run rect per row — tile-aligned,
    tile-sized rects that behave like river-bank tiles edge to edge."""
    return list(tile_runs(foot, tile))


def occluded_stand_tiles(surf, foot_pad, min_px=100,
                         box_w=56, box_h=82, depth_only=True):
    """Whole tiles where a player standing on them would be painted over.
    Two gates: depth (the structure must sort after the player) and coverage
    (enough opaque art pixels inside the player's box).
    """
    import numpy as np
    if surf is None:
        return set()
    w, h = surf.get_size()
    alpha = pygame.surfarray.array_alpha(surf) > 10
    tiles = set()
    # Bounding ranges: the player box must intersect the art at all.
    # Feet at (64*(dx-dy), 32*(dx+dy)) from the anchor diamond centre;
    # art-local y of the feet = 32*(dx+dy) + h - foot_pad.
    max_dd = (w // 2 + box_w) // 64 + 1
    min_sum = -(h - foot_pad + box_h) // 32 - 1
    for dsum in range(min_sum, 0):          # depth gate: dx+dy < 0
        for ddiff in range(-max_dd, max_dd + 1):
            dx = (dsum + ddiff) // 2
            dy = (dsum - ddiff) // 2
            if dx + dy != dsum:
                continue                    # parity: keep integer tiles
            fx = 64 * ddiff                 # feet offset from anchor
            fy = 32 * dsum
            x0 = fx + w // 2 - box_w // 2
            y0 = fy + h - foot_pad - box_h
            x1, y1 = x0 + box_w, y0 + box_h
            cx0, cy0 = max(x0, 0), max(y0, 0)
            cx1, cy1 = min(x1, w), min(y1, h)
            if cx0 >= cx1 or cy0 >= cy1:
                continue
            n = int(alpha[cx0:cx1, cy0:cy1].sum())
            if n >= min_px:
                tiles.add((dx, dy))
    return tiles
