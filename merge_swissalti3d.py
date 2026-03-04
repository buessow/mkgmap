#!/Volumes/T9/Applications/QGIS.app/Contents/MacOS/python

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

# Set up PROJ environment before importing GDAL
def setup_proj_env():
    """Set up PROJ environment to avoid 'Cannot find proj.db' warnings."""
    # Try to find QGIS PROJ directory
    qgis_contents = "/Volumes/T9/Applications/QGIS.app/Contents"
    proj_paths = [
        f"{qgis_contents}/Resources/qgis/proj",
        f"{qgis_contents}/Resources/proj",
    ]
    for path in proj_paths:
        if os.path.exists(path):
            os.environ["PROJ_LIB"] = path
            os.environ["PROJ_DATA"] = path
            break

setup_proj_env()

try:
    from osgeo import gdal
    # Enable GDAL exceptions to suppress FutureWarning
    gdal.UseExceptions()
    # Set GDAL config to suppress CRS mismatch warnings
    gdal.SetConfigOption('GTIFF_SRS_SOURCE', 'EPSG')
except Exception as e:
    print("ERROR: GDAL Python bindings not available. Install GDAL or run with QGIS Python.", file=sys.stderr)
    raise


TILE_REGEX = re.compile(r"swissalti3d_\d+_(\d+)-(\d+)_.*\.tif$", re.IGNORECASE)


def find_tiles(input_dir: str) -> Dict[Tuple[int, int], str]:
    tiles: Dict[Tuple[int, int], str] = {}
    for root, _, files in os.walk(input_dir):
        for fn in files:
            if not fn.lower().endswith(".tif"):
                continue
            m = TILE_REGEX.match(fn)
            if not m:
                continue
            x = int(m.group(1))
            y = int(m.group(2))
            path = os.path.join(root, fn)
            tiles[(x, y)] = path
    return tiles


