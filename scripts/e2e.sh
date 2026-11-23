#!/usr/bin/env bash
# End-to-end: build the first image, publish it, generate the site, and check
# that a second run changes nothing and a second generation is identical.
#
# The script needs a dosker binary with `registry check-final`, the FreeDOS
# source, the DOS agent, and QEMU. Source `examples/hello-dos/setup.sh` in the
# dosker checkout first, then set DOSKER_BIN to that checkout's binary.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dosker="${DOSKER_BIN:-dosker}"
image="$repo/images/i-zhirov/hello-dos"
version="$(python3 -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["version"])' "$image/registry.toml")"
owner="i-zhirov"
name="hello-dos"
tag="$owner-$name"
reference="$tag:$version"
epoch="${E2E_EPOCH:-1763900000}"
registry_url="${E2E_REGISTRY_URL:-https://example.invalid}"

work="$(mktemp -d "${TMPDIR:-/tmp}/dosker-registry-e2e.XXXXXX")"
trap 'rm -rf "$work"' EXIT
release="$work/release/$tag"
mkdir -p "$release"

echo "== build $reference"
"$dosker" build -t "$reference" "$image"

echo "== save and check the final tree"
"$dosker" save -o "$work/image.tar" "$reference"
"$dosker" registry check-final "$reference"

echo "== publish"
published_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 "$repo/scripts/publish.py" \
  --image "$owner/$name" \
  --version "$version" \
  --asset "$work/image.tar" \
  --release-dir "$release" \
  --published-at "$published_at"

python3 - "$release" "$tag" "$work/releases.json" <<'PY'
import hashlib
import json
import pathlib
import sys

release = pathlib.Path(sys.argv[1])
tag = sys.argv[2]
out = pathlib.Path(sys.argv[3])
assets = []
for path in sorted(release.iterdir()):
    data = path.read_bytes()
    assets.append(
        {
            "name": path.name,
            "browser_download_url": f"https://example.invalid/{tag}/{path.name}",
            "size": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        }
    )
out.write_text(json.dumps([{"tag_name": tag, "assets": assets}]), encoding="utf-8")
PY

echo "== generate and check"
python3 "$repo/scripts/generate_site.py" \
  --repo "$repo" \
  --releases "$work/releases.json" \
  --assets "$work/release" \
  --out "$work/site" \
  --epoch "$epoch" \
  --registry-url "$registry_url"
"$repo/scripts/check_site.sh" "$work/site"

echo "== second publish is a no-op"
before="$(cat "$release/$version.json")"
second="$(python3 "$repo/scripts/publish.py" \
  --image "$owner/$name" \
  --version "$version" \
  --asset "$work/image.tar" \
  --release-dir "$release" \
  --published-at "$published_at")"
case "$second" in
  *"already published"*) ;;
  *) echo "error: the second publish changed the release: $second" >&2; exit 1 ;;
esac
after="$(cat "$release/$version.json")"
if [ "$before" != "$after" ]; then
  echo "error: the second publish changed the sidecar" >&2
  exit 1
fi

echo "== a second generation reproduces the catalog"
python3 "$repo/scripts/generate_site.py" \
  --repo "$repo" \
  --releases "$work/releases.json" \
  --assets "$work/release" \
  --out "$work/site-2" \
  --epoch "$epoch" \
  --registry-url "$registry_url"
cmp "$work/site/index.json" "$work/site-2/index.json"

echo "ok: end-to-end"
