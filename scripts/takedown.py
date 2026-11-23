#!/usr/bin/env python3
"""Check a takedown record and name the release asset to delete."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tomllib


class TakedownError(Exception):
    """A takedown input or record is invalid."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify the revoked record")
    mode.add_argument("--names", action="store_true", help="print the tar and sidecar names")
    parser.add_argument(
        "--repo",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help="registry checkout root",
    )
    parser.add_argument("--assets", type=pathlib.Path, help="directory of downloaded sidecars")
    parser.add_argument(
        "--release-assets",
        type=pathlib.Path,
        help="release assets JSON from gh release view",
    )
    parser.add_argument("--namespace")
    parser.add_argument("--name")
    parser.add_argument("--digest", required=True)
    return parser.parse_args(argv)


def load_revoked(repo: pathlib.Path) -> list[dict]:
    try:
        data = tomllib.loads((repo / "revoked.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise TakedownError(f"cannot read revoked.toml: {error}") from error
    records = data.get("revoked")
    if not isinstance(records, list):
        raise TakedownError("revoked.toml has no revoked list")
    return records


def check_record(repo: pathlib.Path, namespace: str, name: str, digest: str) -> None:
    for record in load_revoked(repo):
        if (
            record.get("namespace"),
            record.get("name"),
            record.get("digest"),
        ) == (namespace, name, digest):
            return
    raise TakedownError(
        f"revoked.toml has no record for {namespace}/{name} {digest}; open a pull request first"
    )


def sidecar_names(
    assets: pathlib.Path, digest: str, release_assets: pathlib.Path | None = None
) -> tuple[str, str]:
    for path in sorted(assets.glob("*.json")):
        try:
            sidecar = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TakedownError(f"invalid sidecar {path}: {error}") from error
        if sidecar.get("digest") != digest:
            continue
        asset_digest = sidecar.get("asset_digest")
        version = sidecar.get("version")
        if not isinstance(asset_digest, str) or not isinstance(version, str):
            raise TakedownError(f"sidecar {path} has no asset_digest or version")
        tar = f"{asset_digest}.tar"
        if release_assets is not None:
            try:
                published = json.loads(release_assets.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise TakedownError(f"invalid release assets JSON: {error}") from error
            for asset in published.get("assets", []):
                if (
                    asset.get("digest") == asset_digest
                    and isinstance(asset.get("name"), str)
                    and asset["name"].endswith(".tar")
                ):
                    tar = asset["name"]
                    break
        return tar, f"{version}.json"
    raise TakedownError(f"no sidecar in {assets} matches {digest}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.check:
            for field in ("namespace", "name"):
                if not getattr(args, field):
                    raise TakedownError(f"--{field} is required with --check")
            check_record(args.repo, args.namespace, args.name, args.digest)
            print(f"recorded: {args.namespace}/{args.name} {args.digest}")
            return 0
        if args.assets is None:
            raise TakedownError("--assets is required with --names")
        tar, sidecar = sidecar_names(args.assets, args.digest, args.release_assets)
        print(f"{tar}\t{sidecar}")
        return 0
    except TakedownError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
