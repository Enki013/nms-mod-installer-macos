#!/usr/bin/env python3
"""
NMS Mod Installer for macOS
============================
Extracts HGPAK .pak archives, replaces files with mod contents,
repacks with LZ4 compression, and installs them back into the game.

Requires: hgpaktool (pip3 install --user hgpaktool)

Usage:
    python3 nms_mod_installer.py set-game <path>
    python3 nms_mod_installer.py install <mod_folder> [--game <path>] [--dry-run]
    python3 nms_mod_installer.py uninstall <mod_name>  [--game <path>]
    python3 nms_mod_installer.py list                  [--game <path>]
    python3 nms_mod_installer.py scan <mod_folder>     [--game <path>]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from collections import defaultdict
from typing import Optional, List, Dict, Tuple

# ── Constants ────────────────────────────────────────────────────────────────

MACOSBANKS_REL = "Contents/Resources/GAMEDATA/MACOSBANKS"
BACKUP_DIR_NAME = "_MOD_BACKUPS"
REGISTRY_FILE = "_mod_registry.json"
CONFIG_FILE = "_config.json"

GAME_SEARCH_PATHS = [
    "/Applications/No Man's Sky.app",
    os.path.expanduser("~/Applications/No Man's Sky.app"),
    os.path.expanduser("~/Library/Application Support/Steam/steamapps/common/No Man's Sky/No Man's Sky.app"),
]

HGPAKTOOL_CANDIDATES = [
    shutil.which("hgpaktool"),
    os.path.expanduser("~/Library/Python/3.9/bin/hgpaktool"),
    os.path.expanduser("~/Library/Python/3.10/bin/hgpaktool"),
    os.path.expanduser("~/Library/Python/3.11/bin/hgpaktool"),
    os.path.expanduser("~/Library/Python/3.12/bin/hgpaktool"),
]

SCRIPT_DIR = Path(__file__).resolve().parent
MBINCOMPILER_DLL = SCRIPT_DIR / "bin" / "MBINCompiler.dll"

GLOBAL_PREFIXES = ["globals/"]


# ── Helpers ──────────────────────────────────────────────────────────────────

class Style:
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def info(msg):
    print(f"{Style.CYAN}[INFO]{Style.RESET} {msg}")


def success(msg):
    print(f"{Style.GREEN}[OK]{Style.RESET}   {msg}")


def warn(msg):
    print(f"{Style.YELLOW}[WARN]{Style.RESET} {msg}")


def error(msg):
    print(f"{Style.RED}[ERR]{Style.RESET}  {msg}")


def fatal(msg):
    error(msg)
    sys.exit(1)


def human_size(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def find_hgpaktool():
    for candidate in HGPAKTOOL_CANDIDATES:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def run_hgpaktool(tool_path, args, cwd=None):
    cmd = [tool_path] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        error(f"hgpaktool failed: {result.stderr.strip()}")
        raise RuntimeError(f"hgpaktool exited with code {result.returncode}")
    return result.stdout


def load_config() -> dict:
    config_path = SCRIPT_DIR / CONFIG_FILE
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    config_path = SCRIPT_DIR / CONFIG_FILE
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def auto_detect_game() -> Optional[str]:
    for path in GAME_SEARCH_PATHS:
        candidate = Path(path)
        if candidate.exists() and (candidate / MACOSBANKS_REL).exists():
            return str(candidate)
    return None


def resolve_game_path(game_path_override: Optional[str] = None):
    if game_path_override:
        game = Path(game_path_override).expanduser().resolve()
        if not game.exists():
            fatal(f"Game path not found: {game}")
        banks = game / MACOSBANKS_REL
        if not banks.exists():
            fatal(f"MACOSBANKS not found at: {banks}")
        return game, banks

    config = load_config()
    saved = config.get("game_path")
    if saved:
        game = Path(saved)
        if game.exists() and (game / MACOSBANKS_REL).exists():
            return game, game / MACOSBANKS_REL
        warn(f"Saved game path no longer valid: {saved}")

    detected = auto_detect_game()
    if detected:
        game = Path(detected)
        info(f"Auto-detected game at: {game}")
        config["game_path"] = str(game)
        save_config(config)
        return game, game / MACOSBANKS_REL

    fatal(
        "No Man's Sky not found. Specify the path with:\n"
        "  python3 nms_mod_installer.py set-game /path/to/No Man's Sky.app\n"
        "  or use --game /path/to/No Man's Sky.app with any command"
    )


def find_mbincompiler() -> Optional[str]:
    if MBINCOMPILER_DLL.exists():
        dotnet = shutil.which("dotnet")
        if dotnet:
            return str(MBINCOMPILER_DLL)
    return None


def run_mbincompiler(input_path: Path, output_dir: Path) -> Optional[Path]:
    """Run MBINCompiler on a file. Returns path to output file or None."""
    mbinc = find_mbincompiler()
    if not mbinc:
        return None

    is_mbin = input_path.suffix.lower() in (".mbin",)
    is_exml = input_path.suffix.lower() in (".exml", ".mxml")

    with tempfile.TemporaryDirectory(prefix="mbinc_") as tmpdir:
        if is_exml:
            tmp_in = Path(tmpdir) / input_path.with_suffix(".MXML").name
        else:
            tmp_in = Path(tmpdir) / input_path.name
        shutil.copy2(input_path, tmp_in)

        result = subprocess.run(
            ["dotnet", "exec", mbinc, str(tmp_in)],
            capture_output=True, text=True, cwd=tmpdir
        )

        if is_exml:
            tmp_out = tmp_in.with_suffix(".MBIN")
        else:
            tmp_out = tmp_in.with_suffix(".MXML")

        if result.returncode == 0 and tmp_out.exists():
            dest = output_dir / tmp_out.name
            shutil.copy2(tmp_out, dest)
            return dest

        error(f"MBINCompiler failed: {result.stdout.strip()} {result.stderr.strip()}")
        return None


def is_partial_exml(exml_path: Path) -> bool:
    """Detect if an EXML file is a partial modification (delta patch)."""
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(exml_path)
        root = tree.getroot()
        props = root.findall(".//Property")
        has_id = any(p.get("_id") is not None for p in props)
        total_top_level = len(root.findall("./Property"))
        deep_count = len(props)
        if has_id and deep_count < 50:
            return True
        if not has_id and deep_count < 20 and total_top_level > 0:
            return True
        return False
    except Exception:
        return False


def merge_exml(original_exml: Path, mod_exml: Path, output_exml: Path) -> bool:
    """Merge a partial mod EXML into the full original EXML."""
    import xml.etree.ElementTree as ET

    try:
        orig_tree = ET.parse(original_exml)
        mod_tree = ET.parse(mod_exml)
    except ET.ParseError as e:
        error(f"XML parse error: {e}")
        return False

    orig_root = orig_tree.getroot()
    mod_root = mod_tree.getroot()

    def find_by_id(parent, tag, id_val):
        for child in parent.iter(tag):
            if child.get("_id") == id_val:
                return child
        return None

    def find_by_name(parent, name_val):
        for child in parent:
            if child.tag == "Property" and child.get("name") == name_val:
                return child
        return None

    def merge_properties(orig_parent, mod_parent):
        for mod_prop in mod_parent:
            if mod_prop.tag != "Property":
                continue

            mod_id = mod_prop.get("_id")
            mod_name = mod_prop.get("name")
            mod_value = mod_prop.get("value")

            target = None
            if mod_id:
                target = find_by_id(orig_parent, "Property", mod_id)
                if target is not None:
                    for key, val in mod_prop.attrib.items():
                        if key != "_id":
                            target.set(key, val)
                    merge_properties(target, mod_prop)
                    continue

            if mod_name:
                target = find_by_name(orig_parent, mod_name)
                if target is not None:
                    if mod_value is not None:
                        target.set("value", mod_value)
                    if len(mod_prop) > 0:
                        merge_properties(target, mod_prop)
                    continue

    merge_properties(orig_root, mod_root)

    ET.indent(orig_tree, space="  ")
    orig_tree.write(output_exml, encoding="utf-8", xml_declaration=True)
    return True


def convert_exml_to_mbin(exml_path: Path, mbin_path: Path, original_mbin: Optional[Path] = None) -> bool:
    """Convert EXML to MBIN with optional merge for partial mods."""
    mbinc = find_mbincompiler()
    if not mbinc:
        error("MBINCompiler not found. Cannot convert EXML files.")
        return False

    partial = is_partial_exml(exml_path)

    with tempfile.TemporaryDirectory(prefix="exml_conv_") as tmpdir:
        tmpdir_p = Path(tmpdir)

        if partial and original_mbin and original_mbin.exists():
            info(f"    Partial EXML detected -> merging with original game data")
            orig_exml = run_mbincompiler(original_mbin, tmpdir_p)
            if not orig_exml:
                error(f"    Failed to decompile original MBIN")
                return False

            merged_exml = tmpdir_p / "merged.MXML"
            if not merge_exml(orig_exml, exml_path, merged_exml):
                error(f"    EXML merge failed")
                return False

            result_mbin = run_mbincompiler(merged_exml, tmpdir_p)
            if result_mbin:
                shutil.copy2(result_mbin, mbin_path)
                return True
            return False
        else:
            tmp_mxml = tmpdir_p / exml_path.with_suffix(".MXML").name
            shutil.copy2(exml_path, tmp_mxml)
            result_mbin = run_mbincompiler(tmp_mxml, tmpdir_p)
            if result_mbin:
                shutil.copy2(result_mbin, mbin_path)
                return True
            return False


def is_exml_file(path: str) -> bool:
    return path.lower().endswith(".exml")


def exml_to_mbin_path(path: str) -> str:
    """Convert .exml/.EXML extension to .mbin in a path string."""
    if path.lower().endswith(".exml"):
        return path[:-5] + ".mbin"
    return path


def resolve_global_path(filename: str, pak_index: 'PakIndex') -> Optional[str]:
    """Search the pak index for a file that's under a 'Globals/' shorthand prefix."""
    fname_lower = filename.lower()
    for indexed_path in pak_index._index:
        if indexed_path.endswith("/" + fname_lower) or indexed_path == fname_lower:
            return indexed_path
    return None


