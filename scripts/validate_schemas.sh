#!/usr/bin/env bash
# Check the registry TOML documents against the JSON schemas.
set -euo pipefail

root="${1:?usage: validate_schemas.sh <registry-root>}"
if [ ! -f "$root/namespaces.toml" ] || [ ! -d "$root/images" ]; then
  echo "error: $root is not a registry root" >&2
  exit 1
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v check-jsonschema >/dev/null 2>&1; then
  checker=(check-jsonschema)
elif command -v uvx >/dev/null 2>&1; then
  checker=(uvx --quiet check-jsonschema)
else
  echo "error: check-jsonschema is not installed (or uvx is unavailable)" >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 - "$root" "$tmp" <<'PY'
import json
import pathlib
import sys
import tomllib

root = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])

def convert(source: pathlib.Path, target: pathlib.Path) -> None:
    value = tomllib.loads(source.read_text(encoding="utf-8"))
    target.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

convert(root / "namespaces.toml", out / "namespaces.json")
convert(root / "revoked.toml", out / "revoked.json")

images = sorted(root.glob("images/*/*/registry.toml"))
if not images:
    raise SystemExit(f"error: {root} contains no images/*/*/registry.toml")
for path in images:
    image = path.parent.relative_to(root / "images")
    convert(path, out / f"registry-{image.parts[0]}-{image.parts[1]}.json")
PY

"${checker[@]}" --schemafile "$repo/schemas/namespaces.schema.json" "$tmp/namespaces.json"
"${checker[@]}" --schemafile "$repo/schemas/revoked.schema.json" "$tmp/revoked.json"
for file in "$tmp"/registry-*.json; do
  "${checker[@]}" --schemafile "$repo/schemas/registry.schema.json" "$file"
done
