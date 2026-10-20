#!/usr/bin/env python3
"""Command-line entrypoint for the document index.

Usage:
    index-docs <folder> [--reindex]     # build/update the index (slow; run in background)
    index-docs --search "query" [-k 8]  # search the index
"""

import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from server import index_docs, search_docs


def main() -> None:
    parser = argparse.ArgumentParser(prog="index-docs")
    parser.add_argument("folder", nargs="?", default="", help="Folder to index")
    parser.add_argument("--reindex", action="store_true", help="Re-embed every file")
    parser.add_argument("--search", default="", help="Search instead of indexing")
    parser.add_argument("-k", type=int, default=8, help="Results to return when searching")
    args = parser.parse_args()

    if args.search:
        print(search_docs(args.search, k=args.k, folder=args.folder))
    elif args.folder:
        print(index_docs(args.folder, reindex=args.reindex))
    else:
        parser.error("give a folder to index, or --search \"query\"")


if __name__ == "__main__":
    main()
