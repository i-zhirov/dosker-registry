"""The site generator documents."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import support
from tests.fixtures import oci

SITE_REPO = support.ROOT / "tests" / "fixtures" / "site-good"
GOLDEN = support.ROOT / "tests" / "golden" / "site"
EPOCH = 1763900000
REGISTRY_URL = "https://i-zhirov.github.io/doskerfile-registry"


class GenerateSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = pathlib.Path(self.directory.name)
        self.repo = base / "repo"
        shutil.copytree(SITE_REPO, self.repo)
        self.assets = base / "assets"
        inventory = oci.build_site_assets(self.assets)
        self.releases = base / "releases.json"
        support.write_json(self.releases, inventory)
        self.out = base / "site"

    def generate(self) -> None:
        command = [
            sys.executable,
            str(support.ROOT / "scripts" / "generate_site.py"),
            "--repo",
            str(self.repo),
            "--releases",
            str(self.releases),
            "--assets",
            str(self.assets),
            "--out",
            str(self.out),
            "--epoch",
            str(EPOCH),
            "--registry-url",
            REGISTRY_URL,
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def image_indexes(self) -> list[pathlib.Path]:
        return sorted(self.out.glob("v1/*/*/index.json"))

    def test_the_catalog_matches_the_golden_and_schema(self) -> None:
        self.generate()
        catalog = self.out / "index.json"
        self.assertEqual(
            catalog.read_bytes(),
            (GOLDEN / "index.json").read_bytes(),
        )
        support.assert_valid_schema(self, support.ROOT / "schemas" / "catalog.schema.json", catalog)

    def test_the_image_index_matches_the_schema(self) -> None:
        self.generate()
        indexes = self.image_indexes()
        self.assertEqual(len(indexes), len(oci.IMAGES))
        for path in indexes:
            with self.subTest(image=str(path)):
                support.assert_valid_schema(
                    self, support.ROOT / "schemas" / "image-index.schema.json", path
                )

    def test_the_license_record_matches_the_schema(self) -> None:
        self.generate()
        records = sorted(self.out.glob("v1/*/*/versions/*/licenses.json"))
        self.assertEqual(len(records), len(oci.IMAGES))
        for path in records:
            with self.subTest(record=str(path)):
                support.assert_valid_schema(
                    self, support.ROOT / "schemas" / "licenses.schema.json", path
                )

    def test_the_manifest_and_config_are_copied_byte_for_byte(self) -> None:
        self.generate()
        for path in self.image_indexes():
            index = json.loads(path.read_text(encoding="utf-8"))
            version = index["versions"][0]
            release = f"{index['namespace']}-{index['name']}"
            members = oci.read_members(
                (self.assets / release / f"{version['asset_digest']}.tar").read_bytes()
            )
            manifest = members["blobs/sha256/" + version["digest"].split(":", 1)[1]]
            config = members["blobs/sha256/" + version["config_digest"].split(":", 1)[1]]
            folder = path.parent / "versions" / (
                "sha256-" + version["digest"].split(":", 1)[1]
            )
            with self.subTest(image=str(path)):
                self.assertEqual((folder / "manifest.json").read_bytes(), manifest)
                self.assertEqual((folder / "config.json").read_bytes(), config)

    def test_the_current_tags_point_to_the_current_digest(self) -> None:
        self.generate()
        catalog = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        for entry in catalog["images"]:
            index = json.loads(
                (
                    self.out / "v1" / entry["namespace"] / entry["name"] / "index.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(index["tags"], entry["tags"])
            self.assertEqual(set(index["tags"].values()), {entry["latest"]["digest"]})

    def test_the_latest_version_is_the_current_version(self) -> None:
        self.generate()
        catalog = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        for entry in catalog["images"]:
            metadata = support.load_toml(
                self.repo
                / "images"
                / entry["namespace"]
                / entry["name"]
                / "registry.toml"
            )
            self.assertEqual(entry["latest"]["version"], metadata["version"])
            index = json.loads(
                (
                    self.out / "v1" / entry["namespace"] / entry["name"] / "index.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIn(
                entry["latest"],
                [
                    {"version": version["version"], "digest": version["digest"]}
                    for version in index["versions"]
                ],
            )

    def test_two_runs_are_byte_identical(self) -> None:
        self.generate()
        first = {
            path.relative_to(self.out): path.read_bytes()
            for path in sorted(self.out.rglob("*"))
            if path.is_file()
        }
        self.generate()
        second = {
            path.relative_to(self.out): path.read_bytes()
            for path in sorted(self.out.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(first, second)

    def test_check_jsonschema_accepts_every_generated_document(self) -> None:
        self.generate()
        catalog = support.ROOT / "schemas" / "catalog.schema.json"
        image_index = support.ROOT / "schemas" / "image-index.schema.json"
        licenses = support.ROOT / "schemas" / "licenses.schema.json"
        checked = 0
        for path in sorted(self.out.rglob("*.json")):
            if path == self.out / "index.json":
                schema = catalog
            elif path.name == "index.json":
                schema = image_index
            elif path.name == "licenses.json":
                schema = licenses
            else:
                continue
            with self.subTest(path=str(path.relative_to(self.out))):
                support.assert_valid_schema(self, schema, path)
                checked += 1
        self.assertEqual(checked, 1 + 2 * len(oci.IMAGES))


if __name__ == "__main__":
    unittest.main()
