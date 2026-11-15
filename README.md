# PYDEW VALLEY

A Stardew Valley-inspired farming game written in Python with Pygame.

Version **2.6** - Windows.

![title](graphics/world/logo.png)

---

## Playing it

The game ships as a single ZIP. Unzip it somewhere you can write to
(your Desktop, not `C:\Program Files`) and double-click
`Pydew Valley\PydewValley.exe`. There is no installer and nothing is
written outside that folder - the save, the settings, the screenshots
and the log all sit next to the executable.

```
Pydew Valley\
├── PydewValley.exe                    the game
├── PYDEW VALLEY DOCUMENTATION.html    the in-game help page
├── THIRD_PARTY_NOTICES.txt            asset credits and licences
├── README.txt
├── save.json                          your world, inventory and progress
├── keybindings.json                   your key bindings
├── volume.json                        music and sound volume
├── Shots\                             camera screenshots
└── game.log                           written only if something goes wrong
```

Copy the folder to a USB stick and your world comes with it. Delete the
folder and the game and all its data are gone.

The game always opens full screen and stretches to the resolution of
your display.

The in-game help page is opened from the **HELP** button on the title
screen, and the same file is in the folder above.

### Controls

The controls are shown in the in-game help page and can be rebound from
the pause menu. The defaults are:

| Key | Action |
|---|---|
| `W` `A` `S` `D` | Move |
| `Enter` | Use the tool |
| `Right Shift` | Use / interact with the item in front of you |
| `E` | Inventory |
| `C` | Crafting |
| `Q` | Drop the held item |
| `1` - `9` | Pick a hotbar slot |
| `Esc` | Pause menu |

---

## Building it

The game source is at the top of this repository; the build tooling
lives in the `APP\` folder.

```
code\        the game
graphics\    art
audio\       music and sound
font\        fonts
data\        the starting map
APP\         build tooling - build.bat, the PyInstaller spec, scripts
```

Requirements: **Python 3.11+** with `pygame`, `numpy`, `pytmx` and
`opencv-python` installed.

```
pip install pygame numpy pytmx opencv-python
```

```
cd APP
build.bat              # the exe and the ZIP
build.bat exe          # only the single-file executable
build.bat zip          # only the ZIP
build.bat folder       # only the folder build
build.bat all          # everything
```

The result is `APP\dist\Pydew Valley [v2.6] Windows.zip` - one file,
about 111 MB, containing everything a player needs.

The version number comes from `APP\build\VERSION.txt`. That one file is
the single source of truth: the exe's file properties, the ZIP name and
the credits screen all read it. Bump it and rebuild to publish a new
version.

`APP\DISTRIBUTING.md` covers the rest - how to share the game, the
Windows Smart App Control problem and how to sign the executable so
that it is not blocked on other people's machines.

---

## Third-party assets

This game uses third-party art, fonts and music. The full list, with the
authors and their licence terms, is in
[`APP/THIRD_PARTY_NOTICES.txt`](APP/THIRD_PARTY_NOTICES.txt) and is
shipped with the game.

The short version:

* All art is **Sprout Lands** by Cup Nooble.
* The interface font is **Monocraft** by Idrees Inc (SIL OFL 1.1).
* The title screen music is **Yoiyami** (CC0); the in-game music is
  *"8bit attempt"* by Daniel Stephens.
* The project grew out of the **Clear Code** tutorial *"Creating a
  Stardew Valley-inspired game in Python and Pygame"*.

---

## Licence

The game code is MIT licensed - see [`LICENSE`](LICENSE).
