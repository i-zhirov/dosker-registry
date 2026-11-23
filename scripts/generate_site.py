#!/usr/bin/env python3
"""Generate the Pages documents from the registry and the Release inventory.

The generator is deterministic. It reads the registry checkout, the Releases
API inventory, and the downloaded assets. It writes the catalog, the per-image
index, and the per-version license, manifest, and config documents.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tarfile
import tomllib
from datetime import datetime, timezone
from string import Template

SCHEMA = 1
HANDLE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")
NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
STATUSES = {"redistributable", "abandonware"}


class SiteError(Exception):
    """A generation failure with a user-facing message."""


def compact_json(value: object) -> bytes:
    """Return compact, sorted JSON with a trailing newline."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: pathlib.Path, value: object) -> None:
    """Write one deterministic JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compact_json(value))


def safe_segment(value: str, pattern: re.Pattern[str], label: str) -> str:
    """Reject an unsafe path or identifier segment."""
    if ".." in value or "/" in value or "\\" in value or not pattern.fullmatch(value):
        raise SiteError(f"unsafe {label}: {value!r}")
    return value


def load_toml(path: pathlib.Path) -> dict:
    """Load one TOML file."""
    if not path.is_file():
        raise SiteError(f"missing file: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise SiteError(f"invalid TOML at {path}: {error}") from error


def load_inventory(path: pathlib.Path) -> list[dict]:
    """Load the Releases API inventory."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SiteError(f"invalid release inventory at {path}: {error}") from error
    if not isinstance(value, list):
        raise SiteError("the release inventory must be a JSON array")
    return value


def load_sidecar(path: pathlib.Path) -> dict:
    """Load one version sidecar."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SiteError(f"invalid sidecar at {path}: {error}") from error
    if not isinstance(value, dict):
        raise SiteError(f"invalid sidecar at {path}")
    for field in (
        "version",
        "digest",
        "config_digest",
        "license_summary",
        "published_at",
        "asset_digest",
        "asset_size",
    ):
        if field not in value:
            raise SiteError(f"sidecar {path} has no {field}")
    return value


def blob_member(digest: str) -> str:
    """Return the tar member name for one digest."""
    return "blobs/sha256/" + digest.split(":", 1)[1]


def read_archive(
    path: pathlib.Path, asset_digest: str, asset_size: int
) -> tuple[bytes, bytes, str, str]:
    """Verify one image tar and return its manifest and config bytes and digests."""
    if not path.is_file():
        raise SiteError(f"missing asset: {path}")
    data = path.read_bytes()
    actual = "sha256:" + hashlib.sha256(data).hexdigest()
    if actual != asset_digest:
        raise SiteError(f"asset digest mismatch for {path}: {actual} != {asset_digest}")
    if len(data) != asset_size:
        raise SiteError(f"asset size mismatch for {path}: {len(data)} != {asset_size}")

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            members = {
                member.name: archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isfile()
            }
        layout = json.loads(members["oci-layout"])
        index = json.loads(members["index.json"])
        manifest_digest = index["manifests"][0]["digest"]
        if not DIGEST.fullmatch(manifest_digest):
            raise SiteError(f"invalid manifest digest in {path}")
        manifest_bytes = members[blob_member(manifest_digest)]
        manifest = json.loads(manifest_bytes)
        config_digest = manifest["config"]["digest"]
        if not DIGEST.fullmatch(config_digest):
            raise SiteError(f"invalid config digest in {path}")
        config_bytes = members[blob_member(config_digest)]
    except (KeyError, IndexError, json.JSONDecodeError, tarfile.TarError) as error:
        raise SiteError(f"invalid image archive at {path}: {error}") from error

    if layout.get("imageLayoutVersion") != "1.0.0":
        raise SiteError(f"unsupported image layout in {path}")
    return manifest_bytes, config_bytes, manifest_digest, config_digest


def license_summary(entries: list[dict], label: str) -> str:
    """Return the summary of the license entries."""
    if not entries:
        raise SiteError(f"image {label} has no license entries")
    statuses = set()
    for entry in entries:
        status = entry.get("status")
        if status not in STATUSES:
            raise SiteError(f"image {label} has a license entry with status {status!r}")
        statuses.add(status)
    if statuses == {"redistributable"}:
        return "redistributable"
    if statuses == {"abandonware"}:
        return "abandonware"
    return "mixed"


def ts(epoch: int) -> str:
    """Format the generation time."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE_DIR = REPO_ROOT / "site"
