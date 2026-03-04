#!/Volumes/T9/Applications/QGIS.app/Contents/MacOS/python

import argparse
import os
import sys
import time
import subprocess

# Set QGIS environment before importing qgis modules
def resolve_qgis_contents():
    exe = os.path.realpath(sys.executable)
    candidate = os.path.dirname(os.path.dirname(exe))
    if os.path.basename(candidate) == "Contents" and "QGIS.app" in candidate:
        return candidate
    candidates = [
        "/Volumes/T9/Applications/QGIS.app/Contents",
        "/Volumes/QGIS Installer/QGIS.app/Contents",
        "/Applications/QGIS.app/Contents",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return "/Applications/QGIS.app/Contents"


def first_existing(*paths):
    for path in paths:
        if path and os.path.exists(path):
            return path
    return paths[0] if paths else None


def append_sys_path(path):
    if path and path not in sys.path:
        sys.path.append(path)


def prepend_env_path(var_name, value):
    existing = os.environ.get(var_name)
    if existing:
        os.environ[var_name] = f"{value}:{existing}"
    else:
        os.environ[var_name] = value


QGIS_CONTENTS = resolve_qgis_contents()
QGIS_PREFIX = f"{QGIS_CONTENTS}/MacOS"
QGIS_PLUGIN_PATH = f"{QGIS_CONTENTS}/PlugIns/qgis"
QGIS_RESOURCE_BASE = first_existing(
    f"{QGIS_CONTENTS}/Resources/qgis",
    f"{QGIS_CONTENTS}/Resources",
)
QGIS_PYTHON = first_existing(
    f"{QGIS_RESOURCE_BASE}/python",
    f"{QGIS_CONTENTS}/Resources/python",
    f"{QGIS_CONTENTS}/Resources/python3.11",
)
QGIS_PLUGINS = first_existing(
    f"{QGIS_RESOURCE_BASE}/python/plugins",
    f"{QGIS_CONTENTS}/Resources/python/plugins",
)
QGIS_PROJ = first_existing(
    f"{QGIS_RESOURCE_BASE}/proj",
    f"{QGIS_CONTENTS}/Resources/proj",
)
QGIS_GDAL = first_existing(
    f"{QGIS_RESOURCE_BASE}/gdal",
    f"{QGIS_CONTENTS}/Resources/gdal",
)
QGIS_SCRIPTS = first_existing(
    f"{QGIS_CONTENTS}/Resources/scripts",
    f"{QGIS_RESOURCE_BASE}/scripts",
)
QGIS_FRAMEWORKS = f"{QGIS_CONTENTS}/Frameworks"
QGIS_LIB = f"{QGIS_PREFIX}/lib"


def cleanup_pyqt_widget_plugins():
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    widget_dir = (
        f"{QGIS_CONTENTS}/Frameworks/lib/{py_ver}/site-packages/"
        "PyQt5/uic/widget-plugins"
    )
    if not os.path.isdir(widget_dir):
        return
    for name in os.listdir(widget_dir):
        if name.startswith("._") and name.endswith(".py"):
            try:
                os.remove(os.path.join(widget_dir, name))
            except OSError:
                pass


# FORCE QGIS paths. Do not use setdefault, as inherited shell vars (e.g. from Conda)
# will conflict with QGIS libraries and cause 'Cannot find proj.db' or bad CRS.
os.environ["QGIS_PREFIX_PATH"] = QGIS_PREFIX
os.environ["QT_PLUGIN_PATH"] = f"{QGIS_CONTENTS}/PlugIns"
os.environ["QGIS_PLUGINPATH"] = QGIS_PLUGIN_PATH
os.environ["GDAL_DATA"] = QGIS_GDAL
os.environ["PROJ_LIB"] = QGIS_PROJ
os.environ["PROJ_DATA"] = QGIS_PROJ

# Ensure QGIS libs are discoverable (avoids "Application path not initialized")
prepend_env_path("PATH", f"{QGIS_PREFIX}/bin")
prepend_env_path("DYLD_LIBRARY_PATH", QGIS_FRAMEWORKS)
prepend_env_path("DYLD_LIBRARY_PATH", QGIS_LIB)

# Ensure QGIS Python paths are available (core + plugins, includes 'processing')
append_sys_path(QGIS_PYTHON)
append_sys_path(QGIS_PLUGINS)

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
from qgis.analysis import QgsNativeAlgorithms

# Global references to hold the QGIS app and processing module
qgs = None
processing = None


def init_qgis():
    """Initialize QGIS once."""
    global qgs, processing
    # Force environment variables
    os.environ["QGIS_PREFIX_PATH"] = QGIS_PREFIX
    os.environ["QT_PLUGIN_PATH"] = f"{QGIS_CONTENTS}/PlugIns"
    os.environ["QGIS_PLUGINPATH"] = QGIS_PLUGIN_PATH
    os.environ["GDAL_DATA"] = QGIS_GDAL
    os.environ["PROJ_LIB"] = QGIS_PROJ
    os.environ["PROJ_DATA"] = QGIS_PROJ

    # Set prefix path BEFORE creating QgsApplication to avoid "Application path not initialized" warning
    QgsApplication.setPrefixPath(QGIS_PREFIX, True)

    qgs = QgsApplication([], False)
    qgs.initQgis()

    # Initialize Processing plugin and register native algorithms
    cleanup_pyqt_widget_plugins()
    from processing.core.Processing import Processing
    Processing.initialize()
    import processing

# Initialize immediately
init_qgis()

pixel_size = 2.0
slope_threshold = 30.0
min_pixels = 30

def size_mib(path):
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return 0.0

ACTION_WIDTH = 32

def run_step(prefix, label, alg_id, params, output_key='OUTPUT'):
    feedback = QgsProcessingFeedback()

    l = f"{label:>{ACTION_WIDTH}}."
    out_path = None
    if isinstance(params, dict):
        # Prefer explicit output_key, then common 'OUTPUT'
        candidate = params.get(output_key) or params.get('OUTPUT')
        if isinstance(candidate, str):
            out_path = candidate
    if out_path and os.path.exists(out_path):
        print(f"{prefix} {l} Skip, size: {size_mib(out_path):.2f} MiB")
        return {output_key: out_path}
    print(f"{prefix} {l}")
    t0 = time.perf_counter()
    res = processing.run(alg_id, params, feedback=feedback)
    dt = time.perf_counter() - t0
    out = res.get(output_key)
    out_size = size_mib(out) if isinstance(out, str) else 0.0
    print(f"{prefix} {l} Done in {dt:.2f}s, size: {out_size:.2f} MiB")
    return res


def reclassify_slope_gdal_calc(prefix, slope_path, threshold, output_path):
    gdal_calc = os.path.join(QGIS_SCRIPTS, "gdal_calc.py")
    if not os.path.exists(gdal_calc):
        raise FileNotFoundError(f"gdal_calc.py not found at {gdal_calc}")
    cmd = [
        sys.executable,
        gdal_calc,
        "-A",
        slope_path,
        "--calc",
        f"A>{threshold}",
        "--outfile",
        output_path,
        "--type",
        "Byte",
        "--NoDataValue=0",
        "--overwrite",
    ]
    label = f"Reclassify slope > {threshold} (gdal_calc)"
    print(f"{prefix} {label:>{ACTION_WIDTH}}")
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if result.returncode != 0:
        raise RuntimeError(f"gdal_calc failed:\n{result.stderr}")
    out_size = size_mib(output_path)
    print(f"{prefix} {label:>{ACTION_WIDTH}}. Done in {dt:.2f}s, size: {out_size:.2f} MiB")
    return output_path


def sieve_gdal_script(prefix, input_path, min_pixels, output_path, eight_connected):
    gdal_sieve = os.path.join(QGIS_SCRIPTS, "gdal_sieve.py")
    if not os.path.exists(gdal_sieve):
        raise FileNotFoundError(f"gdal_sieve.py not found at {gdal_sieve}")
    cmd = [sys.executable, gdal_sieve, "-st", str(min_pixels), "-of", "GTiff"]
    cmd.append("-8" if eight_connected else "-4")
    cmd.extend([input_path, output_path])
    label = f"Sieve binary raster > {min_pixels} pixels (gdal_sieve)"
    print(f"{prefix} {label:>{ACTION_WIDTH}}")
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if result.returncode != 0:
        raise RuntimeError(f"gdal_sieve failed:\n{result.stderr}")
    out_size = size_mib(output_path)
    print(f"{prefix} {label:>{ACTION_WIDTH}}. Done in {dt:.2f}s, size: {out_size:.2f} MiB")
    return output_path


def pick_polygon_field(layer, preferred_name):
    names = [field.name() for field in layer.fields()]
    if preferred_name in names:
        return preferred_name
    if "DN" in names:
        return "DN"
    if names:
        return names[0]
    return None


def polygonize_gdal_script(prefix, input_path, output_path, field_name, eight_connected):
    gdal_polygonize = os.path.join(QGIS_SCRIPTS, "gdal_polygonize.py")
    if not os.path.exists(gdal_polygonize):
        raise FileNotFoundError(f"gdal_polygonize.py not found at {gdal_polygonize}")
    layer_name = os.path.splitext(os.path.basename(output_path))[0]
    cmd = [sys.executable, gdal_polygonize, input_path, "-b", "1", "-f", "GPKG"]
    if eight_connected:
        cmd.append("-8")
    cmd.extend([output_path, layer_name, field_name])
    label = f"Polygonize binary raster (gdal_polygonize)"
    print(f"{prefix} {label:>{ACTION_WIDTH}}")
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if result.returncode != 0:
        raise RuntimeError(f"gdal_polygonize failed:\n{result.stderr}")
    out_size = size_mib(output_path)
    print(f"{prefix} {label:>{ACTION_WIDTH}}. Done in {dt:.2f}s, size: {out_size:.2f} MiB")
    return output_path


def alti3d_to_slope30(prefix, dem_path, osm_path_out):
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
        prefix,
        f"Compute Slope",
        "qgis:slope",
        {
            'INPUT': dem_out,
            'Z_FACTOR': 1.0,
            'OUTPUT': slope_path
        }
    )
    slope_out = res2['OUTPUT']

    # 2) Reclassify slope > threshold
    slope_layer = QgsRasterLayer(slope_out, "slope")
    if not slope_layer.isValid():
        print(f"Error: Failed to load slope raster layer from {slope_out}")
        return None
    expr = f'"{slope_layer.name()}@1" > {slope_threshold}'
    try:
        res3 = run_step(
            prefix,
            f"Reclassify slope > {slope_threshold}",
            "qgis:rastercalculator",
            {
                'EXPRESSION': expr,
                'LAYERS': [slope_layer],
                'CELLSIZE': pixel_size,
                'EXTENT': slope_layer.extent(),
                'OUTPUT': binary_path
            }
        )
        binary_out = res3['OUTPUT']
    except Exception as e:
        print(f"{prefix} Reclassify slope > {slope_threshold}. QGIS calc failed: {e}")
        binary_out = reclassify_slope_gdal_calc(prefix, slope_out, slope_threshold, binary_path)

    # 3) Sieve
    try:
        res_clean = run_step(
            prefix,
            f"Sieve binary raster > {min_pixels} pixels",
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
    except Exception as e:
        print(f"{prefix} Sieve binary raster > {min_pixels} pixels. QGIS sieve failed: {e}")
        binary_clean = sieve_gdal_script(prefix, binary_out, min_pixels, slope_clean_path, False)

    # 4) Polygonize
    try:
        res4 = run_step(
            prefix,
            "Polygonize binary raster",
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
    except Exception as e:
        print(f"{prefix} Polygonize binary raster. QGIS polygonize failed: {e}")
        poly_out = polygonize_gdal_script(prefix, binary_clean, polygon_path, "slope30", False)

    # 5) Extract steep areas (value == 1)
    poly_layer = QgsVectorLayer(poly_out, "slope_polys", "ogr")
    if not poly_layer.isValid():
        print(f"Error: Failed to load polygon layer from {poly_out}")
        return None
    poly_field = pick_polygon_field(poly_layer, "slope30")
    if not poly_field:
        print(f"Error: No usable field found in {poly_out}")
        return None
    res = run_step(
        prefix,
        "Extract steep areas",
        "native:extractbyattribute",
        {
            "INPUT": poly_out,
            "FIELD": poly_field,
            "OPERATOR": 0,            # 0 = "="
            "VALUE": 1,
            "OUTPUT": slope30_detailed_path
        }
    )

    res_simpl = run_step(
        prefix,
        "Simplify steep areas",
        "native:simplifygeometries",
        {
            "INPUT": res["OUTPUT"],             # or poly_out
            "METHOD": 0,                        # 0 = distance (Douglas–Peucker)
            "TOLERANCE": 2.0,                   # meters; increase to simplify more
            "OUTPUT": slope30_path
        }
    )

    simplified = res_simpl["OUTPUT"]
    return simplified

def rock_to_vector(prefix, rock_tif_path, output_base_path):
    output_dir = os.path.dirname(output_base_path) or "."
    os.makedirs(output_dir, exist_ok=True)

    rock_layer = QgsRasterLayer(rock_tif_path, "Rock")
    if not rock_layer.isValid():
        print(f"Error: Failed to load rock raster layer from {rock_tif_path}")
        return None

    intermediate_path = f"{output_base_path}_all.gpkg"
    extracted_path = f"{output_base_path}_xtrct.gpkg"
    simplified_path = f"{output_base_path}_smpl.gpkg"
    try:
        run_step(
            prefix,
            "Polygonize rock raster",
            "gdal:polygonize",
            {
                "INPUT": rock_layer,
                "BAND": 1,
                "FIELD": "rock",
                'EIGHT_CONNECTEDNESS': True,
                'OUTPUT': intermediate_path
            }
        )
    except Exception as e:
        print(f"{prefix} Polygonize rock raster. QGIS polygonize failed: {e}")
        polygonize_gdal_script(prefix, rock_tif_path, intermediate_path, "rock", True)
    rock_poly_layer = QgsVectorLayer(intermediate_path, "rock_polys", "ogr")
    if not rock_poly_layer.isValid():
        print(f"Error: Failed to load polygon layer from {intermediate_path}")
        return None
    rock_field = pick_polygon_field(rock_poly_layer, "rock")
    if not rock_field:
        print(f"Error: No usable field found in {intermediate_path}")
        return None
    run_step(
        prefix,
        "Extract rock areas",
        "native:extractbyattribute",
        {
            "INPUT": intermediate_path,
            "FIELD": rock_field,
            "OPERATOR": 0,            # 0 = "="
            "VALUE": 0,
            "OUTPUT": extracted_path
        }
    )
    run_step(
        prefix,
        "Simplify rock areas",
        "native:simplifygeometries",
        {
            "INPUT": extracted_path,
            "METHOD": 0,                        # 0 = distance (Douglas–Peucker)
            "TOLERANCE": 3.0,                   # meters; increase to simplify more
            "OUTPUT": simplified_path
        }
    )
    return simplified_path

def convert_to_osm(prefix, input_path, osm_path_out):
    if not input_path:
        print(f"{prefix} Convert to OSM. Skipped (no input layer)")
        return

    if os.path.exists(osm_path_out):
        print(f"{prefix} {'Convert to OSM':>{ACTION_WIDTH}}. Skip, size: {size_mib(osm_path_out):.2f} MiB")
        return

    # Convert GPKG to GeoJSON using ogr2ogr from conda environment
    # QGIS GDAL 3.12.0 creates GeoPackage v1.4.0 that conda GDAL 3.6.4 can't read directly
    geojson_path = input_path.replace('.gpkg', '.geojson')

    if not os.path.exists(geojson_path):
        print(f"{prefix} {'Export to GeoJSON':>{ACTION_WIDTH}}")
        t0 = time.perf_counter()

        # Use ogr2ogr from conda environment (compatible GDAL version)
        ogr2osm_path = os.environ.get('OGR2OSM', '/opt/homebrew/Caskroom/miniforge/base/envs/ogr2osm/bin/ogr2osm')
        ogr2ogr_dir = os.path.dirname(ogr2osm_path)
        ogr2ogr_cmd = os.path.join(ogr2ogr_dir, 'ogr2ogr')

        if not os.path.exists(ogr2ogr_cmd):
            print(f"Error: ogr2ogr not found at {ogr2ogr_cmd}")
            return

        # Create a clean environment for ogr2ogr, removing QGIS-specific variables
        env = os.environ.copy()
        for key in ['PYTHONHOME', 'PYTHONPATH', 'QGIS_PREFIX_PATH', 'QT_PLUGIN_PATH',
                    'QGIS_PLUGINPATH', 'DYLD_LIBRARY_PATH']:
            env.pop(key, None)
        env['OGR_GEOJSON_MAX_OBJ_SIZE'] = '0'  # Allow large features

        cmd = [ogr2ogr_cmd, '-f', 'GeoJSON', geojson_path, input_path]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        dt = time.perf_counter() - t0

        if result.returncode != 0:
            print(f"ogr2ogr failed:\n{result.stderr}", file=sys.stderr)
            return

        print(f"{prefix} {'Export to GeoJSON':>{ACTION_WIDTH}}. Done in {dt:.2f}s")

    # Use the dedicated ogr2osm from conda environment
    ogr2osm_path = os.environ.get('OGR2OSM', '/opt/homebrew/Caskroom/miniforge/base/envs/ogr2osm/bin/ogr2osm')
    if not os.path.exists(ogr2osm_path):
        print(f"Error: ogr2osm not found at {ogr2osm_path}")
        return

    cmd = [ogr2osm_path, "-f", "-o", osm_path_out, geojson_path]

    print(f"{prefix} {'Convert to OSM':>{ACTION_WIDTH}}")
    t0 = time.perf_counter()

    # Create a clean environment for ogr2osm, removing QGIS-specific variables
    env = os.environ.copy()
    for key in ['PYTHONHOME', 'PYTHONPATH', 'QGIS_PREFIX_PATH', 'QT_PLUGIN_PATH',
                'QGIS_PLUGINPATH', 'DYLD_LIBRARY_PATH']:
        env.pop(key, None)
    env['OGR_GEOJSON_MAX_OBJ_SIZE'] = '0'  # Allow large features

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    dt = time.perf_counter() - t0
    out_size = size_mib(osm_path_out)
    print(f"{prefix} {'Convert to OSM':>{ACTION_WIDTH}}. Done in {dt:.2f}s, size: {out_size:.2f} MiB")

    if result.returncode != 0:
        print(f"ogr2osm failed:\n{result.stderr}", file=sys.stderr)


parser = argparse.ArgumentParser(description="Process a single DEM raster file for steep slope analysis.")
parser.add_argument("mode", help="Mode (slope30|rock)")
parser.add_argument("input_dem", help="Input DEM raster file path")
parser.add_argument("output_osm", help="Output OSM file path")
args = parser.parse_args()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python avi-terrain.py (slope30|rock) <input_dem> <output_osm>")
        sys.exit(1)

    output_base_path = os.path.splitext(args.output_osm)[0]
    prefix = os.path.splitext(os.path.basename(args.output_osm))[0]
    if args.mode == "slope30":
        vector_layer = alti3d_to_slope30(prefix, args.input_dem, output_base_path)
        if not vector_layer:
            print("Error: slope30 processing failed. Check disk space and inputs.")
            sys.exit(1)
        convert_to_osm(prefix, vector_layer, args.output_osm)
    elif args.mode == "rock":
        vector_layer = rock_to_vector(prefix, args.input_dem, output_base_path)
        if not vector_layer:
            print("Error: rock processing failed. Check inputs.")
            sys.exit(1)
        convert_to_osm(prefix, vector_layer, args.output_osm)
    else:
        print(f"Unknown mode: {args.mode}")
        sys.exit(1)
