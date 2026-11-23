"""Shared helpers for the registry tests."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def check_jsonschema_command() -> list[str]:
    """Return the command that runs check-jsonschema."""
    binary = shutil.which("check-jsonschema")
    if binary is not None:
        return [binary]
    uvx = shutil.which("uvx")
    if uvx is not None:
        return [uvx, "--quiet", "check-jsonschema"]
    raise unittest.SkipTest("check-jsonschema is not installed")


def load_toml(path: pathlib.Path) -> dict:
    """Load one TOML file."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, value: object) -> None:
    """Write compact JSON with a trailing newline."""
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def check_schema(schema: pathlib.Path, instance: pathlib.Path) -> subprocess.CompletedProcess:
    """Run check-jsonschema on one converted document."""
    command = [*check_jsonschema_command(), "--schemafile", str(schema), str(instance)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def assert_valid_schema(test: unittest.TestCase, schema: pathlib.Path, instance: pathlib.Path) -> None:
    """Assert that one document passes its schema."""
    result = check_schema(schema, instance)
    test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
