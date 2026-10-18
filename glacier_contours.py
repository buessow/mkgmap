#!/usr/bin/env python3
"""Contour lines on glaciers from swissALTI3D, for the Swiss topo map.

swiss-map-vector25 has contours only on rock, scree and other ground - none on the ice, where
the printed map draws them in blue. This script fills that gap: for each merged swissALTI3D
tile that touches a glacier it averages the 2 m model down to --cell metres (2 m contours are
too jagged), generates contours every --interval metres, and keeps their parts on the ice or in the
contour-free zone around it: within --band metres of a glacier and farther than --clear metres
from any Vector25 contour (grown back by --clear). Parts within --gap metres of a Vector25
contour of the same elevation are dropped. Clipping to the glacier outline alone leaves a band
without contours where the ice has retreated since Vector25 was drawn (its contours stop at the
older, larger glacier edge); a plain band around the ice duplicates Vector25 contours there.
Result: lines with an `ele` field in EPSG:2056 as GeoPackage.
Run with the conda ogr2osm python (GDAL + numpy).
"""
import argparse
import collections
import glob
import os

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()


def glaciers_in(layer, minx, miny, maxx, maxy):
    """Union of the glacier polygons within the box, clipped to it; None if there are none."""
    layer.SetSpatialFilterRect(minx, miny, maxx, maxy)
    union = ogr.Geometry(ogr.wkbMultiPolygon)
    for f in layer:
        geom = f.GetGeometryRef()
        if geom is None:
            continue
        geom = geom.MakeValid() if not geom.IsValid() else geom
        for i in range(geom.GetGeometryCount() if geom.GetGeometryType() in
                       (ogr.wkbMultiPolygon, ogr.wkbGeometryCollection) else 0):
            part = geom.GetGeometryRef(i)
            if part.GetGeometryType() == ogr.wkbPolygon:
                union.AddGeometry(part)
        if geom.GetGeometryType() == ogr.wkbPolygon:
            union.AddGeometry(geom)
    layer.SetSpatialFilter(None)
    if union.IsEmpty():
        return None
    box = ogr.CreateGeometryFromWkt(
        f"POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))")
    clipped = union.UnionCascaded().Intersection(box)
    return None if clipped is None or clipped.IsEmpty() else clipped


class Vector25Contours:
    """Vector25 contour lines (T62) of all sheets, queried by box."""

    def __init__(self, vector25_dir):
        self.sheets = []
        for path in sorted(glob.glob(os.path.join(vector25_dir, "*", "smv25_chlv95ln02.gpkg"))):
            ds = ogr.Open(path)
            layer = ds.GetLayerByName("T62_DKM25_HOEHENKURVE")
            self.sheets.append((ds, layer, layer.GetExtent()))  # extent: (minx, maxx, miny, maxy)

    def by_elevation(self, minx, miny, maxx, maxy):
        """{elevation: MultiLineString} of the contours in the box."""
        lines = collections.defaultdict(lambda: ogr.Geometry(ogr.wkbMultiLineString))
        for _, layer, (ex0, ex1, ey0, ey1) in self.sheets:
            if ex1 < minx or ex0 > maxx or ey1 < miny or ey0 > maxy:
                continue
            layer.SetSpatialFilterRect(minx, miny, maxx, maxy)
            for f in layer:
                geom = f.GetGeometryRef()
                if geom is None:
                    continue
                geom.FlattenTo2D()
                parts = [geom] if geom.GetGeometryType() == ogr.wkbLineString else [
                    geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]
                for part in parts:
                    lines[f.GetField("HOEHE")].AddGeometry(part)
            layer.SetSpatialFilter(None)
        return lines


def _grid_like(ref, dtype=gdal.GDT_Byte):
    grid = gdal.GetDriverByName("MEM").Create("", ref.RasterXSize, ref.RasterYSize, 1, dtype)
    grid.SetGeoTransform(ref.GetGeoTransform())
    grid.SetProjection(ref.GetProjection())
    return grid


