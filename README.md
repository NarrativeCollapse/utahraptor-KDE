# Absolution Linux

<!-- BEGIN E2E VERIFICATION -->
*No end-to-end run of Absolution Linux yet: the image cannot build until the
package factory publishes KDE Plasma (see [Status](#status)). The record in
[docs/verification](docs/verification/README.md) is the last upstream Utah
(GNOME) run this fork inherited, kept for its method, not as a claim about
this image.*
<!-- END E2E VERIFICATION -->

A Universal Blue KDE Plasma workstation on [Fedora
Hummingbird](https://packages.redhat.com). Absolution Linux is a fork of
[Utah](https://github.com/projectbluefin/utah) — Project Bluefin's
Hummingbird-based image, codenamed Utahraptor — with the GNOME desktop
replaced by KDE Plasma 6 and [Aurora](https://getaurora.dev)'s Plasma
defaults.

**Experimental pre-alpha, and not buildable yet.** Nothing is published: no
image in a registry, no ISO. Nothing here is ready to run on a machine you
care about. [Filing
issues](https://github.com/NarrativeCollapse/utahraptor-KDE/issues) is the
whole point.

## What it is

Hummingbird supplies a hardened, fast-moving bootable base and no desktop at
all. Absolution Linux adds one:

- **KDE Plasma 6** — the session, KWin, Plasma Login Manager, Dolphin,
  Konsole and system integration (`[plasma]` in `packages/utah.toml`), built
  from source by a package factory because Hummingbird ships none of it.
- **Aurora's Plasma profile** — look-and-feel, KDE defaults, greeter
  configuration, wallpapers and the default Flatpak set, from
  `ghcr.io/get-aurora-dev/common`.
- **Bluefin's plumbing and package contract** — setup services, `ujust`,
  Homebrew and update integration from `ghcr.io/projectbluefin/common`, and
  Bluefin's package list, minus the packages that only serve GNOME.

Two repositories, the way Utah is built:

| Repository | What it does |
|---|---|
| [`NarrativeCollapse/utahraptor-KDE`](https://github.com/NarrativeCollapse/utahraptor-KDE) | This one. Composes the image. |
| a fork of [`projectbluefin/utah-packages`](https://github.com/projectbluefin/utah-packages) | Will build Qt 6, KDE Frameworks 6 and Plasma 6 against Hummingbird and publish them as a digest-pinned OCI package repository. Not set up yet. |

The OS name, id, registry namespace and URLs live in one file,
[`config/identity.json`](config/identity.json); renaming the OS is an edit
there (`tests/test_identity.py` names anything that disagrees). Internal names
— the `utah-*` helpers, `/usr/share/utah`, `packages/utah.toml` — are this
image's Utah lineage and stay.

## Status

The GNOME-to-Plasma migration is done in this repository and recorded, step
by step, in [docs/skills/plasma-migration.md](docs/skills/plasma-migration.md).
What is missing is the packages:

1. **The package factory.** Fork `projectbluefin/utah-packages`, import the
   Qt 6 / KDE Frameworks 6 / Plasma 6 recipes, and let its GitHub Actions
   build them. `just plasma-closure` measures exactly which source packages
   that is.
2. **The pin.** Point `PACKAGE_IMAGE` / `PACKAGE_IMAGE_SHA` in the
   `Containerfile` at the published factory image. Until then the package
   transaction fails: no enabled repository carries Plasma.
3. **The first real build and end-to-end run.** The live ISO, installer and
   LUKS test have been adapted for Plasma but have never run against it.

## Image streams

| Tag | Stream | What it is |
| ---: | ---: | ---: |
| `:testing` | Dev | Built from `testing`, advanced only after end-to-end validation. |
| `:stable` | Stable | Promoted from `:testing`. |

Four flavors per stream — `absolution`, `absolution-nvidia`,
`absolution-gaming`, `absolution-nvidia-gaming`, under
`ghcr.io/narrativecollapse` — derived from the OS id in
`config/identity.json` and the flavor set in `config/flavors.json`.

**None of these are published yet.**

## Package parity with Bluefin

`packages/bluefin.toml` is a byte-for-byte copy of Bluefin's `base.toml` at the
upstream revision pinned in `packages/.bluefin-parity-ref`, and CI diffs it
against that exact revision on every run. Bluefin packages that only serve a
GNOME session are left out on purpose, each with its reason, in
`[not_on_plasma]` in `packages/utah.toml`.

| | count |
| --- | --- |
| Bluefin contract installed | **51** |
| Overlay additions (KDE Plasma 6, base-image parity, device firmware, desktop services) | 93 |
| Genuinely unavailable | **8** |

The install writes its resolved list to `/usr/share/utah/contract.txt` and the
verify step asserts *that file*, so the two cannot disagree. These counts are
generated from `packages/bluefin.toml` and `packages/utah.toml`
(`scripts/generate-site-data.py`, `site/data/packages.json`); `just check`
fails if this table drifts from that output (`scripts/check-doc-counts.py`).

## Known gaps

This is the honest list, and it is why the label above says pre-alpha.

- **It does not build.** See [Status](#status): Plasma needs the package
  factory first.
- **The Plasma package names are Fedora 44's, unverified here.** Run `just
  plasma-closure` somewhere with network access to Hummingbird and Fedora; a
  name Fedora does not carry is reported, not silently dropped.
- **Nothing is published.** No image has been pushed to a registry and no ISO
  artifact has been released.
- **Branding is Aurora's.** The look-and-feel package, logos and wallpapers
  are Aurora's (`dev.getaurora.aurora.desktop`); os-release says Absolution
  Linux. Absolution's own artwork does not exist yet.
- **Live media boot paths and Secure Boot.** Live media requires UEFI boot;
  legacy BIOS and file-backed/Ventoy booting are unsupported (flash directly
  using Fedora Media Writer or `dd`). Live media runs SELinux in Permissive
  mode (`enforcing=0`) because rootless container squashfs generation cannot
  preserve SELinux xattrs; installed systems boot Enforcing. The live
  environment uses `systemd-boot-unsigned`, so Secure Boot must be disabled
  to boot it. Custom OGC kernels and NVIDIA modules likewise require MOK
  enrollment or Secure Boot disabled.
- **Update timers after switching from another bootc image.** Switching from
  Bluefin, Aurora or another bootc image carries its
  `timers.target.wants/bootc-fetch-apply-updates.timer` symlink across
  ostree's 3-way `/etc` merge. Background auto-updates are `uupd`'s job, so
  `bootc-fetch-apply-updates.timer` and `bootc-fetch-apply-updates.service`
  are masked in `/etc` and `/usr/lib` (and preset to disabled), so they cannot
  bypass `uupd` policy or silently undo a rollback (`bootc rollback`). Verify
  with `systemctl is-enabled bootc-fetch-apply-updates.timer`, and re-assert
  the mask if a merged `/etc` symlink remains
  (`systemctl mask --now bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service`).
- **Wi-Fi needs a package the factory has not built yet.** `linux-firmware`
  is installed, but Hummingbird's `NetworkManager-wifi` requires
  `wireless-regdb` and a supplicant that no enabled repository carries
  (inherited from Utah: utah-packages#136, #126).
- **The NVIDIA and gaming flavors are unproven**, as upstream: the OGC kernel
  and NVIDIA module compile, but the flavored builds have not all passed in
  one run.
- **Codec support differs.** Bluefin replaces twelve Fedora multimedia
  packages with negativo17 builds; this image installs Fedora's, so
  hardware-accelerated codecs differ.
- **CUDA is deliberately excluded** — 7.68 GB installed. Use the NVIDIA
  container toolkit, which is included, and run CUDA in a container.

## Contributing or building from source

See [docs/building.md](docs/building.md) for how to build the image locally,
and [docs/skills/](docs/skills/) for the deep documentation. Agents start at
[AGENTS.md](AGENTS.md).