TEMPLATES = SITE_DIR / "templates"


def esc(value: object) -> str:
    """Escape one value for HTML."""
    return html.escape(str(value))


def render(template: str, **values: str) -> str:
    """Render one template fragment."""
    return Template((TEMPLATES / template).read_text(encoding="utf-8")).substitute(values)


def relative_root(out: pathlib.Path, page: pathlib.Path) -> str:
    """Return the prefix that reaches the site root from one page."""
    depth = len(page.parent.relative_to(out).parts)
    return "/".join([".."] * depth) or "."


def badge(summary: str, requires_acceptance: bool) -> str:
    """Render the license badge."""
    markup = f'<span class="badge badge-{esc(summary)}">{esc(summary)}</span>'
    if requires_acceptance:
        markup += ' <span class="muted">(requires acceptance)</span>'
    return markup


class Generator:
    """Builds the site documents for one registry checkout."""

    def __init__(
        self,
        repo: pathlib.Path,
        releases: pathlib.Path,
        assets: pathlib.Path,
        registry_url: str,
    ) -> None:
        self.repo = repo
        self.assets = assets
        self.registry_url = registry_url.rstrip("/")
        self.namespaces = load_toml(repo / "namespaces.toml")
        self.revoked = load_toml(repo / "revoked.toml")
        self.inventory = load_inventory(releases)
        self.records: dict[tuple[str, str], dict[str, dict]] = {}

    def owners(self) -> set[str]:
        """Return the proven owners."""
        owners = self.namespaces.get("owners", {})
        if not isinstance(owners, dict):
            raise SiteError("namespaces.toml has no owners table")
        return set(owners)

    def revoked_digests(self, namespace: str, name: str) -> set[str]:
        """Return the revoked digests for one image."""
        records = self.revoked.get("revoked", [])
        return {
            record["digest"]
            for record in records
            if record.get("namespace") == namespace and record.get("name") == name
        }

    def release_assets(self, tag: str) -> list[dict]:
        """Return the assets of one release."""
        for release in self.inventory:
            if release.get("tag_name") == tag:
                assets = release.get("assets", [])
                if not isinstance(assets, list):
                    raise SiteError(f"release {tag} has no asset list")
                return assets
        return []

    def documents(self) -> tuple[dict, dict[tuple[str, str], dict]]:
        """Build the catalog and the per-image index."""
        owners = self.owners()
        images: list[dict] = []
        indexes: dict[tuple[str, str], dict] = {}
        tags: dict[str, tuple[str, str]] = {}

        for path in sorted((self.repo / "images").glob("*/*/registry.toml")):
            namespace = safe_segment(path.parents[1].name, HANDLE, "namespace")
            name = safe_segment(path.parents[0].name, NAME, "name")
            label = f"{namespace}/{name}"
            if namespace not in owners:
                raise SiteError(f"image {label} has no proven namespace")
            metadata = load_toml(path)
            version = safe_segment(str(metadata.get("version", "")), VERSION, "version")
            declared = metadata.get("tags", [])
            if not isinstance(declared, list) or not declared:
                raise SiteError(f"image {label} declares no tags")
            description = metadata.get("description")
            if not isinstance(description, str) or not description:
                raise SiteError(f"image {label} has no description")

            record = self.image_records(namespace, name, version)
            if record is None:
                continue
            current, versions = record
            self.records[(namespace, name)] = {
                entry["version"]: entry for entry in versions
            }
            for tag in declared:
                safe_segment(str(tag), VERSION, "tag")
                if tag in tags:
                    raise SiteError(
                        f"duplicate tag {tag}: {label} and {tags[tag][0]}/{tags[tag][1]}"
                    )
                tags[tag] = (namespace, name)

            tag_map = {tag: current["digest"] for tag in declared}
            summary = current["license_summary"]
            index = {
                "schema": SCHEMA,
                "image": label,
                "namespace": namespace,
                "name": name,
                "description": description,
                "tags": tag_map,
                "versions": [
                    {key: value for key, value in entry.items() if not key.startswith("_")}
                    for entry in versions
                ],
            }
            for optional in ("homepage", "deprecated"):
                if optional in metadata:
                    index[optional] = metadata[optional]
            indexes[(namespace, name)] = index

            catalog_entry = {
                "namespace": namespace,
                "name": name,
                "description": description,
                "tags": tag_map,
                "license_summary": summary,
                "requires_acceptance": summary != "redistributable",
                "latest": {"version": current["version"], "digest": current["digest"]},
            }
            for optional in ("homepage", "deprecated"):
                if optional in metadata:
                    catalog_entry[optional] = metadata[optional]
            images.append(catalog_entry)

        images.sort(key=lambda entry: (entry["namespace"], entry["name"]))
        catalog = {
            "schema": SCHEMA,
            "generated_at": "",
            "registry": self.registry_url,
            "images": images,
        }
        return catalog, indexes

    def image_records(
        self, namespace: str, name: str, current_version: str
    ) -> tuple[dict, list[dict]] | None:
        """Return the current record and every live version record."""
        tag = f"{namespace}-{name}"
        assets = self.release_assets(tag)
        sidecars = {
            asset["name"][: -len(".json")]: asset
            for asset in assets
            if isinstance(asset.get("name"), str) and asset["name"].endswith(".json")
        }
        tars = {
            asset["name"][: -len(".tar")]: asset
            for asset in assets
            if isinstance(asset.get("name"), str)
            and asset["name"].endswith(".tar")
            and DIGEST.fullmatch(asset["name"][: -len(".tar")])
        }

        if current_version not in sidecars:
            raise SiteError(f"image {namespace}/{name} has no sidecar for {current_version}")

        revoked = self.revoked_digests(namespace, name)
        records: list[dict] = []
        asset_dir = self.assets / f"{namespace}-{name}"
        for version in sorted(sidecars):
            safe_segment(version, VERSION, "version")
            sidecar = load_sidecar(asset_dir / f"{version}.json")
            if sidecar["version"] != version:
                raise SiteError(
                    f"sidecar {asset_dir / f'{version}.json'} names version {sidecar['version']}"
                )
            if sidecar["digest"] in revoked:
                if version == current_version:
                    return None
                continue
            records.append(self.version_record(namespace, name, version, tars, sidecar))

        current = next(record for record in records if record["version"] == current_version)
        records.sort(key=lambda record: (record["published_at"], record["version"]))
        return current, records

    def version_record(
        self,
        namespace: str,
        name: str,
        version: str,
        tars: dict[str, dict],
        sidecar: dict,
    ) -> dict:
        """Build one version record from its sidecar and tar."""
        asset_dir = self.assets / f"{namespace}-{name}"
        sidecar_path = asset_dir / f"{version}.json"
        asset_digest = sidecar["asset_digest"]
        if not isinstance(asset_digest, str) or not DIGEST.fullmatch(asset_digest):
            raise SiteError(f"sidecar {sidecar_path} has an invalid asset digest")
        asset_size = sidecar["asset_size"]
        if not isinstance(asset_size, int) or asset_size < 1:
            raise SiteError(f"sidecar {sidecar_path} has an invalid asset size")

        tar_name = f"{asset_digest}.tar"
        tar = tars.get(asset_digest)
        if tar is None:
            raise SiteError(f"release {namespace}-{name} has no asset {tar_name}")
        if tar.get("size") is not None and tar["size"] != asset_size:
            raise SiteError(f"release size for {tar_name} does not match the sidecar")
        if tar.get("digest") is not None and tar["digest"] != asset_digest:
            raise SiteError(f"release digest for {tar_name} does not match the sidecar")

        manifest_bytes, config_bytes, manifest_digest, config_digest = read_archive(
            asset_dir / tar_name, asset_digest, asset_size
        )
        if manifest_digest != sidecar["digest"]:
            raise SiteError(f"sidecar {sidecar_path} names digest {sidecar['digest']}")
        if config_digest != sidecar["config_digest"]:
            raise SiteError(f"sidecar {sidecar_path} names config digest {sidecar['config_digest']}")

        try:
            entries = json.loads(config_bytes).get("licenses")
        except json.JSONDecodeError as error:
            raise SiteError(f"invalid config in {tar_name}: {error}") from error
        if not isinstance(entries, list):
            raise SiteError(f"config in {tar_name} has no license list")
        summary = license_summary(entries, f"{namespace}/{name}")
        if summary != sidecar["license_summary"]:
            raise SiteError(
                f"sidecar {sidecar_path} summary {sidecar['license_summary']} != {summary}"
            )

        download = tar.get("browser_download_url")
        if not isinstance(download, str) or not download:
            raise SiteError(f"asset {tar_name} has no download URL")
        hex_digest = manifest_digest.split(":", 1)[1]
        base = f"{self.registry_url}/v1/{namespace}/{name}/versions/sha256-{hex_digest}"
        return {
            "version": version,
            "digest": manifest_digest,
            "config_digest": config_digest,
            "manifest_url": f"{base}/manifest.json",
            "config_url": f"{base}/config.json",
            "asset_url": download,
            "asset_digest": asset_digest,
            "asset_size": asset_size,
            "published_at": sidecar["published_at"],
            "license_summary": summary,
            "licenses_url": f"{base}/licenses.json",
            "_entries": entries,
            "_manifest": manifest_bytes,
            "_config": config_bytes,
        }

    def write_page(self, out: pathlib.Path, page: pathlib.Path, title: str, body: str) -> None:
        """Write one HTML page."""
        page.parent.mkdir(parents=True, exist_ok=True)
        root = relative_root(out, page)
        document = render("base.html", title=esc(title), root=esc(root), body=body)
        page.write_text(document, encoding="utf-8")

    def home_item(self, entry: dict) -> str:
        """Render one home list item."""
        label = f"{entry['namespace']}/{entry['name']}"
        href = f"v1/{entry['namespace']}/{entry['name']}/index.html"
        search = " ".join(
            [
                label,
                entry["description"],
                " ".join(entry["tags"]),
                entry["license_summary"],
            ]
        )
        notice = ""
        if entry["requires_acceptance"]:
            notice = '<p class="notice">This image needs acceptance before it runs.</p>'
        return (
            f'<li data-image data-search-text="{esc(search)}">'
            f'<p><a href="{esc(href)}">{esc(label)}</a> '
            f"{badge(entry['license_summary'], entry['requires_acceptance'])}</p>"
            f"<p>{esc(entry['description'])}</p>"
            f'<p class="muted">Tags: {esc(", ".join(entry["tags"]))}</p>'
            f"{notice}</li>"
        )

    def render_html(
        self,
        out: pathlib.Path,
        catalog: dict,
        indexes: dict[tuple[str, str], dict],
    ) -> None:
        """Write the HTML pages and copy the static assets."""
        (out / "site").mkdir(parents=True, exist_ok=True)
        for name in ("style.css", "app.js"):
            shutil.copyfile(SITE_DIR / name, out / "site" / name)

        items = "\n".join(self.home_item(entry) for entry in catalog["images"])
        self.write_page(
            out,
            out / "index.html",
            "DOSker registry",
            render("home.html", items=items),
        )

        for entry in catalog["images"]:
            key = (entry["namespace"], entry["name"])
            index = indexes[key]
            label = f"{key[0]}/{key[1]}"
            page = out / "v1" / key[0] / key[1] / "index.html"
            homepage = ""
            if "homepage" in entry:
                homepage = f'<p><a href="{esc(entry["homepage"])}">Homepage</a></p>'
            tags = "\n".join(f"<li><code>{esc(tag)}</code></li>" for tag in entry["tags"])
            rows = []
            for version in index["versions"]:
                hex_digest = version["digest"].split(":", 1)[1]
                rows.append(
                    f'<tr><td><a href="versions/sha256-{hex_digest}/index.html">'
                    f'{esc(version["version"])}</a></td>'
                    f'<td><code>{esc(version["digest"])}</code></td>'
                    f'<td>{version["asset_size"]:,} bytes</td>'
                    f'<td>{esc(version["published_at"])}</td>'
                    f'<td>{badge(version["license_summary"], version["license_summary"] != "redistributable")}</td></tr>'
                )
            self.write_page(
                out,
                page,
                label,
                render(
                    "image.html",
                    root=esc(relative_root(out, page)),
                    image=esc(label),
                    description=esc(entry["description"]),
                    homepage=homepage,
                    badge=badge(entry["license_summary"], entry["requires_acceptance"]),
                    tags=tags,
                    versions="\n".join(rows),
                ),
            )

            for version in index["versions"]:
                self.render_version_page(out, key, index, version)

    def render_version_page(
        self,
        out: pathlib.Path,
        key: tuple[str, str],
        index: dict,
        version: dict,
    ) -> None:
        """Write one version page."""
        label = f"{key[0]}/{key[1]}"
        hex_digest = version["digest"].split(":", 1)[1]
        page = out / "v1" / key[0] / key[1] / "versions" / f"sha256-{hex_digest}" / "index.html"
        record = self.records[key][version["version"]]
        entries = record["_entries"]

        notice = ""
        abandonware = [entry for entry in entries if entry.get("status") == "abandonware"]
        if abandonware:
            text = next(
                (entry["notice"] for entry in abandonware if entry.get("notice")),
                "This image carries abandonware content.",
            )
            notice = (
                '<div class="notice"><strong>Abandonware notice.</strong>'
                f"<p>{esc(text)}</p></div>"
            )

        license_items = []
        for entry in entries:
            parts = [
                f"<strong>{esc(entry.get('name', ''))}</strong>",
                esc(entry.get("spdx", "")),
                esc(entry.get("status", "")),
            ]
            if entry.get("holder"):
                parts.append(esc(entry["holder"]))
            line = " | ".join(parts)
            links = []
            for field, text in (("license_url", "License"), ("source_url", "Source")):
                if entry.get(field):
                    links.append(f'<a href="{esc(entry[field])}">{text}</a>')
            if links:
                line += " | " + " ".join(links)
            if entry.get("notice"):
                line += f'<br>{esc(entry["notice"])}'
            license_items.append(f"<li>{line}</li>")

        self.write_page(
            out,
            page,
            f"{label}:{version['version']}",
            render(
                "version.html",
                root=esc(relative_root(out, page)),
                image=esc(label),
                version=esc(version["version"]),
                digest=esc(version["digest"]),
                config_digest=esc(version["config_digest"]),
                image_href="../../index.html",
                notice=notice,
                licenses="\n".join(license_items),
                asset_url=esc(version["asset_url"]),
                asset_size=f"{version['asset_size']:,}",
                asset_digest=esc(version["asset_digest"]),
            ),
        )

    def write(self, out: pathlib.Path, epoch: int) -> None:
        """Write every JSON document."""
        catalog, indexes = self.documents()
        catalog["generated_at"] = ts(epoch)
        write_json(out / "index.json", catalog)
        for (namespace, name), index in indexes.items():
            prefix = out / "v1" / namespace / name
            write_json(prefix / "index.json", index)
            stored = self.records[(namespace, name)]
            for version in index["versions"]:
                record = stored[version["version"]]
                hex_digest = version["digest"].split(":", 1)[1]
                folder = prefix / "versions" / f"sha256-{hex_digest}"
                write_json(
                    folder / "licenses.json",
                    {
                        "schema": SCHEMA,
                        "image": f"{namespace}/{name}",
                        "digest": version["digest"],
                        "config_digest": version["config_digest"],
                        "summary": version["license_summary"],
                        "entries": record["_entries"],
                    },
                )
                (folder / "manifest.json").write_bytes(record["_manifest"])
                (folder / "config.json").write_bytes(record["_config"])
        self.render_html(out, catalog, indexes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path, required=True)
    parser.add_argument("--releases", type=pathlib.Path, required=True)
    parser.add_argument("--assets", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--epoch", type=int, default=None)
    parser.add_argument("--registry-url", required=True)
    args = parser.parse_args(argv)

    epoch = args.epoch
    if epoch is None:
        raw = os.environ.get("SOURCE_DATE_EPOCH")
        if raw is None:
            parser.error("pass --epoch or set SOURCE_DATE_EPOCH")
        epoch = int(raw)

    try:
        generator = Generator(args.repo, args.releases, args.assets, args.registry_url)
        generator.write(args.out, epoch)
    except SiteError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
