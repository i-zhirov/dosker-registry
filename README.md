# DOSker registry

This repository holds the text that defines the DOSker image registry. It is a
separate repository from the `dosker` code repository. The live site is
<https://i-zhirov.github.io/dosker-registry/>; the pinned DOSKer release is
`0.1.5`.

## Layout

```
namespaces.toml              proven GitHub handles
revoked.toml                 takedown records
images/<owner>/<name>/       Doskerfile, registry.toml, NOTICE.txt
schemas/                     the six JSON schemas
site/                        HTML templates and CSS
scripts/                     validation, generation, publish, and
                             migration helpers
tests/                       unit tests and fixtures
requirements.txt             pinned Python packages for the scripts
.github/workflows/           validate, publish, site, and takedown
.github/actions/             prepare-image-base
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

The checks need Python 3.11 or newer, `check-jsonschema`, `actionlint`, a
`dosker` binary that contains `registry validate` and `registry check-final`,
and the pinned packages in `requirements.txt`.

```sh
python3 -m pip install -r requirements.txt
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
   `dosker registry check-final`, compresses the asset, uploads the compressed
   asset, uploads the sidecar, and then generates and deploys the site.
5. A second run with the same version and digest changes nothing. A different
   digest for an existing version fails.

The generator reads the downloaded assets from one directory per release:
`<assets>/<owner>-<name>/<asset_digest>.tar.zst` and
`<assets>/<owner>-<name>/<version>.json`. The publish workflow downloads each
Release into that layout. Two images can use the same version number without
a sidecar collision.

`scripts/publish.py` writes the version sidecar and compresses the tar with
zstd. The sidecar records the image content digest and the asset compression.
It refuses a version already bound to a different digest and a new version of
revoked content. It derives the manifest digest, the config digest, and the
license summary from the tar.

## Republishing after a takedown

A takedown records the revoked version's manifest digest in `revoked.toml`. The
version sidecar also carries a `content_digest`: the digest of the ordered
image layer digests. It identifies the files the image carries and ignores
build timestamps and history, so a rebuild that only changes the manifest
digest still matches.

The publisher follows these rules:

- The same revoked version is skipped, not republished.
- A new version with the same content is refused. The build fails with
  `image <owner>/<name> content is revoked; change the content before
  publishing a new version`. Bumping `version` in `registry.toml`, or changing
  the description, tags, `ENV`, or `CMD`, does not change the content digest.
- A new version with genuinely new content is allowed. Change the files the
  image carries (a `COPY` input, the notice, or a `RUN` that writes different
  files), bump `version` in `registry.toml`, and open a pull request. The new
  content digest differs, so the new version publishes; the old version stays
  revoked.

The takedown workflow stamps the sidecar of an older version from its
compressed asset before it deletes the asset, so the content digest is
available for every later publish. The content digest is an internal
release-sidecar field; the public catalog and license documents are unchanged.

## Migrate existing release assets

`scripts/migrate_assets.py` is the one-time operator tool for the zstd asset
migration. The publish, site, and takedown scripts do not use it and do not
read the old format.

Prepare mode reads the old tar and sidecar files. It writes the compressed
asset and the updated sidecar to the output directory. It checks the old
digest, size, manifest, config, and content digests, and it keeps the old tar.

```sh
python3 scripts/migrate_assets.py --prepare \
  --assets <release-dir> --out <new-dir> --backup <backup-dir>
```

Cleanup mode checks the new sidecar and compressed asset, then prints each old
tar name to delete. It does not delete anything.

```sh
python3 scripts/migrate_assets.py --cleanup \
  --assets <release-dir> --backup <backup-dir>
```

Keep the backup directory and the old assets until the new site is live. Use
the backup to restore the old sidecars if the cutover fails.

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

The six schemas use `https://i-zhirov.github.io/dosker-registry/schemas/` as
their `$id` host.
