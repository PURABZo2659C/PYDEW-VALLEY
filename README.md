# PYDEW VALLEY

A Stardew Valley-inspired farming game written in Python with Pygame.

Version **2.6** - Windows, macOS and Linux

![title](graphics/world/logo.png)

---

## Download and play

Download the ZIP for your operating system from the project's
[GitHub Releases](https://github.com/PURABZo2659C/PYDEW-VALLEY/releases)
page. Each release includes:

| ZIP file | Platform | How to start |
|---|---|---|
| `Pydew-Valley-v<version>-windows.zip` | 64-bit Windows | Extract the ZIP, open the `Pydew Valley` folder and run `PydewValley.exe`. |
| `Pydew-Valley-v<version>-macos.zip` | macOS | Extract the ZIP and open `PydewValley.app`. |
| `Pydew-Valley-v<version>-linux.zip` | 64-bit Linux | Extract the ZIP, then run `./PydewValley` from a terminal in the extracted folder. |

There is no installer. Extract the download to a folder you can write to.
On Linux, if the executable does not start because it is not marked
executable, run `chmod +x PydewValley` first. The Linux build targets
64-bit systems and needs a graphical desktop with SDL-compatible
libraries.

The game opens full screen and stretches to your display resolution. The
in-game help page is available from the **HELP** button on the title
screen.

### Saves and settings

The game stores `save.json`, `keybindings.json`, `volume.json`,
screenshots and (if needed) `game.log` next to the game executable.
Keep the extracted game in a folder where your account has write
permission. To back up progress, close the game and copy `save.json`;
to move your settings too, also copy `keybindings.json` and
`volume.json`. When updating, back up these files before replacing the
old game files.

The Windows ZIP also includes `README.txt`, the HTML help page and
`THIRD_PARTY_NOTICES.txt`. The macOS and Linux packages contain their
respective PyInstaller app/executable bundles.

### Platform notes

- **Windows:** Windows may show a security warning for an unsigned
  download. Only run software you trust.
- **macOS:** If Gatekeeper blocks the app because it is from an
  unidentified developer, use macOS **Privacy & Security** settings to
  review and allow it only if you trust this download.
- **Linux:** Run the executable from its extracted folder so it can
  access its bundled files and write its save data.

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

Requirements for building: **Python 3.11+** with `pygame`, `numpy`,
`pytmx`, `opencv-python`, `PyInstaller` and `Pillow` installed. Build
each platform on that platform; PyInstaller does not cross-compile.

```
pip install pygame numpy pytmx opencv-python
pip install pyinstaller pillow
```

### Build Windows

Run these commands in **Command Prompt** from the repository root:

```
cd APP
build.bat              REM executable and ZIP
build.bat exe          REM executable only
build.bat zip          REM ZIP only
build.bat folder       REM folder build only
build.bat all          REM all outputs
```

The Windows package is written to
`APP\dist\Pydew Valley [v<version>] Windows.zip`.

### Build macOS and Linux

On the target OS, install the build dependencies above, then run these
commands from the repository root. On Linux, also install SDL2
development files (for Ubuntu: `sudo apt-get install libsdl2-dev`).

```sh
cd APP
python build/make_version_info.py
python build/make_icon.py
python build/fix_line_endings.py
python -m PyInstaller --clean --noconfirm PydewValley.spec
```

On macOS this creates `APP\dist\PydewValley.app`; on Linux it creates
`APP\dist\PydewValley`. To create the matching release ZIP on macOS:

```sh
VER=$(cat build/VERSION.txt)
cd dist
zip -r "Pydew-Valley-v${VER}-macos.zip" PydewValley.app
```

On Linux, use:

```sh
VER=$(cat build/VERSION.txt)
cd dist
zip "Pydew-Valley-v${VER}-linux.zip" PydewValley
```

The automated release workflow performs these steps and publishes all
three platform ZIPs together.

The version number comes from `APP\build\VERSION.txt`. That one file is
the single source of truth: the exe's file properties, the ZIP name and
the credits screen all read it. Bump it and rebuild to publish a new
version.

GitHub Actions builds Windows, macOS and Linux ZIPs for each release.
Push a `v*` tag or run **Build and Release** from the Actions tab with a
release tag such as `v2.6`. Wait for all platform jobs to finish; the
workflow then creates or updates one GitHub Release with all three ZIPs
attached. The version comes from `APP\build\VERSION.txt`; use a
corresponding tag when publishing a release.

`APP\DISTRIBUTING.md` has additional Windows distribution notes,
including Smart App Control and code signing.

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
