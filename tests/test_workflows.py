"""Structural checks for the reusable site workflow."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read_workflow(name):
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


class SharedSiteWorkflowTest(unittest.TestCase):
    def test_site_workflow_is_reusable(self):
        text = read_workflow("site.yml")
        self.assertIn("workflow_call", text)
        self.assertNotIn("concurrency:", text)
        self.assertIn("REGISTRY_URL", text)

    def test_publish_calls_the_site_workflow(self):
        text = read_workflow("publish.yml")
        self.assertIn("uses: ./.github/workflows/site.yml", text)
        self.assertNotIn("actions/upload-pages-artifact", text)
        self.assertNotIn("actions/deploy-pages", text)

    def test_publish_redeploys_when_the_site_workflow_changes(self):
        text = read_workflow("publish.yml")
        paths = text.split("paths:", 1)[1].split("workflow_dispatch:", 1)[0]
        self.assertIn('".github/workflows/site.yml"', paths)

    def test_publish_downloads_existing_sidecars_before_publishing(self):
        text = read_workflow("publish.yml")
        build = text.split("release_dir=", 1)[1]
        self.assertLess(
            build.index('gh release download "$tag"'),
            build.index("scripts/publish.py"),
        )

    def test_takedown_calls_the_site_workflow(self):
        text = read_workflow("takedown.yml")
        self.assertIn("uses: ./.github/workflows/site.yml", text)
        self.assertIn("group: publish", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)


if __name__ == "__main__":
    unittest.main()
