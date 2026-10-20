#!/usr/bin/env python3
"""Command-line entrypoint for the local LLM.

Usage:
    local-llm "instruction" [FILE_OR_GLOB ...] [--batch --out DIR] [--model M] [--think]
    echo "text" | local-llm "instruction"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="local-llm",
        description="Run an instruction on the local Ollama model over text or files.",
    )
    parser.add_argument("instruction")
    parser.add_argument("paths", nargs="*", help="Files or globs")
    parser.add_argument("--batch", action="store_true",
                        help="Apply the instruction to each file separately")
    parser.add_argument("--out", help="With --batch, write one .md result per file here")
    parser.add_argument("--model", default=core.DEFAULT_MODEL)
    parser.add_argument("--think", action="store_true")
    args = parser.parse_args()

    # Read piped text only when no files are given (or "-" is passed), so a
    # caller with an idle, never-closed stdin doesn't hang.
    read_stdin = "-" in args.paths or (not args.paths and not sys.stdin.isatty())
    args.paths = [p for p in args.paths if p != "-"]
    text = sys.stdin.read() if read_stdin else ""
    try:
        if args.batch:
            print(core.run_batch(args.instruction, args.paths, args.model, args.think, args.out))
        else:
            print(core.run(args.instruction, text, args.paths, args.model, args.think))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
