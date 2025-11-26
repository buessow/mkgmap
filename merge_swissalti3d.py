#!/usr/bin/env /Applications/QGIS.app/Contents/MacOS/bin/python3

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

try:
    from osgeo import gdal
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
        rx = ((x - x_min) // x_span) // width
        rx = x_min + (rx * width * x_span)
        ry = ((y - y_min) // y_span) // height
        ry = y_min + (ry * height * y_span)
        result[(rx, ry)] = result.get((rx, ry), []) + [file]
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
            "COMPRESS=DEFLATE",
            "PREDICTOR=2",
            "TILED=YES",
            "BIGTIFF=IF_SAFER",
        ]
    )
    out_ds = gdal.Translate(out_tif, vrt_path, options=translate_opts)
    if out_ds is None:
        raise RuntimeError(f"Translate failed for {out_tif}")
    out_ds = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge swissalti3d tiles into a 4x4 grid (16 mosaics).")
    parser.add_argument("input_dir", help="Directory containing swissalti3d *.tif tiles")
    parser.add_argument("output_dir", help="Directory to write merged mosaics")
    parser.add_argument("--width", type=int, default=8, help="Grid width (default: 8)")
    parser.add_argument("--height", type=int, default=4, help="Grid height (default: 4)")
    parser.add_argument("--prefix", default="swissalti3d_mosaic", help="Output filename prefix")
    args = parser.parse_args()

    ensure_dir(args.output_dir)

    tiles = find_tiles(args.input_dir)
    if not tiles:
        print("No matching tiles found. Ensure filenames match swissalti3d_*_<x>-<y>_*.tif", file=sys.stderr)
        sys.exit(1)

    xs = sorted({x for (x, _) in tiles.keys()})
    ys = sorted({y for (_, y) in tiles.keys()})
    print(f"Found {len(tiles)} tiles; X unique={len(xs)}, Y unique={len(ys)}")

    chunks = to_chunks(tiles, args.width, args.height)

    total_outputs = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def process_chunk(i, item):
        (rx, ry), files = item
        name = f"{args.prefix}_{rx}-{ry}"
        vrt_path = os.path.join(args.output_dir, f"{name}.vrt")
        out_tif = os.path.join(args.output_dir, f"{name}.tif")
        print(f"Merging group ({i+1}/{len(chunks)}): {rx},{ry} ({len(files)} tiles)")
        build_vrt_and_tif(files, vrt_path, out_tif)
        return 1

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_chunk, i, item) for i, item in enumerate(chunks.items())]
        for future in as_completed(futures):
            total_outputs += future.result()

    print(f"Done. Created/verified {total_outputs} mosaics in {args.output_dir}")


if __name__ == "__main__":
    main()
