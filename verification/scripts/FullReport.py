#!/usr/bin/env python3
"""
Generate a report comparing collection against Redump .dat file.

Reports:
- Games in .dat not in collection
- Games in collection not in .dat
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import html
import re
from collections import defaultdict

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Configuration
SCRIPT_DIR = Path(__file__).parent
LIBRARY_DIR = SCRIPT_DIR.parent.parent / "library"  # Script is in verification/scripts/, go up to workspace root
COMPOSITES_DIR = SCRIPT_DIR.parent.parent / "composites"
EXTRAS_DIR = SCRIPT_DIR.parent.parent / "extras"
DAT_DIR = SCRIPT_DIR.parent / "dat"  # .dat files are in verification/dat/

# Directories to scan
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

# Bespoke icon0 directory (should sync with collection)
PSP_ICON0_BESPOKE_DIR = COMPOSITES_DIR / "psp-icon0" / "psp-icon0-bespoke"


def extract_revision(name: str) -> tuple[str, int | None]:
    """
    Extract revision number from a game name.
    Returns (name_without_revision, revision_number) where revision_number is None if not found.
    """
    match = re.search(r'\(Rev (\d+)\)', name, re.IGNORECASE)
    if match:
        rev_num = int(match.group(1))
        name_without_rev = re.sub(r'\s*\(Rev \d+\)', '', name, flags=re.IGNORECASE).strip()
        return (name_without_rev, rev_num)
    return (name.strip(), None)


def parse_dat_file_for_revisions(dat_path: Path) -> dict[str, int]:
    """
    Parse the Redump .dat XML file and create a mapping from base name
    (without revision) to the highest revision number found.
    Returns: {base_name: highest_revision_number}
    """
    base_to_max_rev = defaultdict(int)
    
    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()
        
        for game in root.findall('game'):
            game_name = game.get('name')
            if game_name:
                # Decode HTML entities (e.g., &amp; -> &)
                game_name = html.unescape(game_name)
                
                # Extract revision
                base_name, rev_num = extract_revision(game_name)
                
                # Track highest revision for each base name
                if rev_num is not None:
                    if rev_num > base_to_max_rev[base_name]:
                        base_to_max_rev[base_name] = rev_num
                else:
                    # No revision means revision 0 (original)
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
    """
    Find the actual Redump name for the latest revision.
    Returns the full Redump name with the highest revision, or None if not found.
    """
    if max_rev == 0:
        # No revision - check if base name exists
        if base_name in redump_names:
            return base_name
        return None
    
    # Look for the revision-specific name
    rev_name = f"{base_name} (Rev {max_rev})"
    if rev_name in redump_names:
        return rev_name
    
    return None


def parse_dat_file(dat_path: Path) -> set[str]:
    """
    Parse the Redump .dat XML file and extract all game names exactly as they appear.
    Returns set of game names.
    """
    print(f"Parsing .dat file: {dat_path.name}")
    
    dat_names = set()
    
    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()
        
        for game in root.findall('game'):
            game_name = game.get('name')
            if game_name:
                # Decode HTML entities (e.g., &amp; -> &)
                game_name = html.unescape(game_name)
                dat_names.add(game_name)
        
        print(f"  Found {len(dat_names)} game names in .dat file")
        return dat_names
        
    except ET.ParseError as e:
        print(f"ERROR: Failed to parse .dat file: {e}")
        return set()
    except Exception as e:
        print(f"ERROR: {e}")
        return set()


def collect_collection_filenames() -> set[str]:
    """
    Collect all unique filenames (stems) from collection directories.
    Returns set of collection filenames.
    """
    print("\nCollecting collection filenames...")
    
    collection_names = set()
    
    for category, dirs in COLLECTION_DIRS.items():
        for directory in dirs:
            if not directory.exists():
                continue
            
            for file_path in directory.glob("*.png"):
                # Skip alt versions
                if " alt" in file_path.stem:
                    continue
                
                collection_names.add(file_path.stem)
    
    print(f"  Found {len(collection_names)} unique collection filenames")
    return collection_names


def collect_all_files_for_name(collection_name: str) -> list[Path]:
    """
    Collect all files with the given name across all collection directories.
    Returns list of file paths.
    """
    files = []
    
    for category, dirs in COLLECTION_DIRS.items():
        for directory in dirs:
            if not directory.exists():
                continue
            
            file_path = directory / f"{collection_name}.png"
            if file_path.exists():
                files.append(file_path)
    
    return files


def check_image_exists(game_name: str, category: str) -> tuple[bool, str]:
    """
    Check if an image exists for a game in a specific category.
    Checks normal, -lq, and -missing variants.
    Returns (exists, location) where location is one of: 'normal', 'lq', 'missing', or None.
    """
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
    """
    Check that every game has 2dbox, 3dbox, and disc images.
    Returns (missing_images, missing_only_games) where:
    - missing_images: dict mapping game_name -> list of missing categories
    - missing_only_games: dict mapping game_name -> list of categories that only exist in -missing
    """
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
    """
    Check if files exist in multiple folders (normal, -lq, -missing) for the same image type.
    Returns dict mapping category -> list of (game_name, locations) where locations
    is a list of all folders the file exists in.
    """
    duplicates = {
        "2dbox": [],
        "3dbox": [],
        "disc": [],
        "psp-icon0": [],
    }

    for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
        # Check each game name
        for game_name in collection_names:
            locations = []

            if category == "psp-icon0":
                # psp-icon0 has different directory structure
                generated_dir = COLLECTION_DIRS[category][0]  # generated
                bespoke_dir = COLLECTION_DIRS[category][1]   # bespoke

                if generated_dir.exists():
                    generated_file = generated_dir / f"{game_name}.png"
                    if generated_file.exists():
                        locations.append("generated")

                if bespoke_dir.exists():
                    bespoke_file = bespoke_dir / f"{game_name}.png"
                    if bespoke_file.exists():
                        locations.append("bespoke")
            else:
                # Standard categories (2dbox, 3dbox, disc)
                normal_dir = COLLECTION_DIRS[category][0]  # normal
                lq_dir = COLLECTION_DIRS[category][1]  # lq
                missing_dir = COLLECTION_DIRS[category][2]  # missing

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

            # If file exists in more than one folder, flag it
            if len(locations) > 1:
                duplicates[category].append((game_name, locations))
    
    return duplicates


def check_psp_icon0_sync(collection_names: set[str]) -> list[Path]:
    """
    Check for files in psp-icon0 directories that don't match any collection name.
    Returns list of file paths that are mismatched (orphaned).
    """
    mismatched_files = []

    # Check both psp-icon0 directories
    psp_dirs = [
        COMPOSITES_DIR / "psp-icon0" / "psp-icon0-generated",
        COMPOSITES_DIR / "psp-icon0" / "psp-icon0-bespoke"
    ]

    for psp_dir in psp_dirs:
        if not psp_dir.exists():
            continue

        # Get all files in directory
        for file_path in psp_dir.glob("*.png"):
            game_name = file_path.stem

            # Check if this name exists in the collection
            if game_name not in collection_names:
                mismatched_files.append(file_path)

    return mismatched_files


def get_image_dimensions(image_path: Path) -> tuple[int, int] | None:
    """
    Get the dimensions (width, height) of an image file.
    Returns (width, height) or None if unable to read.
    """
    if not PIL_AVAILABLE:
        return None
    
    try:
        with Image.open(image_path) as img:
            return img.size  # Returns (width, height)
    except Exception:
        return None


def is_perfect_dimension(category: str, width: int, height: int) -> bool:
    """
    Check if dimensions match "Perfect" standards for the category.
    Returns True if perfect, False otherwise.
    """
    if category == "2dbox":
        # Perfect 2D Box: 1200 x 1200
        return width == 1200 and height == 1200
    elif category == "3dbox":
        # Perfect PAL 3D Boxes: 1325 x 1200
        if width == 1325 and height == 1200:
            return True
        # Perfect NTSC 3D Boxes: 1227 x 1200
        if width == 1227 and height == 1200:
            return True
        # Perfect NTSC Multi-Disc 3D Boxes: 1273 x 1200
        if width == 1273 and height == 1200:
            return True
    elif category == "disc":
        # Perfect Disc: 696 x 694
        return width == 696 and height == 694
    return False


def analyze_image_dimensions(collection_names: set[str]) -> dict:
    """
    Analyze image dimensions for 2dbox, 3dbox, and disc categories.
    Excludes alt versions.
    Breaks down dimensions by directory type (normal, lq, missing).
    Returns a dictionary with dimension statistics and vertical 2dbox flags.
    """
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

    # Analyze each category
    for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
        dirs = COLLECTION_DIRS[category]
        
        for directory in dirs:
            if not directory.exists():
                continue
            
            # Determine directory type
            dir_name = directory.name
            if category == "psp-icon0":
                if dir_name == "psp-icon0-generated":
                    dir_type = "generated"
                elif dir_name == "psp-icon0-bespoke":
                    dir_type = "bespoke"
                else:
                    continue  # Skip unknown directories
            else:
                if dir_name == category:
                    dir_type = "normal"
                elif dir_name == f"{category}-lq":
                    dir_type = "lq"
                elif dir_name == f"{category}-missing":
                    dir_type = "missing"
                else:
                    continue  # Skip unknown directories
            
            for file_path in directory.glob("*.png"):
                game_name = file_path.stem
                
                # Skip alt versions
                if " alt" in game_name:
                    continue
                
                dimensions = get_image_dimensions(file_path)
                if dimensions:
                    width, height = dimensions
                    results[category][dir_type]["dimensions"][(width, height)] += 1
                    results[category][dir_type]["total"] += 1
                    
                    # Check for vertical 2dboxes (height must be significantly greater than width)
                    # Use a 3% threshold to filter out near-square images
                    if category == "2dbox" and height > width:
                        height_percentage = ((height - width) / width) * 100
                        if height_percentage > 3.0:  # Height must be more than 3% greater than width
                            results[category][dir_type]["vertical"].append((game_name, width, height))
    
    return results


def extract_superior_version_name(reason: str) -> str | None:
    """
    Extract the superior version name from a reason string.
    Example: "Superior version: 'Fox Sports Soccer '99 (USA) (En,Es)'" -> "Fox Sports Soccer '99 (USA) (En,Es)"
    Returns None if not a superior version reason.
    """
    if not reason.startswith("Superior version: '"):
        return None
    
    # Extract the name between the quotes
    start = len("Superior version: '")
    if reason.endswith("'"):
        return reason[start:-1]
    
    return None


def move_to_alt_folder(file_path: Path) -> bool:
    """
    Move a file to its corresponding alt folder.
    Example: library/2dbox/Game.png -> extras/2dbox-alt/Game.png
    Returns True if successful, False otherwise.
    """
    try:
        # Determine alt folder path
        parent = file_path.parent
        parent_name = parent.name
        
        # Map to alt folder name in extras directory
        if parent_name == "2dbox":
            alt_dir = EXTRAS_DIR / "2dbox-alt"
        elif parent_name == "2dbox-lq":
            alt_dir = EXTRAS_DIR / "2dbox-alt"
        elif parent_name == "2dbox-missing":
            alt_dir = EXTRAS_DIR / "2dbox-alt"
        elif parent_name == "3dbox":
            alt_dir = EXTRAS_DIR / "3dbox-alt"
        elif parent_name == "3dbox-lq":
            alt_dir = EXTRAS_DIR / "3dbox-alt"
        elif parent_name == "3dbox-missing":
            alt_dir = EXTRAS_DIR / "3dbox-alt"
        elif parent_name == "disc":
            alt_dir = EXTRAS_DIR / "disc-alt"
        elif parent_name == "disc-lq":
            alt_dir = EXTRAS_DIR / "disc-alt"
        elif parent_name == "disc-missing":
            alt_dir = EXTRAS_DIR / "disc-alt"
        else:
            # Not an asset directory that has an alt folder
            return False
        
        # Create alt directory if it doesn't exist
        alt_dir.mkdir(parents=True, exist_ok=True)
        
        # Move file
        alt_file_path = alt_dir / file_path.name
        if alt_file_path.exists():
            # If alt file already exists, just delete the original
            file_path.unlink()
        else:
            file_path.rename(alt_file_path)
        
        return True
    except Exception as e:
        print(f"      ❌ Error moving {file_path.name}: {e}")
        return False


def rename_files_across_collection(old_name: str, new_name: str) -> tuple[int, int]:
    """
    Rename all files with old_name to new_name across all collection directories.
    Returns (renamed_count, error_count).
    """
    files_to_rename = collect_all_files_for_name(old_name)
    renamed_count = 0
    error_count = 0
    
    for file_path in files_to_rename:
        new_file_path = file_path.parent / f"{new_name}.png"
        
        try:
            if new_file_path.exists():
                print(f"    ⚠️ Skipping {file_path.name}: target already exists")
                error_count += 1
                continue
            
            file_path.rename(new_file_path)
            renamed_count += 1
            relative_path = file_path.relative_to(SCRIPT_DIR.parent)
            print(f"    ✅ Renamed: {relative_path}")
        except Exception as e:
            print(f"    ❌ Error renaming {file_path.name}: {e}")
            error_count += 1
    
    return renamed_count, error_count


def print_separator(char: str = "=", length: int = 70):
    print(char * length)


def print_header(title: str):
    print()
    print_separator()
    print(f"  {title}")
    print_separator()
    print()


def find_latest_dat_file(dat_dir: Path) -> Path | None:
    """
    Find the latest .dat file in the specified directory.
    Returns the path to the latest file, or None if no .dat files found.
    """
    if not dat_dir.exists():
        return None
    
    # Find all .dat files
    dat_files = list(dat_dir.glob("*.dat"))
    
    if not dat_files:
        return None
    
    # Sort by modification time (newest first)
    dat_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    return dat_files[0]


def find_latest_txt_file(dat_dir: Path) -> Path | None:
    """
    Find the latest .txt file in the specified directory.
    Returns the path to the latest file, or None if no .txt files found.
    """
    if not dat_dir.exists():
        return None
    
    # Find all .txt files
    txt_files = list(dat_dir.glob("*.txt"))
    
    if not txt_files:
        return None
    
    # Sort by modification time (newest first)
    txt_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    return txt_files[0]


def parse_filter_report(txt_path: Path) -> dict[str, str]:
    """
    Parse the Retool filter report .txt file to extract removed titles and their reasons.
    Returns a dictionary mapping game name -> removal reason.
    """
    print(f"Parsing filter report: {txt_path.name}")
    
    removed_games = {}
    current_section = None
    current_parent = None
    
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip()
                
                # Check for section headers
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
                
                # Skip section headers and separators
                if not line or line.startswith("=") or line.startswith("*") or line.startswith("SECTIONS") or line.startswith("This file"):
                    continue
                
                # Check for kept titles (parent in clone section)
                # Can be "+ Title" or "  + Title" (though usually not indented)
                stripped_line = line.lstrip()
                if stripped_line.startswith("+ "):
                    if current_section == "Clone":
                        current_parent = stripped_line[2:].strip()
                    continue
                
                # Check for removed titles
                # Can be "- Title" or "  - Title" (indented for clones)
                if stripped_line.startswith("- "):
                    game_name = stripped_line[2:].strip()
                    
                    if current_section == "Clone" and current_parent:
                        # Removed because a superior version exists
                        removed_games[game_name] = f"Superior version: '{current_parent}'"
                    elif current_section:
                        # Removed for a specific reason
                        removed_games[game_name] = current_section
                    else:
                        # Fallback (shouldn't happen)
                        removed_games[game_name] = "Removed"
        
        print(f"  Found {len(removed_games)} removed games in filter report")
        return removed_games
        
    except Exception as e:
        print(f"ERROR: Failed to parse filter report: {e}")
        return {}


def main():
    print()
    print_separator("=", 70)
    print("  COLLECTION vs .DAT FILE REPORT")
    print_separator("=", 70)
    
    # Find latest .dat file
    print(f"\nLooking for .dat files in: {DAT_DIR}")
    dat_file = find_latest_dat_file(DAT_DIR)
    
    if not dat_file:
        print(f"\nERROR: No .dat files found in {DAT_DIR}")
        return
    
    print(f"  Using latest .dat file: {dat_file.name}")
    
    # Find latest .txt file (filter report)
    print(f"\nLooking for .txt files in: {DAT_DIR}")
    txt_file = find_latest_txt_file(DAT_DIR)
    
    removal_reasons = {}
    if txt_file:
        print(f"  Using latest .txt file: {txt_file.name}")
        removal_reasons = parse_filter_report(txt_file)
    else:
        print(f"  No .txt file found - removal reasons will not be available")
    
    # Parse .dat file
    dat_names = parse_dat_file(dat_file)
    
    if not dat_names:
        print("\nERROR: No game names found in .dat file. Cannot proceed.")
        return
    
    # Collect collection filenames
    collection_names = collect_collection_filenames()
    
    if not collection_names:
        print("\nERROR: No collection filenames found. Cannot proceed.")
        return
    
    # Compare
    print("\nComparing collection to .dat file...")
    
    # Games in .dat but not in collection
    in_dat_not_collection = sorted(dat_names - collection_names)
    
    # Games in collection but not in .dat
    in_collection_not_dat = sorted(collection_names - dat_names)
    
    # Games in both
    in_both = sorted(collection_names & dat_names)
    
    # Report results
    print_header("SUMMARY")
    print(f"  Total games in .dat file:        {len(dat_names):>6}")
    print(f"  Total games in collection:       {len(collection_names):>6}")
    print(f"  Games in both:                   {len(in_both):>6}")
    print(f"  Games in .dat not in collection: {len(in_dat_not_collection):>6}")
    print(f"  Games in collection not in .dat: {len(in_collection_not_dat):>6}")
    print()
    
    # Check collection completeness (2dbox, 3dbox, disc)
    print("\nChecking collection completeness...")
    missing_images, missing_only_games = check_collection_completeness(collection_names)
    
    print_header("COLLECTION COMPLETENESS CHECK")
    print("  Every game should have 4 images: 2dbox, 3dbox, disc, and psp-icon0")
    print("  (Images can be in normal, -lq, -missing, or -bespoke folders)")
    print()
    
    if not missing_images and not missing_only_games:
        print("  ✅ All games have all 3 required images!")
        print("  ✅ No games have acknowledged missing images!")
        print()
    else:
        # Report games genuinely missing images (no file at all)
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
            print("  ✅ All games have all 3 required images!")
            print()
        
        # Report games with acknowledged missing images (blank template in -missing)
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
    print("\nChecking for duplicate files across folders...")
    missing_duplicates = check_missing_folder_duplicates(collection_names)
    
    has_duplicates = any(missing_duplicates[cat] for cat in ["2dbox", "3dbox", "disc"])
    
    if has_duplicates:
        print_header("DUPLICATE FILES ACROSS FOLDERS")
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
        print_header("DUPLICATE FILES ACROSS FOLDERS")
        print("  ✅ No duplicate files found across folders!")
        print()
    
    # Check for mismatched files in psp-icon0 directories
    print("\nChecking psp-icon0 sync...")
    mismatched_psp = check_psp_icon0_sync(collection_names)

    if mismatched_psp:
        print_header("PSP-ICON0 SYNC CHECK")
        print("  Files in psp-icon0 directories that don't match any collection name:")
        print()

        for file_path in sorted(mismatched_psp):
            relative_path = file_path.relative_to(SCRIPT_DIR.parent)
            print(f"    ⚠️ {file_path.stem}")
            print(f"       Path: {relative_path}")
        print()
    else:
        print_header("PSP-ICON0 SYNC CHECK")
        print("  ✅ All files in psp-icon0 directories match collection names!")
        print()
    
    # Analyze image dimensions
    print("\nAnalyzing image dimensions...")
    dimension_results = analyze_image_dimensions(collection_names)
    
    print_header("IMAGE DIMENSION ANALYSIS")
    
    if "error" in dimension_results:
        print(f"  ⚠️ {dimension_results['error']}")
        print("  Install Pillow to enable dimension analysis: pip install Pillow")
        print()
    else:
        # Report dimensions for each category
        for category in ["2dbox", "3dbox", "disc", "psp-icon0"]:
            cat_data = dimension_results[category]

            # Format category name for display
            if category == "2dbox":
                cat_display = "2DBox"
            elif category == "3dbox":
                cat_display = "3DBox"
            elif category == "disc":
                cat_display = "Disc"
            else:  # psp-icon0
                cat_display = "PSP-Icon0"
            
            # Print category header with underline
            print(f"\n  {cat_display}")
            print("  " + "=" * 20)
            
            # Report for each directory type (normal/lq for standard categories, generated/bespoke for psp-icon0)
            if category == "psp-icon0":
                dir_types = ["generated", "bespoke"]
                dir_indices = [0, 1]  # generated is index 0, bespoke is index 1
            else:
                dir_types = ["normal", "lq"]
                dir_indices = [0, 1]  # normal is index 0, lq is index 1

            for dir_type, dir_index in zip(dir_types, dir_indices):
                if dir_type not in cat_data:
                    continue

                dir_data = cat_data[dir_type]
                total = dir_data["total"]

                # Get the actual directory path
                directory = COLLECTION_DIRS[category][dir_index]
                
                # Format directory path for display (relative to project root)
                try:
                    rel_path = directory.relative_to(SCRIPT_DIR.parent)
                    dir_path_display = str(rel_path).replace("/", "\\") + "\\"
                except ValueError:
                    # If relative path fails, use absolute path
                    dir_path_display = str(directory) + "\\"
                
                print(f"\n  {dir_path_display}")
                
                if total == 0:
                    print("    (no images)")
                    continue
                
                # Show dimension breakdown
                dims = dir_data["dimensions"]
                if dims:
                    # Sort by count (most common first)
                    sorted_dims = sorted(dims.items(), key=lambda x: x[1], reverse=True)

                    # Build rows first so we can calculate column widths
                    rows = []
                    for (width, height), count in sorted_dims:
                        # Check if perfect dimension
                        is_perfect = is_perfect_dimension(category, width, height)
                        # Check if square (width == height)
                        is_square = width == height

                        # Build emoji (perfect takes priority over square, otherwise regular)
                        if is_perfect:
                            emoji = "⭐"
                        elif is_square:
                            emoji = "🟦"
                        else:
                            emoji = "⚪"  # Regular emoji for non-perfect, non-square

                        dim_str = f"{width}x{height}"
                        rows.append((emoji, dim_str, count))

                    # Compute max widths for clean alignment
                    max_dim_len = max(len(dim_str) for _, dim_str, _ in rows)
                    max_count_len = max(len(str(count)) for _, _, count in rows)

                    for emoji, dim_str, count in rows:
                        # Format: "  " + emoji + "    " (increased spacing) + dimension + "  " + count
                        print(
                            f"  {emoji}    {dim_str:<{max_dim_len}}  {count:>{max_count_len}}"
                        )

                
                # Report vertical 2dboxes (only for normal and lq, not missing)
                if category == "2dbox" and dir_type in ["normal", "lq"] and dir_data["vertical"]:
                    print(f"\n      ⚠️ Vertical 2dboxes found ({len(dir_data['vertical'])} images):")
                    print("      (Height > Width - these should be horizontal/landscape)")
                    for game_name, width, height in sorted(dir_data["vertical"]):
                        print(f"        📐 {game_name}: {width}x{height}")
                elif category == "2dbox" and dir_type in ["normal", "lq"]:
                    print("\n      ✅ No vertical 2dboxes found (all are horizontal/landscape)")
        
        print()
    
    # Check for games that need revision updates
    print("\nChecking for games that need revision updates...")
    base_to_max_rev = parse_dat_file_for_revisions(dat_file)
    needs_revision_update = []
    
    if base_to_max_rev:
        for collection_name in sorted(collection_names):
            # Extract revision from collection name
            base_name, collection_rev = extract_revision(collection_name)
            
            # Check if this base name exists in Redump
            if base_name in base_to_max_rev:
                max_rev = base_to_max_rev[base_name]
                
                # Check if collection has an older revision (or no revision when max > 0)
                if collection_rev is None:
                    collection_rev = 0  # No revision means original (rev 0)
                
                if collection_rev < max_rev:
                    # Find the actual latest revision name
                    latest_name = get_latest_revision_name(base_name, max_rev, dat_names)
                    if latest_name:
                        needs_revision_update.append((collection_name, latest_name, collection_rev, max_rev))
    
    if needs_revision_update:
        print_header("REVISION UPDATES")
        print(f"  Found {len(needs_revision_update)} games that need revision updates:")
        print("  Commands: y = yes, rename all files; n = no, skip; s = skip all remaining")
        print()
        
        renamed_count = 0
        skipped_count = 0
        error_count = 0
        
        for i, (collection_name, latest_name, current_rev, max_rev) in enumerate(needs_revision_update, 1):
            rev_info = f"Rev {current_rev}" if current_rev > 0 else "Original"
            print(f"  [{i}/{len(needs_revision_update)}] Collection: {collection_name} ({rev_info})")
            print(f"       Latest:     {latest_name} (Rev {max_rev})")
            
            # Show which files will be renamed
            files_to_rename = collect_all_files_for_name(collection_name)
            if files_to_rename:
                print(f"       Files to rename: {len(files_to_rename)}")
                for file_path in files_to_rename[:3]:
                    relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                    print(f"         - {relative_path}")
                if len(files_to_rename) > 3:
                    print(f"         ... and {len(files_to_rename) - 3} more")
            
            response = input("       Rename? (y/n/s): ").strip().lower()
            
            if response == 's':
                print("       Skipping all remaining updates...")
                skipped_count += len(needs_revision_update) - i + 1
                break
            elif response == 'y' or response == 'yes':
                print(f"       Renaming {collection_name} -> {latest_name}...")
                renamed, errors = rename_files_across_collection(collection_name, latest_name)
                renamed_count += renamed
                error_count += errors
                if renamed > 0:
                    print(f"       ✅ Renamed {renamed} file(s)")
                if errors > 0:
                    print(f"       ⚠️ {errors} error(s)")
            else:
                skipped_count += 1
                print("       Skipped")
            
            print()
        
        if renamed_count > 0 or skipped_count > 0 or error_count > 0:
            print(f"  Summary: {renamed_count} renamed, {error_count} errors, {skipped_count} skipped")
            print()
    else:
        print_header("REVISION UPDATES")
        print("  ✅ All games are using the latest revisions!")
        print()
    
    # Report games in .dat not in collection
    if in_dat_not_collection:
        print_header(f"GAMES IN .DAT NOT IN COLLECTION ({len(in_dat_not_collection)} games)")
        print("  These games exist in the .dat file but are missing from your collection:")
        print()
        for name in in_dat_not_collection:
            print(f"  📋 {name}")
        print()
    else:
        print_header("GAMES IN .DAT NOT IN COLLECTION")
        print("  ✅ All games from .dat file are in your collection!")
        print()
    
    # Report games in collection not in .dat
    if in_collection_not_dat:
        print_header(f"GAMES IN COLLECTION NOT IN .DAT ({len(in_collection_not_dat)} games)")
        print("  These games exist in your collection but are not in the .dat file:")
        print()
        
        # Group by removal reason if available
        if removal_reasons:
            games_with_reasons = []
            games_without_reasons = []
            
            for name in in_collection_not_dat:
                if name in removal_reasons:
                    games_with_reasons.append((name, removal_reasons[name]))
                else:
                    games_without_reasons.append(name)
            
            # Print games with reasons
            if games_with_reasons:
                superior_version_candidates = []
                
                for name, reason in sorted(games_with_reasons):
                    # Choose emoji based on reason type
                    emoji = "🔄"
                    if reason.startswith("Superior version"):
                        emoji = "⭐"
                        # Check if superior version exists in collection
                        superior_name = extract_superior_version_name(reason)
                        if superior_name and superior_name in collection_names:
                            superior_version_candidates.append((name, superior_name, reason))
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
                
                # Handle superior version candidates
                if superior_version_candidates:
                    print_header("SUPERIOR VERSION CLEANUP")
                    print("  The following inferior versions have superior versions in your collection:")
                    print()
                    
                    for inferior_name, superior_name, reason in superior_version_candidates:
                        print(f"  ⭐ {inferior_name}")
                        print(f"     Superior: {superior_name}")
                        
                        # Collect files for inferior version
                        inferior_files = collect_all_files_for_name(inferior_name)
                        
                        if not inferior_files:
                            print(f"     ⚠️ No files found for {inferior_name}")
                            print()
                            continue
                        
                        # Separate asset files (move to alt) from composite files (delete)
                        # Only include files where the superior version exists in the same category
                        asset_files = []
                        composite_files = []
                        
                        for file_path in inferior_files:
                            category = None
                            for cat, dirs in COLLECTION_DIRS.items():
                                if file_path.parent in dirs:
                                    category = cat
                                    break
                            
                            if category is None:
                                continue
                            
                            # Check if superior version exists in the same category
                            superior_exists = False
                            for cat_dir in COLLECTION_DIRS[category]:
                                superior_file = cat_dir / f"{superior_name}.png"
                                if superior_file.exists():
                                    superior_exists = True
                                    break
                            
                            if not superior_exists:
                                # Skip this file - superior version doesn't exist in this category
                                continue
                            
                            if category in ["2dbox", "3dbox", "disc"]:
                                asset_files.append(file_path)
                            elif category in ["psp-icon0"]:
                                composite_files.append(file_path)
                        
                        if not asset_files and not composite_files:
                            print(f"     ⚠️ No files to process (superior version doesn't exist in matching categories)")
                            print()
                            continue
                        
                        if asset_files:
                            print(f"     Files to move to alt folders: {len(asset_files)}")
                        if composite_files:
                            print(f"     Files to delete: {len(composite_files)}")
                        
                        # Ask for confirmation
                        response = input(f"     Move/delete inferior version? (y/n): ").strip().lower()
                        
                        if response == 'y':
                            moved_count = 0
                            deleted_count = 0
                            
                            # Move asset files to alt folders
                            for file_path in asset_files:
                                if move_to_alt_folder(file_path):
                                    moved_count += 1
                                    relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                    print(f"       ✅ Moved to alt: {relative_path}")
                            
                            # Delete composite files
                            for file_path in composite_files:
                                try:
                                    file_path.unlink()
                                    deleted_count += 1
                                    relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                    print(f"       ✅ Deleted: {relative_path}")
                                except Exception as e:
                                    print(f"       ❌ Error deleting {file_path.name}: {e}")
                            
                            print(f"     ✅ Processed: {moved_count} moved, {deleted_count} deleted")
                        else:
                            print(f"     ⊘ Skipped")
                        
                        print()
                
                # Handle Language and Demo/Kiosk/Sample candidates
                language_candidates = []
                demo_candidates = []
                audio_candidates = []
                educational_candidates = []
                application_candidates = []
                coverdisc_candidates = []
                unlicensed_candidates = []
                video_candidates = []
                
                for name, reason in games_with_reasons:
                    if reason == "Language":
                        language_candidates.append((name, reason))
                    elif reason == "Demo/Kiosk/Sample":
                        demo_candidates.append((name, reason))
                    elif reason == "Audio":
                        audio_candidates.append((name, reason))
                    elif reason == "Educational":
                        educational_candidates.append((name, reason))
                    elif reason == "Application":
                        application_candidates.append((name, reason))
                    elif reason == "Coverdisc":
                        coverdisc_candidates.append((name, reason))
                    elif reason == "Unlicensed":
                        unlicensed_candidates.append((name, reason))
                    elif reason == "Video":
                        video_candidates.append((name, reason))
                
                # Helper function to process cleanup for any reason type
                def process_cleanup_candidates(candidates, header_title, emoji):
                    """Process cleanup candidates for a specific removal reason."""
                    if not candidates:
                        return
                    
                    print_header(header_title)
                    print(f"  The following games were removed as {header_title.replace(' CLEANUP', '').lower()}:")
                    print()
                    
                    for game_name, reason in candidates:
                        print(f"  {emoji} {game_name}")
                        
                        # Collect files for this game
                        files = collect_all_files_for_name(game_name)
                        
                        if not files:
                            print(f"     ⚠️ No files found for {game_name}")
                            print()
                            continue
                        
                        # Separate asset files (move to alt) from composite files (delete)
                        asset_files = []
                        composite_files = []
                        
                        for file_path in files:
                            category = None
                            for cat, dirs in COLLECTION_DIRS.items():
                                if file_path.parent in dirs:
                                    category = cat
                                    break
                            
                            if category in ["2dbox", "3dbox", "disc"]:
                                asset_files.append(file_path)
                            elif category in ["psp-icon0"]:
                                composite_files.append(file_path)
                        
                        if asset_files:
                            print(f"     Files to move to alt folders: {len(asset_files)}")
                        if composite_files:
                            print(f"     Files to delete: {len(composite_files)}")
                        
                        # Ask for confirmation
                        response = input(f"     Move/delete? (y/n): ").strip().lower()
                        
                        if response == 'y':
                            moved_count = 0
                            deleted_count = 0
                            
                            # Move asset files to alt folders
                            for file_path in asset_files:
                                if move_to_alt_folder(file_path):
                                    moved_count += 1
                                    relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                    print(f"       ✅ Moved to alt: {relative_path}")
                            
                            # Delete composite files
                            for file_path in composite_files:
                                try:
                                    file_path.unlink()
                                    deleted_count += 1
                                    relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                    print(f"       ✅ Deleted: {relative_path}")
                                except Exception as e:
                                    print(f"       ❌ Error deleting {file_path.name}: {e}")
                            
                            print(f"     ✅ Processed: {moved_count} moved, {deleted_count} deleted")
                        else:
                            print(f"     ⊘ Skipped")
                        
                        print()
                
                # Process all cleanup candidates
                process_cleanup_candidates(language_candidates, "LANGUAGE REMOVAL CLEANUP", "🌐")
                process_cleanup_candidates(demo_candidates, "DEMO/KIOSK/SAMPLE CLEANUP", "🎮")
                process_cleanup_candidates(audio_candidates, "AUDIO CLEANUP", "🎵")
                process_cleanup_candidates(educational_candidates, "EDUCATIONAL CLEANUP", "📚")
                process_cleanup_candidates(application_candidates, "APPLICATION CLEANUP", "💾")
                process_cleanup_candidates(coverdisc_candidates, "COVERDISC CLEANUP", "📰")
                process_cleanup_candidates(unlicensed_candidates, "UNLICENSED CLEANUP", "⚠️")
                process_cleanup_candidates(video_candidates, "VIDEO CLEANUP", "🎬")
                
                # Rename section - offer to rename all games with superior versions
                rename_candidates = []
                for name, reason in games_with_reasons:
                    if reason.startswith("Superior version"):
                        superior_name = extract_superior_version_name(reason)
                        if superior_name:
                            rename_candidates.append((name, superior_name))
                
                if rename_candidates:
                    print_header("RENAME TO SUPERIOR VERSIONS")
                    print("  The following games can be renamed to their superior versions:")
                    print()
                    
                    for old_name, new_name in rename_candidates:
                        print(f"  Would you like to rename (y/n):")
                        print(f"    {old_name}")
                        print(f"    → {new_name}")
                        
                        response = input("  ").strip().lower()
                        
                        if response == 'y' or response == 'yes':
                            files = collect_all_files_for_name(old_name)
                            
                            if not files:
                                print(f"    ⚠️ No files found for {old_name}")
                                print()
                                continue
                            
                            print(f"    Renaming {len(files)} file(s)...")
                            renamed_count, error_count = rename_files_across_collection(old_name, new_name)
                            
                            if renamed_count > 0:
                                print(f"    ✅ Successfully renamed {renamed_count} file(s)")
                            if error_count > 0:
                                print(f"    ⚠️ {error_count} file(s) had errors")
                        else:
                            print(f"    ⊘ Skipped")
                        
                        print()
            
            # Print games without reasons
            if games_without_reasons:
                print("  Games without removal reason in filter report:")
                for name in sorted(games_without_reasons):
                    print(f"  ❓ {name}")
                print()
                
                # Offer cleanup for games without reasons
                if games_without_reasons:
                    print_header("CLEANUP GAMES NOT IN .DAT (NO REMOVAL REASON)")
                    print("  The following games are not in the .dat file and have no removal reason:")
                    print()
                    
                    for game_name in sorted(games_without_reasons):
                        print(f"  ❓ {game_name}")
                        
                        # Collect files for this game
                        files = collect_all_files_for_name(game_name)
                        
                        if not files:
                            print(f"     ⚠️ No files found for {game_name}")
                            print()
                            continue
                        
                        # Separate asset files (move to alt) from composite files (delete)
                        asset_files = []
                        composite_files = []
                        
                        for file_path in files:
                            category = None
                            for cat, dirs in COLLECTION_DIRS.items():
                                if file_path.parent in dirs:
                                    category = cat
                                    break
                            
                            if category in ["2dbox", "3dbox", "disc"]:
                                asset_files.append(file_path)
                            elif category in ["psp-icon0"]:
                                composite_files.append(file_path)
                        
                        if asset_files:
                            print(f"     Files to move to alt folders: {len(asset_files)}")
                        if composite_files:
                            print(f"     Files to delete: {len(composite_files)}")
                        
                        # Ask for confirmation
                        response = input(f"     Move/delete? (y/n): ").strip().lower()
                        
                        if response == 'y':
                            moved_count = 0
                            deleted_count = 0
                            
                            # Move asset files to alt folders
                            for file_path in asset_files:
                                if move_to_alt_folder(file_path):
                                    moved_count += 1
                                    relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                    print(f"       ✅ Moved to alt: {relative_path}")
                            
                            # Delete composite files
                            for file_path in composite_files:
                                try:
                                    file_path.unlink()
                                    deleted_count += 1
                                    relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                    print(f"       ✅ Deleted: {relative_path}")
                                except Exception as e:
                                    print(f"       ❌ Error deleting {file_path.name}: {e}")
                            
                            print(f"     ✅ Processed: {moved_count} moved, {deleted_count} deleted")
                        else:
                            print(f"     ⊘ Skipped")
                        
                        print()
        else:
            # No filter report available, just list all games
            print("  Games not in .dat file:")
            for name in in_collection_not_dat:
                print(f"  ❓ {name}")
            print()
            
            # Offer cleanup for all games not in .dat
            if in_collection_not_dat:
                print_header("CLEANUP GAMES NOT IN .DAT")
                print("  The following games are not in the .dat file:")
                print()
                
                for game_name in sorted(in_collection_not_dat):
                    print(f"  ❓ {game_name}")
                    
                    # Collect files for this game
                    files = collect_all_files_for_name(game_name)
                    
                    if not files:
                        print(f"     ⚠️ No files found for {game_name}")
                        print()
                        continue
                    
                    # Separate asset files (move to alt) from composite files (delete)
                    asset_files = []
                    composite_files = []
                    
                    for file_path in files:
                        category = None
                        for cat, dirs in COLLECTION_DIRS.items():
                            if file_path.parent in dirs:
                                category = cat
                                break
                        
                        if category in ["2dbox", "3dbox", "disc"]:
                            asset_files.append(file_path)
                        elif category in ["psp-icon0"]:
                            composite_files.append(file_path)
                    
                    if asset_files:
                        print(f"     Files to move to alt folders: {len(asset_files)}")
                    if composite_files:
                        print(f"     Files to delete: {len(composite_files)}")
                    
                    # Ask for confirmation
                    response = input(f"     Move/delete? (y/n): ").strip().lower()
                    
                    if response == 'y':
                        moved_count = 0
                        deleted_count = 0
                        
                        # Move asset files to alt folders
                        for file_path in asset_files:
                            if move_to_alt_folder(file_path):
                                moved_count += 1
                                relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                print(f"       ✅ Moved to alt: {relative_path}")
                        
                        # Delete composite files
                        for file_path in composite_files:
                            try:
                                file_path.unlink()
                                deleted_count += 1
                                relative_path = file_path.relative_to(SCRIPT_DIR.parent)
                                print(f"       ✅ Deleted: {relative_path}")
                            except Exception as e:
                                print(f"       ❌ Error deleting {file_path.name}: {e}")
                        
                        print(f"     ✅ Processed: {moved_count} moved, {deleted_count} deleted")
                    else:
                        print(f"     ⊘ Skipped")
                    
                    print()
    else:
        print_header("GAMES IN COLLECTION NOT IN .DAT")
        print("  ✅ All games in your collection are in the .dat file!")
        print()
    
    # Final summary
    print_separator()
    if in_dat_not_collection or in_collection_not_dat:
        print("  ⚠️ Differences found between collection and .dat file")
    else:
        print("  ✅ Collection perfectly matches .dat file!")
    print()


if __name__ == "__main__":
    main()

