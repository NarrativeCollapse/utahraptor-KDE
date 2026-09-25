---
name: desktop-contract
version: "1.0"
last_updated: "2026-09-22"
id: desktop-contract
one_line_purpose: Maintain Utah identity, Bluefin desktop defaults, and first-boot Flatpak policy.
entry_point: docs/skills/desktop-contract.md
category: contracts
mcp_compliance_level: partial
optimization_status: draft
status: active
dependencies: []
tags: [desktop, branding, gnome, flatpak]
description: >-
  The runtime desktop contract in contracts/bluefin-desktop.toml and its
  in-image verifiers. Use when changing branding, os-release, service
  presets, GNOME extensions, or first-boot Flatpak behavior.
metadata:
  type: policy
---

# Desktop Contract

`contracts/bluefin-desktop.toml` is the runtime contract for Utah's
Bluefin-derived desktop experience on top of Hummingbird. It is intentionally
separate from `packages/bluefin.toml`: package parity proves RPMs; this file
proves Utah identity, Bluefin desktop defaults, and first-boot Flatpak policy
(header comment, `contracts/bluefin-desktop.toml`). The contract is data; two
verifier enforces it — `scripts/verify-desktop-contract.py`. The image bundles
no GNOME Shell extensions; they were removed as step 3 of the Plasma migration
([plasma-migration](plasma-migration.md)).

## What the contract asserts

The TOML's sections are the contract's table of contents:

- **`[branding]`** — files that must exist (Bluefin logos, backgrounds, the
  `zz0-bluefin-modifications` gschema override, fastfetch and Bazaar count
  files) plus the os-release identity. The identity fields are exact values:
  `NAME=Utah`, `ID=utah`, `ID_LIKE=fedora`, `VERSION_CODENAME=Utahraptor`,
  `DEFAULT_HOSTNAME=utah`, `IMAGE_ID=utah`, and the projectbluefin.io URLs.
  `[branding.os_release_patterns]` shapes the fields the build generates:
  `PRETTY_NAME` is `Utah (Version: ...)`, `VERSION` carries `(Hummingbird)`,
  `VARIANT_ID` starts with `utah`. The verifier reads `/usr/lib/os-release`.
- **`[branding.image_info]`** — `/usr/share/ublue-os/image-info.json` must
  name image `utah`, vendor `projectbluefin`, base `hummingbird`, with the
  flavor pattern `(main|nvidia|gaming|nvidia-gaming)` and the matching
  `ostree-image-signed` ref pattern.
- **`[configuration]`** — the dconf distro databases and locks under
  `/etc/dconf/db/distro.d/` must exist, and `file_contains` pins their
  content: the gschema override references Bazaar and the Bluefin background
  path, the custom command menu points at `docs.projectbluefin.io`, the
  keybindings set `xdg-terminal-exec`.
- **`[flatpak]`** — first-boot policy: the Flathub remote
  (`https://dl.flathub.org/repo/`), the Bazaar preinstall, the
  `99-flatpaks.sh` privileged-setup hook, and the system-flatpaks Brewfile
  whose app list the contract enumerates.
- **`[services]`** — systemd units the preset must enable: `gdm.service`,
  `bluetooth.service`, `ublue-system-setup.service`, `flatpak-preinstall.service`,
  `flatpak-nuke-fedora.service`, `brew-setup.service`, `dconf-update.service`,
  `bootc-unified-storage.service`, `uupd.timer`. Update policy delegates
  background updates to `uupd.timer`; `bootc-fetch-apply-updates.timer` and
  `bootc-fetch-apply-updates.service` are masked in `/etc` and `/usr/lib` (and
  disabled in `85-utah-desktop.preset`) so cross-vendor `/etc` 3-way merges
  (e.g. switching from Bluefin) do not carry active `timers.target.wants`
  symlinks that bypass uupd staging or undo manual rollbacks. Switchers can
  also manually verify or mask them if a local `/etc` symlink was preserved.

## Services and login defaults

Hummingbird defaults to a server preset and disables unlisted services, so
the desktop policy is applied explicitly. `scripts/configure-services.sh`
mirrors bluefin-lts's `40-services.sh`: it applies the desktop presets,
enables GDM, input-remapper, firmware updates, Tailscale, uupd, user setup and resolved,
configures authselect, and removes the extension build toolchain before
cleanup (Containerfile RUN comment; originated in `docs/building.md`'s former
design section and now lives in this skill).

Hummingbird's base does not include `systemd-resolved` by default; it is listed
under `[services]` in `packages/utah.toml` and configured in
`scripts/configure-services.sh`, which also disables `PrivateTmp` on
`systemd-resolved.service` for bootc early-boot DNS resolution.

### The serial getty is masked (#103)

Two Hummingbird defaults compose into a desktop bug. The base declares the
serial console as a kernel argument in `/usr/lib/bootc/kargs.d/00-base.toml`
(`console=ttyS0,115200n8`), and systemd-getty-generator instantiates
`serial-getty@ttyS0.service` for every serial `console=` on the cmdline. On
hardware with no serial port the agetty dies on EIO and respawns roughly every
ten seconds for the whole session — 197 journal entries in one boot on the
ThinkPad X230 that filed it, and a pointless wakeup each time on battery.
Bluefin carries neither half, which is why it is silent.

The karg cannot be withdrawn from this repository. bootc's `kargs.d` is
additive only, and removing an argument the base image declared there is
documented undefined behavior — so Utah pins the outcome instead of the cause
and masks the unit from both directions the repo already uses:

- `scripts/configure-services.sh` runs `systemctl mask serial-getty@ttyS0.service`
  and writes the `/usr/lib/systemd/system/serial-getty@ttyS0.service` → `/dev/null`
  symlink, the same `/etc` + `/usr/lib` pair the update timer uses so a
  cross-vendor 3-way merge cannot resurrect it.
- `85-utah-desktop.preset` carries `disable serial-getty@ttyS0.service`.
  Presets are read in lexicographic order and the first match wins, so 85-*
  outranks the base's `90-systemd.preset`.
- `[services].masked` in `contracts/bluefin-desktop.toml` lists the unit, so
  the in-image verifier fails the build if the mask is dropped.

The mask names the instance, not `serial-getty@.service`: `ttyS0` is the port
the base names, and a genuinely attached serial device on another port still
gets its login. A mask is also the only lever that works here — the generator's
`getty.target.wants` symlink is created in `/run` at boot, so it cannot be
deleted at build time, and a preset entry alone would not stop it.

## The verifiers run twice

The same verifier runs in the Containerfile and on demand, so a local image
or a CI artifact can be checked after the fact (recipe comment, `Justfile`,
`check-desktop-contract`):

- **In the image build** — the desktop RUN step ends with
  `utah-verify-desktop-contract /usr/share/utah/bluefin-desktop.toml`, after
  branding and services are configured; a contract failure fails the build.
  The extension verifier runs earlier in the same step.
- **On demand** — `just check-desktop-contract <ref>` (default
  `localhost/utah:testing`) podman-runs both verifiers inside an
  already-composed image: the desktop verifier and the contract are
  bind-mounted from the working tree, the extension verifier runs from the
  image's own `/usr/local/libexec`.
- **Off-image** — `verify-desktop-contract.py --check` validates the contract
  TOML itself in source-only CI and is part of `just check`; it asserts
  nothing about any image.

## Verification

```bash
python3 scripts/verify-desktop-contract.py --check contracts/bluefin-desktop.toml
just check-desktop-contract localhost/utah:testing  # requires a locally built image
```
