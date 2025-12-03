IN_DIR = in
WORK_DIR = work
OUT_DIR = out
STYLE_DIR = my-style
STYLE_FILES = $(wildcard $(STYLE_DIR)/*)
TYP_FILES = typ-files/20011.txt typ-files/sameOrder.txt
ROOT_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

QGIS_DIR = /Applications/QGIS.app/Contents/MacOS
PYTHON3 = $(QGIS_DIR)/bin/python3
GDALWARP = $(QGIS_DIR)/bin/gdalwarp

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

SWISSALTI3D_RAW_DIR = swiss-alti3d-raw
SWISSALTI3D_MERGED_DIR = swiss-alti3d
SWISS_VECTOR25_RAW_DIR = swiss-vector25-raw

$(SWISSALTI3D_RAW_DIR):
	mkdir -p $@

download-swissalti3d: swiss-alti3d-2m_urls.txt | $(SWISSALTI3D_RAW_DIR)
	@total=$$(wc -l < $< | tr -d ' '); \
	cat -n $< | xargs -n 2 -P 50 sh -c 'file="$(SWISSALTI3D_RAW_DIR)/$$(basename $$2)"; if [ ! -e "$$file" ]; then echo "Downloading [$$1/'"$$total"'] $$(basename $$2)"; wget -q --directory-prefix=$(SWISSALTI3D_RAW_DIR) --no-clobber $$2; fi' sh

download-swiss-vector25: swiss-vector25_urls.txt | $(SWISS_VECTOR25_RAW_DIR)
	@total=$$(wc -l < $< | tr -d ' '); \
	cat -n $< | xargs -n 2 -P 50 sh -c 'file="$(SWISS_VECTOR25_RAW_DIR)/$$(basename $$2)"; if [ ! -e "$$file" ]; then echo "Downloading [$$1/'"$$total"'] $$(basename $$2)"; wget -q --directory-prefix=$(SWISS_VECTOR25_RAW_DIR) --no-clobber $$2; fi' sh


$(WORK_DIR)/swissalti3d_all.tif:
	$(GDALWARP) -t_srs EPSG:2056 -multi -r bilinear -overwrite /Volumes/T9/qgis-data/alt2/*.tif $@

$(IN_DIR)/skitouren_2056.gpkg.zip:
	wget --directory-prefix=$(IN_DIR) https://data.geo.admin.ch/ch.swisstopo-karto.skitouren/skitouren/skitouren_2056.gpkg.zip


SWISS_SLOPE30_OSMS = $(patsubst %.tif,%.osm,$(wildcard $(SWISSALTI3D_MERGED_DIR)/*_alti3d.tif))
%_alti3d.osm: %_alti3d.tif
	$(PYTHON3) avi-terrain.py slope30 $< $@
print_slope30_osms:
	@echo $(SWISS_SLOPE30_OSMS)
slope30_osms: $(SWISS_SLOPE30_OSMS)

SWISS_ROCK_OSMS = $(patsubst swiss-vector25-raw/%/SMV25_CHLV95LN02_RASTER/FELS.tif,work/swiss-rock/rock_%.osm,$(wildcard $(SWISS_VECTOR25_RAW_DIR)/*/SMV25_CHLV95LN02_RASTER/FELS.tif))

work/swiss-rock/rock_%.tif: swiss-vector25-raw/%/SMV25_CHLV95LN02_RASTER/FELS.tif
	cp $< $@

rock_%.osm: rock_%.tif
	$(PYTHON3) avi-terrain.py rock $< $@

print_rock_osms:
	@echo $(SWISS_ROCK_OSMS)

rock_osms: $(SWISS_ROCK_OSMS)


$(WORK_DIR)/swiss-skitouring/ski_network_2056.gpkg: $(IN_DIR)/skitouren_2056.gpkg.zip
	@mkdir -p $(WORK_DIR)/swiss-skitouring
	unzip -u $(IN_DIR)/skitouren_2056.gpkg.zip -d $(WORK_DIR)/swiss-skitouring

