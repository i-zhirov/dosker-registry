"""The takedown contact, response window, and signing decision stay recorded."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = (ROOT / "POLICY.md").read_text(encoding="utf-8")

    def test_names_the_takedown_contact(self) -> None:
        self.assertIn("https://github.com/i-zhirov/dosker-registry/issues", self.policy)

    def test_names_the_response_window(self) -> None:
        self.assertIn("7 days", self.policy)

    def test_records_the_signing_decision(self) -> None:
        self.assertIn("unsigned", self.policy)
        self.assertIn("digest", self.policy.lower())

    def test_names_the_tar_and_the_sidecar(self) -> None:
        self.assertIn("tar", self.policy)
        self.assertIn("sidecar", self.policy)


if __name__ == "__main__":
    unittest.main()
