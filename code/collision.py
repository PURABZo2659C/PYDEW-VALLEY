"""Structure collision system.

Two kinds of blockers live here:
- whole-tile footprint rects, built from a structure's opaque art pixels,
  for layout work (paths, reserved ground) and the missing-mask cave
  doorway fallback;
- tight outline rects, projected from the authored collision masks in
  graphics/world/Collisions, so a placed structure (village building or
  cave entrance) stops the player at its visible edge instead of at a
  whole ground tile.
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


def structure_outline_blockers(surf, foot_pad, wx, wy, step=8, hole=None):
    """Tight ground-plane rects that follow a structure's collision mask.

    The authored masks in graphics/world/Collisions are drawn in the same
    isometric view as the art, so every opaque mask pixel maps back to the
    ground plane at (mx + 2*my, 2*my - mx) from the structure's anchor.
    Snapping those points to a small grid and merging each row's runs
    traces the visible outline instead of blocking whole ground tiles.

    ``hole`` is an optional world-space rect (the doorstep tile) carved
    out so entrances stay walkable.

    The projection is cached per mask: a village loads the same seven
    masks over and over, and the mask -> ground work is the expensive
    part.
    """
    hole_rel = None
    if hole is not None and hole.width > 0 and hole.height > 0:
        hole_rel = (hole.left - wx, hole.top - wy, hole.width, hole.height)

    # Anchors sit on tile centres, so the mask's grid lines up with the
    # anchor's; the phase keeps the maths right if that ever changes.
    ax, ay = wx // step, wy // step
    phase = (wx - ax * step, wy - ay * step)

    rel_rects = _outline_rects(surf, foot_pad, step, hole_rel, phase)
    if not rel_rects:
        return []

    return [pygame.Rect(r[0] + ax * step, r[1] + ay * step, r[2], r[3])
            for r in rel_rects]


_OUTLINE_CACHE = {}


def _outline_rects(surf, foot_pad, step, hole_rel, phase=(0, 0)):
    """Anchor-relative ground rects for one mask (cached)."""
    key = (surf, foot_pad, step, hole_rel, phase)
    cached = _OUTLINE_CACHE.get(key)
    if cached is not None:
        return cached

    import numpy as np

    w, h = surf.get_size()
    alpha = pygame.surfarray.array_alpha(surf)
    xs, ys = np.nonzero(alpha > 10)
    if xs.size == 0:
        _OUTLINE_CACHE[key] = []
        return []

    # Screen-space offset from the bottom-centre anchor.
    mx = xs.astype(np.int64) - w // 2
    my = ys.astype(np.int64) - (h - foot_pad)
    # Inverse isometric projection: screen offset -> ground offset.
    gx = phase[0] + mx + 2 * my
    gy = phase[1] + 2 * my - mx
    cells = set(zip(np.floor_divide(gx, step).tolist(),
                    np.floor_divide(gy, step).tolist()))

    if hole_rel is not None:
        hx0 = (phase[0] + hole_rel[0]) // step
        hy0 = (phase[1] + hole_rel[1]) // step
        hx1 = (phase[0] + hole_rel[0] + hole_rel[2] - 1) // step
        hy1 = (phase[1] + hole_rel[1] + hole_rel[3] - 1) // step
        cells = {c for c in cells
                 if not (hx0 <= c[0] <= hx1 and hy0 <= c[1] <= hy1)}

    rects = [(r.left, r.top, r.width, r.height)
             for r in tile_runs(cells, step)]
    _OUTLINE_CACHE[key] = rects
    return rects


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
    # Bounding ranges: feet at (64*(dx-dy), 32*(dx+dy)), y = 32*(dx+dy) + h - foot_pad.
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


_FRONT_TILE_CACHE = {}


def structure_front_tiles(surf, foot_pad, door=(0, 0), radius=3):
    """Doorway tiles where a structure's art would cover a standing player.

    Returned relative to the structure's anchor tile. The painter lifts the
    player above the structure on these tiles, so standing at a front door
    never hides them behind the facade. Only tiles within ``radius`` of the
    door keep this priority: walking round the back still lets the roof
    cover the player.
    """
    if surf is None:
        return frozenset()
    key = (surf, foot_pad, door, radius)
    cached = _FRONT_TILE_CACHE.get(key)
    if cached is None:
        dx, dy = door
        cached = frozenset(
            tile for tile in occluded_stand_tiles(surf, foot_pad)
            if abs(tile[0] - dx) <= radius and abs(tile[1] - dy) <= radius)
        _FRONT_TILE_CACHE[key] = cached
    return cached

