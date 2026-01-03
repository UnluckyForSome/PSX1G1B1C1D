#!/usr/bin/env python3
"""
Download and filter Redump PlayStation 1 .dat file using Retool.

Downloads the latest .dat file from Redump, extracts it if it's a .zip,
updates retool if needed, and processes it with Retool using the
specified filter settings.
"""

import requests
import zipfile
import subprocess
from pathlib import Path
from datetime import datetime
import sys


# Retool filter settings based on your filename pattern:
# Sony - PlayStation (2025-12-23 15-09-55) (Retool 2025-12-31 15-21-39) (1,793) (-n) [-AaBbcDdefkMmopPruv]
# The (-n) in the filename indicates local names flag
# The [-AaBbcDdefkMmopPruv] are exclude filters
RETOOL_FLAGS = ["-n"]  # Use local names
RETOOL_EXCLUDE = ["A", "a", "B", "b", "c", "D", "d", "e", "f", "k", "M", "m", "o", "p", "r", "u", "v"]

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


def install_retool_dependencies() -> bool:
    """Install Retool dependencies."""
    print("Installing Retool dependencies...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + RETOOL_DEPENDENCIES,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            print("  ✓ Dependencies installed successfully")
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
        print(f"⚠️  Retool script not found: {retool_script}")
        return True
    
    print("Updating Retool clone lists...")
    print("  (This may take a few minutes - downloading clone lists and metadata files)")
    try:
        # Automatically answer "y" to any prompts (e.g., downloading missing config files)
        # Send multiple "y" responses in case there are multiple prompts
        # Don't capture output - let it stream to console so user can see progress
        result = subprocess.run(
            [sys.executable, str(retool_script), "--update"],
            cwd=retool_dir,
            input="y\ny\ny\n",  # Auto-answer "y" to up to 3 prompts
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            print("  ✓ Clone lists updated successfully")
            return True
        else:
            print(f"  ⚠️  Warning: retool.py --update exited with code {result.returncode}")
            return True  # Continue anyway
    except Exception as e:
        print(f"  ⚠️  Error updating clone lists: {e}", file=sys.stderr)
        return True  # Continue anyway


def update_retool_main(retool_dir: Path) -> bool:
    """Update retool directory using git pull."""
    if not (retool_dir / ".git").exists():
        print(f"⚠️  {retool_dir} is not a git repository, skipping update")
        return True
    
    print(f"Updating retool...")
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
                print("  ✓ Retool is already up to date")
            else:
                print("  ✓ Retool updated successfully")
            return True
        else:
            print(f"  ⚠️  Git pull warning: {result.stderr}", file=sys.stderr)
            return True
    except Exception as e:
        print(f"  ⚠️  Error updating retool: {e}", file=sys.stderr)
        return True


def extract_zip_file(zip_path: Path, output_dir: Path) -> Path | None:
    """Extract .dat file from .zip archive."""
    print(f"Extracting .zip file...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            dat_files = [f for f in zip_ref.namelist() if f.endswith('.dat')]
            
            if not dat_files:
                print(f"  ✗ No .dat file found in archive", file=sys.stderr)
                return None
            
            dat_filename = dat_files[0]
            zip_ref.extract(dat_filename, output_dir)
            extracted_path = output_dir / dat_filename
            print(f"  ✓ Extracted: {extracted_path.name}")
            return extracted_path
            
    except zipfile.BadZipFile:
        print(f"  ✗ Invalid .zip file", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ✗ Error extracting .zip: {e}", file=sys.stderr)
        return None


def download_redump_psx_dat(output_dir: Path = None) -> Path | None:
    """Download the latest Redump PlayStation 1 .dat file (may be .zip)."""
    if output_dir is None:
        script_dir = Path(__file__).parent
        output_dir = script_dir  # Script is now in verification/, so use script_dir directly
    
    output_dir.mkdir(parents=True, exist_ok=True)
    dat_url = "http://redump.org/datfile/psx/"
    
    print(f"Downloading latest Redump PlayStation 1 .dat file...")
    print(f"  URL: {dat_url}")
    print(f"  Output directory: {output_dir}")
    
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
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        file_size = output_path.stat().st_size
        print(f"\n✓ Redump .DAT Download successful!")
        print(f"  Saved to: {output_path}")
        print(f"  File size: {file_size:,} bytes ({file_size / 1024 / 1024:.2f} MB)")
        
        return output_path
        
    except requests.exceptions.RequestException as e:
        print(f"\n✗ Error downloading file: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}", file=sys.stderr)
        return None


def run_retool(input_dat: Path, retool_dir: Path, output_dir: Path) -> Path | None:
    """Run Retool to filter the .dat file."""
    retool_script = retool_dir / "retool.py"
    
    if not retool_script.exists():
        print(f"✗ Retool script not found: {retool_script}", file=sys.stderr)
        return None
    
    print(f"\nRunning Retool to filter .dat file...")
    print(f"  Input: {input_dat}")
    print(f"  Flags: {' '.join(RETOOL_FLAGS)}")
    print(f"  Exclude: {' '.join(RETOOL_EXCLUDE)}")
    
    cmd = [
        sys.executable,
        str(retool_script),
        str(input_dat),
    ] + RETOOL_FLAGS + ["--exclude"] + RETOOL_EXCLUDE + ["--output", str(output_dir)]
    
    try:
        result = subprocess.run(
            cmd,
            cwd=retool_dir,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print(f"✗ Retool failed with exit code {result.returncode}", file=sys.stderr)
            if result.stderr:
                print(f"  Error: {result.stderr}", file=sys.stderr)
            if result.stdout:
                print(f"  Output: {result.stdout}", file=sys.stderr)
            return None
        
        output_files = list(output_dir.glob("*.dat"))
        
        if output_files:
            output_file = max(output_files, key=lambda p: p.stat().st_mtime)
            print(f"✓ Retool processing complete!")
            print(f"  Output: {output_file}")
            return output_file
        else:
            print(f"⚠️  No output .dat file found in {output_dir}", file=sys.stderr)
            return None
            
    except Exception as e:
        print(f"✗ Error running Retool: {e}", file=sys.stderr)
        return None


def main():
    """Main entry point."""
    print("=" * 70)
    print("  REDUMP DAT DOWNLOADER AND RETOOL FILTER")
    print("=" * 70)
    print()
    
    script_dir = Path(__file__).parent
    verification_dir = script_dir  # Script is now in verification/, so use script_dir directly
    retool_dir = script_dir.parent / "tooling" / "retool"
    
    # Step 1: Install dependencies
    if not install_retool_dependencies():
        print("⚠️  Continuing despite dependency installation issues...")
    
    # Step 2: Update retool via git pull
    if not update_retool_main(retool_dir):
        print("⚠️  Continuing despite retool update issues...")
    
    # Step 3: Update clone lists
    if not update_retool_clone_lists(retool_dir):
        print("⚠️  Continuing despite clone list update issues...")
    
    # Step 4: Download .dat/.zip file
    downloaded_file = download_redump_psx_dat(verification_dir)
    if not downloaded_file:
        print("\n✗ Download failed!")
        sys.exit(1)
    
    # Step 5: Extract if it's a .zip file
    input_dat = downloaded_file
    extracted_dat = None
    if downloaded_file.suffix.lower() == '.zip':
        extracted_dat = extract_zip_file(downloaded_file, verification_dir)
        if not extracted_dat:
            print("\n✗ Extraction failed!")
            sys.exit(1)
        input_dat = extracted_dat
        # Delete the .zip file after extraction
        try:
            downloaded_file.unlink()
            print(f"  ✓ Deleted intermediate .zip file")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not delete .zip file: {e}")
    
    # Step 6: Run Retool
    output_dat = run_retool(input_dat, retool_dir, verification_dir)
    if not output_dat:
        print("\n✗ Retool processing failed!")
        sys.exit(1)
    
    # Step 7: Clean up intermediate files
    print("\nCleaning up intermediate files...")
    
    # Delete the extracted Redump .dat file (we only keep the filtered one)
    if extracted_dat and extracted_dat != output_dat:
        try:
            extracted_dat.unlink()
            print(f"  ✓ Deleted intermediate Redump .dat file")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not delete intermediate .dat file: {e}")
    elif input_dat != output_dat and input_dat.exists():
        # If it wasn't extracted from zip, but is different from output, delete it
        try:
            input_dat.unlink()
            print(f"  ✓ Deleted intermediate .dat file")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not delete intermediate .dat file: {e}")
    
    print("\n" + "=" * 70)
    print("✓ All operations completed successfully!")
    print(f"  Final filtered .dat: {output_dat}")
    print("=" * 70)


if __name__ == "__main__":
    main()

