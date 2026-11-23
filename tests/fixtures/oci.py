"""Deterministic OCI image-layout tars for the generator tests."""

from __future__ import annotations

import hashlib
import io
import json
import pathlib
import tarfile

FIXED_MTIME = 0
FIXED_MODE = 0o644

FREEDOS = {
    "name": "FreeDOS",
    "spdx": "GPL-2.0-only",
    "holder": "FreeDOS contributors",
    "status": "redistributable",
    "basis": "open-source-license",
    "license_url": "https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
    "source_url": "https://github.com/FDOS",
    "notice": "FreeDOS is distributed under the GNU General Public License.",
}

AGENT = {
    "name": "DOSKER",
    "spdx": "MIT OR Apache-2.0",
    "holder": "DOSker contributors",
    "status": "redistributable",
    "basis": "open-source-license",
    "license_url": "https://github.com/i-zhirov/dosker#license",
    "notice": "DOSker is dual-licensed under MIT or Apache-2.0.",
}

ABANDONWARE = {
    "name": "OldGame",
    "spdx": "NONE",
    "status": "abandonware",
    "basis": "good-faith",
    "evidence": "https://example.org/old-game/evidence",
    "notice": "This image carries abandonware content.",
}

IMAGES = [
    {
        "release": "i-zhirov-hello-dos",
        "ref": "i-zhirov/hello-dos:1.0.0",
        "version": "1.0.0",
        "published_at": "2026-11-23T12:00:00Z",
        "licenses": [FREEDOS, AGENT],
    },
    {
        "release": "i-zhirov-old-game",
        "ref": "i-zhirov/old-game:1.0.0",
        "version": "1.0.0",
        "published_at": "2026-11-23T13:00:00Z",
        "licenses": [ABANDONWARE],
    },
]


def canonical(value: object) -> bytes:
    """Return compact, sorted JSON bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest_bytes(data: bytes) -> str:
    """Return the sha256 digest of some bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _tar(members: dict[str, bytes]) -> bytes:
    """Build a deterministic tar from the members."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name in sorted(members):
            data = members[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = FIXED_MTIME
            info.mode = FIXED_MODE
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_image(
    licenses: list[dict],
    ref_name: str,
    created: str | None = None,
    layer_digest: str | None = None,
) -> dict:
    """Build one OCI image tar and return its bytes and digests."""
    config = {"schema_version": 1, "licenses": licenses}
    if created is not None:
        config["created"] = created
    config_bytes = canonical(config)
    config_digest = digest_bytes(config_bytes)
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
            "size": len(config_bytes),
        },
        "layers": (
            [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar",
                    "digest": layer_digest,
                    "size": 1,
                }
            ]
            if layer_digest is not None
            else []
        ),
    }
    manifest_bytes = canonical(manifest)
    manifest_digest = digest_bytes(manifest_bytes)
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": manifest_digest,
                "size": len(manifest_bytes),
                "annotations": {"org.opencontainers.image.ref.name": ref_name},
            }
        ],
    }
    layout = canonical({"imageLayoutVersion": "1.0.0"})
    members = {
        "oci-layout": layout,
        "index.json": canonical(index),
        f"blobs/sha256/{manifest_digest.split(':', 1)[1]}": manifest_bytes,
        f"blobs/sha256/{config_digest.split(':', 1)[1]}": config_bytes,
    }
    return {
        "tar": _tar(members),
        "manifest_digest": manifest_digest,
        "config_digest": config_digest,
        "manifest_bytes": manifest_bytes,
        "config_bytes": config_bytes,
    }


def read_members(data: bytes) -> dict[str, bytes]:
    """Read the file members of one tar."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        return {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }


def summary(licenses: list[dict]) -> str:
    """Return the license summary."""
    statuses = {entry["status"] for entry in licenses}
    if statuses == {"redistributable"}:
        return "redistributable"
    if statuses == {"abandonware"}:
        return "abandonware"
    return "mixed"


def build_version_assets(
    assets_dir: pathlib.Path,
    release: str,
    version: str,
    ref: str,
    licenses: list[dict],
    published_at: str,
) -> tuple[list[dict], str]:
    """Write one version's tar and sidecar and return its assets and digest."""
    release_dir = assets_dir / release
    release_dir.mkdir(parents=True, exist_ok=True)
    built = build_image(licenses, ref)
    asset_digest = digest_bytes(built["tar"])
    tar_name = f"{asset_digest}.tar"
    (release_dir / tar_name).write_bytes(built["tar"])
    sidecar = {
        "version": version,
        "digest": built["manifest_digest"],
        "config_digest": built["config_digest"],
        "license_summary": summary(licenses),
        "published_at": published_at,
        "asset_digest": asset_digest,
        "asset_size": len(built["tar"]),
    }
    sidecar_bytes = canonical(sidecar)
    sidecar_name = f"{version}.json"
    (release_dir / sidecar_name).write_bytes(sidecar_bytes)
    base = f"https://example.test/releases/download/{release}"
    assets = [
        {
            "name": tar_name,
            "browser_download_url": f"{base}/{tar_name}",
            "size": len(built["tar"]),
            "digest": asset_digest,
        },
        {
            "name": sidecar_name,
            "browser_download_url": f"{base}/{sidecar_name}",
            "size": len(sidecar_bytes),
            "digest": digest_bytes(sidecar_bytes),
        },
    ]
    return assets, built["manifest_digest"]


def build_site_assets(assets_dir: pathlib.Path) -> list[dict]:
    """Write the fixture assets and return the release inventory."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    inventory = []
    for image in IMAGES:
        assets, _ = build_version_assets(
            assets_dir,
            image["release"],
            image["version"],
            image["ref"],
            image["licenses"],
            image["published_at"],
        )
        inventory.append({"tag_name": image["release"], "assets": assets})
    return inventory
