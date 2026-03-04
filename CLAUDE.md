# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository creates custom Garmin GPS maps from OpenStreetMap data and Swiss terrain data, with specialized overlays for ski touring, avalanche-prone slopes (>30° incline), and rock features. The build process combines OSM data with high-resolution digital elevation models (DEM) to generate Garmin IMG map files.

## Build System Architecture

The project uses Make as the primary build orchestration tool. All major operations are defined in the Makefile with two distinct pipelines:

1. **OSM General Maps Pipeline** (lines 40-143): Downloads OSM data for European countries, splits into tiles, merges with contour data, and compiles to Garmin IMG format using custom styles
2. **Swiss Topo/Ski Maps Pipeline** (lines 144-316): Processes Swiss terrain data (SwissALTI3D DEMs and Swiss Vector25 rock data) to create specialized ski touring maps with slope analysis and terrain features

### Key External Tools

- **mkgmap** (Java): Converts OSM data to Garmin IMG format
- **splitter** (Java): Splits large OSM files into manageable tiles
- **osmosis** (Java): Filters and processes OSM PBF files
- **ogr2osm** (Python/Conda): Converts GeoPackage/vector data to OSM format (path configured via `OGR2OSM` variable in Makefile)
- **QGIS Python environment**: Provides GDAL/PROJ for geospatial operations

## Common Development Commands

### Building Maps

```bash
# Build all configured country maps (austria, germany, france, italy, liechtenstein, spain, switzerland)
make all

# Build a single country map
make out/osm-oa-switzerland.img

# Build all ski touring maps (ski network + slope30 + rock features)
make skitouring

# Build individual ski map components
make out/swiss-ski-network.img
make out/swiss-slope30.img
make out/swiss-rock.img
```

### Data Download and Setup

```bash
# Download Swiss terrain data (SwissALTI3D 2m resolution DEM tiles)
make download-swissalti3d

# Download Swiss vector data (includes rock features)
make download-swiss-vector25

# Download OSM data for a specific country (e.g., switzerland)
make in/switzerland-latest.osm.pbf

# Set up ogr2osm conda environment (one-time setup)
make setup
```

### Intermediate Targets

```bash
# Generate merged SwissALTI3D tiles (creates makefile rules dynamically)
make work/swissalti3d_merged_rules.mk

# Process slope30 data from merged terrain tiles
make slope30_osms

# Process rock features from Swiss Vector25 data
make rock_osms

# Split OSM data into tiles for a country
make work/switzerland/split
make work/switzerland/split-contour
```

### Cleaning

```bash
# Clean intermediate and output files (preserves downloaded data)
make clean

# Clean everything including downloaded data and tools
make cleanall
```

## Python Environment Configuration

The project uses two separate Python environments:

1. **QGIS Python** (configured in Makefile as `PYTHON3`, points to QGIS.app Python):
   - Used by `avi-terrain.py` and `merge_swissalti3d.py`
   - Provides GDAL 3.12.0, QGIS Processing framework, and geospatial tools
   - Environment setup is handled within each script via QGIS path configuration

2. **ogr2osm Conda Environment** (configured in Makefile as `OGR2OSM`):
   - Uses Python 3.11 with GDAL 3.6.4
   - Created via `make setup`
   - Used by `avi-terrain.py` for OSM conversion (passed via environment variable)

**Important**: The two GDAL versions are intentionally separate due to GeoPackage version compatibility. QGIS GDAL 3.12.0 creates GeoPackage v1.4.0 files that conda GDAL 3.6.4 cannot read directly. The `avi-terrain.py` script handles this by using ogr2ogr from the conda environment to convert GPKG to GeoJSON before passing to ogr2osm.

## Key Python Scripts

### avi-terrain.py (Avalanche Terrain Analysis)

Processes DEM rasters to identify and vectorize terrain features for ski touring maps.

**Modes**:
- `slope30`: Identifies slopes >30° (avalanche-prone terrain)
- `rock`: Vectorizes rock features from Swiss Vector25 data

**Pipeline**:
1. Compute slope from DEM using QGIS processing
2. Reclassify to binary (above/below threshold)
3. Sieve small polygons (minimum 30 pixels)
4. Polygonize to vector format
5. Simplify geometry (Douglas-Peucker)
6. Export to GeoJSON using ogr2ogr (from conda environment)
7. Convert to OSM via ogr2osm

**Environment Requirements**: The `OGR2OSM` environment variable must be set (handled automatically by Makefile pattern rules).

### merge_swissalti3d.py (Terrain Tile Merging)

