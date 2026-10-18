#!/usr/bin/env python3
"""Count feature categories across all swiss-map-vector25 sheets.

Writes a TSV of layer / attribute / value / count, deduplicated by DKM_UUID,
used to drive the tag mapping in vector25_translation.py.
"""
import argparse
import collections
import glob
import os
import sqlite3

# Extra attributes to tally per layer besides OBJEKTART.
EXTRA_ATTRS = {
    "T45_DKM25_STRASSE": ["WANDERWEG", "KUNSTBAUTE", "BELAGSART", "BEFAHRBAR", "RICHT_GETR"],
    "T44_DKM25_EISENBAHN": ["KUNSTBAUTE"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vector25_dir", help="Directory with <sheet>/smv25_chlv95ln02.gpkg")
    parser.add_argument("output", help="Output TSV")
    args = parser.parse_args()

    counts = collections.Counter()
    seen = collections.defaultdict(set)
    gpkgs = sorted(glob.glob(os.path.join(args.vector25_dir, "*", "smv25_chlv95ln02.gpkg")))
    for gpkg in gpkgs:
        con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
        layers = [r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")]
        for layer in layers:
            if layer.endswith("_ANNO"):
                continue
            cols = {r[1] for r in con.execute(f'PRAGMA table_info("{layer}")')}
            if "DKM_UUID" not in cols or "OBJEKTART" not in cols:
                continue
            attrs = ["OBJEKTART"] + [a for a in EXTRA_ATTRS.get(layer, []) if a in cols]
            for row in con.execute(f'SELECT DKM_UUID, {", ".join(attrs)} FROM "{layer}"'):
                if row[0] in seen[layer]:
                    continue
                seen[layer].add(row[0])
                for attr, value in zip(attrs, row[1:]):
                    counts[(layer, attr, value)] += 1
        con.close()
        print(f"{os.path.basename(os.path.dirname(gpkg))}", end=" ", flush=True)
    print()

    with open(args.output, "w") as f:
        f.write("layer\tattribute\tvalue\tcount\n")
        for (layer, attr, value), n in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1], -kv[1])):
            f.write(f"{layer}\t{attr}\t{value}\t{n}\n")


if __name__ == "__main__":
    main()
