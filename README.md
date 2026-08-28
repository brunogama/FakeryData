# FakeryData

FakeryData is the reviewed, public source of locale fixture data for [Fakery](https://github.com/brunogama/Fakery). It separates attributable source data from the two-file runtime bundle consumed by Fakery.

## Contracts

- `registry/categories.json` is the ordered category registry.
- `registry/locales.json` maps a locale to its canonical fixture and evidence files.
- `data/*.jsonl` contains canonical runtime fixture records. Record order and UTF-8 text are retained byte-for-byte by packaging. The validator does not deduplicate records.
- `evidence/sources.json` and `evidence/licenses.json` are the source and license registries.
- `evidence/*.jsonl` links each fixture record index to one or more registered source/license pairs and a registered category.
- `schema/` contains the JSON Schema contracts for every registry, evidence record, fixture record, and runtime manifest.

Run the public validation and packaging seams:

```sh
python3 scripts/bundle.py validate --root .
python3 -m unittest discover -s tests -v
rm -rf dist
python3 scripts/bundle.py package --root . --locale en --output dist
```

Packaging creates these immutable, versioned release assets for the committed `VERSION`:

- `fakery-locale-<locale>-<version>.tar.gz`
- `fakery-locale-<locale>-<version>-manifest.json`

The gzip archive contains exactly these two top-level members in this order:

1. `manifest.json`
2. `fakery.jsonl`

For version `2026.08.1`, the immutable tag and URL shape is:

- tag: `locale-en-v2026.08.1`
- archive: `https://github.com/brunogama/FakeryData/releases/download/locale-en-v2026.08.1/fakery-locale-en-2026.08.1.tar.gz`
- manifest: `https://github.com/brunogama/FakeryData/releases/download/locale-en-v2026.08.1/fakery-locale-en-2026.08.1-manifest.json`

## Review and publication boundary

Pull requests and pushes to `main` run `.github/workflows/validate.yml`. No script, bot, or generated agent work has release credentials or a direct publication path. `.github/workflows/publish.yml` is manual-only, accepts only a registered locale, validates the reviewed `main` commit again, refuses an existing tag or release, checks the archive members character-for-character, and then creates the two versioned assets.

Publication is deliberately fail-closed until the GitHub settings in [SETUP.md](SETUP.md) are completed. There is no release in the initial repository setup.
