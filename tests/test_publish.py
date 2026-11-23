"""The publisher and the changed-image helper."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests import support
from tests.fixtures import oci

PUBLISHED_AT = "2026-11-23T12:00:00Z"


class PublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = pathlib.Path(self.directory.name)
        self.release = self.base / "release"
        self.asset = self.base / "image.tar"
        self.asset.write_bytes(oci.build_image([oci.FREEDOS, oci.AGENT], "i-zhirov/hello-dos:1.0.0")["tar"])

    def run_publish(
        self, version: str = "1.0.0", asset: pathlib.Path | None = None, *extra: str
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(support.ROOT / "scripts" / "publish.py"),
                "--image",
                "i-zhirov/hello-dos",
                "--version",
                version,
                "--asset",
                str(asset or self.asset),
                "--release-dir",
                str(self.release),
                "--published-at",
                PUBLISHED_AT,
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_a_first_publish_writes_the_tar_and_the_sidecar(self) -> None:
        result = self.run_publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        tar = next(self.release.glob("*.tar"))
        self.assertEqual(tar.read_bytes(), self.asset.read_bytes())
        sidecar = json.loads((self.release / "1.0.0.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["version"], "1.0.0")
        self.assertEqual(sidecar["license_summary"], "redistributable")
        self.assertEqual(sidecar["published_at"], PUBLISHED_AT)
        self.assertEqual(sidecar["asset_digest"], tar.name[: -len(".tar")])
        self.assertEqual(sidecar["asset_size"], self.asset.stat().st_size)

    def test_a_second_publish_is_a_noop(self) -> None:
        self.assertEqual(self.run_publish().returncode, 0)
        before = (self.release / "1.0.0.json").read_bytes()
        result = self.run_publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already published", result.stdout)
        self.assertEqual(before, (self.release / "1.0.0.json").read_bytes())

    def test_a_different_digest_fails(self) -> None:
        self.release.mkdir(parents=True)
        (self.release / "1.0.0.json").write_text(
            json.dumps({"digest": "sha256:" + "0" * 64}), encoding="utf-8"
        )
        result = self.run_publish()
        self.assertEqual(result.returncode, 1)
        self.assertIn("bump the version", result.stderr)

    def test_a_license_correction_uses_a_new_version(self) -> None:
        self.assertEqual(self.run_publish().returncode, 0)
        corrected = self.base / "corrected.tar"
        corrected.write_bytes(oci.build_image([oci.AGENT], "i-zhirov/hello-dos:1.0.1")["tar"])
        result = self.run_publish("1.0.1", corrected)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.release / "1.0.0.json").is_file())
        self.assertTrue((self.release / "1.0.1.json").is_file())

    def test_a_missing_tar_is_restored_for_an_existing_sidecar(self) -> None:
        self.assertEqual(self.run_publish().returncode, 0)
        tar = next(self.release.glob("*.tar"))
        tar.unlink()
        result = self.run_publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already published", result.stdout)
        self.assertTrue(tar.is_file())

    def test_a_revoked_current_digest_is_not_republished(self) -> None:
        self.assertEqual(self.run_publish().returncode, 0)
        sidecar = json.loads((self.release / "1.0.0.json").read_text(encoding="utf-8"))
        tar = next(self.release.glob("*.tar"))
        tar.unlink()
        repo = self.base / "repo"
        repo.mkdir()
        (repo / "revoked.toml").write_text(
            "schema = 1\n"
            "[[revoked]]\n"
            'namespace = "i-zhirov"\n'
            'name = "hello-dos"\n'
            f'digest = "{sidecar["digest"]}"\n'
            'reason = "test"\n'
            'decided_at = "2026-11-23T00:00:00Z"\n',
            encoding="utf-8",
        )
        result = self.run_publish("1.0.0", None, "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipping revoked", result.stdout)
        self.assertFalse(tar.exists())

    def test_a_dry_run_writes_nothing(self) -> None:
        result = self.run_publish("1.0.0", None, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"version":"1.0.0"', result.stdout)
        self.assertFalse(self.release.exists())


class ChangedImagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        for image in ("images/i-zhirov/one", "images/i-zhirov/two"):
            (self.root / image).mkdir(parents=True)
        (self.root / "docs").mkdir()

    def run_helper(self, lines: list[str]) -> list[str]:
        result = subprocess.run(
            [
                sys.executable,
                str(support.ROOT / "scripts" / "changed_images.py"),
                "--root",
                str(self.root),
                "--json",
            ],
            input="\n".join(lines),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_it_lists_each_changed_image_once(self) -> None:
        images = self.run_helper(
            [
                "images/i-zhirov/one/registry.toml",
                "images/i-zhirov/one/Doskerfile",
                "images/i-zhirov/two/registry.toml",
            ]
        )
        self.assertEqual(images, ["images/i-zhirov/one", "images/i-zhirov/two"])

    def test_it_ignores_other_paths(self) -> None:
        images = self.run_helper(["docs/registry.md", "namespaces.toml", "images/i-zhirov"])
        self.assertEqual(images, [])

    def test_it_skips_a_deleted_image(self) -> None:
        images = self.run_helper(["images/i-zhirov/gone/registry.toml"])
        self.assertEqual(images, [])


if __name__ == "__main__":
    unittest.main()
