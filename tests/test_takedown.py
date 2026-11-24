"""The takedown helper."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests import support
from tests.fixtures import oci

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "c" * 64
ASSET = "sha256:" + "b" * 64


class TakedownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "revoked.toml").write_text(
            "schema = 1\n"
            "[[revoked]]\n"
            'namespace = "i-zhirov"\n'
            'name = "hello-dos"\n'
            f'digest = "{DIGEST}"\n'
            'reason = "test"\n'
            'decided_at = "2026-11-23T00:00:00Z"\n',
            encoding="utf-8",
        )
        self.assets = self.root / "assets"
        self.assets.mkdir()
        (self.assets / "1.0.0.json").write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "digest": DIGEST,
                    "asset_digest": ASSET,
                    "asset_compression": "zstd",
                }
            ),
            encoding="utf-8",
        )

    def run_helper(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(support.ROOT / "scripts" / "takedown.py"), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_finds_a_record(self) -> None:
        result = self.run_helper(
            "--check", "--repo", str(self.repo), "--namespace", "i-zhirov",
            "--name", "hello-dos", "--digest", DIGEST,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("recorded", result.stdout)

    def test_check_rejects_a_missing_record(self) -> None:
        result = self.run_helper(
            "--check", "--repo", str(self.repo), "--namespace", "i-zhirov",
            "--name", "hello-dos", "--digest", OTHER,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("open a pull request first", result.stderr)

    def test_names_finds_the_tar_and_sidecar(self) -> None:
        result = self.run_helper("--names", "--assets", str(self.assets), "--digest", DIGEST)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"{ASSET.replace(':', '.')}.tar.zst\t1.0.0.json")

    def test_stamp_records_the_content_digest(self) -> None:
        built = oci.build_image([oci.AGENT], "i-zhirov/hello-dos:1.0.0")
        compressed = oci.compress(built["tar"])
        tar = self.root / "image.tar.zst"
        tar.write_bytes(compressed)
        sidecar = {
            "version": "1.0.0",
            "digest": built["manifest_digest"],
            "asset_digest": oci.digest_bytes(compressed),
            "asset_size": len(compressed),
            "asset_compression": "zstd",
        }
        path = self.assets / "1.0.0.json"
        path.write_text(json.dumps(sidecar), encoding="utf-8")
        result = self.run_helper(
            "--stamp", "--assets", str(self.assets), "--asset", str(tar),
            "--digest", built["manifest_digest"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        stamped = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("content_digest", stamped)
        self.assertIn(str(path), result.stdout)

    def test_names_uses_the_release_asset_name(self) -> None:
        published = self.root / "release-assets.json"
        published.write_text(
            json.dumps(
                {"assets": [{"name": "sha256.bbb.tar.zst", "digest": ASSET}]}
            ),
            encoding="utf-8",
        )
        result = self.run_helper(
            "--names", "--assets", str(self.assets), "--digest", DIGEST,
            "--release-assets", str(published),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "sha256.bbb.tar.zst\t1.0.0.json")

    def test_names_rejects_a_missing_sidecar(self) -> None:
        result = self.run_helper("--names", "--assets", str(self.assets), "--digest", OTHER)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no sidecar", result.stderr)

    def test_a_retry_still_names_the_sidecar(self) -> None:
        first = self.run_helper("--names", "--assets", str(self.assets), "--digest", DIGEST)
        second = self.run_helper("--names", "--assets", str(self.assets), "--digest", DIGEST)
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue((self.assets / "1.0.0.json").is_file())


if __name__ == "__main__":
    unittest.main()
