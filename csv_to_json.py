#!/usr/bin/env python3
"""
CSV to JSON Converter

Converts CSV files to JSON format with support for:
- Custom delimiters
- Output to file or stdout
- Pretty printing
- Type inference for numeric values
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def parse_value(value: str) -> int | float | str:
    """Attempt to parse a string value as int, float, or keep as string."""
    value = value.strip()

    if not value:
        return value

    # Try integer first
    try:
        return int(value)
    except ValueError:
        pass

    # Try float
    try:
        return float(value)
    except ValueError:
        pass

    return value


def csv_to_json(
    csv_path: str,
    delimiter: str = ",",
    infer_types: bool = True,
) -> list[dict]:
    """
    Convert a CSV file to a list of dictionaries.

    Args:
        csv_path: Path to the CSV file
        delimiter: CSV delimiter character
        infer_types: Whether to infer numeric types from string values

    Returns:
        List of dictionaries representing CSV rows
    """
    path = Path(csv_path)

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {csv_path}")

    records = []

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)

        for row in reader:
            if infer_types:
                row = {key: parse_value(value) for key, value in row.items()}
            records.append(row)

    return records


def main() -> int:
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Convert CSV files to JSON format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.csv                     # Output to stdout
  %(prog)s input.csv -o output.json      # Output to file
  %(prog)s input.csv --pretty            # Pretty-printed output
  %(prog)s input.csv -d ";"              # Use semicolon delimiter
  %(prog)s input.csv --no-type-inference # Keep all values as strings
        """,
    )

    parser.add_argument("csv_file", help="Path to the input CSV file")
    parser.add_argument(
        "-o", "--output",
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument(
        "-d", "--delimiter",
        default=",",
        help="CSV delimiter (default: comma)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output with indentation",
    )
    parser.add_argument(
        "--no-type-inference",
        action="store_true",
        help="Keep all values as strings (don't convert to int/float)",
    )

    args = parser.parse_args()

    try:
        records = csv_to_json(
            args.csv_file,
            delimiter=args.delimiter,
            infer_types=not args.no_type_inference,
        )

        indent = 2 if args.pretty else None
        json_output = json.dumps(records, indent=indent, ensure_ascii=False)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(json_output + "\n", encoding="utf-8")
            print(f"Written to {args.output}", file=sys.stderr)
        else:
            print(json_output)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
