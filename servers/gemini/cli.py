#!/usr/bin/env python3
"""Command-line entrypoint for Gemini offloading (via the Antigravity CLI).

Public material only: the input is sent to Google.

Usage:
    gemini-offload "instruction" [FILE_OR_GLOB ...] [--batch --out DIR] [--model M]
    echo "text" | gemini-offload "instruction"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agy


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gemini-offload",
        description="Run an instruction on Gemini (via agy) over text or files. Public material only.",
    )
    parser.add_argument("instruction")
    parser.add_argument("paths", nargs="*", help="Files or globs")
    parser.add_argument("--batch", action="store_true",
                        help="Apply the instruction to each file separately")
    parser.add_argument("--out", help="With --batch, a folder for one .md per file; "
                                      "otherwise a file to write the answer to")
    parser.add_argument("--model", default=agy.DEFAULT_MODEL)
    args = parser.parse_args()

    # Read piped text only when no files are given (or "-" is passed), so a
    # caller with an idle, never-closed stdin doesn't hang.
    read_stdin = "-" in args.paths or (not args.paths and not sys.stdin.isatty())
    args.paths = [p for p in args.paths if p != "-"]
    text = sys.stdin.read() if read_stdin else ""
    try:
        if args.batch:
            print(agy.run_batch(args.instruction, args.paths, args.model, args.out))
        else:
            print(agy.run(args.instruction, text, args.paths, args.model, args.out))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
