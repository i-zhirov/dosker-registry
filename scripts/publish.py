#!/usr/bin/env python3
"""Write the version sidecar and copy the image tar for a release.

The publisher is idempotent. It refuses a version that is already bound to a
different digest. A license correction is a new version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from generate_site import (  # noqa: E402
    SiteError,
    compact_json,
    license_summary,
    read_archive,
)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--asset", type=pathlib.Path, required=True)
    parser.add_argument("--release-dir", type=pathlib.Path, required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument(
        "--repo",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help="registry checkout root",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def is_revoked(repo: pathlib.Path, namespace: str, name: str, digest: str) -> bool:
    path = repo / "revoked.toml"
    if not path.is_file():
        return False
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for record in data.get("revoked", []):
        if (
            record.get("namespace"),
            record.get("name"),
            record.get("digest"),
        ) == (namespace, name, digest):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        data = args.asset.read_bytes()
        asset_digest = "sha256:" + hashlib.sha256(data).hexdigest()
        manifest_bytes, config_bytes, manifest_digest, config_digest = read_archive(
            args.asset, asset_digest, len(data)
        )
        del manifest_bytes
        namespace, name = args.image.split("/", 1)
        if is_revoked(args.repo, namespace, name, manifest_digest):
            print(f"skipping revoked {args.image} {manifest_digest}")
            return 0
        entries = json.loads(config_bytes).get("licenses")
        if not isinstance(entries, list):
            raise SiteError(f"image {args.image} has no license list")
        summary = license_summary(entries, args.image)
        sidecar = {
            "version": args.version,
            "digest": manifest_digest,
            "config_digest": config_digest,
            "license_summary": summary,
            "published_at": args.published_at,
            "asset_digest": asset_digest,
            "asset_size": len(data),
        }

        if args.dry_run:
            print(compact_json(sidecar).decode("utf-8").rstrip())
            return 0

        args.release_dir.mkdir(parents=True, exist_ok=True)
        tar_path = args.release_dir / f"{asset_digest}.tar"
        sidecar_path = args.release_dir / f"{args.version}.json"

        if sidecar_path.exists():
            existing = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if existing.get("digest") != manifest_digest:
                raise SiteError(
                    f"version {args.version} is bound to {existing.get('digest')}, "
                    f"not {manifest_digest}; bump the version"
                )
            if not tar_path.exists():
                shutil.copyfile(args.asset, tar_path)
            print(f"already published {args.image}:{args.version}")
            return 0

        shutil.copyfile(args.asset, tar_path)
        sidecar_path.write_bytes(compact_json(sidecar))
        print(f"published {args.image}:{args.version} {manifest_digest}")
        return 0
    except SiteError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
