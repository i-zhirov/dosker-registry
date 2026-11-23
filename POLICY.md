# Registry policy

This policy applies to every image in this repository.

## Namespace proof

An owner entry in `namespaces.toml` must name a GitHub handle and a proof URL.
The proof URL must show that the handle controls the namespace. A maintainer
checks the proof during review. Only maintainers change `namespaces.toml`.

## License records

Every image must declare license coverage for the base image and for each
`COPY` input. The coverage is checked against the base configuration and the
`COPY` inputs. Validation does not run a Doskerfile `RUN` step.

An abandonware entry must use:

- `STATUS=abandonware`
- `SPDX=NONE`
- `BASIS=good-faith`
- `EVIDENCE=<URL>`

A copyleft entry must carry `SOURCE_URL`. An image that needs a notice must
contain `C:\DOSKER\NOTICE.TXT`.

## Abandonware claim and takedown

An abandonware claim is a good-faith statement. It does not transfer ownership.
A rights holder can request removal at any time. Send the request with the image
name and the evidence to the maintainers.

The maintainer records the request in `revoked.toml`:

```toml
schema = 1

[[revoked]]
namespace = "i-zhirov"
name = "example"
digest = "sha256:0000..."
reason = "Rights-holder request"
decided_at = "2026-11-22T12:00:00Z"
```

A revoked digest is removed from every tag and version list. The next site
deploy omits it. Local copies on user machines stay unchanged. The asset
deletion step belongs to the takedown workflow and is out of scope for the first
release.

## GPL source offer

FreeDOS is distributed under `GPL-2.0-only`. Each image that carries FreeDOS
must provide the source location in its `SOURCE_URL` entry. The generated
license record and the image page show that link with the FreeDOS entry. The
current entry points to `https://github.com/FDOS`.

The full source-offer wording for the site is still under review. The link is
present, and no image may hide or override it.

## DOSKER agent license

The DOSKER agent is dual-licensed under `MIT OR Apache-2.0`. The `dosker`
release does not include `DOSKER.EXE` today. The way registry CI obtains the
agent binary is still open.

## First image

`i-zhirov/hello-dos` builds from `freedos:1.3`. It inherits the FreeDOS entry
(`GPL-2.0-only`) and the DOSKER agent entry (`MIT OR Apache-2.0`). The image adds
no third-party files. It copies `NOTICE.txt` to `C:\DOSKER\NOTICE.TXT`.

The effective summary is `redistributable`, so the image needs no acceptance
step. The FreeDOS entry carries `SOURCE_URL`, and the image passes
`dosker registry check-final` on its final tree.
