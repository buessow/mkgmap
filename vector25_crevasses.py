#!/usr/bin/env python3
"""Trace crevasses from a swiss-map-vector25 glacier drawing (glet.tif) as lines.

glet.tif is a 1.25 m cartographic drawing (0 = ink) that holds only the crevasse strokes, so
it can't be turned into glacier areas the way vector25_raster_areas.py does for rock and
scree. Instead each stroke becomes one line: the ink is reduced to a 2.5 m grid ("any ink"),
polygonized into connected strokes, and each stroke's centre line is traced along its long
axis - split into ~15 m pieces, each piece's points averaged across the axis - so the curved
crescent strokes keep their shape. Specks and roundish blobs (labels, dots) are dropped; that
also drops the teeth of the comb hachures along glacier edges, keeping their base lines, which
the printed map draws in the same blue.
Result: lines in EPSG:2056 as GeoPackage. Run with the conda ogr2osm python (GDAL + numpy).
"""
import argparse
import os

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()


def centre_line(points, step):
    """Centre line of a stroke outline: points along the principal axis, averaged per piece."""
    mean = points.mean(axis=0)
    centred = points - mean
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    along = centred @ vt[0]
    lo, hi = along.min(), along.max()
    pieces = max(1, int(round((hi - lo) / step)))
    edges = np.linspace(lo, hi, pieces + 1)
    line = []
    for i in range(pieces):
        inside = (along >= edges[i]) & (along <= edges[i + 1])
        if inside.any():
            line.append(points[inside].mean(axis=0))
    # Extend to the stroke's ends, so short strokes keep their length.
    across = centred @ vt[1]
    start = mean + vt[0] * lo + vt[1] * across[along.argmin()]
    end = mean + vt[0] * hi + vt[1] * across[along.argmax()]
    return np.vstack([start, *line, end]) if line else np.vstack([start, end])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="glet.tif")
    parser.add_argument("output", help="Output .gpkg")
    parser.add_argument("--factor", type=int, default=2, help="Raster reduction factor")
    parser.add_argument("--min-length", type=float, default=6.0, help="Min stroke length in m")
    parser.add_argument("--min-elongation", type=float, default=2.5, help="Min length/width")
    parser.add_argument("--step", type=float, default=15.0, help="Centre line point spacing in m")
    args = parser.parse_args()

    src = gdal.Open(args.input)
    gt = src.GetGeoTransform()
    band = src.GetRasterBand(1)
    f = args.factor
    nx, ny = src.RasterXSize // f, src.RasterYSize // f
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2056)
    mem = gdal.GetDriverByName("MEM").Create("", nx, ny, 1, gdal.GDT_Byte)
    mem.SetGeoTransform((gt[0], gt[1] * f, 0, gt[3], 0, gt[5] * f))
    mem.SetProjection(srs.ExportToWkt())
    mband = mem.GetRasterBand(1)
    strip = 512  # rows of the reduced grid per read, to bound memory
    for y0 in range(0, ny, strip):
        rows = min(strip, ny - y0)
        block = band.ReadAsArray(0, y0 * f, nx * f, rows * f)
        ink = (block == 0).reshape(rows, f, nx, f).any(axis=(1, 3))
        mband.WriteArray(ink.astype(np.uint8), 0, y0)

    tmp = ogr.GetDriverByName("Memory").CreateDataSource("")
    strokes = tmp.CreateLayer("strokes", srs, ogr.wkbPolygon)
    strokes.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(mband, mband, strokes, 0)

    if os.path.exists(args.output):
        os.remove(args.output)
    out = ogr.GetDriverByName("GPKG").CreateDataSource(args.output)
    out_layer = out.CreateLayer("crevasses", srs, ogr.wkbLineString)
    defn = out_layer.GetLayerDefn()
    kept = 0
    out_layer.StartTransaction()
    for stroke in strokes:
        ring = stroke.GetGeometryRef().GetGeometryRef(0)
        points = np.array(ring.GetPoints())[:, :2]
        centred = points - points.mean(axis=0)
        _, _, vt = np.linalg.svd(centred, full_matrices=False)
        length = np.ptp(centred @ vt[0])
        width = max(np.ptp(centred @ vt[1]), 0.1)
        if length < args.min_length or length / width < args.min_elongation:
            continue
        line = ogr.Geometry(ogr.wkbLineString)
        for x, y in centre_line(points, args.step):
            line.AddPoint_2D(float(x), float(y))
        feature = ogr.Feature(defn)
        feature.SetGeometry(line)
        out_layer.CreateFeature(feature)
        kept += 1
    out_layer.CommitTransaction()
    print(f"{args.input}: {kept} crevasses from {strokes.GetFeatureCount()} strokes")


if __name__ == "__main__":
    main()
