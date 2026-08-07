# NMS Mod Installer for macOS

A command-line tool for installing mods into **No Man's Sky** on macOS by patching HGPAK `.pak` archives.

On macOS, the game's built-in `MODS` folder does not work. This tool bridges that gap by extracting `.pak` archives, replacing files with mod contents, and repacking them with LZ4 compression — all automatically.

## How It Works

```
┌──────────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Mod Folder  │────>│  Scan &  │────>│  Extract  │────>│ Replace  │────>│  Repack  │
│              │     │  Match   │     │   .pak    │     │  Files   │     │  & Install│
└──────────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘
                          │                                                   │
                     Maps mod files                                    LZ4 compressed
                     to game .paks                                     HGPAK v2 format
                                                                            │
                                                                            ▼
                                                                    ┌──────────────┐
                                                                    │  MACOSBANKS/ │
                                                                    │  (game dir)  │
                                                                    └──────────────┘
```

1. **Scan** — Indexes all `.pak` archives in the game and maps each mod file to its target `.pak`
2. **Backup** — Copies original `.pak` files to `_MOD_BACKUPS/` before any changes
3. **Extract** — Unpacks affected `.pak` archives using `hgpaktool -U -M`
4. **Replace** — Overwrites extracted files with mod versions (case-insensitive matching)
5. **Repack** — Rebuilds `.pak` archives with LZ4 compression using `hgpaktool -R -Z`
6. **Register** — Records installed mod metadata for clean uninstall later

## Requirements

