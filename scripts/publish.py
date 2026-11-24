#!/usr/bin/env python3
"""Write the version sidecar and the compressed image asset for a release.

The publisher is idempotent. It refuses a version that is already bound to a
different digest. A license correction is a new version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from asset_compression import asset_name, compress  # noqa: E402
from content import ContentError, content_digest  # noqa: E402
from generate_site import (  # noqa: E402
    SiteError,
    compact_json,
    license_summary,
    read_tar_bytes,
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


def revoked_digests(repo: pathlib.Path, namespace: str, name: str) -> set[str]:
    path = repo / "revoked.toml"
    if not path.is_file():
        return set()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        record["digest"]
        for record in data.get("revoked", [])
        if (
            record.get("namespace"),
            record.get("name"),
        ) == (namespace, name)
        and isinstance(record.get("digest"), str)
    }


def load_existing(release_dir: pathlib.Path) -> dict[str, dict]:
    existing: dict[str, dict] = {}
    if not release_dir.is_dir():
        return existing
    for path in sorted(release_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SiteError(f"invalid sidecar {path}: {error}") from error
        version = value.get("version") if isinstance(value, dict) else None
        if isinstance(version, str):
            existing[version] = value
    return existing


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        tar_data = args.asset.read_bytes()
        manifest_bytes, config_bytes, manifest_digest, config_digest = read_tar_bytes(
            tar_data, args.asset
        )
        compressed = compress(tar_data)
        asset_digest = "sha256:" + hashlib.sha256(compressed).hexdigest()
        asset_size = len(compressed)
        namespace, name = args.image.split("/", 1)
        revoked = revoked_digests(args.repo, namespace, name)
        content = content_digest(manifest_bytes)
        existing = load_existing(args.release_dir)
        if args.version in existing and existing[args.version].get("digest") in revoked:
            print(f"skipping revoked {args.image} {existing[args.version]['digest']}")
            return 0
        revoked_content = {
            sidecar["content_digest"]
            for sidecar in existing.values()
            if sidecar.get("digest") in revoked
            and isinstance(sidecar.get("content_digest"), str)
        }
        if content in revoked_content:
            raise SiteError(
                f"image {args.image} content is revoked; "
                "change the content before publishing a new version"
            )
        if manifest_digest in revoked:
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
            "asset_size": asset_size,
            "asset_compression": "zstd",
            "content_digest": content,
        }

        if args.dry_run:
            print(compact_json(sidecar).decode("utf-8").rstrip())
            return 0

        args.release_dir.mkdir(parents=True, exist_ok=True)
        asset_path = args.release_dir / asset_name(asset_digest)
        sidecar_path = args.release_dir / f"{args.version}.json"

        if sidecar_path.exists():
            existing = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if existing.get("digest") != manifest_digest:
                raise SiteError(
                    f"version {args.version} is bound to {existing.get('digest')}, "
                    f"not {manifest_digest}; bump the version"
                )
            if existing.get("asset_compression") != "zstd":
                raise SiteError(
                    f"version {args.version} is not migrated to zstd; "
                    "run scripts/migrate_assets.py"
                )
            if existing.get("asset_digest") != asset_digest:
                raise SiteError(
                    f"version {args.version} is bound to asset "
                    f"{existing.get('asset_digest')}, not {asset_digest}; "
                    "bump the version"
                )
            if not asset_path.exists():
                asset_path.write_bytes(compressed)
            print(f"already published {args.image}:{args.version}")
            return 0

        asset_path.write_bytes(compressed)
        sidecar_path.write_bytes(compact_json(sidecar))
        print(f"published {args.image}:{args.version} {manifest_digest}")
        return 0
    except SiteError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ContentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
