#!/usr/bin/env python3
"""Derive rock or scree area polygons from a swiss-map-vector25 raster.

The fels.tif / geroell.tif rasters are 1.25 m cartographic drawings (rock
hachures, scree dot patterns) where 0 = ink. They are not area masks, so the
ink density is computed on a coarser grid, smoothed with a box filter and
thresholded. Result: smooth polygons (EPSG:2056) written as GeoPackage.

Run with the conda ogr2osm python (GDAL 3.6 + numpy).
"""
import argparse
import os

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()


def box_filter(a, r):
    """Mean over a (2r+1)x(2r+1) window, edges padded with zeros."""
    k = 2 * r + 1
    p = np.pad(a, r + 1, mode="constant")
    c = p.cumsum(0).cumsum(1)
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s[:a.shape[0], :a.shape[1]] / (k * k)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="fels.tif or geroell.tif")
    parser.add_argument("output", help="Output .gpkg")
    parser.add_argument("--cell", type=float, default=5.0, help="Analysis cell size in m")
    parser.add_argument("--radius", type=int, default=3, help="Box filter radius in cells")
    parser.add_argument("--threshold", type=float, default=0.03, help="Min smoothed ink fraction")
    parser.add_argument("--min-area", type=float, default=2500, help="Min polygon area in m²")
    parser.add_argument("--simplify", type=float, default=4.0, help="Simplify tolerance in m")
    args = parser.parse_args()

    src = gdal.Open(args.input)
    gt = src.GetGeoTransform()
    factor = max(1, round(args.cell / gt[1]))
    nx, ny = src.RasterXSize // factor, src.RasterYSize // factor

    # Ink fraction per coarse cell, read in strips to bound memory.
    band = src.GetRasterBand(1)
    density = np.zeros((ny, nx), dtype=np.float32)
    strip = 256
    for y0 in range(0, ny, strip):
        rows = min(strip, ny - y0)
        block = band.ReadAsArray(0, y0 * factor, nx * factor, rows * factor)
        ink = (block == 0).reshape(rows, factor, nx, factor)
        density[y0:y0 + rows] = ink.mean(axis=(1, 3))

    mask = (box_filter(density, args.radius) >= args.threshold).astype(np.uint8)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2056)
    mem = gdal.GetDriverByName("MEM").Create("", nx, ny, 1, gdal.GDT_Byte)
    mem.SetGeoTransform((gt[0], gt[1] * factor, 0, gt[3], 0, gt[5] * factor))
    mem.SetProjection(srs.ExportToWkt())
    mband = mem.GetRasterBand(1)
    mband.WriteArray(mask)
    min_cells = int(args.min_area / (gt[1] * factor) ** 2)
    gdal.SieveFilter(mband, None, mband, min_cells, 8)

    tmp = ogr.GetDriverByName("Memory").CreateDataSource("")
    tmp_layer = tmp.CreateLayer("raw", srs, ogr.wkbPolygon)
    tmp_layer.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(mband, mband, tmp_layer, 0)

    if os.path.exists(args.output):
        os.remove(args.output)
    out = ogr.GetDriverByName("GPKG").CreateDataSource(args.output)
    out_layer = out.CreateLayer("areas", srs, ogr.wkbPolygon)
    defn = out_layer.GetLayerDefn()
    n = 0
    out_layer.StartTransaction()
    for f in tmp_layer:
        geom = f.GetGeometryRef().SimplifyPreserveTopology(args.simplify)
        if geom is None or geom.IsEmpty() or geom.GetArea() < args.min_area:
            continue
        of = ogr.Feature(defn)
        of.SetGeometry(geom)
        out_layer.CreateFeature(of)
        n += 1
    out_layer.CommitTransaction()
    print(f"{args.output}: {n} polygons")


if __name__ == "__main__":
    main()
