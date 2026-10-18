#!/usr/bin/env python3
"""Rock, scree and ice areas from the swissTLM3D land cover (tlm_bb_bodenbedeckung).

swissTLM3D is swisstopo's current landscape model (revised yearly), so its rock, scree, glacier
and snowfield polygons come from one survey and share their borders. Writes three GeoPackages in
EPSG:2056 (2D) with a `kind` field:
  rock     Fels (rock), Fels locker (rock_sparse), Felsbloecke [locker] (boulders)
  scree    Lockergestein (scree), Lockergestein locker (scree_sparse)
  glaciers Gletscher (glacier), Schneefeld Toteis (snowfield), plus `name`
The land cover has no names, so each ice area takes the name of the glacier (OSM / SGI) that
overlaps it most.
Run with the conda ogr2osm python (GDAL 3.6).
"""
import argparse
import os

from osgeo import ogr, osr

ogr.UseExceptions()

ROCK = {"Fels": "rock", "Fels locker": "rock_sparse",
        "Felsbloecke": "boulders", "Felsbloecke locker": "boulders"}
SCREE = {"Lockergestein": "scree", "Lockergestein locker": "scree_sparse"}
ICE = {"Gletscher": "glacier", "Schneefeld Toteis": "snowfield"}


def create(path, srs, with_name=False):
    if os.path.exists(path):
        os.remove(path)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = ds.CreateLayer("areas", srs, ogr.wkbMultiPolygon)
    layer.CreateField(ogr.FieldDefn("kind", ogr.OFTString))
    if with_name:
        layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    return ds, layer


def best_name(geom, names_layer):
    """Name of the named glacier polygon with the largest overlap, or None."""
    names_layer.SetSpatialFilter(geom)
    best, best_area = None, 0.0
    for f in names_layer:
        name = f.GetField("name")
        other = f.GetGeometryRef()
        if not name or other is None:
            continue
        try:
            area = geom.Intersection(other.MakeValid()).GetArea()
        except RuntimeError:
            continue
        if area > best_area:
            best, best_area = name, area
    names_layer.SetSpatialFilter(None)
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tlm", help="SWISSTLM3D_*.gpkg")
    parser.add_argument("glacier_names", help="Named glacier polygons (OSM + SGI) in EPSG:2056")
    parser.add_argument("rock", help="Output rock .gpkg")
    parser.add_argument("scree", help="Output scree .gpkg")
    parser.add_argument("glaciers", help="Output glaciers .gpkg")
    args = parser.parse_args()

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2056)
    outputs = {}
    for key, path, classes in (("rock", args.rock, ROCK), ("scree", args.scree, SCREE),
                               ("glaciers", args.glaciers, ICE)):
        ds, layer = create(path, srs, with_name=key == "glaciers")
        outputs[key] = (ds, layer, classes)

    names_ds = ogr.Open(args.glacier_names)
    names_layer = names_ds.GetLayer(0)
    tlm = ogr.Open(args.tlm)
    land = tlm.GetLayerByName("tlm_bb_bodenbedeckung")
    wanted = list(ROCK) + list(SCREE) + list(ICE)
    land.SetAttributeFilter("objektart IN (%s)" % ",".join(f"'{c}'" for c in wanted))

    counts = {}
    for _, layer, _ in outputs.values():
        layer.StartTransaction()
    for f in land:
        objektart = f.GetField("objektart")
        geom = f.GetGeometryRef()
        if geom is None or geom.IsEmpty():
            continue
        geom = geom.Clone()
        geom.FlattenTo2D()
        for key, (_, layer, classes) in outputs.items():
            if objektart not in classes:
                continue
            out = ogr.Feature(layer.GetLayerDefn())
            out.SetField("kind", classes[objektart])
            if key == "glaciers":
                out.SetField("name", best_name(geom, names_layer))
            out.SetGeometry(ogr.ForceToMultiPolygon(geom))
            layer.CreateFeature(out)
            counts[classes[objektart]] = counts.get(classes[objektart], 0) + 1
    for _, layer, _ in outputs.values():
        layer.CommitTransaction()
    print(", ".join(f"{n} {k}" for k, n in sorted(counts.items())))


if __name__ == "__main__":
    main()
