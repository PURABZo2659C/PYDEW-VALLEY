"""Rewrite the long comment blocks into short, to-the-point comments.

Every entry is (file, first line of the block, new comment text). The
text is written without the leading indent - it is taken from the block
it replaces. Blocks are rewritten from the bottom of the file upwards so
the line numbers stay valid while the work is in progress.
"""

import io
import os
import sys

CODE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'code')

# (file, line, new text)
REPLACEMENTS = [
    # ---------------- cave_generator.py ----------------
    ('cave_generator.py', 49,
     "# Cave props (rocks / ore veins / decorations): session state.\n"
     "# Placement is deterministic per tile, so leaving and returning\n"
     "# restores the same veins - except the ones the player mined."),
    ('cave_generator.py', 327,
     "# Lava fill drawn raw and hollow, like the overworld's water plane.\n"
     "# Each tile runs its own phase, so the ocean bubbles out of lockstep."),

    # ---------------- collision.py ----------------
    ('collision.py', 82,
     "# Bounding ranges: the player box must intersect the art at all.\n"
     "# Feet at (64*(dx-dy), 32*(dx+dy)) from the anchor diamond centre;\n"
     "# art-local y of the feet = 32*(dx+dy) + h - foot_pad."),

    # ---------------- debug_controls.py ----------------
    ('debug_controls.py', 459,
     "# Start in the field the click landed on, so the trailing AM / PM\n"
     "# word is directly toggleable instead of only reachable via Tab."),
    ('debug_controls.py', 536,
     "# The player grid takes a leading '-' in EITHER field: a freshly\n"
     "# focused field counts as empty, so '-9999' is as typeable as '9999'."),

    # ---------------- input_manager.py ----------------
    ('input_manager.py', 55,
     "# Mouse buttons can be bound. They are encoded as NEGATIVE ints so\n"
     "# they never collide with pygame key codes: -(event.button)."),

    # ---------------- inventory_model.py ----------------
    ('inventory_model.py', 19,
     "# Older saves stored 'Bread'; keys are lowercase everywhere now, so\n"
     "# slots are normalised on load."),

    # ---------------- main.py ----------------
    ('main.py', 11,
     "# SCALED | FULLSCREEN stretches the logical surface to the desktop\n"
     "# resolution without switching the display mode (alt-tabbing stays\n"
     "# safe). The game always opens full screen."),
    ('main.py', 34,
     "# Another copy of the game may still hold the save file open. Carry\n"
     "# on, but say so - otherwise CONTINUE would bring back the old world."),
    ('main.py', 66,
     "# The loop runs on asyncio so the event loop gets a turn every frame."),

    # ---------------- overlay.py ----------------
    ('overlay.py', 246,
     "# The card is as wide as the coords panel above it, but the panel\n"
     "# art is only 165px, so anchor the art to the card's RIGHT edge."),

    # ---------------- pause_menu.py ----------------
    ('pause_menu.py', 185,
     "# While waiting for a rebind, a mouse button becomes the new\n"
     "# binding. The close button stays a cancel, the wheel still scrolls."),

    # ---------------- quest_menu.py ----------------
    ('quest_menu.py', 228,
     "# DEMO mode: once the town quests are done, stock the materials to\n"
     "# craft the Heart of the Valley."),

    # ---------------- sky.py ----------------
    ('sky.py', 95,
     "# A white grade is an identity multiply: skipping it leaves the\n"
     "# framebuffer untouched and saves a full-screen blit each frame."),

    # ---------------- soil.py ----------------
    ('soil.py', 57,
     "# Transparent rows under each frame's visible art (tomato sprouts\n"
     "# float up to 26px otherwise). The renderer lifts by foot_pad so the\n"
     "# VISIBLE art bottom lands on the tile diamond center."),

    # ---------------- sprites.py ----------------
    ('sprites.py', 10,
     "# Shared decoded sounds: chunk generation creates dozens of sprites\n"
     "# and decoding the file per placement was a profiled hot spot."),
    ('sprites.py', 60,
     "# Remove from every group we registered with. Iterate a copy:\n"
     "# remove() mutates the group's list as we walk it."),
    ('sprites.py', 351,
     "# Fast rect reject, then a pixel-precise overlap so small items\n"
     "# (bush, seed, ore) pick up on their visible shape."),
    ('sprites.py', 386,
     "# Trunk hitbox: a narrow box on the tree's world position, sized\n"
     "# proportionally so it stays correct if the art changes."),
    ('sprites.py', 398,
     "# 'bottom' = art bottom on the tile diamond center (trees).\n"
     "# 'center' = image center on the tile diamond center (logs, stumps)."),
    ('sprites.py', 416,
     "# Natural trees carry a stable chunk id so a felled tree stays gone\n"
     "# across chunk reloads. Planted trees drop their save record."),
    ('sprites.py', 604,
     "# Prop art is not centered in its canvas: pin the BASE DIAMOND\n"
     "# CENTER to the tile diamond center (renderer 'pixel' mode)."),
    ('sprites.py', 735,
     "# This hit would break the bed, so the bed has to fit in the bag\n"
     "# first. A full bag means no break sound or animation at all."),
    ('sprites.py', 788,
     "# The finishing hit needs a free bag slot for the plank, so a full\n"
     "# bag leaves the deck standing."),

    # ---------------- support.py ----------------
    ('support.py', 49,
     "# Extra icon sources: biome art for foraged flowers/fungi and the\n"
     "# world folder for placeables. Overlay art wins on a name clash."),
    ('support.py', 200,
     "# Big downscales alias badly in one pass; halving to ~2x first\n"
     "# box-filters and cuts the per-pixel premultiply work."),
    ('support.py', 302,
     "# array_alpha is indexed [x][y], so np.nonzero hands back the\n"
     "# COLUMN first and the ROW second: xs = c, ys = r."),
    ('support.py', 373,
     "# Diamond edges: the column's half-height grows 0.5px per px from\n"
     "# either side vertex, so it spans top..bottom around the centre row."),

    # ---------------- title_screen.py ----------------
    ('title_screen.py', 110,
     "# background video - OpenCV is optional, without it the title\n"
     "# screen falls back to its still background."),
    ('title_screen.py', 127,
     "# Menu music. First slot that exists wins:\n"
     "#   audio/Title_background.wav    - title theme by Yoiyami (CC0)\n"
     "#   graphics/world/background.mp3 - optional user track\n"
     "#   audio/menu.mp3                 - optional user track\n"
     "#   audio/music.mp3                - in-game track (fallback)\n"
     "# Only the CC0 title theme and the in-game track ship with the game."),
    ('title_screen.py', 354,
     "# Never wipe a save on a single click: ask first. YES starts fresh\n"
     "# (main deletes the old save), NO keeps it and points at CONTINUE."),
    ('title_screen.py', 578,
     "# QUIT calls pygame.quit() before sys.exit(), so the mixer may\n"
     "# already be down. Guard every teardown call."),
]


