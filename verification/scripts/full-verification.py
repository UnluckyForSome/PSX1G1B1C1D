#!/usr/bin/env python3
"""
Full verification script combining DAT download/filtering and collection report generation.

This script:
1. Downloads the latest Redump .dat file
2. Updates and runs Retool to filter the .dat file
3. Generates a comprehensive report comparing the collection to the filtered .dat file

For automated runs (non-interactive), cleanup prompts are skipped.
"""

import requests
import zipfile
import subprocess
import shutil
import io
from pathlib import Path
from datetime import datetime
import sys
import xml.etree.ElementTree as ET
import html
import re
from collections import defaultdict

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
LIBRARY_DIR = SCRIPT_DIR.parent.parent / "library"
COMPOSITES_DIR = SCRIPT_DIR.parent.parent / "composites"
EXTRAS_DIR = SCRIPT_DIR.parent.parent / "extras"
DAT_DIR = SCRIPT_DIR.parent / "dat"
REPORTS_DIR = SCRIPT_DIR.parent / "reports"
RETOOL_DIR = SCRIPT_DIR.parent.parent / "tooling" / "retool"
USER_CONFIG_SOURCE = SCRIPT_DIR.parent / "configs" / "user-config.yaml"
RETOOL_CONFIG_DIR = RETOOL_DIR / "config"
RETOOL_CONFIG_DEST = RETOOL_CONFIG_DIR / "user-config.yaml"
RETOOL_REPO_URL = "https://github.com/unexpectedpanda/retool.git"
COMPLETION_MD_PATH = SCRIPT_DIR.parent.parent / "COMPLETION.md"
README_MD_PATH = SCRIPT_DIR.parent.parent / "README.md"
README_MD_PATH = SCRIPT_DIR.parent.parent / "README.md"

# Retool filter settings
RETOOL_FLAGS = ["-n", "-l", "--report"]

# "AabBcDdefkMmoPpruv" taken from the filename when using the gui version of Retool
RETOOL_EXCLUDE = ["A", "a", "b", "B", "c", "D", "d", "e", "f", "k", "M", "m", "o", "P", "p", "r", "u", "v"]

# Retool dependencies
RETOOL_DEPENDENCIES = [
    "alive-progress",
    "darkdetect",
    "lxml",
    "psutil",
    "pyside6",
    "strictyaml",
    "validators"
]

# Collection directories
COLLECTION_DIRS = {
    "2dbox": [
        LIBRARY_DIR / "2dbox",
        LIBRARY_DIR / "2dbox-lq",
        LIBRARY_DIR / "2dbox-missing",
    ],
    "3dbox": [
        LIBRARY_DIR / "3dbox",
        LIBRARY_DIR / "3dbox-lq",
        LIBRARY_DIR / "3dbox-missing",
    ],
    "disc": [
        LIBRARY_DIR / "disc",
        LIBRARY_DIR / "disc-lq",
        LIBRARY_DIR / "disc-missing",
    ],
    "psp-icon0": [
        COMPOSITES_DIR / "psp-icon0" / "psp-icon0-generated",
        COMPOSITES_DIR / "psp-icon0" / "psp-icon0-bespoke",
    ],
}

PSP_ICON0_BESPOKE_DIR = COMPOSITES_DIR / "psp-icon0" / "psp-icon0-bespoke"

# Check if running in non-interactive mode (e.g., GitHub Actions)
NON_INTERACTIVE = not sys.stdin.isatty()


# ============================================================================
# DAT Download and Filtering Functions (from download-and-filter-redump-dat.py)
# ============================================================================