# ── Pak Index ────────────────────────────────────────────────────────────────

class PakIndex:
    """Builds and caches a mapping of internal file paths -> pak filenames."""

    CACHE_FILE = "_pak_index_cache.json"

    def __init__(self, banks_dir: Path, tool_path: str):
        self.banks_dir = banks_dir
        self.tool_path = tool_path
        self._index = {}  # lowercase_internal_path -> pak_filename
        self._pak_contents = {}  # pak_filename -> [internal_paths]

    def build(self, force=False):
        cache_path = self.banks_dir / self.CACHE_FILE
        if not force and cache_path.exists():
            cache_age = time.time() - cache_path.stat().st_mtime
            if cache_age < 86400:  # 24h cache
                info("Using cached pak index (< 24h old). Use --force-reindex to rebuild.")
                with open(cache_path) as f:
                    data = json.load(f)
                self._index = data.get("index", {})
                self._pak_contents = data.get("contents", {})
                return

        info("Building pak index (scanning all .pak files)...")
        pak_files = sorted(self.banks_dir.glob("NMSARC.*.pak"))
        total = len(pak_files)

        with tempfile.TemporaryDirectory() as tmpdir:
            listing_path = os.path.join(tmpdir, "filenames.json")
            for i, pak in enumerate(pak_files, 1):
                pak_name = pak.name
                if pak_name.startswith("_"):
                    continue
                print(f"\r  Scanning [{i}/{total}] {pak_name:<45}", end="", flush=True)
                try:
                    run_hgpaktool(self.tool_path, ["-L", str(pak)], cwd=tmpdir)
                    with open(listing_path) as f:
                        data = json.load(f)
                    for _pak_path, files in data.items():
                        self._pak_contents[pak_name] = files
                        for fpath in files:
                            self._index[fpath.lower()] = pak_name
                except Exception as e:
                    warn(f"Could not scan {pak_name}: {e}")

            print()  # newline after progress

        info(f"Indexed {len(self._index)} files across {len(self._pak_contents)} paks.")

        with open(cache_path, "w") as f:
            json.dump({"index": self._index, "contents": self._pak_contents}, f)

    def find_pak(self, internal_path: str) -> Optional[str]:
        return self._index.get(internal_path.lower())

    def get_pak_files(self, pak_name: str) -> List[str]:
        return self._pak_contents.get(pak_name, [])


