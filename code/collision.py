"""Structure collision system.

Builds whole-tile collision blockers from a structure's opaque art pixels
(``ground_footprint_tiles``) merged into per-row run rects
(``tile_runs``). Applied to village houses, cave entrances, and any other
bottom-anchored structure: the player stops on the tile line exactly at the
art's visible outline (river-bank rule — no invisible wall in open ground,
no squeezing between art pixels), and the ground the roof hides behind
stays solid so nobody walks into the structure.

Blockers are invisible Generic sprites added to ``collision_sprites``; they
ride the chunk sprite list so unloading cleans them up.

Usage::

    from collision import structure_blockers
    foot = ground_footprint_tiles(art, pad, wx, wy)
    for block in structure_blockers(foot):
        blocker = Generic(block.topleft, invisible_surf,
                          [collision_sprites], z=0)
        blocker.hitbox = block
        sprites.append(blocker)

The same footprint tiles are also used by the layout planner so paths never
cross a building, and by villager pathfinding so NPCs never cut through a
house.
"""

from support import ground_footprint_tiles, tile_runs

import pygame


def structure_footprint(surf, foot_pad, wx, wy, min_frac=0.125):
    """Return the set of whole ground tiles this bottom-anchored structure
    covers. ``min_frac=0.125`` drops only true slivers (under an eighth of
    the tile, i.e. a roof edge shaving the tile) so doorsteps and paths
    stay free, while every tile the structure really sits on — down to the
    corner the wall just clips — stays solid and the player stops on the
    tile line at the visible outline."""
    return ground_footprint_tiles(surf, foot_pad, wx, wy, min_frac=min_frac)


def structure_blockers(foot, tile=None):
    """Merge footprint tiles into one run rect per row — tile-aligned,
    tile-sized rects that behave like river-bank tiles edge to edge."""
    return list(tile_runs(foot, tile))


def occluded_stand_tiles(surf, foot_pad, min_px=100,
                         box_w=56, box_h=82, depth_only=True):
    """Whole tiles where a player standing on them would be PAINTED OVER
    by this bottom-anchored structure.

    The art is drawn bottom-centred on its anchor tile's diamond centre
    (lifted by ``foot_pad``); a player standing on a tile occupies
    ``box_w x box_h`` px directly above that tile's diamond centre (the
    measured opaque body box of the player sprite: 56x82). Two gates:

    * depth — the structure must sort AFTER the player there. In the
      iso depth key both use ``128 * (x + y) + 128`` (+ SPRITE_LIFT,
      which cancels), so the structure draws over a player standing on
      relative tile ``(dx, dy)`` exactly when ``dx + dy < 0``. On the
      front side (``dx + dy >= 0`` — doorway, apron, the depth tie
      itself) the player draws on top and can never be covered, so
      those tiles are never blocked: that is the structure's front.
    * coverage — at least ``min_px`` opaque art pixels must fall inside
      the player's box, so a roof edge that only clips the air above
      someone's head does not turn open ground into a wall.

    Returns tiles RELATIVE to the structure's anchor. The result is the
    walkable complement of "visible overlap": everywhere else a player
    may stand next to the structure and stay fully visible, in front of
    it as well as behind it.
    """
    import numpy as np
    if surf is None:
        return set()
    w, h = surf.get_size()
    alpha = pygame.surfarray.array_alpha(surf) > 10
    tiles = set()
    # bounding ranges: the player box must intersect the art at all.
    # feet at (64*(dx-dy), 32*(dx+dy)) from the anchor diamond centre;
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
