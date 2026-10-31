IN_DIR = in
WORK_DIR = work
OUT_DIR = out
STYLE_DIR = my-style
STYLE_FILES = $(wildcard $(STYLE_DIR)/*)
TYP_FILES = typ-files/20011.txt typ-files/sameOrder.txt
ROOT_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OGR2OSM = /opt/homebrew/Caskroom/miniforge/base/envs/ogr2osm/bin/ogr2osm

QGIS_DIR = /Volumes/T9/Applications/QGIS.app/Contents
PYTHON3 = $(QGIS_DIR)/MacOS/python
GDALWARP = $(QGIS_DIR)/MacOS/gdalwarp
GDALBUILDVRT = $(QGIS_DIR)/MacOS/gdalbuildvrt

OSMOSIS_VERSION = 0.49.2
OSMOSIS = osmosis-$(OSMOSIS_VERSION)
SPLITTER = splitter-r654
MKGMAP = mkgmap-r4923

# Precompiled sea tiles for mkgmap --precomp-sea (replaces generate-sea coastline
# reconstruction, which floods inland tiles near clipped Geofabrik extract edges).
SEA_ZIP = $(IN_DIR)/sea-latest.zip

# ISO 3166-1 alpha-3 country codes for middle Europe
COUNTRY_CODES = \
	austria:AUT:0043 \
	belgium:BEL:0032 \
	czechia:CZE:0420 \
	germany:DEU:0049 \
	france:FRA:0033 \
	italy:ITA:0039 \
	hungary:HUN:0036 \
	liechtenstein:LIE:0423 \
	luxembourg:LUX:0352 \
	netherlands:NLD:0031 \
	poland:POL:0048 \
	portugal:PRT:0035 \
	romania:ROU:0040 \
	slovakia:SVK:0421 \
	slovenia:SVN:0386 \
	spain:ESP:0034 \
	switzerland:CHE:0041

COUNTRIES = austria germany france italy liechtenstein poland spain switzerland

# Convert country name to ISO code
country_to_iso = $(word 2,$(subst :, ,$(filter $(1):%,$(COUNTRY_CODES))))

# Convert ISO code to country name
iso_to_country = $(word 1,$(subst :, ,$(filter %:$(1),$(COUNTRY_CODES))))

%.defined:
	country=$(basename $@ .foo); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	if [ -z "$$country3" ]; then echo "Error: No ISO code found for country '$$country'." >&2; exit 1; fi; \
	echo $$country3


$(IN_DIR)/$(OSMOSIS).tar:
	wget --directory-prefix=$(IN_DIR) https://github.com/openstreetmap/osmosis/releases/download/$(OSMOSIS_VERSION)/$(OSMOSIS).tar

$(OSMOSIS): $(IN_DIR)/$(OSMOSIS).tar
	tar xf $(IN_DIR)/$(OSMOSIS).tar

$(IN_DIR)/$(SPLITTER).tar.gz:
	wget --directory-prefix=$(IN_DIR) https://www.mkgmap.org.uk/download/$(SPLITTER).tar.gz

$(SPLITTER)/splitter.jar: $(IN_DIR)/$(SPLITTER).tar.gz
	tar xzf $(IN_DIR)/$(SPLITTER).tar.gz
	touch $(SPLITTER)/splitter.jar

$(IN_DIR)/$(MKGMAP).tar.gz:
	wget --directory-prefix=$(IN_DIR) https://www.mkgmap.org.uk/download/$(MKGMAP).tar.gz

$(MKGMAP)/mkgmap.jar: $(IN_DIR)/$(MKGMAP).tar.gz
	tar xzf $(IN_DIR)/$(MKGMAP).tar.gz
	touch $(MKGMAP)/mkgmap.jar

$(IN_DIR)/%-latest.osm.pbf:
	rm -f $@
	wget --directory-prefix=$(IN_DIR) https://download.geofabrik.de/europe/$(notdir $@)

$(SEA_ZIP):
	wget --directory-prefix=$(IN_DIR) https://www.thkukuk.de/osm/data/sea-latest.zip

$(WORK_DIR)/%-contour.osm.pbf: %.defined
	@country=$$(basename $@ -contour.osm.pbf); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	$(MAKE) $(IN_DIR)/Hoehendaten_Freizeitkarte_$$country3.osm.pbf; \
	cp $(IN_DIR)/Hoehendaten_Freizeitkarte_$$country3.osm.pbf $@

$(IN_DIR)/Hoehendaten_Freizeitkarte_%.osm.pbf:
	wget --directory-prefix=$(IN_DIR) http://develop.freizeitkarte-osm.de/ele_20_100_500/$(notdir $@)

# Unused
$(WORK_DIR)/%-filtered.osm.pbf: $(IN_DIR)/%-latest.osm.pbf osmosis.args
	@cmd="sed s=INPUT=$<=g osmosis.args | xargs -J % $(OSMOSIS)/bin/osmosis % --write-pbf $@"; \
	echo $cmd; \
	$cmd

# Map IDs: <type><4-digit dial code><3-digit tile>, type 5=overview, 6=tiles,
# 7=contour tiles. Each country gets its own 1000-ID range; IDs must be unique
# across all maps on the device or tiles with the same ID hide each other.
#$(WORK_DIR)/%/split: $(WORK_DIR)/%-filtered.osm.pbf $(SPLITTER) Makefile
$(WORK_DIR)/%/split: $(IN_DIR)/%-latest.osm.pbf $(SPLITTER)/splitter.jar %.defined
	@country=$$(basename $$(dirname $@) | sed 's/osm-oa-//'); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	dialcode=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:...:\(....\)/\1/p"); \
	id="6$${dialcode}000"; \
	cmd="java -jar $(SPLITTER)/splitter.jar --mapid=$$id --output-dir=$(dir $@) $<"; \
	echo "$$cmd"; \
	$$cmd
	touch $(dir $@)split

$(WORK_DIR)/%/split-contour: $(WORK_DIR)/%-contour.osm.pbf $(WORK_DIR)/%/split $(SPLITTER)/splitter.jar %.defined
	@country=$$(basename $$(dirname $@) | sed 's/osm-oa-//'); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	sed -E 's/^6([0-9]{7}):/7\1:/' $(dir $@)areas.list > $(dir $@)areas-contour.list; \
	cmd="java -jar $(SPLITTER)/splitter.jar --split-file=$(dir $@)areas-contour.list --output-dir=$(dir $@)/contour $<"; \
	echo "$$cmd"; \
	$$cmd
	touch $(dir $@)/split-contour

$(OUT_DIR)/osm-oa-%.img: $(WORK_DIR)/%/split $(WORK_DIR)/%/split-contour my.cfg $(MKGMAP)/mkgmap.jar $(STYLE_FILES) $(TYP_FILES) $(SEA_ZIP) %.defined
	@mkdir -p $(OUT_DIR); \
	country=$$(basename $@ .img | sed 's/osm-oa-//'); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	dialcode=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:...:\(....\)/\1/p"); \
	id="5$${dialcode}000"; \
	fid=1$$dialcode; \
	cmd="cd $(WORK_DIR)/$$country; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/$(STYLE_DIR) \
			--read-config=$(ROOT_DIR)/my.cfg \
			--precomp-sea=$(ROOT_DIR)/$(SEA_ZIP) \
			--mapname=$$id \
			--country-name=$$country \
			--country-abbr=$$country3 \
			--family-id=$$fid \
			--family-name=OSM\ Outabout \
			--description=Outabout\ OSM\ $$country \
			--area-name=RB_A_OSM_$$country \
			--series-name=RB_S_OSM_$$country \
			--overview-mapname=RB_O_OSM_$$country \
			--overview-mapnumber=$$id \
			--read-config=template.args \
			--read-config=contour/template.args \
			$(patsubst %,$(ROOT_DIR)/%,$(TYP_FILES)) \
			"; \
	echo "($$cmd)"; \
	bash -c "$$cmd"; \
	mv $(WORK_DIR)/$$country/gmapsupp.img $(OUT_DIR)/osm-oa-$$country.img

# TOPO / SKITOURING

setup:
	conda create -n ogr2osm -c conda-forge python=3.11 "gdal=3.6.4=*_11"
	conda activate ogr2osm
	python -m pip install --upgrade pip
	python -m pip install ogr2osm
	which python
	python -c "from osgeo import gdal; print(gdal.__version__)"
	ogr2osm -h

SWISSALTI3D_RAW_DIR = in/swiss-alti3d-raw
SWISSALTI3D_MERGED_DIR = work/swiss-alti3d
SWISSALTI3D_MERGED_RULES_MK = $(WORK_DIR)/swissalti3d_merged_rules.mk
-include $(SWISSALTI3D_MERGED_RULES_MK)

SWISS_VECTOR25_RAW_DIR = in/swiss-vector25-raw
SWISS_VECTOR25_1_DIR = work/swiss-vector25

$(SWISSALTI3D_RAW_DIR):
	mkdir -p $@

download-swissalti3d: swiss-alti3d-2m_urls.txt | $(SWISSALTI3D_RAW_DIR)
	@total=$$(wc -l < $< | tr -d ' '); \
	cat -n $< | xargs -n 2 -P 50 sh -c 'file="$(SWISSALTI3D_RAW_DIR)/$$(basename $$2)"; if [ ! -e "$$file" ]; then echo "Downloading [$$1/'"$$total"'] $$(basename $$2)"; wget -q --directory-prefix=$(SWISSALTI3D_RAW_DIR) --no-clobber $$2; fi' sh

download-swiss-vector25: swiss-vector25_urls.txt | $(SWISS_VECTOR25_RAW_DIR)
	@total=$$(wc -l < $< | tr -d ' '); \
	cat -n $< | xargs -n 2 -P 50 sh -c 'file="$(SWISS_VECTOR25_RAW_DIR)/$$(basename $$2)"; if [ ! -e "$$file" ]; then echo "Downloading [$$1/'"$$total"'] $$(basename $$2)"; wget -q --directory-prefix=$(SWISS_VECTOR25_RAW_DIR) --no-clobber $$2; fi' sh

SWISS_VECTOR24_GPKGPS=$(patsubst $(SWISS_VECTOR25_RAW_DIR)/swiss-map-vector25_2024_%_2056.gpkg.zip,$(SWISS_VECTOR25_1_DIR)/%/SMV25_CHLV95LN02.gpkg,$(wildcard $(SWISS_VECTOR25_RAW_DIR)/*.zip))
$(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02.gpkg: $(SWISS_VECTOR25_RAW_DIR)/swiss-map-vector25_2024_%_2056.gpkg.zip
	@mkdir -p $(SWISS_VECTOR25_1_DIR)
	unzip -u -LL $< -d $(SWISS_VECTOR25_1_DIR) || [ $$? -eq 1 ] # unzip returns 1 on warnings (due to filesep)
	touch $@ # unzip keeps the archive timestamps

swiss-vector25-gpkps: $(SWISS_VECTOR24_GPKGPS)

$(SWISSALTI3D_MERGED_RULES_MK): merge_swissalti3d.py download-swissalti3d
	@mkdir -p $(dir $@)
	@$(PYTHON3) merge_swissalti3d.py $(SWISSALTI3D_RAW_DIR) $(SWISSALTI3D_MERGED_DIR) --print-make-rules > $@

swissalti3d-merged: $(SWISSALTI3D_MERGED_FILES)

$(IN_DIR)/skitouren_2056.gpkg.zip:
	wget --directory-prefix=$(IN_DIR) https://data.geo.admin.ch/ch.swisstopo-karto.skitouren/skitouren/skitouren_2056.gpkg.zip

SWISS_SLOPE30_OSMS = $(patsubst %.tif,%.osm,$(SWISSALTI3D_MERGED_FILES))
%_alti3d.osm: %_alti3d.tif
	OGR2OSM=$(OGR2OSM) $(PYTHON3) avi-terrain.py slope30 $< $@
print_slope30_osms:
	@echo $(SWISS_SLOPE30_OSMS)
slope30_osms: $(SWISS_SLOPE30_OSMS)

#SWISS_ROCK_OSMS = $(patsubst $(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/fels.tif,work/swiss-rock/rock_%.osm,$(wildcard $(SWISS_VECTOR25_1_DIR)/*/SMV25_CHLV95LN02_RASTER/FELS.tif))
SWISS_ROCK_OSMS = $(patsubst $(SWISS_VECTOR25_RAW_DIR)/swiss-map-vector25_2024_%_2056.gpkg.zip,work/swiss-rock/rock_%.osm,$(wildcard $(SWISS_VECTOR25_RAW_DIR)/*.zip))
$(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/fels.tif: $(SWISS_VECTOR25_RAW_DIR)/swiss-map-vector25_2024_%_2056.gpkg.zip
	@mkdir -p $(dir $@)
	unzip -u -LL $< -d $(SWISS_VECTOR25_1_DIR) || [ $$? -eq 1 ] # unzip returns 1 on warnings (due to filesep)
	touch $@ # unzip keeps the archive timestamps

work/swiss-rock/rock_%.tif: $(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/fels.tif
	@mkdir -p $(dir $@)
	cp $< $@

work/swiss-rock/rock_%.osm: work/swiss-rock/rock_%.tif
	OGR2OSM=$(OGR2OSM) $(PYTHON3) avi-terrain.py rock $< $@

print_rock_osms:
	@echo $(SWISS_ROCK_OSMS)

rock_osms: $(SWISS_ROCK_OSMS)


$(WORK_DIR)/swiss-skitouring/ski_network_2056.gpkg: $(IN_DIR)/skitouren_2056.gpkg.zip
	@mkdir -p $(WORK_DIR)/swiss-skitouring
	unzip -u $(IN_DIR)/skitouren_2056.gpkg.zip -d $(WORK_DIR)/swiss-skitouring

$(WORK_DIR)/swiss-skitouring/ski_network_2056.osm: $(WORK_DIR)/swiss-skitouring/ski_network_2056.gpkg
	$(OGR2OSM) --id=-2000000000 --positive-id -f -o $@ $<

$(WORK_DIR)/swiss-skitouring/ski_network_2056_updated.osm: $(WORK_DIR)/swiss-skitouring/ski_network_2056.osm find_nearby_peaks.py db_config.py
	$(PYTHON3) find_nearby_peaks.py --osm-file $< --output-osm-file $@

$(OUT_DIR)/swiss-ski-network.img: $(WORK_DIR)/swiss-skitouring/ski_network_2056_updated.osm topo-ski/topo.cfg topo-ski/topo-typ.txt $(wildcard topo-ski/style/*)
	@mkdir -p $(OUT_DIR)
	@mkdir -p $(WORK_DIR)/swiss-skitouring
	@cmd="cd $(WORK_DIR)/swiss-skitouring; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties \
		    -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/topo-ski/style \
			--read-config=$(ROOT_DIR)/topo-ski/topo.cfg \
			--draw-priority=10 \
			--mapname=30001001 \
			--family-id=30001 \
			--family-name=Outabout\ Ski\ Network \
			--series-name=RB_S_OUTABOUT_SKI_NETWORK \
			--area-name=RB_A_OUTABOUT_SKI_NETWORK \
			--description=Outabout\ Swiss\ Ski\ Network \
			--overview-mapname=RB_OUTABOUT_SKI_NETWORK \
			--overview-mapnumber=30001001 \
			ski_network_2056_updated.osm \
			$(ROOT_DIR)/topo-ski/topo-typ.txt \
			"; \
	cmd=$$(echo $$cmd | sed 's/  */ /g'); \
	echo "($$cmd)"; \
	bash -c "$$cmd"; \
	mv $(WORK_DIR)/swiss-skitouring/gmapsupp.img $(OUT_DIR)/swiss-ski-network.img

$(WORK_DIR)/swiss-skitouring/swiss-slope30.args: $(SWISS_SLOPE30_OSMS)
	rm -f $@
	@id=30003000; \
	list='$^'; \
	if [ -n "$$list" ]; then \
		for file in $$list; do \
			echo "mapname: $$id" >> $@; \
			echo "input-file: $(ROOT_DIR)/$$file" >> $@; \
			id=$$((id+1)); \
		done; \
	fi

$(OUT_DIR)/swiss-slope30.img: $(WORK_DIR)/swiss-skitouring/swiss-slope30.args topo-ski/topo.cfg topo-ski/topo-typ.txt $(wildcard topo-ski/style/*)
	@mkdir -p $(OUT_DIR)
	@mkdir -p $(WORK_DIR)/swiss-skitouring
	@cmd="cd $(WORK_DIR)/swiss-skitouring; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties \
		    -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/topo-ski/style \
			--read-config=$(ROOT_DIR)/topo-ski/topo.cfg \
			--family-id=30003 \
			--family-name=Outabout\ Slope30 \
			--series-name=RB_S_OUTABOUT_SKI_SLOPE30 \
			--area-name=RB_A_OUTABOUT_SKI_SLOPE30 \
			--description=Outabout\ Swiss\ Slope30 \
			--overview-mapname=RB_OUTABOUT_SKI_SLOPE30 \
			--overview-mapnumber=30001003 \
			--read-config=$(ROOT_DIR)/$(WORK_DIR)/swiss-skitouring/swiss-slope30.args \
			$(ROOT_DIR)/topo-ski/topo-typ.txt \
			"; \
	cmd=$$(echo $$cmd | sed 's/  */ /g'); \
	echo "($$cmd)"; \
	bash -c "$$cmd"; \
	mv $(WORK_DIR)/swiss-skitouring/gmapsupp.img $@

$(WORK_DIR)/swiss-rock/swiss-rock.args: $(SWISS_ROCK_OSMS)
	rm -f $@
	@id=30004000; \
	echo "LL $^"; \
	list='$^'; \
	if [ -n "$$list" ]; then \
		for file in $$list; do \
			echo "mapname: $$id" >> $@; \
			echo "input-file: $(ROOT_DIR)/$$file" >> $@; \
			id=$$((id+2)); \
		done; \
	fi

$(OUT_DIR)/swiss-rock.img: $(WORK_DIR)/swiss-rock/swiss-rock.args topo-ski/topo.cfg topo-ski/topo-typ.txt $(wildcard topo-ski/style/*)
	@mkdir -p $(OUT_DIR)
	@mkdir -p $(WORK_DIR)/swiss-rock
	@cmd="cd $(WORK_DIR)/swiss-rock; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties \
		    -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/topo-ski/style \
			--read-config=$(ROOT_DIR)/topo-ski/topo.cfg \
			--family-id=30004 \
			--family-name=Outabout\ Rock \
			--series-name=RB_S_OUTABOUT_SKI_ROCK \
			--area-name=RB_A_OUTABOUT_SKI_ROCK \
			--description=Outabout\ Swiss\ Rock \
			--overview-mapname=RB_OUTABOUT_SKI_ROCK \
			--overview-mapnumber=30001004 \
			--read-config=$(ROOT_DIR)/$(WORK_DIR)/swiss-rock/swiss-rock.args \
			$(ROOT_DIR)/topo-ski/topo-typ.txt \
			"; \
	cmd=$$(echo $$cmd | sed 's/  */ /g'); \
	echo "($$cmd)"; \
	bash -c "$$cmd"; \
	mv $(WORK_DIR)/swiss-rock/gmapsupp.img $@


skitouring: $(OUT_DIR)/swiss-ski-network.img $(OUT_DIR)/swiss-slope30.img $(OUT_DIR)/swiss-rock.img

# SWISS TOPO BASEMAP (swiss-map-vector25)
#
# Routable topo basemap built from swiss-map-vector25 instead of OSM. The
# conversion scripts run in the conda ogr2osm env (GDAL 3.6 + numpy) and
# write PBF through the osmium CLI. Unzipped sheets are order-only
# prerequisites: unzip keeps the archive timestamps, and the 2024 edition
# does not change.
# OSM ID ranges per input file must not overlap (splitter merges them):
#   net 1e9, feat 2e9, contour 100e9 + sheet * 1e8, rock 300e9, scree 310e9 (swissTLM3D),
#   glacier 400e9, glacier-contour 410e9, crevasse 420e9, station 430e9.
# Map IDs: 3005xxxx (overview 30050000, tiles from 30050001).

CONDA_PYTHON = $(dir $(OGR2OSM))python
SWISS_TOPO_DIR = $(WORK_DIR)/swiss-topo
# Sized for a 24 GB machine: ~2 GB per parallel tile (max-jobs=3 in topo.cfg)
# plus the gmapsupp index. A 16 GB heap made the machine swap itself to death.
SWISS_TOPO_JAVA = java -Xms1g -Xmx6g -XX:+UseParallelGC
SWISS_TOPO_STYLE_FILES = $(wildcard swiss-topo/style/*) swiss-topo/topo.cfg swiss-topo/swiss-topo-typ.txt
SWISS_VECTOR25_SHEETS = $(patsubst $(SWISS_VECTOR25_RAW_DIR)/swiss-map-vector25_2024_%_2056.gpkg.zip,%,$(wildcard $(SWISS_VECTOR25_RAW_DIR)/*.zip))
SWISS_VECTOR25_GPKGS = $(foreach s,$(SWISS_VECTOR25_SHEETS),$(SWISS_VECTOR25_1_DIR)/$(s)/smv25_chlv95ln02.gpkg)
SWISS_TOPO_ROCK_GPKGS = $(foreach s,$(SWISS_VECTOR25_SHEETS),$(SWISS_TOPO_DIR)/areas/rock_$(s).gpkg)
SWISS_TOPO_SCREE_GPKGS = $(foreach s,$(SWISS_VECTOR25_SHEETS),$(SWISS_TOPO_DIR)/areas/scree_$(s).gpkg)
SWISS_TOPO_CREVASSE_GPKGS = $(foreach s,$(SWISS_VECTOR25_SHEETS),$(SWISS_TOPO_DIR)/crevasses/crevasse_$(s).gpkg)

$(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/geroell.tif: $(SWISS_VECTOR25_RAW_DIR)/swiss-map-vector25_2024_%_2056.gpkg.zip
	@mkdir -p $(dir $@)
	unzip -u -LL $< -d $(SWISS_VECTOR25_1_DIR) || [ $$? -eq 1 ] # unzip returns 1 on warnings (due to filesep)
	touch $@ # unzip keeps the archive timestamps

$(SWISS_TOPO_DIR)/inventory.tsv: vector25_inventory.py | $(SWISS_VECTOR25_GPKGS)
	@mkdir -p $(dir $@)
	python3 -I vector25_inventory.py $(SWISS_VECTOR25_1_DIR) $@

$(SWISS_TOPO_DIR)/net.osm.pbf: vector25_to_osm.py | $(SWISS_VECTOR25_GPKGS)
	@mkdir -p $(dir $@)
	$(CONDA_PYTHON) vector25_to_osm.py net $(SWISS_VECTOR25_1_DIR) $@

$(SWISS_TOPO_DIR)/feat.osm.pbf: vector25_to_osm.py | $(SWISS_VECTOR25_GPKGS)
	@mkdir -p $(dir $@)
	$(CONDA_PYTHON) vector25_to_osm.py feat $(SWISS_VECTOR25_1_DIR) $@

# One process for all sheets so contours on sheet edges are deduplicated.
$(SWISS_TOPO_DIR)/contour/done: vector25_to_osm.py | $(SWISS_VECTOR25_GPKGS)
	$(CONDA_PYTHON) vector25_to_osm.py contour $(SWISS_VECTOR25_1_DIR) $(dir $@)
	touch $@

$(SWISS_TOPO_DIR)/areas/rock_%.gpkg: vector25_raster_areas.py | $(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/fels.tif
	@mkdir -p $(dir $@)
	$(CONDA_PYTHON) vector25_raster_areas.py $| $@

$(SWISS_TOPO_DIR)/areas/scree_%.gpkg: vector25_raster_areas.py | $(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/geroell.tif
	@mkdir -p $(dir $@)
	$(CONDA_PYTHON) vector25_raster_areas.py $| $@

$(SWISS_TOPO_DIR)/rock.osm.pbf: $(SWISS_TOPO_DIR)/glaciers.gpkg vector25_to_osm.py
	$(CONDA_PYTHON) vector25_to_osm.py areas rock $@ $(SWISS_TOPO_DIR)/tlm-rock.gpkg --id-base 300000000000

$(SWISS_TOPO_DIR)/scree.osm.pbf: $(SWISS_TOPO_DIR)/glaciers.gpkg vector25_to_osm.py
	$(CONDA_PYTHON) vector25_to_osm.py areas scree $@ $(SWISS_TOPO_DIR)/tlm-scree.gpkg --id-base 310000000000

# Glaciers: Vector25 has no ice outlines (only name areas and a crevasse drawing), so the areas
# come from OSM, contours on the ice from swissALTI3D, and crevasses from glet.tif.
$(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/glet.tif: $(SWISS_VECTOR25_RAW_DIR)/swiss-map-vector25_2024_%_2056.gpkg.zip
	@mkdir -p $(dir $@)
	unzip -u -LL $< -d $(SWISS_VECTOR25_1_DIR) || [ $$? -eq 1 ] # unzip returns 1 on warnings (due to filesep)
	touch $@ # unzip keeps the archive timestamps

# Swiss Glacier Inventory 2016 (GLAMOS): official outlines incl. high firn that OSM often
# leaves out (e.g. below the Jungfrau). Glacier areas are OSM plus SGI.
SGI_ZIP = $(IN_DIR)/sgi2016/inventory_sgi2016_r2020.zip
SGI_SHP = $(WORK_DIR)/sgi2016/SGI_2016_glaciers.shp

$(SGI_ZIP):
	@mkdir -p $(dir $@)
	wget -O $@ https://doi.glamos.ch/data/inventory/inventory_sgi2016_r2020.zip

$(SGI_SHP): $(SGI_ZIP)
	@mkdir -p $(dir $@)
	unzip -o -q $< -d $(dir $@)
	touch $@ # unzip keeps the archive timestamps

# Named glacier outlines from OSM and SGI; only used to name the swissTLM3D ice areas.
$(SWISS_TOPO_DIR)/glacier-names.gpkg: $(IN_DIR)/switzerland-latest.osm.pbf $(SGI_SHP)
	@mkdir -p $(dir $@)
	osmium tags-filter --overwrite -o $(SWISS_TOPO_DIR)/glaciers-osm.osm.pbf $< nwr/natural=glacier
	rm -f $@
	$(dir $(OGR2OSM))ogr2ogr -f GPKG -t_srs EPSG:2056 -nln glaciers -nlt MULTIPOLYGON \
		-where "natural='glacier'" $@ $(SWISS_TOPO_DIR)/glaciers-osm.osm.pbf multipolygons
	$(dir $(OGR2OSM))ogr2ogr -f GPKG -append -t_srs EPSG:2056 -nln glaciers -nlt MULTIPOLYGON \
		-sql "SELECT name FROM SGI_2016_glaciers" $@ $(SGI_SHP)

# swissTLM3D (swisstopo landscape model, revised yearly): rock, scree, glacier and snowfield
# areas from one survey. tlm_landcover.py writes all three GeoPackages in one run.
TLM_ZIP = $(IN_DIR)/swisstlm3d/swisstlm3d_2026-02_2056_5728.gpkg.zip
TLM_GPKG = $(WORK_DIR)/swisstlm3d/SWISSTLM3D_2026_LV95_LN02.gpkg

$(TLM_ZIP):
	@mkdir -p $(dir $@)
	wget -O $@ https://data.geo.admin.ch/ch.swisstopo.swisstlm3d/swisstlm3d_2026-02/swisstlm3d_2026-02_2056_5728.gpkg.zip

$(TLM_GPKG): $(TLM_ZIP)
	@mkdir -p $(dir $@)
	unzip -o -q $< -d $(dir $@)
	touch $@ # unzip keeps the archive timestamps

$(SWISS_TOPO_DIR)/glaciers.gpkg: $(TLM_GPKG) $(SWISS_TOPO_DIR)/glacier-names.gpkg tlm_landcover.py
	$(CONDA_PYTHON) tlm_landcover.py $(TLM_GPKG) $(SWISS_TOPO_DIR)/glacier-names.gpkg \
		$(SWISS_TOPO_DIR)/tlm-rock.gpkg $(SWISS_TOPO_DIR)/tlm-scree.gpkg $@

# Train stations (Vector25 has none): swissTLM3D rail stops, one point per name. Tram stops are
# named "Town, Stop", train stations "Town Station", so names with a comma are left out.
$(SWISS_TOPO_DIR)/stations.gpkg: $(TLM_GPKG)
	rm -f $@
	$(dir $(OGR2OSM))ogr2ogr -f GPKG -dim XY -nln stations -nlt POINT -dialect SQLITE \
		-sql "SELECT name, ST_Centroid(ST_Collect(geom)) AS geom FROM tlm_oev_haltestelle WHERE objektart = 'Haltestelle Bahn' AND name NOT LIKE '%,%' GROUP BY name" \
		$@ $(TLM_GPKG)

$(SWISS_TOPO_DIR)/station.osm.pbf: $(SWISS_TOPO_DIR)/stations.gpkg vector25_to_osm.py
	$(CONDA_PYTHON) vector25_to_osm.py areas station $@ $< --id-base 430000000000

$(SWISS_TOPO_DIR)/glacier.osm.pbf: $(SWISS_TOPO_DIR)/glaciers.gpkg vector25_to_osm.py
	$(CONDA_PYTHON) vector25_to_osm.py areas glacier $@ $< --id-base 400000000000

$(SWISS_TOPO_DIR)/glacier-contours.gpkg: $(SWISS_TOPO_DIR)/glaciers.gpkg glacier_contours.py | $(SWISSALTI3D_MERGED_FILES) $(SWISS_VECTOR25_GPKGS)
	$(CONDA_PYTHON) glacier_contours.py --vector25-dir $(SWISS_VECTOR25_1_DIR) $< $@ $(SWISSALTI3D_MERGED_FILES)

$(SWISS_TOPO_DIR)/glacier-contour.osm.pbf: $(SWISS_TOPO_DIR)/glacier-contours.gpkg vector25_to_osm.py
	$(CONDA_PYTHON) vector25_to_osm.py areas glacier-contour $@ $< --id-base 410000000000

$(SWISS_TOPO_DIR)/crevasses/crevasse_%.gpkg: vector25_crevasses.py | $(SWISS_VECTOR25_1_DIR)/%/smv25_chlv95ln02_raster/glet.tif
	@mkdir -p $(dir $@)
	$(CONDA_PYTHON) vector25_crevasses.py $| $@

$(SWISS_TOPO_DIR)/crevasse.osm.pbf: $(SWISS_TOPO_CREVASSE_GPKGS) vector25_to_osm.py
	$(CONDA_PYTHON) vector25_to_osm.py areas crevasse $@ $(SWISS_TOPO_CREVASSE_GPKGS) --id-base 420000000000

$(SWISS_TOPO_DIR)/split/done: $(SWISS_TOPO_DIR)/net.osm.pbf $(SWISS_TOPO_DIR)/feat.osm.pbf $(SWISS_TOPO_DIR)/contour/done $(SWISS_TOPO_DIR)/rock.osm.pbf $(SWISS_TOPO_DIR)/scree.osm.pbf $(SWISS_TOPO_DIR)/glacier.osm.pbf $(SWISS_TOPO_DIR)/glacier-contour.osm.pbf $(SWISS_TOPO_DIR)/crevasse.osm.pbf $(SWISS_TOPO_DIR)/station.osm.pbf $(SPLITTER)/splitter.jar
	rm -rf $(dir $@)
	mkdir -p $(dir $@)
	# splitter reads the inputs as one stream: list them in ascending ID order.
	java -Xmx6g -jar $(SPLITTER)/splitter.jar --mapid=30050001 --output-dir=$(dir $@) \
		$(SWISS_TOPO_DIR)/net.osm.pbf $(SWISS_TOPO_DIR)/feat.osm.pbf \
		$(SWISS_TOPO_DIR)/contour/contour_*.osm.pbf \
		$(SWISS_TOPO_DIR)/rock.osm.pbf $(SWISS_TOPO_DIR)/scree.osm.pbf \
		$(SWISS_TOPO_DIR)/glacier.osm.pbf $(SWISS_TOPO_DIR)/glacier-contour.osm.pbf \
		$(SWISS_TOPO_DIR)/crevasse.osm.pbf $(SWISS_TOPO_DIR)/station.osm.pbf
	touch $@ # splitter writes template.args before it finishes

$(OUT_DIR)/swiss-topo.img: $(SWISS_TOPO_DIR)/split/done $(SWISS_TOPO_STYLE_FILES) $(MKGMAP)/mkgmap.jar
	@mkdir -p $(OUT_DIR)
	@cmd="cd $(SWISS_TOPO_DIR)/split; \
		$(SWISS_TOPO_JAVA) -Dlog.config=$(ROOT_DIR)/logging.properties \
		    -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/swiss-topo/style \
			--read-config=$(ROOT_DIR)/swiss-topo/topo.cfg \
			--mapname=30050000 \
			--description=Outabout\ Swiss\ Topo\ $$(date +%Y-%m-%d_%H%M) \
			--area-name=RB_A_SWISS_TOPO \
			--series-name=RB_S_SWISS_TOPO \
			--overview-mapname=RB_O_SWISS_TOPO \
			--overview-mapnumber=30050000 \
			--read-config=template.args \
			$(ROOT_DIR)/swiss-topo/swiss-topo-typ.txt \
			"; \
	cmd=$$(echo $$cmd | sed 's/  */ /g'); \
	echo "($$cmd)"; \
	bash -c "$$cmd" && \
	mv $(SWISS_TOPO_DIR)/split/gmapsupp.img $@ # only on success, keeps the previous map otherwise

swisstopo: $(OUT_DIR)/swiss-topo.img

# Publish the existing Swiss outputs without starting a map rebuild.
# gh creates the tag on GitHub at the current commit when it creates the release.
GITHUB_REPO ?= buessow/mkgmap
RELEASE_TAG ?= swiss-$(shell date -u +%Y%m%dT%H%M%SZ)

publish-swiss:
	@set -eu; \
	set -- $(OUT_DIR)/swiss-*; \
	if [ ! -f "$$1" ]; then echo "No $(OUT_DIR)/swiss-* files to publish" >&2; exit 1; fi; \
	command -v gh >/dev/null || { echo "GitHub CLI (gh) is required" >&2; exit 1; }; \
	gh release create "$(RELEASE_TAG)" "$$@" \
		--repo "$(GITHUB_REPO)" \
		--target "$$(git rev-parse HEAD)" \
		--title "Swiss maps $(RELEASE_TAG)" \
		--notes "Swiss map files."

publish-swiss-topo: publish-swiss

.PHONY: swisstopo publish-swiss publish-swiss-topo

all: $(foreach country,$(COUNTRIES),$(OUT_DIR)/osm-oa-$(country).img)

/Volumes/GARMIN/Garmin/%.img: out/%.img
	cp $< $@

clean:
	rm -rf $(WORK_DIR)/*
	rm -rf $(OUT_DIR)/*

cleanall: clean
	rm -rf $(IN_DIR)/*
	rm -rf $(SPLITTER)
	rm -rf $(MKGMAP)

.PHONY: clean cleanall %.defined
.SECONDARY:
.PRECIOUS: $(IN_DIR)/% $(SPLITTER)/splitter.jar $(MKGMAP)/mkgmap.jar
.PRECIOUS: $(WORK_DIR)/%/split $(WORK_DIR)/%/split-contour
.PRECIOUS: $(OUT_DIR)/%.img