# ── Mod Registry ─────────────────────────────────────────────────────────────

class ModRegistry:
    """Tracks installed mods and which pak files they modified."""

    def __init__(self, banks_dir: Path):
        self.path = banks_dir / REGISTRY_FILE
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {"mods": {}}

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def register(self, mod_name, mod_info):
        self.data["mods"][mod_name] = mod_info
        self.save()

    def unregister(self, mod_name):
        self.data["mods"].pop(mod_name, None)
        self.save()

    def get(self, mod_name):
        return self.data["mods"].get(mod_name)

    def list_mods(self):
        return self.data["mods"]


# ── Core Operations ──────────────────────────────────────────────────────────

def scan_mod(mod_folder: Path, banks_dir: Path, tool_path: str):
    """Scan a mod folder and determine which pak files it affects."""
    index = PakIndex(banks_dir, tool_path)
    index.build()

    SKIP_FILES = {".ds_store", "thumbs.db", "desktop.ini", "readme.txt", "readme.md"}

    mod_files = []
    for root, _dirs, files in os.walk(mod_folder):
        for fname in files:
            if fname.lower() in SKIP_FILES:
                continue
            full = Path(root) / fname
            rel = full.relative_to(mod_folder)
            internal = str(rel).lower()
            mod_files.append((full, internal))

    pak_map = defaultdict(list)  # pak_name -> [(mod_file_path, internal_path, needs_convert)]
    unmatched = []

    for full_path, internal_path in mod_files:
        needs_convert = False
        search_path = internal_path

        if is_exml_file(internal_path):
            search_path = exml_to_mbin_path(internal_path)
            needs_convert = True

        pak = index.find_pak(search_path)

        if not pak:
            for prefix in GLOBAL_PREFIXES:
                if internal_path.startswith(prefix):
                    filename = internal_path[len(prefix):]
                    if is_exml_file(filename):
                        filename = exml_to_mbin_path(filename)
                        needs_convert = True
                    resolved = resolve_global_path(filename, index)
                    if resolved:
                        search_path = resolved
                        pak = index.find_pak(resolved)
                        break

        if pak:
            pak_map[pak].append((full_path, search_path, needs_convert))
        else:
            unmatched.append(internal_path)

    return pak_map, unmatched


