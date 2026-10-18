#!/usr/bin/env python3
"""Convert swiss-map-vector25 GeoPackages to OSM PBF with OSM-style tags.

Run with the conda ogr2osm python (GDAL 3.6). Output is streamed through
`osmium cat` so national-scale layers never have to fit in memory as XML.

Subcommands:
  net      roads, trails, railways, aerialways of all sheets in one file, so
           ways that meet across sheet edges share nodes (routing).
  feat     all other vector features of all sheets.
  contour  contour lines, one output file per sheet.
  areas    raster-derived rock/scree polygons (see vector25_raster_areas.py).

Features crossing sheet edges are stored whole in every sheet; they are
deduplicated by DKM_UUID.
"""
import argparse
import collections
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import quoteattr

from osgeo import ogr, osr

ogr.UseExceptions()
osr.UseExceptions()

GPKG_NAME = "smv25_chlv95ln02.gpkg"


# --------------------------------------------------------------------------
# OSM writer
# --------------------------------------------------------------------------

class OsmWriter:
    """Streams nodes to osmium; buffers ways and relations to keep OSM order.

    With share_nodes, nodes are deduplicated by rounded WGS84 coordinates
    across the whole file so lines that share an endpoint share an OSM node
    (needed for routing). Otherwise nodes are only reused within one way,
    which closes rings but keeps memory flat.
    """

    def __init__(self, path, id_base, share_nodes=False):
        self.path = path
        self.share_nodes = share_nodes
        self.next_node = id_base
        self.next_way = id_base
        self.next_rel = id_base
        self.first_id = id_base
        self.nodes = {}
        self.tmp_dir = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(path)))
        self.ways = open(os.path.join(self.tmp_dir, "ways.xml"), "w", encoding="utf-8")
        self.rels = open(os.path.join(self.tmp_dir, "rels.xml"), "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            ["osmium", "cat", "--overwrite", "-F", "osm", "-o", path, "-"],
            stdin=subprocess.PIPE)
        self.out = open(self.proc.stdin.fileno(), "w", encoding="utf-8", closefd=False,
                        buffering=1 << 20)
        self.out.write("<?xml version='1.0' encoding='UTF-8'?>\n"
                       "<osm version='0.6' generator='vector25_to_osm'>\n")
        self.count = collections.Counter()

    @staticmethod
    def _tags(tags):
        return "".join(f"<tag k={quoteattr(k)} v={quoteattr(str(v))}/>"
                       for k, v in tags.items() if v is not None and v != "")

    def node(self, lon, lat, tags=None, nodes=None):
        """Write a node; untagged nodes are looked up and registered in `nodes`."""
        key = (round(lon * 1e7), round(lat * 1e7))
        if nodes is not None:
            nid = nodes.get(key)
            if nid is not None:
                return nid
        nid = self.next_node
        self.next_node += 1
        if nodes is not None:
            nodes[key] = nid
        if tags:
            self.out.write(f"<node id='{nid}' version='1' lat='{key[1] / 1e7:.7f}' lon='{key[0] / 1e7:.7f}'>"
                           f"{self._tags(tags)}</node>\n")
            self.count["poi"] += 1
        else:
            self.out.write(f"<node id='{nid}' version='1' lat='{key[1] / 1e7:.7f}' lon='{key[0] / 1e7:.7f}'/>\n")
        return nid

    def way(self, coords, tags=None):
        ids = []
        nodes = self.nodes if self.share_nodes else {}
        for lon, lat in coords:
            nid = self.node(lon, lat, nodes=nodes)
            if not ids or ids[-1] != nid:
                ids.append(nid)
        if len(ids) < 2:
            return None
        wid = self.next_way
        self.next_way += 1
        nds = "".join(f"<nd ref='{n}'/>" for n in ids)
        self.ways.write(f"<way id='{wid}' version='1'>{nds}{self._tags(tags or {})}</way>\n")
        self.count["way"] += 1
        return wid

    def relation(self, members, tags):
        rid = self.next_rel
        self.next_rel += 1
        mem = "".join(f"<member type='way' ref='{ref}' role='{role}'/>" for ref, role in members)
        self.rels.write(f"<relation id='{rid}' version='1'>{mem}{self._tags(tags)}</relation>\n")
        self.count["relation"] += 1
        return rid

    def line(self, geom, tags):
        for part in _parts(geom):
            self.way(part.GetPoints(), tags)

    def polygon(self, geom, tags):
        for poly in _parts(geom):
            rings = [poly.GetGeometryRef(i) for i in range(poly.GetGeometryCount())]
            rings = [r.GetPoints() for r in rings if r.GetPointCount() >= 4]
            if not rings:
                continue
            if len(rings) == 1:
                self.way(rings[0], tags)
                continue
            members = []
            for i, ring in enumerate(rings):
                wid = self.way(ring)
                if wid is not None:
                    members.append((wid, "outer" if i == 0 else "inner"))
            if members and members[0][1] == "outer":
                self.relation(members, {"type": "multipolygon", **tags})

    def point(self, geom, tags):
        for part in _parts(geom):
            self.node(part.GetX(), part.GetY(), tags)

    def close(self):
        for f in (self.ways, self.rels):
            f.close()
            with open(f.name, encoding="utf-8") as src:
                shutil.copyfileobj(src, self.out, 1 << 20)
        self.out.write("</osm>\n")
        self.out.close()
        self.proc.stdin.close()
        rc = self.proc.wait()
        shutil.rmtree(self.tmp_dir)
        if rc != 0:
            raise RuntimeError(f"osmium failed with exit code {rc}")
        print(f"{self.path}: {self.next_node - self.first_id} nodes, "
              f"{', '.join(f'{v} {k}s' for k, v in sorted(self.count.items()))}", flush=True)


