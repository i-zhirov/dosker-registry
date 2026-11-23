"""The site generator refusal cases."""

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
EPOCH = 1763900000
REGISTRY_URL = "https://i-zhirov.github.io/dosker-registry"


class GenerateSiteErrorTests(unittest.TestCase):
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

    def run_generator(self) -> subprocess.CompletedProcess:
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
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def assert_fails(self, fragment: str) -> None:
        result = self.run_generator()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(fragment, result.stderr)

    def generate(self) -> None:
        result = self.run_generator()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def inventory(self) -> list[dict]:
        return json.loads(self.releases.read_text(encoding="utf-8"))

    def write_inventory(self, value: list[dict]) -> None:
        support.write_json(self.releases, value)

    def release(self, tag: str) -> dict:
        return next(item for item in self.inventory() if item["tag_name"] == tag)

    def replace(self, path: pathlib.Path, old: str, new: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def revoke(self, namespace: str, name: str, digest: str) -> None:
        (self.repo / "revoked.toml").write_text(
            "schema = 1\n\n[[revoked]]\n"
            f'namespace = "{namespace}"\nname = "{name}"\ndigest = "{digest}"\n'
            'reason = "Test"\ndecided_at = "2026-11-23T12:00:00Z"\n',
            encoding="utf-8",
        )

    def metadata(self, name: str) -> pathlib.Path:
        return self.repo / "images" / "i-zhirov" / name / "registry.toml"

    def test_a_duplicate_tag_fails(self) -> None:
        self.replace(self.metadata("old-game"), 'tags = ["legacy"]', 'tags = ["latest"]')
        self.assert_fails("duplicate tag")

    def test_a_missing_asset_fails(self) -> None:
        release_dir = self.assets / "i-zhirov-hello-dos"
        next(release_dir.glob("*.tar")).unlink()
        self.assert_fails("missing asset")

    def test_a_tampered_asset_fails(self) -> None:
        release_dir = self.assets / "i-zhirov-hello-dos"
        with next(release_dir.glob("*.tar")).open("ab") as handle:
            handle.write(b"x")
        self.assert_fails("asset digest mismatch")

    def test_a_version_conflict_fails(self) -> None:
        sidecar = self.assets / "i-zhirov-hello-dos" / "1.0.0.json"
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        value["digest"] = "sha256:" + "0" * 64
        support.write_json(sidecar, value)
        self.assert_fails("names digest")

    def test_a_missing_current_sidecar_fails(self) -> None:
        (self.assets / "i-zhirov-hello-dos" / "1.0.0.json").unlink()
        self.assert_fails("invalid sidecar")

    def test_an_image_without_tags_fails(self) -> None:
        self.replace(self.metadata("old-game"), 'tags = ["legacy"]', "tags = []")
        self.assert_fails("declares no tags")

    def test_a_path_traversal_is_rejected(self) -> None:
        self.replace(self.metadata("hello-dos"), 'version = "1.0.0"', 'version = "../escape"')
        self.assert_fails("unsafe version")

    def test_a_revoked_version_and_its_tags_are_omitted(self) -> None:
        assets, digest = oci.build_version_assets(
            self.assets,
            "i-zhirov-hello-dos",
            "0.9.0",
            "i-zhirov/hello-dos:0.9.0",
            [oci.AGENT],
            "2026-11-22T12:00:00Z",
        )
        inventory = self.inventory()
        self.release_assets(inventory, "i-zhirov-hello-dos").extend(assets)
        self.write_inventory(inventory)
        self.revoke("i-zhirov", "hello-dos", digest)
        revoked_tar = next(asset for asset in assets if asset["name"].endswith(".tar"))
        (self.assets / "i-zhirov-hello-dos" / revoked_tar["name"]).unlink()

        self.generate()

        index = json.loads(
            (self.out / "v1" / "i-zhirov" / "hello-dos" / "index.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([version["version"] for version in index["versions"]], ["1.0.0"])
        self.assertEqual(set(index["tags"].values()), {index["versions"][0]["digest"]})
        self.assertNotIn(digest, json.dumps(index))
        hex_digest = digest.split(":", 1)[1]
        self.assertFalse(
            (self.out / "v1" / "i-zhirov" / "hello-dos" / "versions" / f"sha256-{hex_digest}").exists()
        )

    def test_a_revoked_current_version_omits_the_image_with_older_live_versions(self) -> None:
        assets, _ = oci.build_version_assets(
            self.assets,
            "i-zhirov-hello-dos",
            "0.9.0",
            "i-zhirov/hello-dos:0.9.0",
            [oci.AGENT],
            "2026-11-22T12:00:00Z",
        )
        inventory = self.inventory()
        self.release_assets(inventory, "i-zhirov-hello-dos").extend(assets)
        self.write_inventory(inventory)
        sidecar = self.assets / "i-zhirov-hello-dos" / "1.0.0.json"
        current = json.loads(sidecar.read_text(encoding="utf-8"))["digest"]
        self.revoke("i-zhirov", "hello-dos", current)

        self.generate()

        catalog = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual([image["name"] for image in catalog["images"]], ["old-game"])
        self.assertFalse((self.out / "v1" / "i-zhirov" / "hello-dos").exists())

    def test_an_image_with_no_live_version_is_omitted(self) -> None:
        sidecar = self.assets / "i-zhirov-old-game" / "1.0.0.json"
        digest = json.loads(sidecar.read_text(encoding="utf-8"))["digest"]
        self.revoke("i-zhirov", "old-game", digest)

        self.generate()

        catalog = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual([image["name"] for image in catalog["images"]], ["hello-dos"])
        self.assertFalse((self.out / "v1" / "i-zhirov" / "old-game").exists())

    def test_a_revoked_digest_does_not_remove_a_local_copy(self) -> None:
        sidecar = self.assets / "i-zhirov-old-game" / "1.0.0.json"
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        self.revoke("i-zhirov", "old-game", value["digest"])
        tar = self.assets / "i-zhirov-old-game" / f"{value['asset_digest']}.tar"

        self.generate()

        self.assertTrue(tar.is_file())
        self.assertEqual(
            oci.digest_bytes(tar.read_bytes()), value["asset_digest"]
        )

    @staticmethod
    def release_assets(inventory: list[dict], tag: str) -> list[dict]:
        return next(item for item in inventory if item["tag_name"] == tag)["assets"]


if __name__ == "__main__":
    unittest.main()