def install_mod(mod_folder: Path, game_path: Path, banks_dir: Path, tool_path: str,
                dry_run=False, force_reindex=False):
    """Full mod installation pipeline."""
    mod_name = mod_folder.name
    info(f"Installing mod: {Style.BOLD}{mod_name}{Style.RESET}")
    print()

    registry = ModRegistry(banks_dir)
    if registry.get(mod_name):
        warn(f"Mod '{mod_name}' is already installed. Uninstall first or use a different name.")
        return False

    # 1) Scan
    info("Phase 1: Scanning mod files and matching to pak archives...")
    if force_reindex:
        cache = banks_dir / PakIndex.CACHE_FILE
        if cache.exists():
            cache.unlink()

    pak_map, unmatched = scan_mod(mod_folder, banks_dir, tool_path)

    if not pak_map:
        fatal("No mod files matched any game pak archive. Check the mod folder structure.")

    has_exml = any(nc for _, _, nc in sum(pak_map.values(), []))
    if has_exml:
        mbinc = find_mbincompiler()
        if not mbinc:
            fatal(
                "This mod contains .EXML files that require MBINCompiler for conversion.\n"
                "  MBINCompiler.dll not found in bin/ directory.\n"
                "  See README for setup instructions."
            )
        info(f"MBINCompiler found (EXML -> MBIN conversion available)")

    print()
    info(f"Mod affects {Style.BOLD}{len(pak_map)}{Style.RESET} pak archive(s):")
    for pak_name, files in sorted(pak_map.items()):
        print(f"  {Style.CYAN}{pak_name}{Style.RESET} ({len(files)} file(s))")
        for _, internal, needs_convert in files:
            tag = f" {Style.YELLOW}[EXML->MBIN]{Style.RESET}" if needs_convert else ""
            print(f"    -> {internal}{tag}")

    if unmatched:
        print()
        warn(f"{len(unmatched)} file(s) did not match any pak (will be skipped):")
        for u in unmatched:
            print(f"    {Style.DIM}{u}{Style.RESET}")

    if dry_run:  
        print()
        info("Dry run complete. No files were modified.")
        return True

    # 2) Backup
    print()
    info("Phase 2: Backing up original pak files...")
    backup_dir = banks_dir / BACKUP_DIR_NAME / mod_name
    backup_dir.mkdir(parents=True, exist_ok=True)

    backed_up_paks = []
    for pak_name in pak_map:
        pak_path = banks_dir / pak_name
        backup_path = backup_dir / pak_name
        if not backup_path.exists():
            shutil.copy2(pak_path, backup_path)
            backed_up_paks.append(pak_name)
            success(f"Backed up {pak_name} ({human_size(pak_path.stat().st_size)})")
        else:
            info(f"Backup already exists for {pak_name}")

    # 3) Extract, Replace, Repack
    print()
    info("Phase 3: Patching pak archives...")

    with tempfile.TemporaryDirectory(prefix="nms_mod_") as tmpdir:
        tmpdir = Path(tmpdir)

        for pak_name, files in sorted(pak_map.items()):
            pak_path = banks_dir / pak_name
            extract_dir = tmpdir / pak_name.replace(".pak", "")
            extract_dir.mkdir()

            print()
            info(f"Processing {Style.BOLD}{pak_name}{Style.RESET}...")

            # Extract
            info(f"  Extracting...")
            run_hgpaktool(tool_path, [
                "-U", "-M", str(pak_path),
                "-O", str(extract_dir)
            ], cwd=str(extract_dir))

            manifest_name = f"{pak_name}.manifest"
            manifest_path = extract_dir / manifest_name
            if not manifest_path.exists():
                error(f"  Manifest not found after extraction: {manifest_name}")
                continue

            # Replace files
            replaced = 0
            for mod_file, internal_path, needs_convert in files:
                target = extract_dir / internal_path
                if target.exists():
                    old_size = target.stat().st_size
                    if needs_convert:
                        info(f"  Converting EXML -> MBIN: {Path(mod_file).name}")
                        converted = target.parent / (target.stem + ".converted.mbin")
                        if not convert_exml_to_mbin(mod_file, converted, original_mbin=target):
                            warn(f"  Skipping {internal_path} (conversion failed)")
                            continue
                        shutil.copy2(converted, target)
                        converted.unlink()
                    else:
                        shutil.copy2(mod_file, target)
                    new_size = target.stat().st_size
                    success(f"  Replaced: {internal_path} ({human_size(old_size)} -> {human_size(new_size)})")
                    replaced += 1
                else:
                    warn(f"  Target not found in extracted pak: {internal_path}")

            if replaced == 0:
                warn(f"  No files replaced in {pak_name}, skipping repack.")
                continue

            # Repack
            info(f"  Repacking with LZ4 compression...")
            output_pak = tmpdir / pak_name
            run_hgpaktool(tool_path, [
                "-R", "-Z",
                str(manifest_path),
                "-O", str(output_pak)
            ], cwd=str(extract_dir))

            # Install
            final_size = output_pak.stat().st_size
            original_size = pak_path.stat().st_size
            shutil.copy2(output_pak, pak_path)
            success(f"  Installed: {pak_name} ({human_size(original_size)} -> {human_size(final_size)})")

    # 4) Register
    print()
    registry.register(mod_name, {
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_folder": str(mod_folder),
        "affected_paks": list(pak_map.keys()),
        "file_count": sum(len(v) for v in pak_map.values()),
        "backed_up_paks": backed_up_paks,
    })

    success(f"Mod '{Style.BOLD}{mod_name}{Style.RESET}' installed successfully!")
    info(f"Backups stored in: {backup_dir}")
    return True