def _parts(geom):
    if geom.GetGeometryCount() > 0 and ogr.GT_Flatten(geom.GetGeometryType()) in (
            ogr.wkbMultiLineString, ogr.wkbMultiPolygon, ogr.wkbMultiPoint, ogr.wkbGeometryCollection):
        return [geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]
    return [geom]


# --------------------------------------------------------------------------
# Tag mapping
# --------------------------------------------------------------------------

def clean_name(name):
    """Undo cartographic label splitting, e.g. 'Glacier de- -Moming', "d ' Otemma"."""
    if not name:
        return None
    # A line break after a particle was a space ("de Moming"), otherwise a hyphen ("Saas-Fee").
    name = re.sub(r"\b(d[aeiu]|des|del|della|la|le|les|von|vom|am|im)- -", r"\1 ", name, flags=re.I)
    name = re.sub(r"- -", "-", name)
    name = re.sub(r"\s*'\s*", "'", name)
    name = name.replace("§", " / ")  # separator of bilingual names, e.g. "Biel§Bienne"
    return re.sub(r"\s+", " ", name).strip() or None


def yes_no(value):
    return value == "Wahr"


HIGHWAY = {
    "Autobahn": "motorway",
    "Autostrasse": "trunk",
    "Einfahrt": "motorway_link",
    "Ausfahrt": "motorway_link",
    "10m_Strasse": "primary",
    "8m_Strasse": "primary",
    "6m_Strasse": "secondary",
    "4m_Strasse": "tertiary",
    "3m_Strasse": "unclassified",
    "Zufahrt": "service",
    "Dienstzufahrt": "service",
    "Raststaette": "service",
    "Platz": "service",
    "2m_Weg": "track",
    "2m_Wegfragment": "track",
    "1m_Weg": "path",
    "1m_Wegfragment": "path",
    "Markierte_Spur": "path",
    "Klettersteig": "via_ferrata",
}

ROAD_IMPORTANCE = {
    "Durchgangsstrasse": "primary",
    "Verbindungsstrasse": "secondary",
}

SAC_SCALE = {
    "Wanderweg": "hiking",
    "Bergwanderweg": "mountain_hiking",
    "Alpinwanderweg": "alpine_hiking",
}


