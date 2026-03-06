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

COUNTRIES = austria germany france italy liechtenstein spain switzerland

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

#$(WORK_DIR)/%/split: $(WORK_DIR)/%-filtered.osm.pbf $(SPLITTER) Makefile
$(WORK_DIR)/%/split: $(IN_DIR)/%-latest.osm.pbf $(SPLITTER)/splitter.jar %.defined
	@country=$$(basename $$(dirname $@) | sed 's/osm-oa-//'); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	dialcode=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:...:\(....\)/\1/p"); \
	id="22$${dialcode}00"; \
	cmd="java -jar $(SPLITTER)/splitter.jar --mapid=$$id --output-dir=$(dir $@) $<"; \
	echo "$$cmd"; \
	$$cmd
	touch $(dir $@)split

$(WORK_DIR)/%/split-contour: $(WORK_DIR)/%-contour.osm.pbf $(SPLITTER)/splitter.jar %.defined
	@country=$$(basename $$(dirname $@) | sed 's/osm-oa-//'); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	dialcode=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:...:\(....\)/\1/p"); \
	id="21$${dialcode}00"; \
	cmd="java -jar $(SPLITTER)/splitter.jar --mapid=$$id --output-dir=$(dir $@)/contour $<"; \
	echo "$$cmd"; \
	$$cmd
	touch $(dir $@)/split-contour

$(OUT_DIR)/osm-oa-%.img: $(WORK_DIR)/%/split $(WORK_DIR)/%/split-contour my.cfg $(MKGMAP)/mkgmap.jar $(STYLE_FILES) $(TYP_FILES) %.defined
	@mkdir -p $(OUT_DIR); \
	country=$$(basename $@ .img | sed 's/osm-oa-//'); \
	country3=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:\(...\):..../\1/p"); \
	dialcode=$$(echo $(COUNTRY_CODES) | tr ' ' '\n' | sed -n "s/$$country:...:\(...\)/\1/p"); \
	id="20$${dialcode}00"; \
	fid=1$$dialcode; \
	cmd="cd $(WORK_DIR)/$$country; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/$(STYLE_DIR) \
			--read-config=$(ROOT_DIR)/my.cfg \
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
