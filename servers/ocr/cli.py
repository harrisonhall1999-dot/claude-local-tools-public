#!/usr/bin/env python3
"""Command-line entrypoint for local OCR (PaddleOCR).

Usage:
    ocr <path/to/file.png|jpg|pdf> [--dpi 300]

Prints extracted text to stdout. All model-loading log noise goes to
stderr, so output is safe to pipe.
"""

import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from server import ocr


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ocr", description="Extract text from a local image or PDF using PaddleOCR."
    )
    parser.add_argument("path", help="Path to an image or PDF file")
    parser.add_argument(
        "--dpi", type=int, default=300, help="PDF rasterization DPI (default: 300)"
    )
    args = parser.parse_args()

    result = ocr(args.path, dpi=args.dpi)
    print(result)
    if result.startswith("Error:"):
        sys.exit(1)


if __name__ == "__main__":
    main()