def tags_strasse(f):
    highway = HIGHWAY.get(f["OBJEKTART"])
    if not highway:
        return None
    # Width says little about importance (the Chur-Arosa road is a 4 m road); BEDEUTUNG does.
    if highway in ("primary", "secondary", "tertiary", "unclassified"):
        highway = ROAD_IMPORTANCE.get(f["BEDEUTUNG"]) or (
            "tertiary" if f["OBJEKTART"] in ("10m_Strasse", "8m_Strasse", "6m_Strasse") else "unclassified")
    tags = {"highway": highway, "name": clean_name(f["NAME"]), "ref": f["ROUTEN_NR"] or None,
            "oneway": "no"}  # digitizing direction of dual carriageways is unknown
    if f["OBJEKTART"].endswith("Wegfragment"):
        tags["trail_visibility"] = "bad"
    if f["OBJEKTART"] == "Markierte_Spur":
        tags["trail_visibility"] = "intermediate"
    ww = f["WANDERWEG"]
    if ww in SAC_SCALE:
        tags["sac_scale"] = SAC_SCALE[ww]
        tags["hiking"] = "yes"
    elif ww == "Andere":
        tags["hiking"] = "yes"
    kb = f["KUNSTBAUTE"] or ""
    if kb.startswith("Bruecke") or kb == "Steg":
        tags["bridge"] = "yes"
        tags["layer"] = "1"
    if kb.startswith("Treppe") or kb.endswith("_Treppe"):
        if highway in ("path", "track"):
            tags["highway"] = "steps"
    if kb.startswith("Unterfuehrung") or kb == "Tunnel":
        tags["tunnel"] = "yes"
        tags["layer"] = "-1"
    if kb == "Galerie" or kb.endswith("_Galerie"):
        tags["tunnel"] = "avalanche_protector"
    if kb == "Furt":
        tags["ford"] = "yes"
    belag = f["BELAGSART"]
    if belag == "Hartbelag":
        tags["surface"] = "paved"
    elif belag == "Naturbelag":
        tags["surface"] = "unpaved"
    if f["BEFAHRBAR"] == "Falsch" and highway not in ("path", "via_ferrata"):
        tags["motor_vehicle"] = "no"
    return tags


RAILWAY = {
    "Normalspur": "rail",
    "Schmalspur": "narrow_gauge",
    "Schmalspur_mit_Normalspur": "rail",
    "Kleinbahn": "narrow_gauge",
    "Bahnhof_Gleis": "rail",
    "Bahnhof_Klein": "rail",
}


def tags_eisenbahn(f, tunnel=False):
    railway = RAILWAY.get(f["OBJEKTART"])
    if not railway:
        return None
    tags = {"railway": railway, "name": clean_name(f["NAME"])}
    if f["OBJEKTART"].startswith("Bahnhof"):
        tags["service"] = "siding"
    kb = f["KUNSTBAUTE"] if not tunnel else "Tunnel"
    if kb and kb.startswith("Bruecke"):
        tags["bridge"] = "yes"
        tags["layer"] = "1"
    elif kb in ("Tunnel", "Unterfuehrung"):
        tags["tunnel"] = "yes"
        tags["layer"] = "-1"
    elif kb == "Galerie":
        tags["tunnel"] = "avalanche_protector"
    return tags


OEV_LIN = {
    "Luftseilbahn": {"aerialway": "cable_car"},
    "Gondelbahn": {"aerialway": "gondola"},
    "Sesselbahn": {"aerialway": "chair_lift"},
    "Skilift": {"aerialway": "drag_lift"},
    "Transportseil": {"aerialway": "goods"},
    "Foerderband": {"man_made": "goods_conveyor"},
    "Personenfaehre_mit_Seil": {"route": "ferry"},
    "Personenfaehre_ohne_Seil": {"route": "ferry"},
}

OEV_PKT = {
    "Luftseilbahn": {"aerialway": "station"},
    "Gondelbahn": {"aerialway": "station"},
    "Sesselbahn": {"aerialway": "station"},
    "Lift": {"aerialway": "station"},
    "Haltestelle_Schiff": {"amenity": "ferry_terminal"},
}

