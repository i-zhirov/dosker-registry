"""The registry schemas and the root metadata files."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from tests.support import ROOT, assert_valid_schema, check_schema, check_jsonschema_command
from tests.support import load_toml, write_json

SCHEMAS = [
    "catalog",
    "image-index",
    "licenses",
    "namespaces",
    "registry",
    "revoked",
]


class SchemaTests(unittest.TestCase):
    def test_every_schema_parses(self) -> None:
        for name in SCHEMAS:
            with self.subTest(schema=name):
                path = ROOT / "schemas" / f"{name}.schema.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertTrue(value["$id"].startswith("https://"))

    def test_namespaces_toml_passes_the_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instance = pathlib.Path(directory) / "namespaces.json"
            write_json(instance, load_toml(ROOT / "namespaces.toml"))
            assert_valid_schema(self, ROOT / "schemas" / "namespaces.schema.json", instance)

    def test_revoked_toml_passes_the_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instance = pathlib.Path(directory) / "revoked.json"
            write_json(instance, load_toml(ROOT / "revoked.toml"))
            assert_valid_schema(self, ROOT / "schemas" / "revoked.schema.json", instance)

    def test_every_registry_toml_passes_the_schema(self) -> None:
        image_dirs = sorted((ROOT / "images").glob("*/*/registry.toml"))
        if not image_dirs:
            self.skipTest("the first image lands with Task 2")
        with tempfile.TemporaryDirectory() as directory:
            for path in image_dirs:
                with self.subTest(image=str(path.parent.relative_to(ROOT))):
                    instance = pathlib.Path(directory) / (path.parent.name + ".json")
                    write_json(instance, load_toml(path))
                    assert_valid_schema(
                        self, ROOT / "schemas" / "registry.schema.json", instance
                    )

    def test_a_bad_namespace_document_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            instance = pathlib.Path(directory) / "namespaces.json"
            write_json(instance, {"schema": 1, "owners": {"I-Zhirov": {"github": "i-zhirov", "proof": "nope"}}})
            result = check_schema(ROOT / "schemas" / "namespaces.schema.json", instance)
            self.assertNotEqual(result.returncode, 0)

    def test_the_schema_checker_is_available(self) -> None:
        self.assertTrue(check_jsonschema_command())

    def test_the_validate_workflow_is_read_only(self) -> None:
        text = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("pages: write", text)
        self.assertNotIn("dosker build", text)
        self.assertNotIn("dosker run", text)
        self.assertIn('DOSKER_VERSION: "0.1.4"', text)
        self.assertIn("dosker registry validate", text)

    def test_the_local_checker_uses_every_schema(self) -> None:
        text = (ROOT / "scripts" / "validate_schemas.sh").read_text(encoding="utf-8")
        for name in ("namespaces", "revoked", "registry"):
            with self.subTest(schema=name):
                self.assertIn(f"{name}.schema.json", text)


if __name__ == "__main__":
    unittest.main()
