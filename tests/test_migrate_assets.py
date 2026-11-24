"""The one-time asset migration tool."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import zstandard

from tests import support
from tests.fixtures import oci

PUBLISHED_AT = "2026-11-23T12:00:00Z"


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class MigrateAssetsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.assets = self.root / "assets"
        self.out = self.root / "out"
        self.backup = self.root / "backup"
        self.assets.mkdir()
        built = oci.build_image([oci.FREEDOS, oci.AGENT], "i-zhirov/hello-dos:1.0.0")
        self.old_bytes = built["tar"]
        self.old_digest = oci.digest_bytes(self.old_bytes)
        self.old_tar = self.assets / f"{self.old_digest}.tar"
        self.old_tar.write_bytes(self.old_bytes)
        self.old_sidecar = {
            "version": "1.0.0",
            "digest": built["manifest_digest"],
            "config_digest": built["config_digest"],
            "license_summary": oci.summary([oci.FREEDOS, oci.AGENT]),
            "published_at": PUBLISHED_AT,
            "asset_digest": self.old_digest,
            "asset_size": len(self.old_bytes),
            "content_digest": oci.content_digest(built["manifest_bytes"]),
        }
        support.write_json(self.assets / "1.0.0.json", self.old_sidecar)

    def run_tool(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(support.ROOT / "scripts" / "migrate_assets.py"), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def prepare(self) -> subprocess.CompletedProcess:
        return self.run_tool(
            "--prepare",
            "--assets",
            str(self.assets),
            "--out",
            str(self.out),
            "--backup",
            str(self.backup),
        )

    def copy_migrated(self) -> pathlib.Path:
        for path in self.out.iterdir():
            shutil.copy2(path, self.assets / path.name)
        return self.assets / "1.0.0.json"

    def test_prepare_writes_the_compressed_asset_and_sidecar(self) -> None:
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        sidecar = json.loads((self.out / "1.0.0.json").read_text(encoding="utf-8"))
        compressed_path = self.out / (
            sidecar["asset_digest"].replace(":", ".") + ".tar.zst"
        )
        compressed = compressed_path.read_bytes()

        self.assertEqual(sidecar["asset_compression"], "zstd")
        self.assertEqual(sidecar["asset_digest"], digest(compressed))
        self.assertEqual(sidecar["asset_size"], len(compressed))
        self.assertEqual(sidecar["digest"], self.old_sidecar["digest"])
        self.assertEqual(sidecar["config_digest"], self.old_sidecar["config_digest"])
        self.assertEqual(sidecar["content_digest"], self.old_sidecar["content_digest"])
        self.assertEqual(zstandard.ZstdDecompressor().decompress(compressed), self.old_bytes)
        self.assertEqual(self.old_tar.read_bytes(), self.old_bytes)
        self.assertEqual(
            (self.backup / "1.0.0.json").read_bytes(),
            (self.assets / "1.0.0.json").read_bytes(),
        )
        self.assertIn("prepared 1.0.0", result.stdout)

    def test_prepare_finds_a_sanitized_old_tar_name(self) -> None:
        sanitized = self.old_tar.with_name(
            self.old_sidecar["asset_digest"].replace(":", ".") + ".tar"
        )
        self.old_tar.rename(sanitized)
        self.old_tar = sanitized
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.out / "1.0.0.json").is_file())

    def test_prepare_is_deterministic(self) -> None:
        first = self.prepare()
        self.assertEqual(first.returncode, 0, first.stderr)
        second_out = self.root / "out2"
        second_backup = self.root / "backup2"
        second = self.run_tool(
            "--prepare",
            "--assets",
            str(self.assets),
            "--out",
            str(second_out),
            "--backup",
            str(second_backup),
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        for path in sorted(self.out.iterdir()):
            self.assertEqual(path.read_bytes(), (second_out / path.name).read_bytes())

    def test_prepare_rejects_a_tampered_old_tar(self) -> None:
        self.old_tar.write_bytes(self.old_bytes + b"tampered")
        result = self.prepare()
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match its sidecar", result.stderr)
        self.assertFalse((self.out / "1.0.0.json").exists())

    def test_prepare_rejects_a_changed_manifest_digest(self) -> None:
        sidecar_path = self.assets / "1.0.0.json"
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["digest"] = "sha256:" + "0" * 64
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
        result = self.prepare()
        self.assertEqual(result.returncode, 1)
        self.assertIn("names", result.stderr)
        self.assertFalse((self.out / "1.0.0.json").exists())

    def test_prepare_adds_a_missing_content_digest(self) -> None:
        sidecar_path = self.assets / "1.0.0.json"
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        del sidecar["content_digest"]
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        migrated = json.loads((self.out / "1.0.0.json").read_text(encoding="utf-8"))
        self.assertIn("content_digest", migrated)

    def test_prepare_skips_an_already_migrated_sidecar(self) -> None:
        self.assertEqual(self.prepare().returncode, 0)
        self.copy_migrated()
        second_out = self.root / "out2"
        second_backup = self.root / "backup2"
        result = self.run_tool(
            "--prepare",
            "--assets",
            str(self.assets),
            "--out",
            str(second_out),
            "--backup",
            str(second_backup),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already migrated", result.stdout)
        self.assertFalse((second_out / "1.0.0.json").exists())

    def test_cleanup_prints_the_old_tar_after_verification(self) -> None:
        self.assertEqual(self.prepare().returncode, 0)
        self.copy_migrated()
        result = self.run_tool(
            "--cleanup", "--assets", str(self.assets), "--backup", str(self.backup)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), self.old_tar.name)
        self.assertTrue(self.old_tar.is_file())

    def test_cleanup_rejects_an_unmigrated_sidecar(self) -> None:
        self.assertEqual(self.prepare().returncode, 0)
        result = self.run_tool(
            "--cleanup", "--assets", str(self.assets), "--backup", str(self.backup)
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not migrated", result.stderr)

    def test_cleanup_rejects_a_tampered_new_asset(self) -> None:
        self.assertEqual(self.prepare().returncode, 0)
        self.copy_migrated()
        new_asset = next(self.assets.glob("*.tar.zst"))
        new_asset.write_bytes(new_asset.read_bytes() + b"tampered")
        result = self.run_tool(
            "--cleanup", "--assets", str(self.assets), "--backup", str(self.backup)
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("wrong", result.stderr)

    def test_cleanup_tolerates_a_missing_old_tar(self) -> None:
        self.assertEqual(self.prepare().returncode, 0)
        self.copy_migrated()
        self.old_tar.unlink()
        result = self.run_tool(
            "--cleanup", "--assets", str(self.assets), "--backup", str(self.backup)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("already absent", result.stderr)

    def test_cleanup_rejects_a_tampered_old_tar(self) -> None:
        self.assertEqual(self.prepare().returncode, 0)
        self.copy_migrated()
        self.old_tar.write_bytes(self.old_bytes + b"tampered")
        result = self.run_tool(
            "--cleanup", "--assets", str(self.assets), "--backup", str(self.backup)
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match its sidecar", result.stderr)

    def test_prepare_rejects_the_same_directory(self) -> None:
        result = self.run_tool(
            "--prepare",
            "--assets",
            str(self.assets),
            "--out",
            str(self.assets),
            "--backup",
            str(self.backup),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("different directories", result.stderr)


if __name__ == "__main__":
    unittest.main()