def _burn(ref, geometries):
    """Boolean array: grid cells touched by the geometries."""
    grid = _grid_like(ref)
    ds = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = ds.CreateLayer("g", ref.GetSpatialRef())
    for geom in geometries:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(geom)
        layer.CreateFeature(feature)
    gdal.RasterizeLayer(grid, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    return grid.GetRasterBand(1).ReadAsArray() == 1


def _distance(ref, mask):
    """Distance in metres from each cell to the nearest True cell of mask."""
    src = _grid_like(ref)
    src.GetRasterBand(1).WriteArray(mask.astype("uint8"))
    dist = _grid_like(ref, gdal.GDT_Float32)
    gdal.ComputeProximity(src.GetRasterBand(1), dist.GetRasterBand(1), ["VALUES=1", "DISTUNITS=GEO"])
    return dist.GetRasterBand(1).ReadAsArray()


def fill_region(ref, ice, band_area, v25_lines, clear):
    """Polygon where glacier contours go: the ice, plus the parts of the band around it that
    have no Vector25 contour within `clear` metres (grown back by `clear`). Computed on the
    DEM grid; vector buffers of all Vector25 contours are far too slow."""
    in_band = _burn(ref, [band_area])
    on_ice = _burn(ref, [ice])
    lines = [g for multi in v25_lines.values() for g in
             (multi.GetGeometryRef(i) for i in range(multi.GetGeometryCount()))]
    if lines:
        free = _distance(ref, _burn(ref, lines)) > clear
        grown = _distance(ref, free) <= clear if free.any() else free
    else:
        grown = in_band
    mask = (on_ice | grown) & in_band
    if not mask.any():
        return None
    src = _grid_like(ref)
    src.GetRasterBand(1).WriteArray(mask.astype("uint8"))
    ds = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = ds.CreateLayer("fill", ref.GetSpatialRef(), ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(src.GetRasterBand(1), src.GetRasterBand(1), layer, 0)
    region = ogr.Geometry(ogr.wkbMultiPolygon)
    for f in layer:
        region.AddGeometry(f.GetGeometryRef())
    return region


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("glaciers", help="Glacier polygons GeoPackage in EPSG:2056")
    parser.add_argument("output", help="Output .gpkg")
    parser.add_argument("dems", nargs="+", help="swissALTI3D GeoTIFFs in EPSG:2056")
    parser.add_argument("--interval", type=float, default=20.0, help="Contour interval in m")
    parser.add_argument("--cell", type=float, default=10.0, help="Resampled cell size in m")
    parser.add_argument("--vector25-dir", required=True,
                        help="Directory with <sheet>/smv25_chlv95ln02.gpkg (contours to join)")
    parser.add_argument("--band", type=float, default=400.0,
                        help="Keep contours up to this distance around the glaciers, in m")
    parser.add_argument("--clear", type=float, default=75.0,
                        help="Outside the ice, fill only where Vector25 has no contour this close")
    parser.add_argument("--gap", type=float, default=30.0,
                        help="Drop contour parts this close to a Vector25 contour of the same height")
    args = parser.parse_args()
    v25 = Vector25Contours(args.vector25_dir)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2056)
    glacier_ds = ogr.Open(args.glaciers)
    glacier_layer = glacier_ds.GetLayer(0)

    if os.path.exists(args.output):
        os.remove(args.output)
    out = ogr.GetDriverByName("GPKG").CreateDataSource(args.output)
    out_layer = out.CreateLayer("contours", srs, ogr.wkbLineString)
    out_layer.CreateField(ogr.FieldDefn("ele", ogr.OFTInteger))
    out_layer.CreateField(ogr.FieldDefn("on_ice", ogr.OFTInteger))
    defn = out_layer.GetLayerDefn()

    total = 0
    for path in args.dems:
        dem = gdal.Open(path)
        gt = dem.GetGeoTransform()
        minx, maxy = gt[0], gt[3]
        maxx, miny = minx + gt[1] * dem.RasterXSize, maxy + gt[5] * dem.RasterYSize
        ice = glaciers_in(glacier_layer, minx - args.band, miny - args.band,
                          maxx + args.band, maxy + args.band)
        if ice is None:
            continue
        # Area to fill: the glaciers plus a band around them, within this tile.
        box = ogr.CreateGeometryFromWkt(
            f"POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))")
        band_area = ice.Buffer(args.band, 4).Intersection(box)
        if band_area is None or band_area.IsEmpty():
            continue
        ex = band_area.GetEnvelope()  # (minx, maxx, miny, maxy)
        margin = 3 * args.cell
        bounds = (max(minx, ex[0] - margin), max(miny, ex[2] - margin),
                  min(maxx, ex[1] + margin), min(maxy, ex[3] + margin))
        warped = gdal.Warp("", dem, format="MEM", resampleAlg="average",
                           xRes=args.cell, yRes=args.cell, outputBounds=bounds)
        pad = max(args.gap, args.clear)
        v25_lines = v25.by_elevation(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)
        region = fill_region(warped, ice, band_area, v25_lines, args.clear)
        if region is None:
            continue
        v25_near = {}  # elevation -> buffer around the Vector25 contours of that height
        band = warped.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        tmp = ogr.GetDriverByName("Memory").CreateDataSource("")
        raw = tmp.CreateLayer("raw", srs, ogr.wkbLineString)
        raw.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
        raw.CreateField(ogr.FieldDefn("ele", ogr.OFTReal))
        gdal.ContourGenerate(band, args.interval, 0, [], 1 if nodata is not None else 0,
                             nodata or 0, raw, 0, 1)
        n = 0
        out_layer.StartTransaction()
        for f in raw:
            ele = int(round(f.GetField("ele")))
            piece = f.GetGeometryRef().Intersection(region)
            if piece is None or piece.IsEmpty():
                continue
            if ele in v25_lines:
                if ele not in v25_near:
                    v25_near[ele] = v25_lines[ele].Buffer(args.gap, 4)
                piece = piece.Difference(v25_near[ele])
                if piece is None or piece.IsEmpty():
                    continue
            # Split into the parts on and off the ice: off-ice parts are drawn as normal contours.
            for on_ice, part in ((1, piece.Intersection(ice)), (0, piece.Difference(ice))):
                if part is None or part.IsEmpty():
                    continue
                lines = [part] if part.GetGeometryType() == ogr.wkbLineString else [
                    part.GetGeometryRef(i) for i in range(part.GetGeometryCount())]
                for line in lines:
                    if line.GetGeometryType() != ogr.wkbLineString or line.Length() < 2 * args.cell:
                        continue
                    feature = ogr.Feature(defn)
                    feature.SetGeometry(line)
                    feature.SetField("ele", ele)
                    feature.SetField("on_ice", on_ice)
                    out_layer.CreateFeature(feature)
                    n += 1
        out_layer.CommitTransaction()
        total += n
        print(f"{os.path.basename(path)}: {n} glacier contour lines", flush=True)
    print(f"{total} glacier contour lines in {args.output}")


if __name__ == "__main__":
    main()
