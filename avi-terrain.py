import os
import sys
import time
# Set QGIS environment before importing qgis modules
QGIS_CONTENTS = "/Applications/QGIS.app/Contents"
os.environ.setdefault("QGIS_PREFIX_PATH", f"{QGIS_CONTENTS}/MacOS")
os.environ.setdefault("QT_PLUGIN_PATH", f"{QGIS_CONTENTS}/PlugIns")
os.environ.setdefault("GDAL_DATA", f"{QGIS_CONTENTS}/Resources/gdal")
os.environ.setdefault("PROJ_LIB", f"{QGIS_CONTENTS}/Resources/proj")
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
    QgsProviderRegistry
)
from qgis import processing
from qgis.core import QgsProcessingFeedback
from qgis.analysis import QgsNativeAlgorithms


QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
QgsApplication.setPluginPath(f"{QGIS_CONTENTS}/PlugIns/qgis")

qgs = QgsApplication([], False)
qgs.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
qgs.initQgis()
# Initialize Processing plugin and register native algorithms
from processing.core.Processing import Processing
Processing.initialize()
import processing

def size_mib(path):
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return 0.0


def run_step(label, alg_id, params, output_key='OUTPUT'):
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

feedback = QgsProcessingFeedback()

OUTPUT_DIR = "work/swiss-skitouring"
slope_path = os.path.join(OUTPUT_DIR, "slope.tif")
slope_clean_path = os.path.join(OUTPUT_DIR, "slope30_clean.tif")
binary_path = os.path.join(OUTPUT_DIR, "slope30.tif")
polygon_path = os.path.join(OUTPUT_DIR, "steep_areas.gpkg")
slope30_detailed_path = os.path.join(OUTPUT_DIR, "slope30_detailed.gpkg")
slope30_path = os.path.join(OUTPUT_DIR, "slope30.gpkg")

pixel_size = 2.0
z_factor = 1.0
slope_threshold = 30.0
min_pixels = 30

dem_out = QgsRasterLayer("work/swissalti3d_all.tif", "DEM")

# 1) Slope
res2 = run_step(
    f"Compute Slope from {dem_out.source()}",
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
    f"Reclassify slope > {slope_threshold}",
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

# 4) Polygonize
res4 = run_step(
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

# 5) Extract steep areas (value == 1)
res = run_step(
    "Extract steep areas",
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

QgsProject.instance().clear()

# Drop Python refs so providers/rasters are destroyed before QGIS shuts down
point_layer = None
dem_out = None
vl = None
binary_out = None

import gc
gc.collect()
qgs.exitQgis()
