#!/usr/bin/env python3
"""Migrate existing uncompressed release assets to deterministic zstd.

This is a one-time operator tool. ``publish.py``, ``generate_site.py``, and
``takedown.py`` do not use it and do not read the old format.

Prepare mode reads the old tar assets and sidecars in ``--assets``. It checks
the old digest, size, manifest, config, and content digests. It writes the
compressed asset and the updated sidecar to ``--out`` and backs up the old
sidecar to ``--backup``. It keeps the old tar for rollback.

Cleanup mode reads the old sidecars from ``--backup`` and the current release
assets from ``--assets``. It checks the new compressed asset and sidecar, then
prints each old tar asset name to delete. It does not delete anything.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import re
import sys
import tarfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from asset_compression import CompressionError, asset_name, compress, decompress  # noqa: E402
from content import ContentError, content_digest  # noqa: E402

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
REQUIRED_SIDECAR_FIELDS = (
    "version",
    "digest",
    "config_digest",
    "asset_digest",
    "asset_size",
)
COMPRESSION = "zstd"


class MigrationError(Exception):
    """A release asset or sidecar cannot be migrated."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="write compressed assets and sidecars")
    mode.add_argument("--cleanup", action="store_true", help="print old tar names after verification")
    parser.add_argument("--assets", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, help="prepare output directory")
    parser.add_argument("--backup", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    if args.prepare and args.out is None:
        parser.error("--out is required with --prepare")
    if args.cleanup and args.out is not None:
        parser.error("--out is not used with --cleanup")
    return args


def digest_bytes(data: bytes) -> str:
    """Return the sha256 digest of some bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def compact_json(value: object) -> bytes:
    """Return compact, sorted JSON with a trailing newline."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def read_json(path: pathlib.Path) -> dict:
    """Read one JSON object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"invalid JSON at {path}: {error}") from error
    if not isinstance(value, dict):
        raise MigrationError(f"invalid JSON object at {path}")
    return value


def write_json(path: pathlib.Path, value: object) -> None:
    """Write one deterministic JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compact_json(value))


def safe_version(value: object, path: pathlib.Path) -> str:
    """Return a sidecar version that is safe to use as a file name."""
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise MigrationError(f"sidecar {path} has an invalid version")
    return value