GEWAESSER_LIN = {
    "Fliessgewaesser": {"waterway": "stream"},
    "Trockenrinne": {"waterway": "stream", "intermittent": "yes"},
    "Bisse_Suone": {"waterway": "ditch"},
    "Druckleitung_einfach": {"man_made": "pipeline"},
    "Druckleitung_mehrfach": {"man_made": "pipeline"},
}

GEWAESSER_PLY = {
    "See": {"natural": "water", "water": "lake"},
    "Fluss": {"natural": "water", "water": "river"},
}

NUTZUNGSAREAL = {
    "Reben": {"landuse": "vineyard"},
    "Obstanlage": {"landuse": "orchard"},
    "Friedhof": {"landuse": "cemetery"},
    "Baumschule": {"landuse": "plant_nursery"},
    "Schrebergartenareal": {"landuse": "allotments"},
    "Oeffentliches_Parkareal": {"leisure": "park"},
    "Spitalareal": {"amenity": "hospital"},
    "Unterwerkareal": {"power": "substation"},
    "Deponieareal": {"landuse": "landfill"},
}

FREIZEITAREAL = {
    "Sportplatzareal": {"leisure": "sports_centre"},
    "Schwimmbadareal": {"leisure": "sports_centre", "sport": "swimming"},
    "Campingplatzareal": {"tourism": "camp_site"},
    "Golfplatzareal": {"leisure": "golf_course"},
    "Zooareal": {"tourism": "zoo"},
}

VERKEHRSAREAL = {
    "Parkplatzareal_oeffentlich": {"amenity": "parking"},
    "Rastplatzareal": {"amenity": "parking"},
    "Heliport": {"aeroway": "heliport"},
}

BAUTE_PLY = {
    "Sportplatz": {"leisure": "pitch"},
    "Wasserbecken": {"natural": "water", "water": "basin"},
    "Schwimmbecken": {"leisure": "swimming_pool"},
    "Staumauer": {"waterway": "dam"},
    "Wehr": {"waterway": "weir"},
    "Rollfeld_Hartbelag": {"aeroway": "runway"},
    "Hartbelagpiste": {"aeroway": "runway"},
    "Graspiste": {"aeroway": "runway"},
    "Rollfeld_Gras": {"aeroway": "runway"},
}

BOESCHUNG = {
    "Boeschungsschraffe": {"natural": "earth_bank"},
    "Steinboeschungsschraffe": {"natural": "earth_bank", "material": "stone"},
}

BAUTE_LIN = {
    "Lawinenverbauung": {"man_made": "avalanche_barrier"},
    "Mauer": {"barrier": "wall"},
    "Trockenmauer": {"barrier": "wall"},
    "Hochspannungsleitung": {"power": "line"},
    "Hafensteg": {"man_made": "pier"},
}

BAUTE_PKT = {
    "Quelle": {"natural": "spring"},
    "Brunnen": {"amenity": "fountain"},
    "Gipfelkreuz": {"man_made": "cross", "summit:cross": "yes"},
    "Grotte_Hoehle": {"natural": "cave_entrance"},
    "Bildstock": {"historic": "wayside_shrine"},
    "Denkmal": {"historic": "memorial"},
    "Antenne_gross": {"man_made": "mast"},
    "Windturbine": {"power": "generator", "generator:source": "wind"},
    "Triangulationspyramide": {"man_made": "survey_point"},
}

GEBAEUDE_SYMB = {
    "Kapelle": {"amenity": "place_of_worship", "building": "chapel"},
    "Sakraler_Turm": {"amenity": "place_of_worship"},
    "Sakrales_Gebaeude": {"amenity": "place_of_worship"},
    "Turm": {"man_made": "tower"},
    "Hochkamin": {"man_made": "chimney"},
}

MORPH_PKT = {
    "Felsblock": {"natural": "stone"},
    "Erratischer_Block": {"natural": "stone"},
    "Doline": {"natural": "sinkhole"},
}

