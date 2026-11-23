#!/usr/bin/env bash
# Validate one registry root: schemas, then dosker registry validate per image.
set -euo pipefail

root="${1:?usage: validate.sh <registry-root>}"
if [ ! -d "$root/images" ] && [ "$(basename "$root")" = "images" ] && [ -f "$root/../namespaces.toml" ]; then
  root="$root/.."
fi
if [ ! -d "$root/images" ]; then
  echo "error: $root has no images directory" >&2
  exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$here/validate_schemas.sh" "$root"

dosker="${DOSKER_BIN:-dosker}"
if ! command -v "$dosker" >/dev/null 2>&1; then
  echo "error: dosker binary not found: $dosker (set DOSKER_BIN)" >&2
  exit 1
fi

shopt -s nullglob
for dir in "$root"/images/*/*/; do
  echo "validating $dir"
  "$dosker" registry validate "$dir"
done