def check_git_available() -> bool:
    """Check if git is available on the system."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def clone_retool_if_needed(retool_dir: Path) -> bool:
    """Clone Retool repository if it doesn't exist or is not a git repository."""
    retool_script = retool_dir / "retool.py"
    
    # If retool.py exists, assume Retool is already set up
    if retool_script.exists():
        print(f"  ✅ Retool already exists")
        print(f"     Location: {retool_dir}")
        return True
    
    # Check if git is available
    if not check_git_available():
        print(f"✗ Git is not available. Cannot clone Retool.", file=sys.stderr)
        print(f"  Please install git or ensure Retool is already set up at {retool_dir}", file=sys.stderr)
        return False
    
    # Check if it's a git repository (might be a partial clone)
    is_git_repo = (retool_dir / ".git").exists()
    
    try:
        # Remove directory if it exists but isn't a valid Retool installation
        if retool_dir.exists() and not is_git_repo:
            print(f"  🗑️  Removing invalid Retool directory...")
            shutil.rmtree(retool_dir)
        
        # Clone Retool if directory doesn't exist or was removed
        if not retool_dir.exists():
            print(f"  📥 Cloning Retool from GitHub...")
            print(f"     Repository: {RETOOL_REPO_URL}")
            result = subprocess.run(
                ["git", "clone", RETOOL_REPO_URL, str(retool_dir)],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                print(f"  ❌ Failed to clone Retool: {result.stderr}", file=sys.stderr)
                return False
            
            print(f"  ✅ Retool cloned successfully")
            print(f"     Location: {retool_dir}")
        else:
            print(f"  ✅ Retool directory already exists")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error setting up Retool: {e}", file=sys.stderr)
        return False


def copy_user_config() -> bool:
    """Copy user-config.yaml to Retool config directory."""
    if not USER_CONFIG_SOURCE.exists():
        print(f"  ⚠️  User config not found")
        print(f"     Expected: {USER_CONFIG_SOURCE}")
        print(f"     ℹ️  Retool will use default configuration")
        return True
    
    try:
        # Ensure config directory exists
        RETOOL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Copy the file
        shutil.copy2(USER_CONFIG_SOURCE, RETOOL_CONFIG_DEST)
        
        print(f"  ✅ User config copied successfully")
        print(f"     From: {USER_CONFIG_SOURCE.name}")
        print(f"     To:   {RETOOL_CONFIG_DEST}")
        return True
        
    except Exception as e:
        print(f"  ⚠️  Warning: Could not copy user config: {e}", file=sys.stderr)
        return True  # Continue anyway - Retool will use defaults


def install_retool_dependencies() -> bool:
    """Install Retool dependencies."""
    print(f"  📦 Installing {len(RETOOL_DEPENDENCIES)} package(s)...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + RETOOL_DEPENDENCIES,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            print(f"  ✅ Dependencies installed successfully")
            return True
        else:
            print(f"  ⚠️  Warning installing dependencies: {result.stderr}", file=sys.stderr)
            return True  # Continue anyway
    except Exception as e:
        print(f"  ⚠️  Error installing dependencies: {e}", file=sys.stderr)
        return True  # Continue anyway


def update_retool_clone_lists(retool_dir: Path) -> bool:
    """Run retool.py --update to get latest clone lists."""
    retool_script = retool_dir / "retool.py"
    
    if not retool_script.exists():
        print(f"  ⚠️  Retool script not found: {retool_script}")
        return True
    try:
        # Don't capture output so it streams in real-time
        result = subprocess.run(
            [sys.executable, str(retool_script), "--update"],
            cwd=retool_dir,
            input="y\ny\ny\n",
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            return True
        else:
            print(f"  ⚠️  Warning: retool.py --update exited with code {result.returncode}", file=sys.stderr)
            return True  # Continue anyway
    except Exception as e:
        print(f"  ⚠️  Error updating clone lists: {e}", file=sys.stderr)
        return True  # Continue anyway


def update_retool_main(retool_dir: Path) -> bool:
    """Update retool directory using git pull."""
    if not (retool_dir / ".git").exists():
        print(f"  ⚠️  Not a git repository, skipping update")
        return True
    
    # Check if git is available
    if not check_git_available():
        print(f"  ⚠️  Git is not available, skipping Retool update")
        return True
    
    print(f"  🔄 Checking for Retool updates...")
    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=retool_dir,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            if "Already up to date" in result.stdout:
                print(f"  ✅ Retool is already up to date")
            else:
                print(f"  ✅ Retool updated successfully")
            return True
        else:
            print(f"  ⚠️  Git pull warning: {result.stderr}", file=sys.stderr)
            return True
    except Exception as e:
        print(f"  ⚠️  Error updating retool: {e}", file=sys.stderr)
        return True


def extract_zip_file(zip_path: Path, output_dir: Path) -> Path | None:
    """Extract .dat file from .zip archive."""
    print(f"  📂 Extracting archive...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            dat_files = [f for f in zip_ref.namelist() if f.endswith('.dat')]
            
            if not dat_files:
                print(f"  ❌ No .dat file found in archive", file=sys.stderr)
                return None
            
            dat_filename = dat_files[0]
            zip_ref.extract(dat_filename, output_dir)
            extracted_path = output_dir / dat_filename
            print(f"  ✅ Extracted: {extracted_path.name}")
            return extracted_path
            
    except zipfile.BadZipFile:
        print(f"  ❌ Invalid .zip file", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ❌ Error extracting .zip: {e}", file=sys.stderr)
        return None


def download_redump_psx_dat(output_dir: Path) -> Path | None:
    """Download the latest Redump PlayStation 1 .dat file (may be .zip)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dat_url = "http://redump.org/datfile/psx/"
    
    print(f"  🌐 Connecting to Redump.org...")
    print(f"     URL: {dat_url}")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(dat_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        content_disposition = response.headers.get('Content-Disposition', '')
        if 'filename=' in content_disposition:
            filename = content_disposition.split('filename=')[1].strip('"\'')
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d")
            filename = f"Sony - PlayStation ({timestamp}) (Redump).zip"
        
        output_path = output_dir / filename
        
        print(f"  ⬇️  Downloading file...")
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        file_size = output_path.stat().st_size
        print(f"  ✅ Download successful!")
        print(f"     File: {output_path.name}")
        print(f"     Size: {file_size / 1024 / 1024:.2f} MB ({file_size:,} bytes)")
        
        return output_path
        
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Error downloading file: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}", file=sys.stderr)
        return None


def run_retool(input_dat: Path, retool_dir: Path, output_dir: Path) -> Path | None:
    """Run Retool to filter the .dat file."""
    retool_script = retool_dir / "retool.py"
    
    if not retool_script.exists():
        print(f"  ❌ Retool script not found: {retool_script}", file=sys.stderr)
        return None
    
    cmd = [
        sys.executable,
        str(retool_script),
        str(input_dat),
    ] + RETOOL_FLAGS + ["--exclude", "".join(RETOOL_EXCLUDE)] + ["--output", str(output_dir)]
    
    try:
        # Don't capture output so it streams in real-time
        result = subprocess.run(
            cmd,
            cwd=retool_dir,
            input="y\ny\ny\n",
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print(f"  ❌ Retool failed with exit code {result.returncode}", file=sys.stderr)
            return None
        
        output_files = list(output_dir.glob("*.dat"))
        
        if output_files:
            output_file = max(output_files, key=lambda p: p.stat().st_mtime)
            return output_file
        else:
            print(f"  ⚠️  No output .dat file found in {output_dir}", file=sys.stderr)
            return None
            
    except Exception as e:
        print(f"  ❌ Error running Retool: {e}", file=sys.stderr)
        return None


def cleanup_old_files(directory: Path, pattern: str, keep_count: int = 7) -> int:
    """Keep only the most recent files matching the pattern, delete older ones."""
    if not directory.exists():
        return 0
    
    files = list(directory.glob(pattern))
    if len(files) <= keep_count:
        return 0
    
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    deleted_count = 0
    for file_to_delete in files[keep_count:]:
        try:
            file_to_delete.unlink()
            deleted_count += 1
        except Exception as e:
            print(f"  ⚠️  Warning: Could not delete {file_to_delete.name}: {e}")
    
    return deleted_count


def print_title(title: str, emoji: str = ""):
    """Print a centered title with decorative lines."""
    width = 70
    if emoji:
        full_title = f"{emoji}  {title}"
    else:
        full_title = title
    padding = (width - len(full_title)) // 2
    print()
    print("═" * width)
    print(" " * padding + full_title)
    print("═" * width)
    print()


def print_step(step_num: int, total_steps: int, description: str, emoji: str = "⚙️"):
    """Print a step indicator with progress."""
    print(f"\n[{step_num}/{total_steps}] {emoji} {description}")
    print("  " + "─" * 66)


def run_dat_download_and_filter() -> tuple[Path | None, Path | None]:
    """
    Run the DAT download and filtering process.
    Returns (output_dat_path, report_txt_path) or (None, None) on failure.
    """
    print_title("REDUMP DAT DOWNLOADER AND RETOOL FILTER", "📥")
    
    # Step 1: Download .dat/.zip file
    print_step(1, 9, "Downloading Redump DAT file", "⬇️")
    downloaded_file = download_redump_psx_dat(DAT_DIR)
    if not downloaded_file:
        print("\n  ❌ Download failed!")
        return None, None
    
    # Step 2: Extract if it's a .zip file
    print_step(2, 9, "Extracting DAT file", "📂")
    input_dat = downloaded_file
    extracted_dat = None
    if downloaded_file.suffix.lower() == '.zip':
        extracted_dat = extract_zip_file(downloaded_file, DAT_DIR)
        if not extracted_dat:
            print("\n  ❌ Extraction failed!")
            return None, None
        input_dat = extracted_dat
        # Delete the .zip file after extraction
        try:
            downloaded_file.unlink()
            print("  🗑️  Deleted intermediate .zip file")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not delete .zip file: {e}")
    else:
        print("  ℹ️  File is already a .dat file, skipping extraction")
    
    # Step 3: Clone Retool if needed
    print_step(3, 9, "Setting up Retool", "🔧")
    if not clone_retool_if_needed(RETOOL_DIR):
        print("  ⚠️  Continuing despite Retool setup issues...")
    
    # Step 4: Copy user-config.yaml
    print_step(4, 9, "Configuring Retool", "⚙️")
    if not copy_user_config():
        print("  ⚠️  Continuing despite config copy issues...")
    
    # Step 5: Install dependencies
    print_step(5, 9, "Installing Python dependencies", "📦")
    if not install_retool_dependencies():
        print("  ⚠️  Continuing despite dependency installation issues...")
    
    # Step 6: Update retool via git pull
    print_step(6, 9, "Updating Retool repository", "🔄")
    if not update_retool_main(RETOOL_DIR):
        print("  ⚠️  Continuing despite retool update issues...")
    
    # Step 7: Update Retool clone lists & Filter DAT file (combined)
    print_step(7, 9, "Updating Retool & Filtering DAT file", "📥")
    print(f"  🔍 Downloading clone lists and metadata files and processing DAT with Retool...")
    print(f"     Input file: {input_dat.name}")
    print(f"     Flags: {' '.join(RETOOL_FLAGS)}")
    print(f"     Exclude: {''.join(RETOOL_EXCLUDE)}")
    print(f"     (This may take a few moments...)")
    print()
    print("═" * 70)
    print("  📢 Raw Retool Output - START")
    print("═" * 70)
    
    if not update_retool_clone_lists(RETOOL_DIR):
        print("  ⚠️  Continuing despite clone list update issues...")
    
    output_dat = run_retool(input_dat, RETOOL_DIR, DAT_DIR)
    
    print()
    print("═" * 70)
    print("  📢 Raw Retool Output - END")
    print("═" * 70)
    print()
    
    if not output_dat:
        print("  ❌ Retool processing failed!")
        return None, None
    
    print(f"  ✅ Retool processing complete!")
    print(f"     Output: {output_dat.name}")
    
    # Step 8a: Delete intermediate .dat file immediately after Retool finishes
    # (the extracted Redump .dat, not the filtered output)
    if extracted_dat and extracted_dat != output_dat and extracted_dat.exists():
        try:
            extracted_dat.unlink()
            print("  🗑️  Deleted intermediate Redump .dat file")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not delete intermediate .dat file: {e}")
    elif input_dat != output_dat and input_dat.exists() and input_dat != extracted_dat:
        # If it wasn't extracted from zip, but is different from output, delete it
        try:
            input_dat.unlink()
            print("  🗑️  Deleted intermediate .dat file")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not delete intermediate .dat file: {e}")
    
    # Step 8: Move report files to reports directory
    print_step(8, 9, "Organizing report files", "📄")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_files = list(DAT_DIR.glob("*.txt"))
    moved_reports = []
    report_txt_path = None
    if report_files:
        for report_file in report_files:
            try:
                dest_file = REPORTS_DIR / report_file.name
                report_file.rename(dest_file)
                moved_reports.append(dest_file)
                report_txt_path = dest_file
                print(f"  ✅ Moved: {report_file.name}")
            except Exception as e:
                print(f"  ⚠️  Warning: Could not move {report_file.name}: {e}")
    else:
        print("  ℹ️  No report files to move")
    
    # Step 9: Clean up old files (keep only last 7)
    print_step(9, 9, "Cleaning up old files", "🧹")
    print("  Keeping only the 7 most recent files...")
    
    deleted_dats = cleanup_old_files(DAT_DIR, "*.dat", keep_count=7)
    if deleted_dats > 0:
        print(f"  🗑️  Deleted {deleted_dats} old .dat file(s)")
    else:
        remaining = len(list(DAT_DIR.glob("*.dat")))
        print(f"  ✅ No old .dat files to delete (keeping {remaining} file{'s' if remaining != 1 else ''})")
    
    deleted_reports = cleanup_old_files(REPORTS_DIR, "*.txt", keep_count=7)
    if deleted_reports > 0:
        print(f"  🗑️  Deleted {deleted_reports} old report file(s)")
    else:
        remaining = len(list(REPORTS_DIR.glob("*.txt")))
        print(f"  ✅ No old report files to delete (keeping {remaining} file{'s' if remaining != 1 else ''})")
    
    # Summary
    print_title("✅ DAT PROCESSING COMPLETE", "✅")
    print(f"  📁 Final filtered .dat:")
    print(f"     {output_dat.name}")
    if moved_reports:
        print(f"\n  📄 Report file{'s' if len(moved_reports) > 1 else ''}:")
        for report in moved_reports:
            print(f"     {report.name}")
    print()
    
    return output_dat, report_txt_path


# ============================================================================
# Report Generation Functions (from FullReport.py)
# ============================================================================

def extract_revision(name: str) -> tuple[str, int | None]:
    """Extract revision number from a game name."""
    match = re.search(r'\(Rev (\d+)\)', name, re.IGNORECASE)
    if match:
        rev_num = int(match.group(1))
        name_without_rev = re.sub(r'\s*\(Rev \d+\)', '', name, flags=re.IGNORECASE).strip()
        return (name_without_rev, rev_num)
    return (name.strip(), None)


def parse_dat_file_for_revisions(dat_path: Path) -> dict[str, int]:
    """Parse the Redump .dat XML file and create a mapping from base name to highest revision."""
    base_to_max_rev = defaultdict(int)
    
    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()
        
        for game in root.findall('game'):
            game_name = game.get('name')
            if game_name:
                game_name = html.unescape(game_name)
                base_name, rev_num = extract_revision(game_name)
                
                if rev_num is not None:
                    if rev_num > base_to_max_rev[base_name]:
                        base_to_max_rev[base_name] = rev_num
                else:
                    if base_name not in base_to_max_rev:
                        base_to_max_rev[base_name] = 0
        
        return dict(base_to_max_rev)
        
    except ET.ParseError as e:
        print(f"ERROR: Failed to parse .dat file for revisions: {e}")
        return {}
    except Exception as e:
        print(f"ERROR: {e}")
        return {}


def get_latest_revision_name(base_name: str, max_rev: int, redump_names: set[str]) -> str | None:
    """Find the actual Redump name for the latest revision."""
    if max_rev == 0:
        if base_name in redump_names:
            return base_name
        return None
    
    rev_name = f"{base_name} (Rev {max_rev})"
    if rev_name in redump_names:
        return rev_name
    
    return None


def parse_dat_file(dat_path: Path) -> set[str]:
    """Parse the Redump .dat XML file and extract all game names."""
    print(f"  📄 Parsing .dat file: {dat_path.name}")
    
    dat_names = set()
    
    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()
        
        for game in root.findall('game'):
            game_name = game.get('name')
            if game_name:
                game_name = html.unescape(game_name)
                dat_names.add(game_name)
        
        print(f"     Found {len(dat_names)} game names")
        return dat_names
        
    except ET.ParseError as e:
        print(f"  ❌ ERROR: Failed to parse .dat file: {e}", file=sys.stderr)
        return set()
    except Exception as e:
        print(f"  ❌ ERROR: {e}", file=sys.stderr)
        return set()


def collect_collection_filenames() -> set[str]:
    """Collect all unique filenames (stems) from collection directories."""
    print(f"  📂 Collecting collection filenames...")
    
    collection_names = set()
    
    for category, dirs in COLLECTION_DIRS.items():
        for directory in dirs:
            if not directory.exists():
                continue
            
            for file_path in directory.glob("*.png"):
                if " alt" in file_path.stem:
                    continue
                
                collection_names.add(file_path.stem)
    
    print(f"     Found {len(collection_names)} unique collection filenames")
    return collection_names


def check_image_exists(game_name: str, category: str) -> tuple[bool, str]:
    """Check if an image exists for a game in a specific category."""
    if category == "2dbox":
        dirs = [
            (LIBRARY_DIR / "2dbox", "normal"),
            (LIBRARY_DIR / "2dbox-lq", "lq"),
            (LIBRARY_DIR / "2dbox-missing", "missing"),
        ]
    elif category == "3dbox":
        dirs = [
            (LIBRARY_DIR / "3dbox", "normal"),
            (LIBRARY_DIR / "3dbox-lq", "lq"),
            (LIBRARY_DIR / "3dbox-missing", "missing"),
        ]
    elif category == "disc":
        dirs = [
            (LIBRARY_DIR / "disc", "normal"),
            (LIBRARY_DIR / "disc-lq", "lq"),
            (LIBRARY_DIR / "disc-missing", "missing"),
        ]
    elif category == "psp-icon0":
        dirs = [
            (COMPOSITES_DIR / "psp-icon0" / "psp-icon0-generated", "generated"),
            (COMPOSITES_DIR / "psp-icon0" / "psp-icon0-bespoke", "bespoke"),
        ]
    else:
        return (False, None)
    
    for directory, location in dirs:
        if directory.exists():
            file_path = directory / f"{game_name}.png"
            if file_path.exists():
                return (True, location)
    
    return (False, None)


def check_collection_completeness(collection_names: set[str]) -> tuple[dict, dict]:
    """Check that every game has 2dbox, 3dbox, disc, and psp-icon0 images."""
    missing_images = {}
    missing_only_games = {}
    
    for game_name in collection_names:
        missing_cats = []
        missing_only_cats = []

        for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
            exists, location = check_image_exists(game_name, category)
            
            if not exists:
                missing_cats.append(category)
            elif location == "missing":
                missing_only_cats.append(category)
        
        if missing_cats:
            missing_images[game_name] = missing_cats
        
        if missing_only_cats:
            missing_only_games[game_name] = missing_only_cats
    
    return missing_images, missing_only_games


def check_missing_folder_duplicates(collection_names: set[str]) -> dict:
    """Check if files exist in multiple folders for the same image type."""
    duplicates = {
        "2dbox": [],
        "3dbox": [],
        "disc": [],
        "psp-icon0": [],
    }

    for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
        for game_name in collection_names:
            locations = []

            if category == "psp-icon0":
                generated_dir = COLLECTION_DIRS[category][0]
                bespoke_dir = COLLECTION_DIRS[category][1]

                if generated_dir.exists():
                    generated_file = generated_dir / f"{game_name}.png"
                    if generated_file.exists():
                        locations.append("generated")

                if bespoke_dir.exists():
                    bespoke_file = bespoke_dir / f"{game_name}.png"
                    if bespoke_file.exists():
                        locations.append("bespoke")
            else:
                normal_dir = COLLECTION_DIRS[category][0]
                lq_dir = COLLECTION_DIRS[category][1]
                missing_dir = COLLECTION_DIRS[category][2]

                if normal_dir.exists():
                    normal_file = normal_dir / f"{game_name}.png"
                    if normal_file.exists():
                        locations.append("normal")

                if lq_dir.exists():
                    lq_file = lq_dir / f"{game_name}.png"
                    if lq_file.exists():
                        locations.append("lq")

                if missing_dir.exists():
                    missing_file = missing_dir / f"{game_name}.png"
                    if missing_file.exists():
                        locations.append("missing")

            if len(locations) > 1:
                duplicates[category].append((game_name, locations))
    
    return duplicates


def check_psp_icon0_sync(collection_names: set[str]) -> list[Path]:
    """Check for files in psp-icon0 directories that don't match any collection name."""
    mismatched_files = []

    psp_dirs = [
        COMPOSITES_DIR / "psp-icon0" / "psp-icon0-generated",
        COMPOSITES_DIR / "psp-icon0" / "psp-icon0-bespoke"
    ]

    for psp_dir in psp_dirs:
        if not psp_dir.exists():
            continue

        for file_path in psp_dir.glob("*.png"):
            game_name = file_path.stem
            if game_name not in collection_names:
                mismatched_files.append(file_path)

    return mismatched_files


def get_image_dimensions(image_path: Path) -> tuple[int, int] | None:
    """Get the dimensions (width, height) of an image file."""
    if not PIL_AVAILABLE:
        return None
    
    try:
        with Image.open(image_path) as img:
            return img.size
    except Exception:
        return None


def is_perfect_dimension(category: str, width: int, height: int) -> bool:
    """Check if dimensions match 'Perfect' standards for the category."""
    if category == "2dbox":
        return width == 1200 and height == 1200
    elif category == "3dbox":
        if width == 1325 and height == 1200:
            return True
        if width == 1227 and height == 1200:
            return True
        if width == 1273 and height == 1200:
            return True
    elif category == "disc":
        return width == 696 and height == 694
    return False


def analyze_image_dimensions(collection_names: set[str]) -> dict:
    """Analyze image dimensions for 2dbox, 3dbox, disc, and psp-icon0 categories."""
    if not PIL_AVAILABLE:
        return {
            "error": "PIL/Pillow not available - cannot analyze dimensions"
        }
    
    results = {
        "2dbox": {
            "normal": {"dimensions": defaultdict(int), "vertical": [], "total": 0},
            "lq": {"dimensions": defaultdict(int), "vertical": [], "total": 0},
            "missing": {"dimensions": defaultdict(int), "vertical": [], "total": 0},
        },
        "3dbox": {
            "normal": {"dimensions": defaultdict(int), "total": 0},
            "lq": {"dimensions": defaultdict(int), "total": 0},
            "missing": {"dimensions": defaultdict(int), "total": 0},
        },
        "disc": {
            "normal": {"dimensions": defaultdict(int), "total": 0},
            "lq": {"dimensions": defaultdict(int), "total": 0},
            "missing": {"dimensions": defaultdict(int), "total": 0},
        },
        "psp-icon0": {
            "generated": {"dimensions": defaultdict(int), "total": 0},
            "bespoke": {"dimensions": defaultdict(int), "total": 0},
        },
    }

    for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
        dirs = COLLECTION_DIRS[category]
        
        for directory in dirs:
            if not directory.exists():
                continue
            
            dir_name = directory.name
            if category == "psp-icon0":
                if dir_name == "psp-icon0-generated":
                    dir_type = "generated"
                elif dir_name == "psp-icon0-bespoke":
                    dir_type = "bespoke"
                else:
                    continue
            else:
                if dir_name == category:
                    dir_type = "normal"
                elif dir_name == f"{category}-lq":
                    dir_type = "lq"
                elif dir_name == f"{category}-missing":
                    dir_type = "missing"
                else:
                    continue
            
            for file_path in directory.glob("*.png"):
                game_name = file_path.stem
                
                if " alt" in game_name:
                    continue
                
                dimensions = get_image_dimensions(file_path)
                if dimensions:
                    width, height = dimensions
                    results[category][dir_type]["dimensions"][(width, height)] += 1
                    results[category][dir_type]["total"] += 1
                    
                    if category == "2dbox" and height > width:
                        height_percentage = ((height - width) / width) * 100
                        if height_percentage > 3.0:
                            results[category][dir_type]["vertical"].append((game_name, width, height))
    
    return results


def find_latest_dat_file(dat_dir: Path) -> Path | None:
    """Find the latest .dat file in the specified directory."""
    if not dat_dir.exists():
        return None
    
    dat_files = list(dat_dir.glob("*.dat"))
    
    if not dat_files:
        return None
    
    dat_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    return dat_files[0]


def find_latest_txt_file(reports_dir: Path) -> Path | None:
    """Find the latest .txt file in the reports directory."""
    if not reports_dir.exists():
        return None
    
    txt_files = list(reports_dir.glob("*.txt"))
    
    if not txt_files:
        return None
    
    txt_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    return txt_files[0]


def parse_filter_report(txt_path: Path) -> dict[str, str]:
    """Parse the Retool filter report .txt file to extract removed titles and their reasons."""
    print(f"  📋 Parsing filter report: {txt_path.name}")
    
    removed_games = {}
    current_section = None
    current_parent = None
    
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip()
                
                if line == "TITLES WITH CLONES":
                    current_section = "Clone"
                    current_parent = None
                    continue
                elif line == "APPLICATION REMOVES":
                    current_section = "Application"
                    current_parent = None
                    continue
                elif line == "AUDIO REMOVES":
                    current_section = "Audio"
                    current_parent = None
                    continue
                elif line == "COVERDISC REMOVES":
                    current_section = "Coverdisc"
                    current_parent = None
                    continue
                elif line == "DEMO, KIOSK, AND SAMPLE REMOVES":
                    current_section = "Demo/Kiosk/Sample"
                    current_parent = None
                    continue
                elif line == "EDUCATIONAL REMOVES":
                    current_section = "Educational"
                    current_parent = None
                    continue
                elif line == "UNLICENSED REMOVES":
                    current_section = "Unlicensed"
                    current_parent = None
                    continue
                elif line == "VIDEO REMOVES":
                    current_section = "Video"
                    current_parent = None
                    continue
                elif line == "LANGUAGE REMOVES":
                    current_section = "Language"
                    current_parent = None
                    continue
                
                if not line or line.startswith("=") or line.startswith("*") or line.startswith("SECTIONS") or line.startswith("This file"):
                    continue
                
                stripped_line = line.lstrip()
                if stripped_line.startswith("+ "):
                    if current_section == "Clone":
                        current_parent = stripped_line[2:].strip()
                    continue
                
                if stripped_line.startswith("- "):
                    game_name = stripped_line[2:].strip()
                    
                    if current_section == "Clone" and current_parent:
                        removed_games[game_name] = f"Superior version: '{current_parent}'"
                    elif current_section:
                        removed_games[game_name] = current_section
                    else:
                        removed_games[game_name] = "Removed"
        
        print(f"     Found {len(removed_games)} removed games")
        return removed_games
        
    except Exception as e:
        print(f"  ❌ ERROR: Failed to parse filter report: {e}", file=sys.stderr)
        return {}


def print_separator(char: str = "=", length: int = 70):
    """Print a separator line."""
    print(char * length)


def print_header(title: str):
    """Print a section header with consistent formatting."""
    print()
    print_separator()
    print(f"  {title}")
    print_separator()
    print()


def generate_collection_report(dat_file: Path, txt_file: Path | None = None) -> None:
    """Generate the full collection report."""
    print_title("COLLECTION vs .DAT FILE REPORT", "📊")
    
    print(f"  Using .dat file: {dat_file.name}")
    
    removal_reasons = {}
    if txt_file:
        print(f"  Using filter report: {txt_file.name}")
        removal_reasons = parse_filter_report(txt_file)
    else:
        print(f"  ⚠️  No .txt file found - removal reasons will not be available")
    
    # Parse .dat file
    dat_names = parse_dat_file(dat_file)
    
    if not dat_names:
        print()
        print("  ❌ ERROR: No game names found in .dat file. Cannot proceed.")
        return
    
    # Collect collection filenames
    collection_names = collect_collection_filenames()
    
    if not collection_names:
        print()
        print("  ❌ ERROR: No collection filenames found. Cannot proceed.")
        return
    
    # Compare
    print()
    print(f"  🔍 Comparing collection to .dat file...")
    
    in_dat_not_collection = sorted(dat_names - collection_names)
    in_collection_not_dat = sorted(collection_names - dat_names)
    in_both = sorted(collection_names & dat_names)
    
    # Report results
    print_title("SUMMARY", "📈")
    print(f"  Total games in .dat file:        {len(dat_names):>6}")
    print(f"  Total games in collection:       {len(collection_names):>6}")
    print(f"  Games in both:                   {len(in_both):>6}")
    print(f"  Games in .dat not in collection: {len(in_dat_not_collection):>6}")
    print(f"  Games in collection not in .dat: {len(in_collection_not_dat):>6}")
    print()
    
    # Check collection completeness
    print()
    print(f"  🔍 Checking collection completeness...")
    missing_images, missing_only_games = check_collection_completeness(collection_names)
    
    print_title("COLLECTION COMPLETENESS CHECK", "✅")
    print("  Every game should have 4 images: 2dbox, 3dbox, disc, and psp-icon0")
    print("  (Images can be in normal, -lq, -missing, or -bespoke folders)")
    print()
    
    if not missing_images and not missing_only_games:
        print("  ✅ All games have all 4 required images!")
        print("  ✅ No games have acknowledged missing images!")
        print()
    else:
        if missing_images:
            print(f"  ⚠️ Games genuinely missing images ({len(missing_images)} games):")
            print("  (No file exists in normal, -lq, or -missing folders)")
            print()
            for game_name in sorted(missing_images.keys()):
                missing_cats = missing_images[game_name]
                missing_str = ", ".join(missing_cats)
                print(f"    ❌ {game_name}")
                print(f"       Genuinely missing: {missing_str}")
            print()
        else:
            print("  ✅ All games have all 4 required images!")
            print()
        
        if missing_only_games:
            print(f"  ℹ️  Games with acknowledged missing images ({len(missing_only_games)} games):")
            print("  (Blank template exists in -missing folder)")
            print()
            for game_name in sorted(missing_only_games.keys()):
                missing_only_cats = missing_only_games[game_name]
                missing_only_str = ", ".join(missing_only_cats)
                print(f"    📍 {game_name}")
                print(f"       Acknowledged missing: {missing_only_str} (blank template exists in -missing folder)")
            print()
        else:
            print("  ✅ No games have acknowledged missing images!")
            print()
    
    # Check for duplicate files across folders
    print()
    print(f"  🔍 Checking for duplicate files across folders...")
    missing_duplicates = check_missing_folder_duplicates(collection_names)
    
    has_duplicates = any(missing_duplicates[cat] for cat in ["2dbox", "3dbox", "disc"])
    
    if has_duplicates:
        print_title("DUPLICATE FILES ACROSS FOLDERS", "⚠️")
        print("  Files should only exist in one folder per image type:")
        print("  (normal/-lq/-missing for library assets, generated/bespoke for psp-icon0)")
        print()

        for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
            if missing_duplicates[category]:
                cat_display = category.upper()
                print(f"  {cat_display} ({len(missing_duplicates[category])} files):")
                print()
                for game_name, locations in sorted(missing_duplicates[category]):
                    locations_str = ", ".join(locations)
                    print(f"    ⚠️ {game_name}")
                    print(f"       Exists in: {locations_str}")
                print()
    else:
        print_title("DUPLICATE FILES ACROSS FOLDERS", "✅")
        print("  ✅ No duplicate files found across folders!")
        print()
    
    # Check for mismatched files in psp-icon0 directories
    print()
    print(f"  🔍 Checking psp-icon0 sync...")
    mismatched_psp = check_psp_icon0_sync(collection_names)

    if mismatched_psp:
        print_title("PSP-ICON0 SYNC CHECK", "⚠️")
        print("  Files in psp-icon0 directories that don't match any collection name:")
        print()

        for file_path in sorted(mismatched_psp):
            relative_path = file_path.relative_to(SCRIPT_DIR.parent)
            print(f"    ⚠️ {file_path.stem}")
            print(f"       Path: {relative_path}")
        print()
    else:
        print_title("PSP-ICON0 SYNC CHECK", "✅")
        print("  ✅ All files in psp-icon0 directories match collection names!")
        print()
    
    # Analyze image dimensions
    print()
    print(f"  🔍 Analyzing image dimensions...")
    dimension_results = analyze_image_dimensions(collection_names)
    
    print_title("IMAGE DIMENSION ANALYSIS", "📐")
    
    if "error" in dimension_results:
        print(f"  ⚠️ {dimension_results['error']}")
        print("  Install Pillow to enable dimension analysis: pip install Pillow")
        print()
    else:
        for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
            cat_data = dimension_results[category]

            if category == "2dbox":
                cat_display = "2DBox"
                cat_emoji = "📦"
            elif category == "3dbox":
                cat_display = "3DBox"
                cat_emoji = "📦"
            elif category == "disc":
                cat_display = "Disc"
                cat_emoji = "💿"
            else:
                cat_display = "PSP-Icon0"
                cat_emoji = "🎮"
            
            print(f"\n  {cat_emoji} {cat_display}")
            print("  " + "─" * 66)
            
            if category == "psp-icon0":
                dir_types = ["generated", "bespoke"]
                dir_indices = [0, 1]
            else:
                dir_types = ["normal", "lq"]
                dir_indices = [0, 1]

            for dir_type, dir_index in zip(dir_types, dir_indices):
                if dir_type not in cat_data:
                    continue

                dir_data = cat_data[dir_type]
                total = dir_data["total"]

                directory = COLLECTION_DIRS[category][dir_index]
                
                try:
                    # Use workspace root (parent.parent) for relative paths
                    rel_path = directory.relative_to(SCRIPT_DIR.parent.parent)
                    dir_path_display = str(rel_path).replace("/", "\\") + "\\"
                except ValueError:
                    # Fallback: just use the directory name if relative path fails
                    dir_path_display = directory.name + "\\"
                
                print(f"\n  {dir_path_display}")
                
                if total == 0:
                    print("    (no images)")
                    continue
                
                dims = dir_data["dimensions"]
                if dims:
                    sorted_dims = sorted(dims.items(), key=lambda x: x[1], reverse=True)

                    rows = []
                    for (width, height), count in sorted_dims:
                        is_perfect = is_perfect_dimension(category, width, height)
                        is_square = width == height

                        if is_perfect:
                            emoji = "⭐"
                        elif is_square:
                            emoji = "🟦"
                        else:
                            emoji = "⚪"

                        dim_str = f"{width}x{height}"
                        rows.append((emoji, dim_str, count))

                    max_dim_len = max(len(dim_str) for _, dim_str, _ in rows)
                    max_count_len = max(len(str(count)) for _, _, count in rows)

                    for emoji, dim_str, count in rows:
                        print(
                            f"  {emoji}    {dim_str:<{max_dim_len}}  {count:>{max_count_len}}"
                        )

                if category == "2dbox" and dir_type in ["normal", "lq"] and dir_data["vertical"]:
                    print(f"\n      ⚠️ Vertical 2dboxes found ({len(dir_data['vertical'])} images):")
                    print("      (Height > Width - these should be horizontal/landscape)")
                    for game_name, width, height in sorted(dir_data["vertical"]):
                        print(f"        📐 {game_name}: {width}x{height}")
                elif category == "2dbox" and dir_type in ["normal", "lq"]:
                    print("\n      ✅ No vertical 2dboxes found (all are horizontal/landscape)")
        
        print()
    
    # Report games in .dat not in collection
    if in_dat_not_collection:
        print_title(f"GAMES IN .DAT NOT IN COLLECTION ({len(in_dat_not_collection)} games)", "📋")
        print("  These games exist in the .dat file but are missing from your collection:")
        print()
        for name in in_dat_not_collection:
            print(f"  📋 {name}")
        print()
    else:
        print_title("GAMES IN .DAT NOT IN COLLECTION", "✅")
        print("  ✅ All games from .dat file are in your collection!")
        print()
    
    # Report games in collection not in .dat
    if in_collection_not_dat:
        print_title(f"GAMES IN COLLECTION NOT IN .DAT ({len(in_collection_not_dat)} games)", "❓")
        print("  These games exist in your collection but are not in the .dat file:")
        print()
        
        if removal_reasons:
            games_with_reasons = []
            games_without_reasons = []
            
            for name in in_collection_not_dat:
                if name in removal_reasons:
                    games_with_reasons.append((name, removal_reasons[name]))
                else:
                    games_without_reasons.append(name)
            
            if games_with_reasons:
                for name, reason in sorted(games_with_reasons):
                    emoji = "🔄"
                    if reason.startswith("Superior version"):
                        emoji = "⭐"
                    elif reason == "Language":
                        emoji = "🌐"
                    elif reason == "Demo/Kiosk/Sample":
                        emoji = "🎮"
                    elif reason == "Application":
                        emoji = "💾"
                    elif reason == "Audio":
                        emoji = "🎵"
                    elif reason == "Coverdisc":
                        emoji = "📰"
                    elif reason == "Educational":
                        emoji = "📚"
                    elif reason == "Unlicensed":
                        emoji = "⚠️"
                    elif reason == "Video":
                        emoji = "🎬"
                    
                    print(f"  {emoji} {name} → {reason}")
                print()
            
            if games_without_reasons:
                print("  Games without removal reason in filter report:")
                for name in sorted(games_without_reasons):
                    print(f"  ❓ {name}")
                print()
        else:
            for name in in_collection_not_dat:
                print(f"  ❓ {name}")
            print()
    else:
        print_title("GAMES IN COLLECTION NOT IN .DAT", "✅")
        print("  ✅ All games in your collection are in the .dat file!")
        print()
    
    # Final summary
    print()
    if in_dat_not_collection or in_collection_not_dat:
        print("  ⚠️  Differences found between collection and .dat file")
    else:
        print("  ✅ Collection perfectly matches .dat file!")
    print()


def run_collection_report(dat_file: Path | None = None, txt_file: Path | None = None) -> None:
    """
    Run the collection report generation.
    If dat_file or txt_file are not provided, finds the latest files.
    """
    # Find latest .dat file if not provided
    if dat_file is None:
        print()
        print(f"  🔍 Looking for .dat files in: {DAT_DIR}")
        dat_file = find_latest_dat_file(DAT_DIR)
        
        if not dat_file:
            print()
            print(f"  ❌ ERROR: No .dat files found in {DAT_DIR}")
            return
        
        print(f"     Using latest .dat file: {dat_file.name}")
    
    # Find latest .txt file if not provided
    if txt_file is None:
        print()
        print(f"  🔍 Looking for .txt files in: {REPORTS_DIR}")
        txt_file = find_latest_txt_file(REPORTS_DIR)
        
        if txt_file:
            print(f"     Using latest .txt file: {txt_file.name}")
        else:
            print(f"     ⚠️  No .txt file found - removal reasons will not be available")
    
    # Generate the report
    generate_collection_report(dat_file, txt_file)


# ============================================================================
# Main Entry Point
# ============================================================================

def count_hq_images(category: str, collection_names: set[str]) -> int:
    """Count high-quality images (not in -lq directories) for a category."""
    hq_count = 0
    
    if category == "2dbox":
        hq_dir = LIBRARY_DIR / "2dbox"
    elif category == "3dbox":
        hq_dir = LIBRARY_DIR / "3dbox"
    elif category == "disc":
        hq_dir = LIBRARY_DIR / "disc"
    else:
        return 0
    
    if not hq_dir.exists():
        return 0
    
    for game_name in collection_names:
        file_path = hq_dir / f"{game_name}.png"
        if file_path.exists():
            hq_count += 1
    
    return hq_count


def update_readme_progress(dat_file: Path, collection_names: set[str]) -> bool:
    """Update README.md with progress bar images for HQ images."""
    try:
        # Count total games from DAT
        dat_names = parse_dat_file(dat_file)
        total_games = len(dat_names)
        
        # Count HQ images for each category
        hq_2dbox = count_hq_images("2dbox", collection_names)
        hq_3dbox = count_hq_images("3dbox", collection_names)
        hq_disc = count_hq_images("disc", collection_names)
        
        # Calculate percentages
        percentage_2d = int((hq_2dbox / total_games) * 100) if total_games > 0 else 0
        percentage_3d = int((hq_3dbox / total_games) * 100) if total_games > 0 else 0
        percentage_disc = int((hq_disc / total_games) * 100) if total_games > 0 else 0
        
        # Read current README
        if not README_MD_PATH.exists():
            print(f"  ⚠️  README.md not found: {README_MD_PATH}", file=sys.stderr)
            return False
        
        with open(README_MD_PATH, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        
        # Replace progress bar URLs
        import re
        # Match and replace 2D progress bar (flexible whitespace)
        pattern_2d = r'<img src="https://progress-bar\.xyz/\d+/\?title=2D&style=for-the-badge&width=100"\s*/>'
        replacement_2d = f'<img src="https://progress-bar.xyz/{percentage_2d}/?title=2D&style=for-the-badge&width=100" />'
        readme_content = re.sub(pattern_2d, replacement_2d, readme_content)
        
        # Match and replace 3D progress bar (flexible whitespace)
        pattern_3d = r'<img src="https://progress-bar\.xyz/\d+/\?title=3D&style=for-the-badge&width=100"\s*/>'
        replacement_3d = f'<img src="https://progress-bar.xyz/{percentage_3d}/?title=3D&style=for-the-badge&width=100" />'
        readme_content = re.sub(pattern_3d, replacement_3d, readme_content)
        
        # Match and replace Disc progress bar (flexible whitespace)
        pattern_disc = r'<img src="https://progress-bar\.xyz/\d+/\?title=Disc&style=for-the-badge&width=100"\s*/>'
        replacement_disc = f'<img src="https://progress-bar.xyz/{percentage_disc}/?title=Disc&style=for-the-badge&width=100" />'
        readme_content = re.sub(pattern_disc, replacement_disc, readme_content)
        
        # Write updated README
        with open(README_MD_PATH, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        
        print(f"  ✅ Progress bars updated in README.md")
        print(f"     2D Box: {percentage_2d}% ({hq_2dbox}/{total_games})")
        print(f"     3D Box: {percentage_3d}% ({hq_3dbox}/{total_games})")
        print(f"     Disc: {percentage_disc}% ({hq_disc}/{total_games})")
        return True
        
    except Exception as e:
        print(f"  ⚠️  Warning: Could not update README.md: {e}", file=sys.stderr)
        return False


def write_completion_md(report_content: str, description: str = None) -> bool:
    """Write the report to COMPLETION.md with proper formatting."""
    if description is None:
        description = "This completion report is updated weekly via automated full verification. It contains the most recent completion status."
    
    try:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        with open(COMPLETION_MD_PATH, 'w', encoding='utf-8') as f:
            f.write(f"{description}\n\n")
            f.write(f"**Last Updated:** {timestamp}\n\n")
            f.write("```\n")
            f.write("\n")
            f.write(report_content)
            f.write("\n```\n")
        
        print(f"  ✅ Report written to COMPLETION.md")
        return True
        
    except Exception as e:
        print(f"  ⚠️  Warning: Could not write to COMPLETION.md: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point - runs both DAT download/filter and collection report."""
    # Part 1: Download and filter DAT file
    output_dat, report_txt = run_dat_download_and_filter()
    
    if not output_dat:
        print("\n  ❌ DAT download and filtering failed!")
        print("     Cannot generate collection report.")
        sys.exit(1)
    
    # Part 2: Generate collection report
    # Capture report output
    report_buffer = io.StringIO()
    original_stdout = sys.stdout
    
    try:
        # Redirect stdout to buffer during report generation
        sys.stdout = report_buffer
        run_collection_report(output_dat, report_txt)
        sys.stdout = original_stdout
        
        # Get the report content
        report_content = report_buffer.getvalue()
        
        # Print report to console
        print(report_content)
        
        # Write to COMPLETION.md
        write_completion_md(
            report_content,
            "This completion report is updated weekly via automated full verification. It contains the most recent completion status."
        )
        
        # Update README.md with progress bars
        # Get collection names for progress calculation
        collection_names = collect_collection_filenames()
        if collection_names:
            update_readme_progress(output_dat, collection_names)
        
        print_title("✅ VERIFICATION COMPLETE", "✨")
        
    finally:
        # Restore stdout
        sys.stdout = original_stdout
        report_buffer.close()


if __name__ == "__main__":
    main()