- **macOS** (tested on macOS 15+)
- **Python 3.9+** (pre-installed on macOS)
- **[hgpaktool](https://github.com/monkeyman192/HGPAKtool)** — installed automatically with pip
- **.NET 8 Runtime** — required for EXML-based mods, installed once via `nms-mod-installer setup`

## Installation

### PyPI (recommended)

```bash
pip install nms-mod-installer-macos
```

Then run the one-time setup to download MBINCompiler (required for EXML mods):

```bash
nms-mod-installer setup
```

This downloads `MBINCompiler.exe` + `libMBIN.dll` from the
[official MBINCompiler releases](https://github.com/monkeyman192/MBINCompiler/releases)
into `~/.local/share/nms-mod-installer/bin/` and verifies your `dotnet` installation.

> **Note:** `.NET 8 Runtime` must be installed before running `setup`.
> [Download here](https://dotnet.microsoft.com/en-us/download/dotnet/8.0)

### Git clone (developers / contributors)

```bash
git clone https://github.com/Enki013/nms-mod-installer-macos.git
cd nms-mod-installer-macos
pip install hgpaktool
python3 nms_mod_installer.py setup
```

## Usage

All commands are available as `nms-mod-installer <command>` after pip install,
or `python3 nms_mod_installer.py <command>` from a git clone.

### Set game path (first time only)

The tool auto-detects the game in common locations (`/Applications`, `~/Applications`, Steam library). If auto-detection fails, set it manually:

```bash
nms-mod-installer set-game "/Applications/No Man's Sky.app"
```

The path is saved to `~/.local/share/nms-mod-installer/` and remembered for future runs.
You can also use `--game <path>` with any command to override.

### Scan a mod (preview, no changes)

```bash
nms-mod-installer scan ~/Downloads/MyMod
```

Shows which `.pak` files the mod will affect without modifying anything.

### Interactive wizard (beginner mode)

```bash
nms-mod-installer wizard
```

Step-by-step guided CLI flow for scan/install/list/uninstall without remembering commands.

### Install a mod

```bash
nms-mod-installer install ~/Downloads/MyMod
```

Full pipeline: scan, backup originals, extract, replace, repack, install.

<img src="docs/images/install.gif" alt="Install command in terminal">

To preview which paks a mod touches without installing, use `scan` (see above).

### List installed mods

```bash
nms-mod-installer list
```

<img src="docs/images/list.png" alt="Installed mods list with index numbers" width="900">

### Uninstall a mod

```bash
nms-mod-installer uninstall 2
# or by name:
nms-mod-installer uninstall "MyMod"
```

Restores original `.pak` files from backup.

<img src="docs/images/uninstall.png" alt="Uninstalling a mod by index" width="900">

### Options

| Flag | Description |
|---|---|
| `--game <path>` | Path to `No Man's Sky.app` (auto-detected or saved via `set-game`) |
| `--force-reindex` | Rebuild the pak index cache (use after game updates) |

## Mod Folder Structure

Mods must mirror the game's internal directory structure. File and folder names are **case-insensitive**.

```
MyMod/
├── LANGUAGE/
│   └── NMS_LOC1_ENGLISH.MBIN
├── FONTS/
│   └── GAME/
│       └── CONSOLEFONT2.TTF
├── TEXTURES/
│   └── PLANETS/
│       └── ...
└── METADATA/
    └── REALITY/
        └── TABLES/
            └── SOME_TABLE.MBIN
```

The tool automatically determines which `.pak` archive each file belongs to.

## Example: Turkish Language Patch

```bash
# Preview
nms-mod-installer scan ~/Downloads/Turkish\ Localisation

# Output:
# Mod would affect 3 pak(s):
#   NMSARC.Language.pak    (8 files)
#   NMSARC.Precache.pak    (1 file)
#   NMSARC.fonts.pak       (1 file)

# Install
nms-mod-installer install ~/Downloads/Turkish\ Localisation

# Verify
nms-mod-installer list

# Uninstall if needed
nms-mod-installer uninstall 1
```

## Game File Structure (macOS)

On macOS, No Man's Sky stores assets differently from Windows:

| | Windows | macOS |
|---|---|---|
| Archive directory | `GAMEDATA/PCBANKS/` | `GAMEDATA/MACOSBANKS/` |
| MODS folder | Supported | **Not supported** |
| Compression | ZSTD | LZ4 |
| Archive format | HGPAK v2 | HGPAK v2 |

```
No Man's Sky.app/
└── Contents/Resources/GAMEDATA/MACOSBANKS/
    ├── NMSARC.Language.pak      # Localization strings
    ├── NMSARC.fonts.pak         # Game fonts
    ├── NMSARC.Precache.pak      # Metadata, dialog tables, UI
    ├── NMSARC.globals.pak       # Global game settings
    ├── NMSARC.Materials.pak     # Material definitions
    ├── NMSARC.UI.pak            # UI definitions
    ├── NMSARC.TexPlanet*.pak    # Planet textures (per-biome)
    ├── NMSARC.MeshPlanet*.pak   # 3D models
    └── ...
```

## Technical Details

### HGPAK Format

- **Magic:** `HGPAK\x00\x00\x00` (8 bytes)
- **Version:** 2 (uint64 LE)
- **Compression:** LZ4 (macOS), ZSTD (Windows/Linux), Oodle (Switch)
- Introduced in NMS 5.50 (Worlds Part II), replacing the older PSARC format

### Tool Chain

```bash
hgpaktool -L <pak>                          # List contents (outputs filenames.json)
hgpaktool -U -M <pak> -O <dir>             # Extract + generate manifest
hgpaktool -R -Z <manifest> -O <output.pak>  # Repack with compression
```

### Caching

On first run, the tool scans all `.pak` files and builds an index cache (`_pak_index_cache.json`). This cache is valid for 24 hours. After a game update, use `--force-reindex` to rebuild it.

## Troubleshooting

### Permission denied (do not use `sudo`)

The installer must write inside `No Man's Sky.app/.../MACOSBANKS/`. If you see **Permission denied**, do **not** run it with `sudo` (that runs the script as root and can confuse file ownership).

**Preferred:** install or copy the game under your user, e.g. `~/Applications/No Man's Sky.app`, so you already own the files.

**If the game is in `/Applications` and owned by root**, fix ownership once:

```bash
sudo chown -R "$(whoami)" "/Applications/No Man's Sky.app"
```

### hgpaktool not found

```bash
pip install hgpaktool

# If not on PATH after pip install:
export PATH="$PATH:$HOME/Library/Python/3.9/bin"
```

### MBINCompiler not found (EXML mods)

If you see `MBINCompiler not found`, run the setup command:

```bash
nms-mod-installer setup
```

This downloads `MBINCompiler.exe` and `libMBIN.dll` automatically.
Requires [.NET 8 Runtime](https://dotnet.microsoft.com/en-us/download/dotnet/8.0).

### `.NET` is installed but `dotnet` is not found

If you've already installed the .NET SDK but the installer still reports that `dotnet` is missing, try the following:

1. Close and reopen Terminal.
2. Verify that .NET is available:

   ```bash
   dotnet --info
   ```

3. If the command is still not found, ensure the .NET installation directory is in your `PATH`.

On macOS (Apple Silicon), add this to your shell profile if necessary:

```bash
export PATH="$PATH:/usr/local/share/dotnet"
```

or, if using Homebrew:

```bash
export PATH="$PATH:/opt/homebrew/share/dotnet"
```

After updating your `PATH`, restart your terminal and run:

```bash
dotnet --info
```

### Mod stopped working after game update

Game updates overwrite `.pak` files. Reinstall the mod:

```bash
nms-mod-installer install ~/Downloads/MyMod --force-reindex
```

### Game won't launch / crashes

Remove mods and restore originals:

```bash
nms-mod-installer uninstall "MyMod"
```

Or manually:

```bash
cd "No Man's Sky.app/Contents/Resources/GAMEDATA/MACOSBANKS"
cp _MOD_BACKUPS/MyMod/*.pak ./
```

### macOS "damaged app" warning

Modifying `.pak` files may break the app's code signature:

```bash
xattr -cr ~/Applications/No\ Man\'s\ Sky.app
codesign --force --deep --sign - ~/Applications/No\ Man\'s\ Sky.app
```

## License

[MIT](LICENSE)

## Credits

- **[hgpaktool](https://github.com/monkeyman192/HGPAKtool)** by monkeyman192 — HGPAK extraction and repacking
- **[Hello Games](https://hellogames.org/)** — No Man's Sky