NAME_PKT = {
    "Hauptgipfel": {"natural": "peak", "rank": "1"},
    "Alpiner_Gipfel": {"natural": "peak", "rank": "1"},
    "Gipfel": {"natural": "peak", "rank": "2"},
    "Felskopf": {"natural": "peak", "rank": "3"},
    "Haupthuegel": {"natural": "peak", "rank": "2"},
    "Huegel": {"natural": "peak", "rank": "3"},
    "Pass": {"mountain_pass": "yes", "natural": "saddle"},
    "Strassenpass": {"mountain_pass": "yes", "natural": "saddle"},
}

SIEDLUNGSNAME = {
    "Ort": "village",
    "Ortsteil": "suburb",
    "Quartier": "suburb",
    "Quartierteil": "neighbourhood",
}

GELAENDENAME = {
    "Tal": {"natural": "valley"},
    "Haupttal": {"natural": "valley"},
    "Grat": {"natural": "ridge"},
    "Massiv": {"natural": "mountain_range"},
    "Huegelzug": {"natural": "ridge"},
    "Graben": {"natural": "valley", "rank": "3"},
    "Seeinsel": {"place": "island"},
    # Only the name: these polygons mark where the name goes, not the ice. The glacier areas
    # come from OSM (see the Makefile's glacier rule).
    "Gletscher": {"natural": "glacier"},
}

HUT_RE = re.compile(r"(h(ü|u)tte|cabane|capanna|chamanna|rifugio|refuge|\bSAC\b|\bCAS\b|\bCAI\b)", re.I)
BIVOUAC_RE = re.compile(r"(biwak|bivacco|bivouac|bivacc)", re.I)


def tags_gebaeude(f):
    tags = {"building": "yes"}
    if f["OBJEKTART"] in ("Sakrales_Gebaeude", "Kapelle"):
        tags["building"] = "church"
    name = clean_name(f["NAME"])
    if name:
        tags["name"] = name
        if BIVOUAC_RE.search(name):
            tags["tourism"] = "wilderness_hut"
        elif HUT_RE.search(name):
            tags["tourism"] = "alpine_hut"
    return tags


def simple(mapping, name_field="NAME"):
    def fn(f):
        tags = mapping.get(f["OBJEKTART"])
        if tags is None:
            return None
        tags = dict(tags)
        if name_field and name_field in f.keys():
            tags["name"] = clean_name(f[name_field])
        return tags
    return fn


def with_ele(fn):
    def wrapped(f):
        tags = fn(f)
        if tags is not None and f["HOEHE"]:
            tags["ele"] = str(f["HOEHE"])
        return tags
    return wrapped


def tags_hoehenkote(f):
    if f["OBJEKTART"] == "Seebodenkote" or not f["HOEHE"]:
        return None
    return {"natural": "spot_height", "ele": str(f["HOEHE"])}


def tags_grenze(f):
    level = {"Landesgrenze_Schweiz": "2", "Landesgrenze_Drittstaaten": "2", "Kantonsgrenze": "4"}.get(f["OBJEKTART"])
    return {"boundary": "administrative", "admin_level": level} if level else None


def tags_wald(f):
    return {"landuse": "forest"} if f["OBJEKTART"] == "Wald" else None


def tags_siedlung(f):
    place = SIEDLUNGSNAME.get(f["OBJEKTART"])
    name = clean_name(f["NAME"])
    return {"place": place, "name": name} if place and name else None


def tags_gelaende(f):
    name = clean_name(f["NAME"])
    if not name:
        return None
    tags = GELAENDENAME.get(f["OBJEKTART"])
    return dict(tags, name=name) if tags else None


def tags_gebiet(f):
    name = clean_name(f["NAME"])
    if not name:
        return None
    return {"place": "region" if f["OBJEKTART"] == "Landschaftsname" else "locality", "name": name}


def tags_flurname(f):
    name = clean_name(f["NAME"])
    if not name:
        return None
    return {"place": "locality", "name": name,
            "rank": "2" if f["OBJEKTART"] == "Flurname_swisstopo" else "3"}


