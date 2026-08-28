import hashlib
import json
import os
import shutil
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

    def copy_root(self, temporary_directory: str) -> Path:
        copied = Path(temporary_directory) / "repository"
        shutil.copytree(ROOT, copied)
        return copied

    def archive_bytes(self, archive: tarfile.TarFile, name: str) -> bytes:
        member = archive.extractfile(name)
        if member is None:
            self.fail(f"archive member is not a regular file: {name}")
        return member.read()

    def test_validate_rejects_wrong_source_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = self.copy_root(temporary_directory)
            path = root / "evidence" / "sources.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["schemaVersion"] = 99
            path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli("validate", "--root", str(root))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evidence/sources.json.schemaVersion must equal 1", result.stderr)

    def test_validate_rejects_license_without_spdx_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = self.copy_root(temporary_directory)
            path = root / "evidence" / "licenses.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            del document["licenses"][0]["spdxId"]
            path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli("validate", "--root", str(root))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires property spdxId", result.stderr)

    def test_validate_rejects_forbidden_fixture_property(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = self.copy_root(temporary_directory)
            path = root / "data" / "en.jsonl"
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            records[0]["unexpected"] = "not allowed"
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
            )

            result = self.run_cli("validate", "--root", str(root))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture data line 1 forbids property unexpected", result.stderr)

    def test_remote_tag_guard_rejects_tag_missing_from_shallow_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            remote = temporary / "remote.git"
            source = temporary / "source"
            shallow = temporary / "shallow"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            (source / "reviewed.txt").write_text("reviewed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "reviewed.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "reviewed"], check=True)
            subprocess.run(["git", "-C", str(source), "tag", "existing-tag"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "push", str(remote), "HEAD:main", "existing-tag"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "clone", "--depth", "1", f"file://{remote}", str(shallow)],
                check=True,
                capture_output=True,
            )

            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "refuse_existing_release.sh")],
                cwd=shallow,
                env={**os.environ, "TAG": "existing-tag"},
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to replace existing immutable tag or release", result.stderr)

    def test_validate_rejects_source_without_required_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = self.copy_root(temporary_directory)
            path = root / "evidence" / "sources.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            del document["sources"][0]["url"]
            path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli("validate", "--root", str(root))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires property url", result.stderr)

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
                manifest = json.loads(self.archive_bytes(archive, "manifest.json"))
                fixture_bytes = self.archive_bytes(archive, "fakery.jsonl")

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
                packaged = self.archive_bytes(archive, "fakery.jsonl")

        self.assertEqual(packaged, (ROOT / "data" / "en.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