def uninstall_mod(mod_name: str, banks_dir: Path):
    """Restore original pak files from backup."""
    registry = ModRegistry(banks_dir)
    mod_info = registry.get(mod_name)

    if not mod_info:
        available = list(registry.list_mods().keys())
        if available:
            fatal(f"Mod '{mod_name}' is not installed. Installed mods: {', '.join(available)}")
        else:
            fatal(f"No mods are installed.")

    info(f"Uninstalling mod: {Style.BOLD}{mod_name}{Style.RESET}")
    backup_dir = banks_dir / BACKUP_DIR_NAME / mod_name

    if not backup_dir.exists():
        fatal(f"Backup directory not found: {backup_dir}")

    for pak_name in mod_info["affected_paks"]:
        backup_pak = backup_dir / pak_name
        target_pak = banks_dir / pak_name
        if backup_pak.exists():
            shutil.copy2(backup_pak, target_pak)
            success(f"Restored: {pak_name}")
        else:
            warn(f"Backup not found for {pak_name}")

    shutil.rmtree(backup_dir, ignore_errors=True)
    registry.unregister(mod_name)
    success(f"Mod '{mod_name}' uninstalled.")


def resolve_mod_name(identifier: str, banks_dir: Path) -> str:
    """Resolve a mod name from an index number or exact name."""
    registry = ModRegistry(banks_dir)
    mods = registry.list_mods()

    if not mods:
        fatal("No mods are installed.")

    try:
        idx = int(identifier)
        mod_names = list(mods.keys())
        if 1 <= idx <= len(mod_names):
            return mod_names[idx - 1]
        fatal(f"Invalid index: {idx}. Use a number between 1 and {len(mod_names)}.")
    except ValueError:
        pass

    if identifier in mods:
        return identifier

    for name in mods:
        if name.lower() == identifier.lower():
            return name

    available = list(mods.keys())
    fatal(f"Mod '{identifier}' not found. Installed mods: {', '.join(available)}")


