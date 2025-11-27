#!/Applications/QGIS.app/Contents/MacOS/bin/python3

import argparse
import os
import sys
import time

# Set QGIS environment before importing qgis modules
QGIS_CONTENTS = "/Applications/QGIS.app/Contents"

# FORCE QGIS paths. Do not use setdefault, as inherited shell vars (e.g. from Conda)
# will conflict with QGIS libraries and cause 'Cannot find proj.db' or bad CRS.
os.environ["QGIS_PREFIX_PATH"] = f"{QGIS_CONTENTS}/MacOS"
os.environ["QT_PLUGIN_PATH"] = f"{QGIS_CONTENTS}/PlugIns"
os.environ["GDAL_DATA"] = f"{QGIS_CONTENTS}/Resources/gdal"
os.environ["PROJ_LIB"] = f"{QGIS_CONTENTS}/Resources/proj"

# Ensure QGIS Python paths are available (core + plugins, includes 'processing')
sys.path.append(f"{QGIS_CONTENTS}/Resources/python")
sys.path.append(f"{QGIS_CONTENTS}/Resources/python/plugins")

from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsProviderRegistry,
    QgsProcessingFeedback
)
from qgis import processing
from qgis.core import QgsProcessingFeedback
from qgis.analysis import QgsNativeAlgorithms

# Global reference to hold the QGIS app
qgs = None




def init_qgis():
    """Initialize QGIS once."""
    global qgs
    # Force environment variables
    os.environ["QGIS_PREFIX_PATH"] = f"{QGIS_CONTENTS}/MacOS"
    os.environ["QT_PLUGIN_PATH"] = f"{QGIS_CONTENTS}/PlugIns"
    os.environ["GDAL_DATA"] = f"{QGIS_CONTENTS}/Resources/gdal"
    os.environ["PROJ_LIB"] = f"{QGIS_CONTENTS}/Resources/proj"

    QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
    QgsApplication.setPluginPath(f"{QGIS_CONTENTS}/PlugIns/qgis")

    qgs = QgsApplication([], False)
    qgs.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
    qgs.initQgis()

    # Initialize Processing plugin and register native algorithms
    from processing.core.Processing import Processing
    Processing.initialize()
    import processing

# Initialize immediately
init_qgis()

pixel_size = 2.0
z_factor = 1.0
slope_threshold = 30.0
min_pixels = 30

def size_mib(path):
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return 0.0

def run_step(label, alg_id, params, output_key='OUTPUT'):
    feedback = QgsProcessingFeedback()

    print(label)
    out_path = None
    if isinstance(params, dict):
        # Prefer explicit output_key, then common 'OUTPUT'
        candidate = params.get(output_key) or params.get('OUTPUT')
        if isinstance(candidate, str):
            out_path = candidate
    if out_path and os.path.exists(out_path):
        print(f"  skip (cache hit), size: {size_mib(out_path):.2f} MiB")
        return {output_key: out_path}
    t0 = time.perf_counter()
    res = processing.run(alg_id, params, feedback=feedback)
    dt = time.perf_counter() - t0
    out = res.get(output_key)
    out_size = size_mib(out) if isinstance(out, str) else 0.0
    print(f"  done in {dt:.2f}s, size: {out_size:.2f} MiB")
    return res


parser = argparse.ArgumentParser(description="Process a single DEM raster file for steep slope analysis.")
parser.add_argument("input_dem", help="Input DEM raster file path")
parser.add_argument("output_osm", help="Output OSM file path")
args = parser.parse_args()

def process_dem(prefix, dem_path, osm_path_out):
    # Derive intermediate paths based on input filename, placed in output directory
    output_dir = os.path.dirname(osm_path_out) or "."
    input_basename = os.path.splitext(os.path.basename(dem_path))[0]
    base_out = os.path.join(output_dir, input_basename)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    slope_path = f"{base_out}_slope.tif"
    slope_clean_path = f"{base_out}_slope30_clean.tif"
    binary_path = f"{base_out}_slope30.tif"
    polygon_path = f"{base_out}_steep_areas.gpkg"
    slope30_detailed_path = f"{base_out}_slope30_detailed.gpkg"
    slope30_path = f"{base_out}_slope30.gpkg"

    dem_out = QgsRasterLayer(dem_path, "DEM")


    # 1) Slope
    res2 = run_step(
        f"{prefix} Compute Slope from {dem_out.source()}",
        "qgis:slope",
        {
            'INPUT': dem_out,
            'Z_FACTOR': z_factor,
            'OUTPUT': slope_path
        }
    )
    slope_out = res2['OUTPUT']

    # 2) Reclassify slope > threshold
    expr = f'"{slope_out}@1" > {slope_threshold}'
    res3 = run_step(
        f"{prefix} Reclassify slope > {slope_threshold}",
        "qgis:rastercalculator",
        {
            'EXPRESSION': expr,
            'LAYERS': [slope_out],
            'CELLSIZE': pixel_size,
            'EXTENT': dem_out.extent(),
            'OUTPUT': binary_path
        }
    )
    binary_out = res3['OUTPUT']

    # 3) Sieve
    res_clean = run_step(
        f"{prefix} Sieve binary raster > {min_pixels} pixels",
        "gdal:sieve",
        {
            'INPUT': binary_out,
            'BAND': 1,
            'THRESHOLD': min_pixels,
            'EIGHT_CONNECTEDNESS': False,
            'OUTPUT': slope_clean_path
        }
    )
    binary_clean = res_clean['OUTPUT']

    # 4) Polygonize
    res4 = run_step(
        f"{prefix} Polygonize binary raster",
        "gdal:polygonize",
        {
            'INPUT': binary_clean,
            'BAND': 1,
            'FIELD': 'slope30',
            'EIGHT_CONNECTEDNESS': False,
            'OUTPUT': f"{polygon_path}"
        }
    )
    poly_out = res4['OUTPUT']

    # 5) Extract steep areas (value == 1)
    res = run_step(
        f"{prefix} Extract steep areas",
        "native:extractbyattribute",
        {
            "INPUT": poly_out,
            "FIELD": "slope30",
            "OPERATOR": 0,            # 0 = "="
            "VALUE": 1,
            "OUTPUT": slope30_detailed_path
        }
    )

    res_simpl = run_step(
        f"{prefix} Simplify steep areas",
        "native:simplifygeometries",
        {
            "INPUT": res["OUTPUT"],             # or poly_out
            "METHOD": 0,                        # 0 = distance (Douglas–Peucker)
            "TOLERANCE": 2.0,                   # meters; increase to simplify more
            "OUTPUT": slope30_path
        }
    )

    simplified = res_simpl["OUTPUT"]

    # Convert to OSM using the same python binary
    import subprocess
    import shutil

    # Run ogr2osm using the CURRENT python interpreter
    cmd = [sys.executable, "-m", "ogr2osm", "-f", "-o", osm_path_out, simplified]

    print(f"{prefix} ogr2osm -> {osm_path_out}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ogr2osm failed:\n{result.stderr}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python avi-terrain.py <input_dem> <output_osm>")
        sys.exit(1)

    try:
        process_dem("1/1", args.input_dem, args.output_osm)
    except Exception as e:
        print(f"Error processing {args.input_dem}: {e}", file=sys.stderr)

    # Cleanup
    if qgs:
        qgs.exitQgis()