def to_chunks(tiles: Dict[Tuple[int, int], str], width: int, height: int) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    coords = tiles.keys()
    x_vals = sorted(set(x for x, _ in coords))
    y_vals = sorted(set(y for _, y in coords))
    x_min = x_vals[0]
    y_min = y_vals[0]
    x_span = (x_vals[1] - x_vals[0])
    y_span = (y_vals[1] - y_vals[0])

    result: Dict[Tuple[int, int], List[str]] = {}
    for (x, y), file in tiles.items():
        rxi = ((x - x_min) // x_span) // (len(x_vals) // width)
        rx = x_min + (rxi * x_span * len(x_vals) // width)
        ryi = ((y - y_min) // y_span) // (len(y_vals) // height)
        ry = y_min + (ryi * y_span * len(y_vals) // height)
        result[(rx, ry)] = result.get((rx, ry), []) + [file]

    unique_files = set(f for files in result.values() for f in files)
    total_assigned = len(unique_files)
    assert total_assigned == len(tiles), f"Total assigned tiles {total_assigned} != total tiles {len(tiles)}"
    return result


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def build_vrt_and_tif(files: List[str], vrt_path: str, out_tif: str) -> None:
    print(f"  VRT -> {vrt_path} ({len(files)} tiles)")
    if os.path.exists(out_tif):
        print(f"  skip (exists): {out_tif}")
        return
    vrt_ds = gdal.BuildVRT(vrt_path, files, options=gdal.BuildVRTOptions(resolution="highest"))
    if vrt_ds is None:
        raise RuntimeError(f"BuildVRT failed for {vrt_path}")
    vrt_ds = None

    print(f"  GTiff <- {out_tif}")
    translate_opts = gdal.TranslateOptions(
        creationOptions=[
            "COMPRESS=DEFLATE",     # deflate compression
            "PREDICTOR=2",          # store horizontal deltas
            "TILED=YES",            # tiled format rather than strip
            "BIGTIFF=IF_SAFER",     # use bigtiff if safe
            "NUM_THREADS=ALL_CPUS", # use all CPUs for parallel processing
        ]
    )
    out_ds = gdal.Translate(out_tif, vrt_path, options=translate_opts)
    if out_ds is None:
        raise RuntimeError(f"Translate failed for {out_tif}")
    out_ds = None


def chunk_name(i: int, key: Tuple[int, int]) -> str:
    rx, ry = key
    return f"{i:03}_{rx}-{ry}_alti3d"


def chunk_paths(i: int, key: Tuple[int, int], output_dir: str) -> Tuple[str, str]:
    name = chunk_name(i, key)
    vrt_path = os.path.join(output_dir, f"{name}.vrt")
    out_tif = os.path.join(output_dir, f"{name}.tif")
    return vrt_path, out_tif


def process_chunk(i, item, prefix, output_dir):
    (rx, ry), files = item
    vrt_path, out_tif = chunk_paths(i, (rx, ry), output_dir)
    if os.path.exists(out_tif):
        print(f"  skip (exists): {out_tif}")
        return 0
    print(f"{i:03} Merging group {rx},{ry} ({len(files)} tiles)")
    build_vrt_and_tif(files, vrt_path, out_tif)
    return 1


def iter_output_paths(chunks, output_dir):
    for i, item in enumerate(sorted(chunks.items())):
        (rx, ry), _ = item
        _, out_tif = chunk_paths(i, (rx, ry), output_dir)
        yield out_tif


def format_make_list(name: str, items: List[str], indent: str = "  ") -> str:
    if not items:
        return f"{name} :="
    lines = [f"{name} := \\"]
    for i, item in enumerate(items):
        suffix = " \\" if i < len(items) - 1 else ""
        lines.append(f"{indent}{item}{suffix}")
    return "\n".join(lines)


def load_filenames_from_urls(urls_file: str) -> List[str]:
    """Extract filenames from URLs in the given file."""
    filenames = []
    with open(urls_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                # Extract the filename from the URL
                filename = line.split('/')[-1]
                filenames.append(filename)
    return filenames


def print_make_rules(chunks, input_dir, output_dir, width, height, raw_files: List[str], urls_file: str = None):
    script_name = os.path.basename(__file__)
    output_paths = [path for path in iter_output_paths(chunks, output_dir)]

    # If urls_file is provided, load filenames from it
    if urls_file and os.path.exists(urls_file):
        url_filenames = load_filenames_from_urls(urls_file)
        # Map filenames to their full paths in input_dir
        raw_files_from_urls = [os.path.join(input_dir, fn) for fn in url_filenames]
        raw_files = raw_files_from_urls

    print(format_make_list("SWISSALTI3D_RAW_FILES", raw_files))
    print()
    print(format_make_list("SWISSALTI3D_MERGED_FILES", output_paths))
    print()

    # Generate a separate rule for each merged output file
    sorted_chunks = sorted(chunks.items())
    for i, item in enumerate(sorted_chunks):
        (rx, ry), input_files = item
        _, out_tif = chunk_paths(i, (rx, ry), output_dir)

        # Format the input files for this specific chunk
        deps = " \\\n  ".join(input_files)

        print(f"{out_tif}: \\")
        print(f"  {deps} \\")
        print(f"  {script_name}")
        print(
            f"\t$(PYTHON3) {script_name} {input_dir} {output_dir} "
            f"--width {width} --height {height} --chunk-index {i}"
        )
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge swissalti3d tiles into a 4x4 grid (16 mosaics).")
    parser.add_argument(
        "input_dir",
        nargs="?",
        default="in/swiss-alti3d-raw",
        help="Directory containing swissalti3d *.tif tiles (default: swiss-alti3d-raw)"
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="work/swiss-alti3d",
        help="Directory to write merged mosaics (default: swiss-alti3d)"
    )
    parser.add_argument("--width", type=int, default=16, help="Grid width (default: 16)")
    parser.add_argument("--height", type=int, default=8, help="Grid height (default: 8)")
    parser.add_argument("--prefix", default="swissalti3d_mosaic", help="Output filename prefix")
    parser.add_argument(
        "--print-make-rules",
        action="store_true",
        help="Print make rules to create merged .tif files and exit"
    )
    parser.add_argument(
        "--print-output-paths",
        action="store_true",
        help="Print expected output .tif paths and exit"
    )
    parser.add_argument(
        "--chunk-index",
        type=int,
        help="Process only the given chunk index and exit"
    )
    parser.add_argument(
        "--urls-file",
        default="swiss-alti3d-2m_urls.txt",
        help="File containing URLs for input .tif files (default: swiss-alti3d-2m_urls.txt)"
    )
    args = parser.parse_args()

    ensure_dir(args.output_dir)

    tiles = find_tiles(args.input_dir)
    if not tiles:
        print("No matching tiles found. Ensure filenames match swissalti3d_*_<x>-<y>_*.tif", file=sys.stderr)
        sys.exit(1)


    chunks = to_chunks(tiles, args.width, args.height)
    raw_files = sorted(set(tiles.values()))
    if args.print_make_rules:
        print_make_rules(chunks, args.input_dir, args.output_dir, args.width, args.height, raw_files, args.urls_file)
        return
    if args.print_output_paths:
        for path in iter_output_paths(chunks, args.output_dir):
            print(path)
        return
    if args.chunk_index is not None:
        chunk_items = sorted(chunks.items())
        if args.chunk_index < 0 or args.chunk_index >= len(chunk_items):
            print(f"Invalid chunk index {args.chunk_index}; expected 0..{len(chunk_items) - 1}", file=sys.stderr)
            sys.exit(1)
        process_chunk(args.chunk_index, chunk_items[args.chunk_index], args.prefix, args.output_dir)
        return

    xs = sorted({x for (x, _) in tiles.keys()})
    ys = sorted({y for (_, y) in tiles.keys()})
    print(f"Found {len(tiles)} tiles; X unique={len(xs)}, Y unique={len(ys)}")
    total_outputs = 0
    from concurrent.futures import ProcessPoolExecutor, as_completed

    with ProcessPoolExecutor(max_workers=4) as executor:
        def msg(i): return f"{args.prefix}_{i+1:03}/{len(chunks):03}"
        futures = []
        for i, item in enumerate(sorted(chunks.items())):
            futures.append(executor.submit(process_chunk, i, item, args.prefix, args.output_dir))
        for future in as_completed(futures):
            total_outputs += future.result()

    print(f"Done. Created/verified {total_outputs} mosaics in {args.output_dir}")


if __name__ == "__main__":
    main()