def tags_contour(f):
    tags = {"contour": "elevation", "ele": str(f["HOEHE"]),
            "contour_ext": "elevation_major" if f["OBJEKTART"] == "Zaehlkurve" else "elevation_minor"}
    surface = {"Fels": "rock", "Geroell": "scree"}.get(f["OBERFLAECH"])
    if surface:
        tags["contour_surface"] = surface
    return tags


# (layer, geometry kind, tag function, simplify tolerance in m)
NET_LAYERS = [
    ("T45_DKM25_STRASSE", "line", tags_strasse, 0),
    ("T44_DKM25_EISENBAHN", "line", tags_eisenbahn, 0),
    ("T46_DKM25_EISENBAHN_TUNNEL", "line", lambda f: tags_eisenbahn(f, tunnel=True), 0),
    ("T42_DKM25_OEV_LIN", "line", simple(OEV_LIN), 0),
]

FEAT_LAYERS = [
    ("T65_DKM25_BODENBEDECKUNG", "polygon", tags_wald, 2),
    ("T64_DKM25_NUTZUNGSAREAL", "polygon", simple(NUTZUNGSAREAL), 1),
    ("T63_DKM25_FREIZEITAREAL", "polygon", simple(FREIZEITAREAL), 1),
    ("T61_DKM25_VERKEHRSAREAL", "polygon", simple(VERKEHRSAREAL), 1),
    ("T60_DKM25_BAUTE_PLY", "polygon", simple(BAUTE_PLY), 1),
    ("T56_DKM25_GEWAESSER_PLY", "polygon", simple(GEWAESSER_PLY), 1),
    # Escarpments: the hatching strips of the printed map (a few m wide).
    ("T51_DKM25_BOESCHUNG_SYMB", "polygon", simple(BOESCHUNG, name_field=None), 0.5),
    ("T48_DKM25_GEBAEUDE", "polygon", tags_gebaeude, 0.5),
    ("T57_DKM25_GEWAESSER_LIN", "line_outside_water", simple(GEWAESSER_LIN), 1),
    ("T40_DKM25_BAUTE_LIN", "line", simple(BAUTE_LIN), 1),
    ("T53_DKM25_HOHEITSGRENZE", "line", tags_grenze, 5),
    ("T37_DKM25_NAME_PKT", "point", with_ele(simple(NAME_PKT)), 0),
    ("T38_DKM25_HOEHENKOTE", "point", tags_hoehenkote, 0),
    ("T32_DKM25_BAUTE_PKT", "point", simple(BAUTE_PKT, name_field=None), 0),
    ("T33_DKM25_GEBAEUDE_SYMB", "point", simple(GEBAEUDE_SYMB, name_field=None), 0),
    ("T39_DKM25_MORPH_KLEINFORM_PKT", "point", simple(MORPH_PKT, name_field=None), 0),
    ("T30_DKM25_OEV_PKT", "point", simple(OEV_PKT, name_field=None), 0),
    ("DKM25_SIEDLUNGSNAME", "label", tags_siedlung, 0),
    ("DKM25_GELAENDENAME", "label", tags_gelaende, 0),
    ("DKM25_GEBIETSNAME", "label", tags_gebiet, 0),
    ("DKM25_FLURNAME", "label", tags_flurname, 0),
]

CONTOUR_LAYER = ("T62_DKM25_HOEHENKURVE", "line", tags_contour, 2)


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def make_transform():
    src = osr.SpatialReference()
    src.ImportFromEPSG(2056)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(src, dst)


TRANSFORM = None


def write_feature(writer, kind, geom, tags, tolerance):
    if geom is None or geom.IsEmpty():
        return
    geom = geom.Clone()
    geom.FlattenTo2D()
    try:
        if kind == "label":
            geom = geom.PointOnSurface()
        elif tolerance:
            geom = geom.SimplifyPreserveTopology(tolerance)
        if geom is None or geom.IsEmpty():
            return
        geom.Transform(TRANSFORM)
    except RuntimeError as e:  # a few source geometries contain NaN coordinates
        print(f"  skipped invalid geometry ({tags}): {e}", file=sys.stderr)
        return
    if kind == "line":
        writer.line(geom, tags)
    elif kind == "polygon":
        writer.polygon(geom, tags)
    else:
        writer.point(geom, tags)


