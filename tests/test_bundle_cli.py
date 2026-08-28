import hashlib
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "bundle.py"


class BundleCLITests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(CLI), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_validate_accepts_reviewed_fixture_and_evidence(self) -> None:
        result = self.run_cli("validate", "--root", str(ROOT))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "validated 5 fixture records for en\n")

    def test_validate_rejects_a_fixture_without_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory) / "en.jsonl"
            evidence_path = Path(temporary_directory) / "en-evidence.jsonl"
            fixture_path.write_text(
                '{"locale":"en","key":"name.first_name","value":"Ada"}\n'
                '{"locale":"en","key":"name.last_name","value":"Lovelace"}\n',
                encoding="utf-8",
            )
            evidence_path.write_text(
                '{"recordIndex":0,"category":"name","sourceId":"faker-upstream","licenseId":"mit"}\n',
                encoding="utf-8",
            )
            result = self.run_cli(
                "validate",
                "--root",
                str(ROOT),
                "--fixtures",
                str(fixture_path),
                "--evidence",
                str(evidence_path),
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture record 1 has no source/license evidence", result.stderr)

    def test_package_is_deterministic_and_has_exact_runtime_members(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_result = self.run_cli(
                "package", "--root", str(ROOT), "--locale", "en", "--output", first
            )
            second_result = self.run_cli(
                "package", "--root", str(ROOT), "--locale", "en", "--output", second
            )
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)

            archive_name = "fakery-locale-en-2026.08.1.tar.gz"
            manifest_name = "fakery-locale-en-2026.08.1-manifest.json"
            first_archive = Path(first) / archive_name
            second_archive = Path(second) / archive_name
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            self.assertTrue((Path(first) / manifest_name).is_file())

            with tarfile.open(first_archive, "r:gz") as archive:
                self.assertEqual(archive.getnames(), ["manifest.json", "fakery.jsonl"])
                manifest = json.load(archive.extractfile("manifest.json"))
                fixture_bytes = archive.extractfile("fakery.jsonl").read()

            self.assertEqual(
                manifest,
                {
                    "fixtureSHA256": hashlib.sha256(fixture_bytes).hexdigest(),
                    "locale": "en",
                    "packVersion": "2026.08.1",
                    "schemaVersion": 1,
                },
            )

    def test_package_preserves_fixture_order_duplicates_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = self.run_cli(
                "package",
                "--root",
                str(ROOT),
                "--locale",
                "en",
                "--output",
                temporary_directory,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            archive_path = (
                Path(temporary_directory) / "fakery-locale-en-2026.08.1.tar.gz"
            )
            with tarfile.open(archive_path, "r:gz") as archive:
                packaged = archive.extractfile("fakery.jsonl").read()

        self.assertEqual(packaged, (ROOT / "data" / "en.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