Merges hundreds of 2m-resolution SwissALTI3D tiles into a manageable grid (default 8×4 = 32 mosaics) for processing.

**Dynamic Make Rule Generation**: Running with `--print-make-rules` generates makefile fragments that define dependencies for each merged tile, enabling parallel builds.

### find_nearby_peaks.py (Ski Route Enhancement)

Queries a PostgreSQL/PostGIS database to find nearby peaks for ski routes and adds peak names to the OSM data.

**Database Configuration**: Requires `db_config.py` with PostgreSQL credentials (not in repo).

## Map Styles

### my-style/ (General OSM Maps)

Custom mkgmap style for general outdoor/hiking maps. Contains standard OSM feature rendering rules:
- `points`: POI rendering (peaks, shelters, etc.)
- `lines`: Road, trail, and path rendering
- `polygons`: Area rendering (forests, water, buildings)
- `inc/`: Include files for access rules, name handling, contours

### topo-ski/ (Ski Touring Maps)

Specialized style for ski touring and avalanche terrain visualization:
- Renders ski routes with proper symbology
- Displays slope30 polygons (avalanche-prone terrain)
- Shows rock features and terrain hazards
- Includes custom TYP file (`topo-typ.txt`) for Garmin device styling

## Directory Structure

- `in/` → Downloaded source data (OSM PBF files, terrain tiles, ski routes) - symlink to `/Volumes/T9/mkgmap/in`
- `work/` → Intermediate processing files (split tiles, merged DEMs, vector data) - symlink to `/Volumes/T9/mkgmap/work`
- `out/` → Final Garmin IMG map files - symlink to `/Volumes/T9/mkgmap/out`
- `my-style/` → mkgmap style for general OSM maps
- `topo-ski/` → mkgmap style and config for ski touring maps
- `typ-files/` → Garmin TYP files for custom map styling
- `mkgmap-r4923/`, `splitter-r654/`, `osmosis-0.49.2/` → Java tool distributions

## Coordinate Reference Systems

- **OSM data**: WGS84 (EPSG:4326)
- **Swiss data**: CH1903+ / LV95 (EPSG:2056)
- **Transformations**: Handled automatically by QGIS/GDAL in processing scripts

## Country Code Mapping

The Makefile includes ISO 3166-1 country code mappings for middle European countries. When building maps:
- Map IDs are derived from country dial codes (e.g., Switzerland 0041 → map family 10041)
- Country names are converted to ISO3 codes for mkgmap parameters

## Makefile Pattern Rules

The Makefile uses advanced GNU Make features:
- Pattern rules with `%.defined` for country code validation
- Dynamic rule generation via `-include $(SWISSALTI3D_MERGED_RULES_MK)`
- Parallel execution with `ProcessPoolExecutor` in Python scripts
- `.PRECIOUS` and `.SECONDARY` to preserve intermediate files

## Java Tool Memory Configuration

mkgmap is invoked with substantial heap allocation for large maps:
```bash
java -Xms5g -Xmx16g -XX:+UseParallelGC -jar mkgmap.jar ...
```

Adjust these values if building fails with OutOfMemoryError or if working on a system with different RAM constraints.

## Data Sources

- **OSM Data**: Geofabrik Europe extracts (https://download.geofabrik.de/europe/)
- **Contour Lines**: Freizeitkarte contour data (http://develop.freizeitkarte-osm.de/ele_20_100_500/)
- **SwissALTI3D**: Swiss Federal Office of Topography (2m resolution DEM)
- **Swiss Vector25**: Swiss topographic vector data (rock features)
- **Ski Routes**: Swiss Topo ski touring data (data.geo.admin.ch)

## Deployment

Compiled maps can be copied directly to a Garmin device:
```bash
# Copy to mounted Garmin device
make /Volumes/GARMIN/Garmin/swiss-ski-network.img
```

The Makefile includes a pattern rule for copying `out/*.img` to `/Volumes/GARMIN/Garmin/*.img`.

## Troubleshooting

### Corrupted GeoPackage Files

If you encounter "malformed database schema" errors when processing terrain data, the intermediate GPKG file is likely corrupted. Delete the corrupted `.gpkg` file and re-run the make command to regenerate it.

### Sound Notifications

For audio feedback when long-running tasks complete (useful on macOS):
```bash
make slope30_osms; afplay /System/Library/Sounds/Glass.aiff
```

Claude Code can also play sounds directly using the Bash tool:
```bash
afplay /System/Library/Sounds/Glass.aiff
```
