#!/usr/bin/env python3
"""Command-line entrypoint for local Office document text extraction.

Usage:
    read-document <path/to/file.docx|pptx|xlsx>
"""

import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from server import read_document


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="read-document",
        description="Extract text from a local .docx/.pptx/.xlsx file.",
    )
    parser.add_argument("path", help="Path to a .docx, .pptx, or .xlsx file")
    args = parser.parse_args()

    result = read_document(args.path)
    print(result)
    if result.startswith("Error:"):
        sys.exit(1)


if __name__ == "__main__":
    main()
