import xml.etree.ElementTree as ET
import psycopg2
import sys
import os
import socket

try:
    import db_config
except ImportError:
    print("Error: db_config.py not found. Please create it with DB credentials.")
    sys.exit(1)

# Search Configuration
SEARCH_RADIUS_METERS = 100  # Distance to search for peaks
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Find and update peaks in OSM file.")
    parser.add_argument(
        "--osm-file",
        type=str,
        default="work/swiss-skitouring/ski_network_2056.osm",
        help="Input OSM file path",
    )
    parser.add_argument(
        "--output-osm-file",
        type=str,
        default="work/swiss-skitouring/ski_network_2056_updated.osm",
        help="Output OSM file path",
    )
    return parser.parse_args()

args = parse_args()
OSM_FILE = args.osm_file
OUTPUT_OSM_FILE = args.output_osm_file

def get_db_connection():
    try:
        # Make sure postgres supports IPv6
        conn = psycopg2.connect(
            host=db_config.DB_HOST,
            database=db_config.DB_NAME,
            user=db_config.DB_USER,
            password=db_config.DB_PASS,
            port=db_config.DB_PORT,
            sslmode='require'
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def parse_osm_nodes(file_path):
    """
    First pass: Extract all node coordinates into a dictionary.
    id -> (lat, lon)
    """
    print("Parsing nodes...")
    nodes = {}
    context = ET.iterparse(file_path, events=('end',))
    for event, elem in context:
        if elem.tag == 'node':
            try:
                lat = float(elem.attrib['lat'])
                lon = float(elem.attrib['lon'])
                nodes[elem.attrib['id']] = (lat, lon)
            except KeyError:
                pass
            elem.clear()
    return nodes

def find_peak_by_geometry(cursor, wkt_geometry, radius_meters):
    """
    Finds the highest peak within radius_meters of the given WKT geometry.
    Returns name or None.
    """
    query = """
        WITH input AS (
          SELECT ST_GeomFromText(%s, 4326)::geography AS geo
        )
        SELECT name,
               elevation,
               ST_Distance(geog, input.geo) as distance
          FROM peak CROSS JOIN input
         WHERE ST_DWithin(geog, input.geo, %s)
         ORDER BY elevation DESC NULLS LAST
         LIMIT 1
    """
    cursor.execute(query, (wkt_geometry, radius_meters))
    result = cursor.fetchone()
    if result:
        return result[0]
    return None

def process_and_update_osm(file_path, output_path, nodes, conn):
    """
    Second pass: Iterate ways, query DB, update XML, and write to new file.
    """
    print(f"Processing ways, querying DB, and writing to {output_path}...")
    cursor = conn.cursor()

    count = 0
    matched_count = 0

    with open(output_path, 'wb') as f_out:
        f_out.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')

        # We need to capture the root element to get its attributes,
        # but iterate events to process children.
        context = ET.iterparse(file_path, events=('start', 'end'))
        context = iter(context)

        # Get root element
        event, root = next(context)

        # Write root tag with attributes
        attrs = ' '.join([f'{k}="{v}"' for k, v in root.attrib.items()])
        f_out.write(f'<osm {attrs}>\n'.encode('utf-8'))

        for event, elem in context:
            if event == 'end':
                if elem.tag == 'node':
                    f_out.write(ET.tostring(elem, encoding='utf-8'))
                    root.clear() # Clear memory

                elif elem.tag == 'way':
                    way_id = elem.attrib['id']

                    # 1. Check for nearby peaks
                    peak_name = None

                    # Extract node refs
                    node_refs = []
                    for child in elem:
                        if child.tag == 'nd':
                            node_refs.append(child.attrib['ref'])

                    # Construct LineString geometry
                    valid_coords = []
                    for ref in node_refs:
                        if ref in nodes:
                            lat, lon = nodes[ref]
                            valid_coords.append(f"{lon} {lat}")

                    if len(valid_coords) >= 2:
                        linestring_wkt = f"LINESTRING({', '.join(valid_coords)})"

                        try:
                            peak_name = find_peak_by_geometry(cursor, linestring_wkt, SEARCH_RADIUS_METERS)

                            if peak_name:
                                matched_count += 1
                        except Exception as e:
                            print(f"Query error for way {way_id}: {e}")
                            conn.rollback()

                    # 2. Modify Element if peak found
                    if peak_name:
                        # Check if name tag exists, maybe append or ignore?
                        # User request: "add an entry <tag k="name" v=PEAK_NAME />"
                        ET.SubElement(elem, 'tag', {'k': 'name', 'v': peak_name})

                    # 3. Write Element
                    f_out.write(ET.tostring(elem, encoding='utf-8'))

                    root.clear()
                    count += 1
                    if count % 1000 == 0:
                        print(f"Processed {count} ways (Matched: {matched_count})...")

                elif elem.tag == 'relation':
                    f_out.write(ET.tostring(elem, encoding='utf-8'))
                    root.clear()

        f_out.write(b'</osm>')

    cursor.close()
    print(f"Done. Total ways matched with peaks: {matched_count}")

def main():
    if not os.path.exists(OSM_FILE):
        print(f"File not found: {OSM_FILE}")
        return

    # 1. Parse Nodes
    nodes = parse_osm_nodes(OSM_FILE)
    print(f"Loaded {len(nodes)} nodes.")

    # 2. Connect DB
    conn = get_db_connection()

    # 3. Process Ways and Update OSM
    process_and_update_osm(OSM_FILE, OUTPUT_OSM_FILE, nodes, conn)

    conn.close()

if __name__ == "__main__":
    main()
