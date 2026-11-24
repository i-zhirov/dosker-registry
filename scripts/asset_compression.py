"""Deterministic zstd compression for registry image assets."""

from __future__ import annotations

import zstandard

# The level and frame options are part of the published asset format. Change
# them together with a new asset encoding version, not in place.
LEVEL = 19
MAX_DECODED_BYTES = 2 * 1024**3


class CompressionError(Exception):
    """A compressed asset cannot be decoded."""


def compress(data: bytes) -> bytes:
    """Return one deterministic zstd frame for the asset tar."""
    return zstandard.ZstdCompressor(
        level=LEVEL,
        write_checksum=False,
        write_content_size=True,
        threads=0,
    ).compress(data)


def decompress(data: bytes, max_output_size: int = MAX_DECODED_BYTES) -> bytes:
    """Decode one zstd frame and enforce the decoded size cap."""
    try:
        return zstandard.ZstdDecompressor().decompress(
            data, max_output_size=max_output_size
        )
    except zstandard.ZstdError as error:
        raise CompressionError(f"invalid zstd frame: {error}") from error


def asset_name(digest: str) -> str:
    """Return the release asset file name for one compressed digest."""
    return digest.replace(":", ".") + ".tar.zst"