$(WORK_DIR)/swiss-skitouring/ski_network_2056.osm: $(WORK_DIR)/swiss-skitouring/ski_network_2056.gpkg
	ogr2osm --id=-2000000000 --positive-id -f -o $@ $<

$(WORK_DIR)/swiss-skitouring/ski_network_2056_updated.osm: $(WORK_DIR)/swiss-skitouring/ski_network_2056.osm find_nearby_peaks.py db_config.py
	$(PYTHON3) find_nearby_peaks.py --osm-file $< --output-osm-file $@

$(OUT_DIR)/swiss-ski-network.img: $(WORK_DIR)/swiss-skitouring/ski_network_2056_updated.osm topo/topo.cfg topo/topo-typ.txt $(wildcard topo/style/*)
	@mkdir -p $(OUT_DIR)
	@mkdir -p $(WORK_DIR)/swiss-skitouring
	@cmd="cd $(WORK_DIR)/swiss-skitouring; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties \
		    -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/topo/style \
			--read-config=$(ROOT_DIR)/topo/topo.cfg \
			--draw-priority=10 \
			--mapname=30001001 \
			--family-id=30001 \
			--series-name=RB_S_OUTABOUT_SKI_NETWORK \
			--area-name=RB_A_OUTABOUT_SKI_NETWORK \
			--description=Outabout\ Swiss\ Ski\ Network \
			--overview-mapname=RB_OUTABOUT_SKI_NETWORK \
			--overview-mapnumber=30001001 \
			ski_network_2056_updated.osm \
			$(ROOT_DIR)/topo/topo-typ.txt \
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

$(OUT_DIR)/swiss-slope30.img: $(WORK_DIR)/swiss-skitouring/swiss-slope30.args topo/topo.cfg topo/topo-typ.txt $(wildcard topo/style/*)
	@mkdir -p $(OUT_DIR)
	@mkdir -p $(WORK_DIR)/swiss-skitouring
	@cmd="cd $(WORK_DIR)/swiss-skitouring; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties \
		    -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/topo/style \
			--read-config=$(ROOT_DIR)/topo/topo.cfg \
			--family-id=30003 \
			--series-name=RB_S_OUTABOUT_SKI_SLOPE30 \
			--area-name=RB_A_OUTABOUT_SKI_SLOPE30 \
			--description=Outabout\ Swiss\ Slope30 \
			--overview-mapname=RB_OUTABOUT_SKI_SLOPE30 \
			--overview-mapnumber=30001003 \
			--read-config=$(ROOT_DIR)/$(WORK_DIR)/swiss-skitouring/swiss-slope30.args \
			$(ROOT_DIR)/topo/topo-typ.txt \
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

$(OUT_DIR)/swiss-rock.img: $(WORK_DIR)/swiss-rock/swiss-rock.args topo/topo.cfg topo/topo-typ.txt $(wildcard topo/style/*)
	@mkdir -p $(OUT_DIR)
	@mkdir -p $(WORK_DIR)/swiss-rock
	@cmd="cd $(WORK_DIR)/swiss-rock; \
		java -Xms5g -Xmx16g -XX:+UseParallelGC -Dlog.config=$(ROOT_DIR)/logging.properties \
		    -jar $(ROOT_DIR)/$(MKGMAP)/mkgmap.jar \
			--style-file=$(ROOT_DIR)/topo/style \
			--read-config=$(ROOT_DIR)/topo/topo.cfg \
			--family-id=30004 \
			--series-name=RB_S_OUTABOUT_SKI_ROCK \
			--area-name=RB_A_OUTABOUT_SKI_ROCK \
			--description=Outabout\ Swiss\ Rock \
			--overview-mapname=RB_OUTABOUT_SKI_ROCK \
			--overview-mapnumber=30001004 \
			--read-config=$(ROOT_DIR)/$(WORK_DIR)/swiss-rock/swiss-rock.args \
			$(ROOT_DIR)/topo/topo-typ.txt \
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
