#!/usr/bin/env /Applications/QGIS.app/Contents/MacOS/bin/python3

import os
import sys
import argparse
import urllib.request
import time
from typing import Dict, Optional

try:
    from osgeo import gdal
except ImportError:
    print("ERROR: GDAL Python bindings not available. Run with QGIS Python.", file=sys.stderr)
    sys.exit(1)

# Suppress GDAL error messages to console
gdal.PushErrorHandler('CPLQuietErrorHandler')

def load_urls(url_file: str) -> Dict[str, str]:
    """Load URLs from file and return a map of filename -> url."""
    url_map = {}
    print(f"Loading URLs from {url_file}...")
    try:
        with open(url_file, 'r') as f:
            for line in f:
                url = line.strip()
                if not url:
                    continue
                filename = url.split('/')[-1]
                url_map[filename] = url
    except Exception as e:
        print(f"Error reading URL file: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(url_map)} URLs.")
    return url_map

def download_file(url: str, dest_path: str) -> bool:
    """Download a file from a URL to a destination path."""
    print(f"Downloading {url} -> {dest_path}")
    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}", file=sys.stderr)
        return False

def is_valid_tif(path: str) -> bool:
    """Check if a TIFF file is valid by attempting to read it."""
    ds = None
    try:
        ds = gdal.Open(path)
        if ds is None:
            return False
        # Try reading the first band to ensure data integrity
        band = ds.GetRasterBand(1)
        if band.ReadAsArray() is None:
            return False
        return True
    except Exception:
        return False
    finally:
        ds = None

def main():
    parser = argparse.ArgumentParser(description="Verify TIFF files and re-download corrupt ones.")
    parser.add_argument("url_file", help="File containing list of URLs")
    parser.add_argument("input_path", help="Directory containing TIFF files or a single TIFF file")
    args = parser.parse_args()

    if not os.path.exists(args.input_path):
        print(f"Input path not found: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    url_map = load_urls(args.url_file)

    corrupt_count = 0
    fixed_count = 0
    missing_url_count = 0

    files_to_check = []
    if os.path.isfile(args.input_path):
        files_to_check.append(args.input_path)
    else:
        for root, _, files in os.walk(args.input_path):
            for fn in files:
                if fn.startswith("._"):
                    continue
                if fn.lower().endswith(".tif"):
                    files_to_check.append(os.path.join(root, fn))

    total_files = len(files_to_check)
    print(f"Checking {total_files} TIFF files in {args.input_path}...")

    for i, file_path in enumerate(files_to_check):
        filename = os.path.basename(file_path)

        # Simple progress indicator
        if (i + 1) % 100 == 0:
            print(f"Processed {i + 1}/{total_files} files...")

        if not is_valid_tif(file_path):
            print(f"CORRUPT: {file_path}")
            corrupt_count += 1

            # Remove corrupt file
            try:
                os.remove(file_path)
                print(f"  Deleted {file_path}")
            except OSError as e:
                print(f"  Failed to delete {file_path}: {e}", file=sys.stderr)
                continue

            # Look up URL and re-download
            if filename in url_map:
                url = url_map[filename]
                if download_file(url, file_path):
                    # Validate the downloaded file
                    if is_valid_tif(file_path):
                        print(f"  Successfully repaired {filename}")
                        fixed_count += 1
                    else:
                        print(f"  Downloaded file is still corrupt: {filename}", file=sys.stderr)
            else:
                print(f"  No URL found for {filename} in {args.url_file}", file=sys.stderr)
                missing_url_count += 1

    print("\nSummary:")
    print(f"  Total checked: {total_files}")
    print(f"  Corrupt:       {corrupt_count}")
    print(f"  Fixed:         {fixed_count}")
    print(f"  Missing URL:   {missing_url_count}")

if __name__ == "__main__":
    main()
