#!/usr/bin/env python3
"""Validate reviewed source fixtures and build deterministic Fakery locale bundles."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path
from typing import Any


class ValidationError(Exception):
    """A stable validation failure intended for CLI output."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot read JSON {path}: {error}") from error


def load_jsonl(path: Path, document_name: str) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        raw_data = path.read_bytes()
        text = raw_data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValidationError(f"cannot read {document_name} {path}: {error}") from error
    if raw_data.startswith(b"\xef\xbb\xbf"):
        raise ValidationError(f"{document_name} must be UTF-8 without a byte-order mark")
    lines = text.splitlines()
    if not lines:
        raise ValidationError(f"{document_name} is empty")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line:
            raise ValidationError(f"{document_name} line {index + 1} is blank")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValidationError(
                f"{document_name} line {index + 1} is invalid JSON: {error.msg}"
            ) from error
        if not isinstance(record, dict):
            raise ValidationError(f"{document_name} line {index + 1} must be an object")
        records.append(record)
    return raw_data, records


def required_text(record: dict[str, Any], field: str, context: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or value == "":
        raise ValidationError(f"{context} requires non-empty text field {field}")
    return value


def registry_entries(root: Path, name: str) -> list[dict[str, Any]]:
    document = load_json(root / "registry" / f"{name}.json")
    entries = document.get(name) if isinstance(document, dict) else None
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValidationError(f"registry/{name}.json requires an ordered {name} array")
    return entries


def validate_locale(
    root: Path,
    locale_entry: dict[str, Any],
    fixture_override: Path | None = None,
    evidence_override: Path | None = None,
) -> tuple[bytes, int, str]:
    locale = required_text(locale_entry, "id", "locale registry entry")
    fixture_path = fixture_override or root / required_text(
        locale_entry, "fixture", f"locale {locale}"
    )
    evidence_path = evidence_override or root / required_text(
        locale_entry, "evidence", f"locale {locale}"
    )
    fixture_data, fixtures = load_jsonl(fixture_path, "fixture data")
    _, evidence = load_jsonl(evidence_path, "fixture evidence")

    categories = registry_entries(root, "categories")
    category_prefixes = {
        required_text(category, "id", "category registry entry"): required_text(
            category, "keyPrefix", "category registry entry"
        )
        for category in categories
    }
    source_document = load_json(root / "evidence" / "sources.json")
    license_document = load_json(root / "evidence" / "licenses.json")
    source_entries = source_document.get("sources") if isinstance(source_document, dict) else None
    license_entries = (
        license_document.get("licenses") if isinstance(license_document, dict) else None
    )
    if not isinstance(source_entries, list) or not isinstance(license_entries, list):
        raise ValidationError("source and license evidence require ordered arrays")
    source_ids = {
        required_text(entry, "id", "source evidence entry")
        for entry in source_entries
        if isinstance(entry, dict)
    }
    license_ids = {
        required_text(entry, "id", "license evidence entry")
        for entry in license_entries
        if isinstance(entry, dict)
    }

    evidence_by_index: dict[int, list[dict[str, Any]]] = {}
    for link_number, link in enumerate(evidence):
        record_index = link.get("recordIndex")
        if not isinstance(record_index, int) or isinstance(record_index, bool):
            raise ValidationError(
                f"fixture evidence line {link_number + 1} requires integer recordIndex"
            )
        if record_index < 0 or record_index >= len(fixtures):
            raise ValidationError(
                f"fixture evidence line {link_number + 1} references absent fixture record {record_index}"
            )
        category = required_text(link, "category", "fixture evidence")
        source_id = required_text(link, "sourceId", "fixture evidence")
        license_id = required_text(link, "licenseId", "fixture evidence")
        if category not in category_prefixes:
            raise ValidationError(f"fixture evidence uses unregistered category {category}")
        if source_id not in source_ids:
            raise ValidationError(f"fixture evidence uses unknown source {source_id}")
        if license_id not in license_ids:
            raise ValidationError(f"fixture evidence uses unknown license {license_id}")
        evidence_by_index.setdefault(record_index, []).append(link)

    for index, fixture in enumerate(fixtures):
        context = f"fixture record {index}"
        fixture_locale = required_text(fixture, "locale", context)
        key = required_text(fixture, "key", context)
        if "value" not in fixture or fixture["value"] is None:
            raise ValidationError(f"{context} requires value")
        if fixture_locale != locale:
            raise ValidationError(
                f"{context} locale {fixture_locale!r} does not match {locale!r}"
            )
        links = evidence_by_index.get(index)
        if not links:
            raise ValidationError(f"{context} has no source/license evidence")
        matching_categories = [
            category
            for category, prefix in category_prefixes.items()
            if key.startswith(prefix)
        ]
        if len(matching_categories) != 1:
            raise ValidationError(f"{context} key {key!r} has no single registered category")
        for link in links:
            if link["category"] != matching_categories[0]:
                raise ValidationError(
                    f"{context} category {link['category']!r} does not match key {key!r}"
                )

    return fixture_data, len(fixtures), locale


def selected_locale(root: Path, locale: str) -> dict[str, Any]:
    entries = registry_entries(root, "locales")
    matches = [entry for entry in entries if entry.get("id") == locale]
    if len(matches) != 1:
        raise ValidationError(f"locale {locale!r} is not registered exactly once")
    return matches[0]


def deterministic_archive(
    archive_path: Path, manifest_data: bytes, fixture_data: bytes
) -> None:
    with archive_path.open("wb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT
            ) as archive:
                for name, data in (
                    ("manifest.json", manifest_data),
                    ("fakery.jsonl", fixture_data),
                ):
                    information = tarfile.TarInfo(name)
                    information.size = len(data)
                    information.mtime = 0
                    information.mode = 0o644
                    information.uid = 0
                    information.gid = 0
                    information.uname = ""
                    information.gname = ""
                    archive.addfile(information, io.BytesIO(data))


def validate_command(arguments: argparse.Namespace) -> None:
    root = arguments.root.resolve()
    if arguments.fixtures or arguments.evidence:
        locale_entry = selected_locale(root, "en")
        _, count, locale = validate_locale(
            root, locale_entry, arguments.fixtures, arguments.evidence
        )
        print(f"validated {count} fixture records for {locale}")
        return
    total = 0
    locales: list[str] = []
    for locale_entry in registry_entries(root, "locales"):
        _, count, locale = validate_locale(root, locale_entry)
        total += count
        locales.append(locale)
    print(f"validated {total} fixture records for {','.join(locales)}")


def package_command(arguments: argparse.Namespace) -> None:
    root = arguments.root.resolve()
    locale_entry = selected_locale(root, arguments.locale)
    fixture_data, _, locale = validate_locale(root, locale_entry)
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip("\n")
    except OSError as error:
        raise ValidationError(f"cannot read VERSION: {error}") from error
    if version == "" or "\n" in version or "\r" in version:
        raise ValidationError("VERSION must contain one non-empty line")
    manifest = {
        "fixtureSHA256": hashlib.sha256(fixture_data).hexdigest(),
        "locale": locale,
        "packVersion": version,
        "schemaVersion": 1,
    }
    manifest_data = (
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base_name = f"fakery-locale-{locale}-{version}"
    archive_path = output / f"{base_name}.tar.gz"
    manifest_path = output / f"{base_name}-manifest.json"
    deterministic_archive(archive_path, manifest_data, fixture_data)
    manifest_path.write_bytes(manifest_data)
    print(archive_path)
    print(manifest_path)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    subcommands = cli.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("--root", type=Path, default=Path.cwd())
    validate.add_argument("--fixtures", type=Path)
    validate.add_argument("--evidence", type=Path)
    validate.set_defaults(handler=validate_command)
    package = subcommands.add_parser("package")
    package.add_argument("--root", type=Path, default=Path.cwd())
    package.add_argument("--locale", required=True)
    package.add_argument("--output", type=Path, required=True)
    package.set_defaults(handler=package_command)
    return cli


def main() -> int:
    arguments = parser().parse_args()
    try:
        arguments.handler(arguments)
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
