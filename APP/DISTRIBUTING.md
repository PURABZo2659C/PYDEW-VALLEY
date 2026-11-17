# Distributing PYDEW VALLEY

The build tooling lives in this `APP` folder. The game source
(`code\`, `graphics\`, `audio\`, `font\`, `data\`) is one level up.

**Windows packaging.** There is no browser build. The release workflow
also builds macOS and Linux ZIPs; this file covers the Windows one.

## What you have

| File | What it is |
|---|---|
| `dist\Pydew Valley [v*] Windows.zip` | **The Windows deliverable.** One file, ~111 MB. A friend unzips it and plays - no installer, no admin rights. |
| `dist\Pydew-Valley-v*-macos.zip` | The macOS build, downloaded by `build.bat` from the GitHub release. |
| `dist\Pydew-Valley-v*-linux.zip` | The Linux build, downloaded by `build.bat` from the GitHub release. |
| `dist\PydewValley.exe` | The single-file build on its own, ~111 MB. Same game, no ZIP. |
| `dist\PydewValley\` | The folder build: `PydewValley.exe` + a `data\` folder. Instant start, but the small launcher is the one Smart App Control dislikes. |

The version number comes from `build\VERSION.txt` - that one file is the
single source of truth. The exe's file properties, the ZIP name and the
credits screen all read it.

PyInstaller cannot cross-compile, so `build.bat` only builds Windows
locally. The macOS and Linux ZIPs are built by the Build and Release
workflow and copied into `dist\` for the same version.

Rebuild with:

```
build.bat              # exe + Windows ZIP + the other two OS ZIPs
build.bat exe          # only the single-file executable
build.bat zip          # only the Windows ZIP
build.bat folder       # only the folder build
build.bat all          # everything Windows (used by CI)
build.bat fetch        # macOS/Linux ZIPs only (downloads again)
```

---

## How to share it

Send someone the **ZIP**. They unzip it somewhere they can write to
(their Desktop, not `C:\Program Files`) and double-click
`Pydew Valley\PydewValley.exe`. That is the whole install.

The ZIP contains:

```
Pydew Valley/
├── PydewValley.exe                  the game
├── PYDEW VALLEY DOCUMENTATION.html   the in-game help page
├── THIRD_PARTY_NOTICES.txt          asset credits and licences
└── README.txt                       how to play, where the save is
```

The first start unpacks the game into a temporary folder, so give it a
few seconds before the window appears.

The game always opens full screen and stretches to the resolution of
the display. There is no windowed mode and no settings file.

## The portable model

Everything the game writes goes into the folder next to the executable:

```
Pydew Valley\
├── PydewValley.exe
├── PYDEW VALLEY DOCUMENTATION.html
├── THIRD_PARTY_NOTICES.txt
├── README.txt
├── save.json                    your world, inventory and progress
├── keybindings.json             your key bindings
├── volume.json                  music and sound volume
├── Shots\                       camera screenshots
└── game.log                     written only if something goes wrong
```

So the game is genuinely portable:

* **Copy the folder to a USB stick** and your world comes with it.
* **Unzip a new version straight over the old folder** - your save stays
  where it is. That is the entire update process.
* **Delete the folder** and the game and all its data are gone.

Nothing is written to `%APPDATA%` or anywhere else on the machine.

---

## Smart App Control - the thing that will bite you

**Windows 11 blocks unsigned executables outright.** This is not the
SmartScreen "Windows protected your PC" screen with its *More info -> Run
anyway* button. Smart App Control has no such button - the file simply
refuses to run:

```
'PydewValley.exe' was blocked by your organization's Device Guard policy.
```

Windows records it under **Microsoft-Windows-CodeIntegrity/Operational**:

```
did not meet the Enterprise signing level requirements
```

### What was measured on the build machine

| Test | Result |
|---|---|
| Smart App Control state | **On** (`VerifiedAndReputablePolicyState = 1`) |
| Folder build launcher (~5 MB) | **BLOCKED** - every time |
| Single file build (~111 MB) | **Runs** - but see below |
| Same bytes, copied to other folders | Same verdict, so it is not the path |
| A rebuilt single file build (new hash) | **BLOCKED** again |
| Self-signed certificate in the *user's* Root store | Signature reports `Valid` - still blocked |

Two conclusions:

**The 5 MB folder launcher is reliably blocked.** It is the stock
PyInstaller bootloader, byte for byte the same file that thousands of
PyInstaller applications share - including malware - so Windows'
reputation service treats it badly. The single file build is a
completely different binary and stands a much better chance. That is
why the ZIP ships the single file build.

**An unsigned build is never guaranteed.** Windows decides on the *cloud
reputation of that exact binary*. A build that was allowed this
afternoon can be blocked after you rebuild it, because the new file has
never been seen before. You cannot rely on an unsigned build for other
people.

### Your options

#### 0. Sign it with your own certificate (free, two steps)

Smart App Control validates the signature chain against the **local
machine's** Trusted Root store. A certificate that is only in your own
user profile is *not* enough - that was tested and the game was still
blocked.

```
build\sign_local_setup.cmd     (run once, as your normal user)
build\sign_local.cmd           (right-click -> Run as administrator)
```

The first creates a self-signed code-signing certificate and exports it
to `build\pydew-valley.cer`. The second installs it into
LocalMachine\Root and signs `dist\PydewValley.exe`.

For friends, send the `.cer` next to the ZIP. They double-click it,
choose **Trusted Root Certification Authorities**, click **Install**,
and the game runs. One extra step, but it is permanent and it does not
turn off a protection feature on their machine.

> This path was not finished on the build machine - the UAC prompt could
> not be completed from the session that ran the build. The machine-level
> trust store is what Device Guard consults, so this is expected to work,
> but please confirm it on your own machine first.

**Re-sign after every rebuild** - a signature lives inside the file, so a
new build has none.

#### 1. Buy a code-signing certificate

The only option where your friends do nothing at all, and it also
removes the slow startup.

| Option | Cost | Notes |
|---|---|---|
| OV code-signing cert (DigiCert, Sectigo, Certum) | ~$70-200 / year | Smart App Control accepts it straight away |
| EV code-signing cert | ~$250-600 / year | Faster reputation, useful if you publish widely |
| Microsoft Azure Trusted Signing | ~$10 / month | Needs an Azure tenant and an identity check |
| SignPath.io | free | Only for **public open-source** repos |

Then:

1. Export the certificate as a `.pfx`
2. Put it at `build\cert.pfx`
3. Put the password in `build\cert.pfx.pass` (or set `CERT_PASSWORD`)
4. Run:

```
powershell -ExecutionPolicy Bypass -File build\sign_build.ps1
```

That signs the executable with SHA256 and a timestamp, so the signature
stays valid after the certificate expires.

> `sign_build.ps1` uses `Set-AuthenticodeSignature`, which is part of
> Windows - no Windows SDK and no `signtool` needed.

#### 2. Have your friends turn Smart App Control off

Windows Security -> App & browser control -> Smart App Control -> **Off**.

Free, and it works. Two warnings:

* It is a **one-way door** - once off, it cannot be turned back on without
  resetting Windows.
* It turns off a protection layer on their machine, so only ask friends
  who understand that trade-off.

#### 3. Stick to Windows 10 players

No Smart App Control, no certificate, no changes.

---

## Updating

Bump the version in `build\VERSION.txt` (that one file is the single
source of truth - the exe's file properties, the ZIP name and the
credits screen all read it), then:

```
build.bat
build\sign_local.cmd  (as administrator, if you are signing)
```

The new ZIP has the new version in its name, for example
`Pydew Valley [v2.7] Windows.zip`. Send it to your friends; they unzip
it over the old folder and keep their save.

---

## Third-party assets

`THIRD_PARTY_NOTICES.txt` is bundled inside the game and shipped in the
ZIP. It credits every third-party asset and its licence.

The short version:

* All art is **Sprout Lands by Cup Nooble** - the free Basic Pack allows
  non-commercial projects, and the credit in the credits screen and in
  `THIRD_PARTY_NOTICES.txt` satisfies the licence. Selling the game would
  need the Premium pack.
* The interface font is **Monocraft** by Idrees Inc (SIL Open Font
  License 1.1). The credits screen font is **pixelFont-7-8x14** by Cup
  Nooble.
* The title screen music is **Yoiyami** (CC0). The in-game music is
  *"8bit attempt"* by **Daniel Stephens**.
* The audio files and the starting TMX map, plus the project name, come
  from the **Clear Code** tutorial *"Creating a Stardew Valley-inspired
  game in Python and Pygame"*. This game grew out of that project. The
  credits screen and the notices file credit it.
* The "Inspired by" row in the credits shows the Minecraft, Stardew Valley,
  Mine Mogul and Isocore logos.
