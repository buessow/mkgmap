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
    t0 = time.perf_counter()
    res = processing.run(alg_id, params, feedback=feedback)
    dt = time.perf_counter() - t0
    out = res.get(output_key)
    out_size = size_mib(out) if isinstance(out, str) else 0.0
    print(f"  done in {dt:.2f}s, size: {out_size:.2f} MiB")
    return res


# slope_params = {
#     'INPUT': '/Volumes/T9/qgis-data/swissalti3d_2019_2504-1115_2_2056_5728.tif',
#     'BAND': 1,
#     'SCALE': 1,
#     'AS_PERCENT': False,
#     'COMPUTE_EDGES': False,
#     'ZEVENBERGEN': False,
#     'OPTIONS': None,
#     'EXTRA': '',
#     'OUTPUT': 'TEMPORARY_OUTPUT'
# }
# processing.run("gdal:slope", slope_params)


# if not QgsApplication.processingRegistry().providerByName('native'):
# QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

feedback = QgsProcessingFeedback()

# --- PARAMETERS, adjust as needed ---
xyz_path = os.path.abspath("SWISSALTI3D_0.5_XYZ_CHLV95_LN02_2705_1207.xyz")


dem_path = "work/dem.tif"
slope_path = "work/slope.tif"
slope_clean_path = "work/slope30_clean.tif"
binary_path = "work/slope30.tif"
polygon_path = "work/steep_areas.gpkg"
polygon_layer_name = "steep30"
pixel_size = 2.0
z_factor = 1.0
slope_threshold = 30.0
min_pixels = 20

if not os.path.exists(xyz_path):
    raise RuntimeError(f"XYZ file not found: {xyz_path}")

# Import your XYZ as a vector (delimited text)
# Use header names (X Y Z), point geometry, and LV95 CRS
uri = (
    f"file://{xyz_path}"
    f"?encoding=UTF-8"
    f"&delimiter=%20"
    f"&useHeader=yes"
    f"&xField=X&yField=Y&zField=Z"
    f"&geomType=point"
    f"&crs=EPSG:2056"
    f"&decimalPoint=."
)

point_layer = QgsVectorLayer(uri, "XYZ Elevation Points", "delimitedtext")
if not point_layer.isValid():
    raise RuntimeError(f"Could not load XYZ points layer {uri}")
QgsProject.instance().addMapLayer(point_layer)

# Input DEM
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
        'FIELD': 'value',
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
        "FIELD": "value",
        "OPERATOR": 0,            # 0 = "="
        "VALUE": 1,
        "OUTPUT": "work/steep_areas_value1.gpkg"
    }
)

QgsProject.instance().clear()

# Drop Python refs so providers/rasters are destroyed before QGIS shuts down
point_layer = None
dem_out = None
vl = None
binary_out = None

import gc
gc.collect()
qgs.exitQgis()
