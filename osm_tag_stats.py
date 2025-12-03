import xml.etree.ElementTree as ET
import argparse
from collections import defaultdict, Counter
import sys

def parse_osm_tags(file_path):
    # Dictionary to store stats: key -> value -> count
    tag_stats = defaultdict(Counter)
    total_elements = 0

    print(f"Parsing {file_path}...")

    try:
        # Use iterparse to handle large files without loading everything into memory
        context = ET.iterparse(file_path, events=('end',))

        for event, elem in context:
            if elem.tag in ('node', 'way', 'relation'):
                total_elements += 1

                # Iterate through tag children
                for tag in elem.findall('tag'):
                    k = tag.get('k')
                    v = tag.get('v')
                    if k is not None:
                        tag_stats[k][v] += 1

                # Clear element to save memory
                elem.clear()

    except ET.ParseError as e:
        print(f"Error parsing XML: {e}")
        return None
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None

    return tag_stats, total_elements

def print_stats(tag_stats, total_elements, top_n_values=5):
    print(f"\nTotal elements processed (node/way/relation): {total_elements}")
    print(f"Total unique keys found: {len(tag_stats)}")
    print("-" * 60)

    # Sort keys by total usage (sum of all value counts for that key)
    sorted_keys = sorted(tag_stats.items(), key=lambda item: sum(item[1].values()), reverse=True)

    for k, value_counts in sorted_keys:
        total_usage = sum(value_counts.values())
        print(f"Key: '{k}' (Total occurrences: {total_usage})")

        # Print top values for this key
        print(f"  Top {top_n_values} values:")
        for v, count in value_counts.most_common(top_n_values):
            print(f"    '{v}': {count}")

        unique_values = len(value_counts)
        if unique_values > top_n_values:
            print(f"    ... and {unique_values - top_n_values} more unique values")
        print("-" * 60)

def main():
    parser = argparse.ArgumentParser(description="Generate statistics for OSM tags from an XML file.")
    parser.add_argument("file", help="Path to the OSM XML file")
    parser.add_argument("--top-values", type=int, default=10, help="Number of top values to display per key")

    args = parser.parse_args()

    result = parse_osm_tags(args.file)
    if result:
        stats, count = result
        print_stats(stats, count, args.top_values)

if __name__ == "__main__":
    main()
