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
A rights holder can request removal at any time through
<https://github.com/i-zhirov/dosker-registry/issues> with the image name,
digest, and evidence. A maintainer acknowledges the request within 7 days.

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
deploy omits it. A maintainer then dispatches the `takedown` workflow with the
namespace, name, and digest. The workflow checks the record, deletes the image
tar from the Release, keeps the version sidecar, and redeploys Pages. A later
publish skips a revoked current digest, so the tar is not restored. The
version sidecar keeps the image content digest, so a later publish of the same
image content under a new version is refused. Local copies on user machines
stay unchanged.

## Signing

Registry release assets are unsigned in the first version. The client verifies
the SHA-256 digest of every manifest, config, and tar before it installs an
image, so a tampered asset fails. Automated signing and attestation are
deferred; this decision covers the first release.

## GPL source offer

FreeDOS is distributed under `GPL-2.0-only`. Each image that carries FreeDOS
must provide the source location in its `SOURCE_URL` entry. The generated
license record and the image page show that link with the FreeDOS entry. The
current entry points to `https://github.com/FDOS`.

The source offer is the `SOURCE_URL` link in the license record and on the
image page. The link points to the upstream FreeDOS source, and no image may
hide or override it.

## DOSKER agent license

The DOSKER agent source is dual-licensed under `MIT OR Apache-2.0`. The
compiled `DOSKER.EXE` also contains the Open Watcom C runtime. Open Watcom is
distributed under the Sybase Open Watcom Public License, which covers the
runtime modules in the binary; the project source remains under `MIT OR
Apache-2.0`. Registry CI builds `DOSKER.EXE` from the pinned `i-zhirov/dosker`
source tag `v0.1.4` with OpenWatcom; the `dosker` release itself does not carry
the agent.

## First image

`i-zhirov/hello-dos` builds from `freedos:1.3`. It inherits the FreeDOS entry
(`GPL-2.0-only`) and the DOSKER agent entry (`MIT OR Apache-2.0`). The image adds
no third-party files. It copies `NOTICE.txt` to `C:\DOSKER\NOTICE.TXT`.

The effective summary is `redistributable`, so the image needs no acceptance
step. The FreeDOS entry carries `SOURCE_URL`, and the image passes
`dosker registry check-final` on its final tree.