def split_by_water(geom, water_layer):
    """(outside, inside) parts of a watercourse line relative to river and lake areas. Like OSM,
    Vector25 has wide rivers both as area and as centre line; drawing both puts a line through
    the river. The name is only on the line, so the inside part is kept as a label."""
    if geom is None or water_layer is None:
        return geom, None
    outside, inside = geom, None
    water_layer.SetSpatialFilter(geom)
    try:
        for w in water_layer:
            area = w.GetGeometryRef()
            if area is None or not outside.Intersects(area):
                continue
            area = area.MakeValid()
            part = outside.Intersection(area)
            inside = part if inside is None else inside.Union(part)
            outside = outside.Difference(area)
            if outside is None or outside.IsEmpty():
                break
    except RuntimeError:
        return geom, None  # broken geometry: keep the line as is
    finally:
        water_layer.SetSpatialFilter(None)
    return outside, inside


def convert_layers(gpkgs, layers, writer, seen, unmapped):
    for gpkg in gpkgs:
        sheet = os.path.basename(os.path.dirname(gpkg))
        ds = ogr.Open(gpkg)
        for name, kind, tag_fn, tolerance in layers:
            layer = ds.GetLayerByName(name)
            if layer is None:
                continue
            seen_layer = seen[(name, kind)]  # DKM_UUID -> sheet it was first read from
            for f in layer:
                uuid = f["DKM_UUID"]
                # Features crossing a sheet edge are repeated in the neighbour sheet; skip those.
                # Within one sheet a UUID can span several rows (pieces of one way): keep them all.
                if seen_layer.setdefault(uuid, sheet) != sheet:
                    continue
                tags = tag_fn(f)
                if tags is None:
                    unmapped[(name, f["OBJEKTART"])] += 1
                    continue
                geom = f.GetGeometryRef()
                if kind == "line_outside_water":
                    outside, inside = split_by_water(geom, ds.GetLayerByName("T56_DKM25_GEWAESSER_PLY"))
                    write_feature(writer, "line", outside, tags, tolerance)
                    if inside is not None and tags.get("name"):
                        # Inside river/lake areas only the name stays (label-only line).
                        write_feature(writer, "line", inside, {"water_label": "yes", "name": tags["name"]}, tolerance)
                    continue
                write_feature(writer, kind, geom, tags, tolerance)
        ds = None
        print(f"  sheet {sheet} done", flush=True)


def sheet_gpkgs(vector25_dir, sheets=None):
    gpkgs = sorted(glob.glob(os.path.join(vector25_dir, "*", GPKG_NAME)))
    if sheets:
        gpkgs = [g for g in gpkgs if os.path.basename(os.path.dirname(g)) in sheets]
    if not gpkgs:
        sys.exit(f"No {GPKG_NAME} found in {vector25_dir}")
    return gpkgs


def report_unmapped(unmapped):
    for (layer, objektart), n in sorted(unmapped.items()):
        print(f"  unmapped {layer} {objektart}: {n}")


def cmd_layers(args, layers):
    writer = OsmWriter(args.output, args.id_base, share_nodes=args.cmd == "net")
    unmapped = collections.Counter()
    convert_layers(sheet_gpkgs(args.vector25_dir, args.sheets), layers, writer,
                   collections.defaultdict(dict), unmapped)
    writer.close()
    report_unmapped(unmapped)


