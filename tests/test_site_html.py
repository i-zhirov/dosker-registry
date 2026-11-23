"""The generated HTML pages."""

from __future__ import annotations

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


class SiteHtmlTests(unittest.TestCase):
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

    def version_page(self, namespace: str, name: str) -> pathlib.Path:
        pages = sorted(self.out.glob(f"v1/{namespace}/{name}/versions/*/index.html"))
        self.assertEqual(len(pages), 1)
        return pages[0]

    def test_the_home_lists_the_images(self) -> None:
        self.generate()
        page = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("i-zhirov/hello-dos", page)
        self.assertIn("i-zhirov/old-game", page)
        self.assertIn("data-search", page)
        self.assertIn("site/app.js", page)

    def test_the_image_page_lists_the_version(self) -> None:
        self.generate()
        page = (self.out / "v1/i-zhirov/hello-dos/index.html").read_text(encoding="utf-8")
        self.assertIn("1.0.0", page)
        self.assertIn("versions/sha256-", page)
        self.assertIn("Minimal DOS environment that echoes a greeting.", page)

    def test_the_version_page_shows_the_entries_and_the_asset(self) -> None:
        self.generate()
        page = self.version_page("i-zhirov", "hello-dos").read_text(encoding="utf-8")
        self.assertIn("FreeDOS", page)
        self.assertIn("GPL-2.0-only", page)
        self.assertIn("Download the image tar", page)
        self.assertIn("sha256:", page)

    def test_the_abandonware_notice_is_present(self) -> None:
        self.generate()
        page = self.version_page("i-zhirov", "old-game").read_text(encoding="utf-8")
        self.assertIn("Abandonware notice.", page)
        self.assertIn("abandonware", page)
        home = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("requires acceptance", home)

    def test_the_static_assets_are_copied(self) -> None:
        self.generate()
        for name in ("style.css", "app.js"):
            with self.subTest(asset=name):
                self.assertEqual(
                    (self.out / "site" / name).read_bytes(),
                    (support.ROOT / "site" / name).read_bytes(),
                )

    def test_user_text_is_escaped(self) -> None:
        self.generate()
        metadata = self.repo / "images" / "i-zhirov" / "hello-dos" / "registry.toml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                "Minimal DOS environment that echoes a greeting.",
                "A <script>alert(1)</script> image.",
            ),
            encoding="utf-8",
        )
        self.generate()
        page = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_the_pages_are_deterministic(self) -> None:
        self.generate()
        first = (self.out / "index.html").read_bytes()
        self.generate()
        self.assertEqual(first, (self.out / "index.html").read_bytes())


if __name__ == "__main__":
    unittest.main()
