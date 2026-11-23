#!/usr/bin/env python3
"""List the changed image directories from a newline-separated file list."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


def changed(lines: list[str], root: pathlib.Path) -> list[str]:
    """Return the sorted image directories that the paths touch."""
    result = set()
    for line in lines:
        text = line.strip()
        if not text:
            continue
        parts = pathlib.PurePosixPath(text).parts
        if len(parts) < 3 or parts[0] != "images":
            continue
        image = root.joinpath(*parts[:3])
        if image.is_dir():
            result.add(image.relative_to(root).as_posix())
    return sorted(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    images = changed(sys.stdin.read().splitlines(), args.root)
    if args.json:
        print(json.dumps(images))
    else:
        for image in images:
            print(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