def load_sidecar(path: pathlib.Path) -> dict:
    """Read and validate one release sidecar."""
    sidecar = read_json(path)
    for field in REQUIRED_SIDECAR_FIELDS:
        if field not in sidecar:
            raise MigrationError(f"sidecar {path} has no {field}")
    safe_version(sidecar["version"], path)
    for field in ("digest", "config_digest", "asset_digest"):
        value = sidecar[field]
        if not isinstance(value, str) or not DIGEST.fullmatch(value):
            raise MigrationError(f"sidecar {path} has an invalid {field}")
    size = sidecar["asset_size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise MigrationError(f"sidecar {path} has an invalid asset_size")
    existing = sidecar.get("content_digest")
    if existing is not None and (not isinstance(existing, str) or not DIGEST.fullmatch(existing)):
        raise MigrationError(f"sidecar {path} has an invalid content_digest")
    return sidecar


def blob_member(digest: str) -> str:
    """Return the tar member name for one digest."""
    return "blobs/sha256/" + digest.split(":", 1)[1]


def read_legacy_archive(path: pathlib.Path, data: bytes) -> tuple[bytes, bytes, str, str]:
    """Read the manifest and config from one uncompressed OCI layout tar."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            layout = json.loads(archive.extractfile("oci-layout").read())
            index = json.loads(archive.extractfile("index.json").read())
            manifest_digest = index["manifests"][0]["digest"]
            if not isinstance(manifest_digest, str) or not DIGEST.fullmatch(manifest_digest):
                raise MigrationError(f"invalid manifest digest in {path}")
            manifest_bytes = archive.extractfile(blob_member(manifest_digest)).read()
            if digest_bytes(manifest_bytes) != manifest_digest:
                raise MigrationError(f"manifest digest mismatch in {path}")
            manifest = json.loads(manifest_bytes)
            config_digest = manifest["config"]["digest"]
            if not isinstance(config_digest, str) or not DIGEST.fullmatch(config_digest):
                raise MigrationError(f"invalid config digest in {path}")
            config_bytes = archive.extractfile(blob_member(config_digest)).read()
            if digest_bytes(config_bytes) != config_digest:
                raise MigrationError(f"config digest mismatch in {path}")
    except (
        AttributeError,
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
        tarfile.TarError,
    ) as error:
        raise MigrationError(f"invalid image archive at {path}: {error}") from error
    if not isinstance(layout, dict) or layout.get("imageLayoutVersion") != "1.0.0":
        raise MigrationError(f"unsupported image layout in {path}")
    return manifest_bytes, config_bytes, manifest_digest, config_digest


def check_archive_matches_sidecar(
    path: pathlib.Path, data: bytes, sidecar: dict
) -> tuple[bytes, bytes]:
    """Verify one uncompressed tar against its sidecar and return its documents."""
    manifest_bytes, config_bytes, manifest_digest, config_digest = read_legacy_archive(
        path, data
    )
    if manifest_digest != sidecar["digest"]:
        raise MigrationError(
            f"sidecar for {sidecar['version']} names {sidecar['digest']}, not {manifest_digest}"
        )
    if config_digest != sidecar["config_digest"]:
        raise MigrationError(
            f"sidecar for {sidecar['version']} names {sidecar['config_digest']}, not {config_digest}"
        )
    try:
        content = content_digest(manifest_bytes)
    except ContentError as error:
        raise MigrationError(f"invalid manifest in {path}: {error}") from error
    expected = sidecar.get("content_digest")
    if expected is not None and expected != content:
        raise MigrationError(
            f"sidecar for {sidecar['version']} names content {expected}, not {content}"
        )
    return manifest_bytes, config_bytes


def tar_index(assets: pathlib.Path) -> dict[str, pathlib.Path]:
    """Return a map from digest to uncompressed tar path."""
    index: dict[str, pathlib.Path] = {}
    for path in sorted(assets.glob("*.tar")):
        try:
            data = path.read_bytes()
        except OSError as error:
            raise MigrationError(f"cannot read {path}: {error}") from error
        index[digest_bytes(data)] = path
    return index


def locate_old_tar(
    sidecar: dict, assets: pathlib.Path, index: dict[str, pathlib.Path]
) -> pathlib.Path | None:
    """Return the old tar path for one sidecar."""
    digest = sidecar["asset_digest"]
    for name in (f"{digest}.tar", f"{digest.replace(':', '.')}.tar"):
        path = assets / name
        if path.is_file():
            return path
    return index.get(digest)


def old_sidecars(assets: pathlib.Path) -> list[tuple[pathlib.Path, dict]]:
    """Read every sidecar in one release asset directory."""
    result = []
    for path in sorted(assets.glob("*.json")):
        result.append((path, load_sidecar(path)))
    result.sort(key=lambda item: (item[1]["version"], item[0].name))
    return result


def backup_sidecar(backup: pathlib.Path, path: pathlib.Path, version: str) -> None:
    """Keep the original sidecar for rollback."""
    target = backup / f"{version}.json"
    original = path.read_bytes()
    if target.exists():
        if target.read_bytes() != original:
            raise MigrationError(f"backup {target} differs from the old sidecar")
        return
    target.write_bytes(original)


def prepare(args: argparse.Namespace) -> int:
    """Write compressed assets and updated sidecars without deleting old files."""
    if not args.assets.is_dir():
        raise MigrationError(f"missing assets directory {args.assets}")
    args.out.mkdir(parents=True, exist_ok=True)
    args.backup.mkdir(parents=True, exist_ok=True)
    paths = {args.assets.resolve(), args.out.resolve(), args.backup.resolve()}
    if len(paths) != 3:
        raise MigrationError("--assets, --out, and --backup must be different directories")

    index = tar_index(args.assets)
    sidecars = old_sidecars(args.assets)
    if not sidecars:
        print("no sidecars to migrate")
        return 0

    for path, sidecar in sidecars:
        version = sidecar["version"]
        if sidecar.get("asset_compression") == COMPRESSION:
            print(f"already migrated {version}")
            continue
        if "asset_compression" in sidecar:
            raise MigrationError(f"sidecar {path} has an unknown asset_compression")

        old_tar = locate_old_tar(sidecar, args.assets, index)
        if old_tar is None:
            raise MigrationError(
                f"missing old tar for {sidecar['version']} ({sidecar['asset_digest']})"
            )
        data = old_tar.read_bytes()
        if digest_bytes(data) != sidecar["asset_digest"]:
            raise MigrationError(f"old asset {old_tar} does not match its sidecar")
        if len(data) != sidecar["asset_size"]:
            raise MigrationError(
                f"old asset {old_tar} is {len(data)} bytes, not {sidecar['asset_size']}"
            )
        manifest_bytes, _config_bytes = check_archive_matches_sidecar(
            old_tar, data, sidecar
        )

        compressed = compress(data)
        if decompress(compressed) != data:
            raise MigrationError(f"the compressed asset for {version} does not round-trip")
        new_digest = digest_bytes(compressed)
        new_name = asset_name(new_digest)
        updated = dict(sidecar)
        updated["asset_digest"] = new_digest
        updated["asset_size"] = len(compressed)
        updated["asset_compression"] = COMPRESSION
        if "content_digest" not in updated:
            try:
                updated["content_digest"] = content_digest(manifest_bytes)
            except ContentError as error:
                raise MigrationError(f"invalid manifest for {version}: {error}") from error
        (args.out / new_name).write_bytes(compressed)
        write_json(args.out / f"{version}.json", updated)
        backup_sidecar(args.backup, path, version)
        print(f"prepared {version} {sidecar['asset_digest']} -> {new_digest}")

    return 0


def current_asset(args: argparse.Namespace, old: dict) -> None:
    """Verify the new asset and sidecar before cleanup prints the old name."""
    version = old["version"]
    sidecar_path = args.assets / f"{version}.json"
    if not sidecar_path.is_file():
        raise MigrationError(f"missing new sidecar {sidecar_path}")
    current = load_sidecar(sidecar_path)
    if current.get("asset_compression") != COMPRESSION:
        raise MigrationError(f"sidecar {sidecar_path} is not migrated to zstd")
    if current["digest"] != old["digest"] or current["config_digest"] != old["config_digest"]:
        raise MigrationError(f"sidecar {sidecar_path} changed the image digests")
    expected_content = old.get("content_digest")
    if expected_content is not None and current.get("content_digest") != expected_content:
        raise MigrationError(f"sidecar {sidecar_path} changed the content digest")

    path = args.assets / asset_name(current["asset_digest"])
    if not path.is_file():
        raise MigrationError(f"missing new asset {path}")
    data = path.read_bytes()
    if len(data) != current["asset_size"]:
        raise MigrationError(f"new asset {path} has the wrong size")
    if digest_bytes(data) != current["asset_digest"]:
        raise MigrationError(f"new asset {path} has the wrong digest")
    try:
        decoded = decompress(data)
    except CompressionError as error:
        raise MigrationError(f"new asset {path} is invalid: {error}") from error
    check_archive_matches_sidecar(path, decoded, current)


def cleanup(args: argparse.Namespace) -> int:
    """Verify the new assets and print each old tar name to delete."""
    if not args.assets.is_dir():
        raise MigrationError(f"missing assets directory {args.assets}")
    if not args.backup.is_dir():
        raise MigrationError(f"missing backup directory {args.backup}")
    if args.assets.resolve() == args.backup.resolve():
        raise MigrationError("--assets and --backup must be different directories")

    backups = []
    for path in sorted(args.backup.glob("*.json")):
        backups.append((path, load_sidecar(path)))
    backups.sort(key=lambda item: (item[1]["version"], item[0].name))
    if not backups:
        print("no backups to clean up")
        return 0

    index = tar_index(args.assets)
    for path, old in backups:
        version = old["version"]
        if "asset_compression" in old:
            raise MigrationError(f"backup {path} is not an old sidecar")
        current_asset(args, old)
        old_tar = locate_old_tar(old, args.assets, index)
        if old_tar is None:
            print(f"already absent {version}", file=sys.stderr)
            continue
        data = old_tar.read_bytes()
        if len(data) != old["asset_size"] or digest_bytes(data) != old["asset_digest"]:
            raise MigrationError(f"old asset {old_tar} does not match its sidecar")
        check_archive_matches_sidecar(old_tar, data, old)
        print(old_tar.name)

    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.prepare:
            return prepare(args)
        return cleanup(args)
    except (MigrationError, CompressionError, ContentError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
