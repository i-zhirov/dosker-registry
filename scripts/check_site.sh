#!/usr/bin/env bash
# Check the generated Pages documents against the schemas.
set -euo pipefail

site="${1:?usage: check_site.sh <site-dir>}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v check-jsonschema >/dev/null 2>&1; then
  checker=(check-jsonschema)
elif command -v uvx >/dev/null 2>&1; then
  checker=(uvx --quiet check-jsonschema)
else
  echo "error: check-jsonschema is not installed (or uvx is unavailable)" >&2
  exit 1
fi

"${checker[@]}" --schemafile "$repo/schemas/catalog.schema.json" "$site/index.json"
shopt -s nullglob
for file in "$site"/v1/*/*/index.json; do
  "${checker[@]}" --schemafile "$repo/schemas/image-index.schema.json" "$file"
done
for file in "$site"/v1/*/*/versions/*/licenses.json; do
  "${checker[@]}" --schemafile "$repo/schemas/licenses.schema.json" "$file"
done