def indent_of(line):
    return line[:len(line) - len(line.lstrip())]


def apply_file(name, edits):
    """edits: list of (line_no, new_text), 1-based, applied bottom-up."""
    path = os.path.join(CODE, name)
    with io.open(path, 'r', encoding='utf-8', newline='') as handle:
        text = handle.read()
    lines = text.split('\n')

    for line_no, new_text in sorted(edits, key=lambda e: -e[0]):
        # find the extent of the comment block starting at line_no
        start = line_no - 1
        if start >= len(lines) or not lines[start].strip().startswith('#'):
            raise SystemExit('%s:%d - not a comment line: %r'
                             % (name, line_no, lines[start] if start < len(lines) else None))
        indent = indent_of(lines[start])
        end = start
        while end + 1 < len(lines) and lines[end + 1].strip().startswith('#'):
            end += 1
        # a trailing lone '#' separator line belongs to the block
        block = lines[start:end + 1]
        if len(block) > 1 and block[-1].strip() == '#':
            end -= 1
            block = lines[start:end + 1]

        new_lines = []
        for part in new_text.split('\n'):
            new_lines.append((indent + part) if part else '')
        lines[start:end + 1] = new_lines

    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write('\n'.join(lines))
    print('  %-24s %d block(s)' % (name, len(edits)))


def main():
    by_file = {}
    for name, line_no, text in REPLACEMENTS:
        by_file.setdefault(name, []).append((line_no, text))

    for name in sorted(by_file):
        apply_file(name, by_file[name])
    print('%d comment blocks rewritten.' % len(REPLACEMENTS))


if __name__ == '__main__':
    main()
