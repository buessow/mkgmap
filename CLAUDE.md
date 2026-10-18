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

# Build the routable Swiss topo basemap from swiss-map-vector25
make swisstopo            # -> out/swiss-topo.img
make work/swiss-topo/inventory.tsv   # Vector25 category counts (reference)
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

### Swiss Topo Basemap (`make swisstopo` -> `out/swiss-topo.img`)

A routable basemap for Garmin watches built from swisstopo data instead of OSM. Sources:

| Content | Source | Script |
|---|---|---|
| Roads, paths, railways, lifts, water, buildings, names, POIs, contours | swiss-map-vector25 (2024), 58 sheets | `vector25_to_osm.py` |
| Rock, sparse rock, boulders, scree, glaciers, snowfields | swissTLM3D land cover (`tlm_bb_bodenbedeckung`, revised 2019-2025) | `tlm_landcover.py` |
| Glacier names | OSM `natural=glacier` + Swiss Glacier Inventory 2016 (GLAMOS), largest overlap | `tlm_landcover.py` |
| Contours on and next to glaciers (Vector25 has none on ice) | swissALTI3D | `glacier_contours.py` |
| Crevasses | Vector25 raster `glet.tif` | `vector25_crevasses.py` |
| Train stations (Vector25 has none) | swissTLM3D `tlm_oev_haltestelle`, names without a comma (tram stops are "Town, Stop") | Makefile `stations.gpkg` rule |

`vector25_to_osm.py` runs in the conda ogr2osm Python (`CONDA_PYTHON`) and streams OSM XML into `osmium cat` (ogr2osm cannot hold the national data in memory). It maps Vector25 attributes to OSM-style tags (its own mapping, no OSM road data): `OBJEKTART` (width/way type), `BEDEUTUNG` (Durchgangsstrasse -> primary, Verbindungsstrasse -> secondary), `WANDERWEG` (`sac_scale`), `KUNSTBAUTE` (tunnel, bridge, steps), `BELAGSART` (paved/unpaved), `BEFAHRBAR`.

- `net`: roads, paths, railways, lifts of all sheets in one file; nodes shared by coordinate so routing works across sheet edges.
- `feat`: everything else. Watercourse lines are split at river/lake areas: outside they stay lines, inside only a label-only line keeps the name (Vector25, like OSM, has wide rivers as area and centre line).
- `contour`: one file per sheet; `contour_surface=rock|scree` from `OBERFLAECH`.
- `areas`: GeoPackages from the other scripts (rock, scree, glacier, glacier-contour, crevasse, station).

Sheets overlap: features crossing a sheet edge are repeated in the neighbour sheet and skipped by `DKM_UUID` if already read from another sheet. Within one sheet a `DKM_UUID` can span several rows (pieces of one way), which must all be kept. Each output file has a disjoint OSM ID range (Makefile comment); splitter reads the inputs as one stream, so they are listed in ascending ID order.

`vector25_raster_areas.py` (rock/scree areas from the Vector25 hachure and dot rasters) and `vector25_inventory.py` (category counts, `make work/swiss-topo/inventory.tsv`) are no longer part of the build but kept for reference.

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

### swiss-topo/ (Swiss Topo Basemap)

Style and TYP for the tags emitted by `vector25_to_osm.py`, modelled on the swisstopo national map legend and tuned for the Fenix 7 (MIP display, 64 colours: channels 00/55/AA/FF). Family ID 30005, map IDs 3005xxxx; the build date is in the map description (shown in the watch's map info).

Findings from testing on the Fenix 7:
- The watch ignores the TYP for **extended area types** (0x1xxxx) and draws its own defaults (e.g. "Ferry"), so all areas use standard types; free codes 0x54-0x5a hold rock, scree, boulders, snowfield, escarpment. Extended line types work.
- **Display-only overlay lines** are drawn under routable roads, so tunnels use their own routable types (0x08 major, 0x0c minor) with the road's `road_class`/`road_speed`. Bridge casings (0x10e16) on paths/tracks work because the casing is wider than the way.
- Only **lines and city-type points** (0x0100-0x1100) get their names printed; other POIs show the name on tap only.
- Line patterns may only use **two colours** (incl. transparent); more makes the TYP compile fail (mkgmap exits at the end without a clear message; test with `java -jar mkgmap.jar --family-id=30005 swiss-topo/swiss-topo-typ.txt`).
- Labels of standard contour types 0x20-0x22 are treated as feet (`conv:m=>ft`); minor contours have no label (with a label, tapping lists every line separately).
- mkgmap drops small areas except at res 24 (`min-size-polygon`); houses and escarpments use `mkgmap:skipSizeFilter`.
- Activity profiles have their own map settings (stored in `GARMIN/Sports/*.fit`, field 29 of message 70 = map theme, e.g. `Resort_Ski`); a theme overrides TYP colours.

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

The swiss-topo build uses `SWISS_TOPO_JAVA` (`-Xmx6g`) and `max-jobs=3` in `swiss-topo/topo.cfg`: with a 16 GB heap and one job per core it swapped a 24 GB Mac into a crash. Run long builds with `caffeinate -s make swisstopo` on AC power; the Mac otherwise sleeps mid-build.

## Data Sources

- **OSM Data**: Geofabrik Europe extracts (https://download.geofabrik.de/europe/)
- **Contour Lines**: Freizeitkarte contour data (http://develop.freizeitkarte-osm.de/ele_20_100_500/)
- **SwissALTI3D**: Swiss Federal Office of Topography (2m resolution DEM)
- **Swiss Vector25**: swiss-map-vector25 2024 (roads, paths, water, names, POIs, contours; rock rasters for the ski overlay)
- **swissTLM3D**: swisstopo landscape model 2026-02 (land cover, stations): https://data.geo.admin.ch/ch.swisstopo.swisstlm3d/
- **Swiss Glacier Inventory 2016**: GLAMOS (glacier names): https://doi.glamos.ch/data/inventory/inventory_sgi2016_r2020.zip
- **Ski Routes**: Swiss Topo ski touring data (data.geo.admin.ch)

## Deployment

Compiled maps can be copied directly to a Garmin device:
```bash
# Copy to mounted Garmin device
make /Volumes/GARMIN/Garmin/swiss-ski-network.img
```

The Makefile includes a pattern rule for copying `out/*.img` to `/Volumes/GARMIN/Garmin/*.img`. The Fenix 7 connects over MTP rather than as a disk, so copy maps with an MTP tool (e.g. OpenMTP) into `GARMIN/` on the watch, deleting the old copy first. For BaseCamp on the Mac, the swiss-topo and ski maps also build `.gmap` bundles (`gmapi`), symlinked into `~/Library/Application Support/Garmin/Maps/`.

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
