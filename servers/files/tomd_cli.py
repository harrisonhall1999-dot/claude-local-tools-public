#!/usr/bin/env python3
"""Command-line entrypoint for converting files and web pages to Markdown.

Usage:
    to-md [-o DIR | --out FILE] [--overwrite] [--links] <file|folder|glob|url> ...
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tomd import to_markdown


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="to-md",
        description="Convert files (PDF, Word, PowerPoint, Excel, HTML, EPUB...) and web pages "
                    "to Markdown on disk, keeping headings, footnotes, lists and page markers, "
                    "and report how much of the source's text made it in.",
    )
    parser.add_argument("sources", nargs="+", help="Files, folders, globs or http(s) URLs")
    parser.add_argument("-o", "--output-dir", default="", help="Folder to write into")
    parser.add_argument("--out", default="", help="Exact output file (one source only)")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing .md files")
    parser.add_argument("--links", action="store_true", help="Keep hyperlinks from web pages")
    args = parser.parse_args()

    result = to_markdown(args.sources, args.output_dir, args.out, args.overwrite, args.links)
    print(result)
    if result.startswith("Error:"):
        sys.exit(1)


if __name__ == "__main__":
    main()