def list_mods(banks_dir: Path):
    """List all installed mods."""
    registry = ModRegistry(banks_dir)
    mods = registry.list_mods()

    if not mods:
        info("No mods installed.")
        return

    print(f"\n{Style.BOLD}Installed Mods:{Style.RESET}\n")
    for i, (name, meta) in enumerate(mods.items(), 1):
        print(f"  {Style.BOLD}[{i}]{Style.RESET} {Style.CYAN}{name}{Style.RESET}")
        print(f"      Installed:     {meta.get('installed_at', '?')}")
        print(f"      Files changed: {meta.get('file_count', '?')}")
        print(f"      Paks affected: {', '.join(meta.get('affected_paks', []))}")
        print()

    info(f"To uninstall: python3 nms_mod_installer.py uninstall <number>")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="nms_mod_installer",
        description="No Man's Sky Mod Installer for macOS (HGPAK)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s set-game "/Applications/No Man's Sky.app"
  %(prog)s install "~/Downloads/Turkish Localisation"
  %(prog)s install ./MyMod --dry-run
  %(prog)s uninstall 2
  %(prog)s list
  %(prog)s scan ./MyMod
        """,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    game_help = "Path to No Man's Sky.app (auto-detected if not provided)"

    # set-game
    p_setgame = sub.add_parser("set-game", help="Set the game path")
    p_setgame.add_argument("game_path", help="Path to No Man's Sky.app")

    # install
    p_install = sub.add_parser("install", help="Install a mod from a folder")
    p_install.add_argument("mod_folder", help="Path to the mod folder")
    p_install.add_argument("--game", default=None, help=game_help)
    p_install.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    p_install.add_argument("--force-reindex", action="store_true", help="Force rebuild of pak index cache")

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="Uninstall a mod by index or name")
    p_uninstall.add_argument("mod_name", help="Index number (from list) or mod name")
    p_uninstall.add_argument("--game", default=None, help=game_help)

    # list
    p_list = sub.add_parser("list", help="List installed mods")
    p_list.add_argument("--game", default=None, help=game_help)

    # scan
    p_scan = sub.add_parser("scan", help="Scan a mod folder without installing")
    p_scan.add_argument("mod_folder", help="Path to the mod folder")
    p_scan.add_argument("--game", default=None, help=game_help)

    args = parser.parse_args()

    # Header
    print()
    print(f"{Style.BOLD}NMS Mod Installer for macOS{Style.RESET}")
    print(f"{Style.DIM}HGPAK extract / replace / repack pipeline{Style.RESET}")
    print()

    # Locate hgpaktool
    tool = find_hgpaktool()
    if not tool:
        fatal(
            "hgpaktool not found. Install it with:\n"
            "  pip3 install --user hgpaktool"
        )
    info(f"Using hgpaktool: {tool}")

    # Handle set-game
    if args.command == "set-game":
        gp = Path(args.game_path).expanduser().resolve()
        if not gp.exists():
            fatal(f"Path not found: {gp}")
        if not (gp / MACOSBANKS_REL).exists():
            fatal(f"Not a valid NMS installation (MACOSBANKS not found): {gp}")
        config = load_config()
        config["game_path"] = str(gp)
        save_config(config)
        success(f"Game path set to: {gp}")
        return

    # Resolve game path
    game_arg = getattr(args, "game", None)
    game_path, banks_dir = resolve_game_path(game_arg)
    info(f"Game: {game_path}")
    info(f"Banks: {banks_dir}")
    print()

    if args.command == "install":
        mod_folder = Path(args.mod_folder).expanduser().resolve()
        if not mod_folder.is_dir():
            fatal(f"Mod folder not found: {mod_folder}")
        install_mod(mod_folder, game_path, banks_dir, tool,
                    dry_run=args.dry_run, force_reindex=args.force_reindex)

    elif args.command == "uninstall":
        mod_name = resolve_mod_name(args.mod_name, banks_dir)
        uninstall_mod(mod_name, banks_dir)

    elif args.command == "list":
        list_mods(banks_dir)

    elif args.command == "scan":
        mod_folder = Path(args.mod_folder).expanduser().resolve()
        if not mod_folder.is_dir():
            fatal(f"Mod folder not found: {mod_folder}")

        pak_map, unmatched = scan_mod(mod_folder, banks_dir, tool)

        print()
        if pak_map:
            info(f"Mod would affect {len(pak_map)} pak(s):")
            for pak_name, files in sorted(pak_map.items()):
                print(f"\n  {Style.CYAN}{pak_name}{Style.RESET}")
                for _, internal, needs_convert in files:
                    tag = f" {Style.YELLOW}[EXML->MBIN]{Style.RESET}" if needs_convert else ""
                    print(f"    {internal}{tag}")
        else:
            warn("No mod files matched any game pak archive.")

        if unmatched:
            print()
            warn(f"{len(unmatched)} file(s) did not match:")
            for u in unmatched:
                print(f"    {Style.DIM}{u}{Style.RESET}")


if __name__ == "__main__":
    main()
