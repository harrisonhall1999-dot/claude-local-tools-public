#!/usr/bin/env python3
"""Command-line entrypoint for local audio/video transcription (MLX Whisper).

Usage:
    transcribe <path/to/file.mp3|wav|m4a|mp4|mov> [--out transcript.txt]
               [--num-speakers N] [--names "Ana (host), Ben"]
               [--context "topic, ACRONYM, Name"] [--language en]
               [--no-speakers] [--model mlx-community/whisper-base-mlx]
    transcribe --rename transcript.txt "Speaker 1=Ana" "Speaker 2=Ben"
"""

import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from server import TRANSCRIBE_MODEL, rename_speakers, transcribe


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="transcribe",
        description="Transcribe a local audio/video file to text using local MLX Whisper.",
    )
    parser.add_argument("path", help="Audio or video file (or, with --rename, a transcript)")
    parser.add_argument("labels", nargs="*",
                        help='With --rename: "Speaker N=Name" pairs')
    parser.add_argument("--out", default="", help="Save the transcript to this file")
    parser.add_argument(
        "--model",
        default=TRANSCRIBE_MODEL,
        help="MLX Whisper model repo (default: whisper-large-v3-turbo; "
        "use whisper-base-mlx for a faster, rougher pass)",
    )
    parser.add_argument("--no-speakers", action="store_true",
                        help="Don't label speakers (faster; blocks break at pauses)")
    parser.add_argument("--num-speakers", type=int, default=0,
                        help="How many people speak, if known (default: guess)")
    parser.add_argument("--names", default="",
                        help="Comma-separated speaker names, to spell them right")
    parser.add_argument("--context", default="",
                        help="Topic plus names, acronyms and terms, comma-separated")
    parser.add_argument("--language", default="", help='Language code, e.g. "es" (default: detect)')
    parser.add_argument("--rename", action="store_true",
                        help="Relabel speakers in an existing transcript instead")
    args = parser.parse_args()

    if args.rename:
        pairs = [label.split("=", 1) for label in args.labels]
        if not pairs or any(len(p) != 2 for p in pairs):
            parser.error('--rename needs "Speaker N=Name" pairs')
        result = rename_speakers(args.path, {k.strip(): v.strip() for k, v in pairs})
    else:
        result = transcribe(args.path, model=args.model, output_path=args.out,
                            speakers=not args.no_speakers, num_speakers=args.num_speakers,
                            speaker_names=args.names, context=args.context,
                            language=args.language)
    print(result)
    if result.startswith("Error:"):
        sys.exit(1)


if __name__ == "__main__":
    main()
