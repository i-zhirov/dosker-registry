# DOSker registry

This repository holds the text that defines the DOSker image registry. It is a
separate repository from the `dosker` code repository.

## Layout

```
namespaces.toml              proven GitHub handles
revoked.toml                 takedown records
images/<owner>/<name>/       Doskerfile, registry.toml, NOTICE.txt
schemas/                     the six JSON schemas
site/                        HTML templates and CSS
scripts/                     validation, generation, and publish helpers
tests/                       unit tests and fixtures
.github/workflows/           validate.yml and publish.yml
```

`images/<owner>/<name>/registry.toml`:

```toml
schema = 1
version = "1.0.0"
tags = ["latest"]
description = "One line about the image"
homepage = "https://example.org/image"
```

A version is immutable. A tag is a movable label. A license correction is a new
version. A rebuild that gives a new digest for an existing version fails.

## Check the repository locally

The checks need Python 3.11 or newer, `check-jsonschema`, `actionlint`, and a
`dosker` binary that contains `registry validate` and `registry check-final`.

```sh
python3 -m unittest discover -s tests
scripts/validate.sh images
scripts/validate_schemas.sh images
scripts/check_site.sh _site
```

`scripts/validate.sh <root>` converts each TOML file to JSON, checks the schemas,
and runs `dosker registry validate` for every image below the root. It does not
build the image and it never runs a Doskerfile `RUN` step.

Set `DOSKER_BIN` to choose the `dosker` binary. The default is `dosker` on
`PATH`. The scripts use `uvx check-jsonschema` when `check-jsonschema` is not
installed.

`scripts/e2e.sh` builds the first image, saves it, runs
`dosker registry check-final`, publishes it into a temporary release directory,
generates the site, checks the schemas, repeats the publish, and repeats the
generation. Source `examples/hello-dos/setup.sh` in the `dosker` checkout first.

## Publish flow

1. A pull request adds or changes an image.
2. `validate.yml` checks the metadata, the licenses, the tag uniqueness, and the
   schemas. It never runs `RUN`.
3. A maintainer merges the pull request.
4. `publish.yml` builds each changed image, saves the tar, runs
   `dosker registry check-final`, uploads the tar, uploads the sidecar, and then
   generates and deploys the site.
5. A second run with the same version and digest changes nothing. A different
   digest for an existing version fails.

The generator reads the downloaded assets from one directory per release:
`<assets>/<owner>-<name>/<asset_digest>.tar` and
`<assets>/<owner>-<name>/<version>.json`. The publish workflow downloads each
Release into that layout. Two images can use the same version number without
a sidecar collision.

`scripts/publish.py` writes the version sidecar and copies the tar. It derives
the manifest digest, the config digest, and the license summary from the tar.

## Contribution rules

- The owner directory must match a proven entry in `namespaces.toml`.
- The image must declare license coverage for the base and the `COPY` inputs.
- An abandonware entry must use `STATUS=abandonware`, `BASIS=good-faith`, and
  `EVIDENCE`.
- A copyleft entry must carry `SOURCE_URL`.
- An image that needs a notice must contain `C:\DOSKER\NOTICE.TXT`.
- Only maintainers change `namespaces.toml` and `revoked.toml`.

Read [`POLICY.md`](POLICY.md) before you submit an image. It names the
takedown contact, the 7-day response window, and the unsigned-asset decision.

## Schema IDs

The six schemas use the placeholder host `https://dosker.dev/schemas/`. Replace
the `$id` host in `schemas/*.schema.json` after the final registry domain is
chosen.