def cmd_contour(args):
    """All sheets in one process so the DKM_UUID dedup set spans sheets; one file per sheet."""
    os.makedirs(args.output_dir, exist_ok=True)
    seen = collections.defaultdict(dict)
    unmapped = collections.Counter()
    for i, gpkg in enumerate(sheet_gpkgs(args.vector25_dir, args.sheets)):
        sheet = os.path.basename(os.path.dirname(gpkg))
        out = os.path.join(args.output_dir, f"contour_{sheet}.osm.pbf")
        # Read the UUIDs even when the output exists, so dedup stays stable.
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(gpkg):
            ds = ogr.Open(gpkg)
            sql = ds.ExecuteSQL(f"SELECT DKM_UUID FROM {CONTOUR_LAYER[0]}")
            seen_layer = seen[(CONTOUR_LAYER[0], CONTOUR_LAYER[1])]
            for f in sql:
                seen_layer.setdefault(f["DKM_UUID"], sheet)
            ds.ReleaseResultSet(sql)
            print(f"  {out} up to date")
            continue
        writer = OsmWriter(out + ".tmp.osm.pbf", args.id_base + int(sheet) * 100_000_000)
        convert_layers([gpkg], [CONTOUR_LAYER], writer, seen, unmapped)
        writer.close()
        os.replace(out + ".tmp.osm.pbf", out)
    report_unmapped(unmapped)


# kind -> (geometry kind, tag function of the source feature, simplify tolerance in m)
AREA_KINDS = {
    # swissTLM3D land cover (tlm_landcover.py), `kind` field.
    "rock": ("polygon", lambda f: {
        "natural": "boulders" if f["kind"] == "boulders" else "bare_rock",
        "density": "sparse" if f["kind"] == "rock_sparse" else None}, 0),
    "scree": ("polygon", lambda f: {
        "natural": "scree", "density": "sparse" if f["kind"] == "scree_sparse" else None}, 0),
    "glacier": ("polygon", lambda f: {
        "natural": "glacier", "glacier:type": "snowfield" if f["kind"] == "snowfield" else None,
        "name": clean_name(f["name"])}, 2),
    "crevasse": ("line", lambda f: {"natural": "crevasse"}, 1),
    # Train stations from swissTLM3D (tlm_oev_haltestelle), one point per name.
    "station": ("point", lambda f: {"railway": "station", "name": clean_name(f["name"])}, 0),
    "glacier-contour": ("line", lambda f: {
        "contour": "elevation", "ele": str(int(f["ele"])),
        # Parts in the retreat zone next to the ice are drawn as normal contours.
        "contour_surface": "glacier" if f["on_ice"] else None,
        "contour_ext": "elevation_major" if int(f["ele"]) % 100 == 0 else "elevation_minor"}, 2),
}


def cmd_areas(args):
    """Features derived outside Vector25 (rasters, OSM, swissALTI3D), from GeoPackages in EPSG:2056."""
    writer = OsmWriter(args.output, args.id_base)
    kind, tag_fn, tolerance = AREA_KINDS[args.kind]
    for path in args.inputs:
        ds = ogr.Open(path)
        layer = ds.GetLayer(0)
        for f in layer:
            write_feature(writer, kind, f.GetGeometryRef(), tag_fn(f), tolerance)
        ds = None
    writer.close()


def main():
    global TRANSFORM
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("net", "feat"):
        p = sub.add_parser(name)
        p.add_argument("vector25_dir")
        p.add_argument("output", help="Output .osm.pbf")
        p.add_argument("--id-base", type=int, default={"net": 1_000_000_000, "feat": 2_000_000_000}[name])
        p.add_argument("--sheets", nargs="*", help="Restrict to these sheet numbers (testing)")
    p = sub.add_parser("contour")
    p.add_argument("vector25_dir")
    p.add_argument("output_dir")
    p.add_argument("--id-base", type=int, default=100_000_000_000)
    p.add_argument("--sheets", nargs="*")
    p = sub.add_parser("areas")
    p.add_argument("kind", choices=sorted(AREA_KINDS))
    p.add_argument("output")
    p.add_argument("inputs", nargs="+", help="Polygon GeoPackages in EPSG:2056")
    p.add_argument("--id-base", type=int, required=True)
    args = parser.parse_args()

    TRANSFORM = make_transform()
    if args.cmd == "net":
        cmd_layers(args, NET_LAYERS)
    elif args.cmd == "feat":
        cmd_layers(args, FEAT_LAYERS)
    elif args.cmd == "contour":
        cmd_contour(args)
    else:
        cmd_areas(args)


if __name__ == "__main__":
    main()
