"""Identify the image content that survives a rebuild.

The manifest layers are the file content the rights holder can revoke. The
config metadata, including build history and timestamps, is not part of the
identity, so a rebuild that changes the manifest digest still matches.
"""

from __future__ import annotations

import hashlib
import json


class ContentError(Exception):
    """A manifest has no usable layers."""


def content_digest(manifest_bytes: bytes) -> str:
    """Return the digest of the ordered manifest layer digests."""
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise ContentError(f"invalid manifest: {error}") from error
    layers = manifest.get("layers")
    if not isinstance(layers, list):
        raise ContentError("manifest has no layers")
    digests = []
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("digest"), str):
            raise ContentError("manifest layer has no digest")
        digests.append(layer["digest"])
    data = json.dumps({"layers": digests}, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()
