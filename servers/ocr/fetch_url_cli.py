#!/usr/bin/env python3
"""Command-line entrypoint for local webpage text extraction.

Usage:
    fetch-url <url>
"""

import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from server import fetch_url


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fetch-url",
        description="Fetch a webpage and print its main readable text (no JS rendering).",
    )
    parser.add_argument("url", help="Page URL (http/https)")
    args = parser.parse_args()

    result = fetch_url(args.url)
    print(result)
    if result.startswith("Error:"):
        sys.exit(1)


if __name__ == "__main__":
    main()
