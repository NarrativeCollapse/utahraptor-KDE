---
name: desktop-contract
version: "1.0"
last_updated: "2026-09-25"
id: desktop-contract
one_line_purpose: Maintain OS identity, Plasma desktop defaults, and first-boot Flatpak policy.
entry_point: docs/skills/desktop-contract.md
category: contracts
mcp_compliance_level: partial
optimization_status: draft
status: active
dependencies: []
tags: [desktop, branding, plasma, aurora, flatpak]
description: >-
  The runtime desktop contract in contracts/bluefin-desktop.toml and its
  in-image verifier. Use when changing branding, os-release, service
  presets, the Aurora common image, KDE defaults, or first-boot Flatpak
  behavior.
metadata:
  type: policy
---

# Desktop Contract

`contracts/bluefin-desktop.toml` is the runtime contract for the Plasma
desktop on top of Hummingbird. It is intentionally separate from
`packages/bluefin.toml`: package parity proves RPMs; this file proves OS
identity, the Plasma defaults Aurora's common image supplies, and first-boot
Flatpak policy (header comment, `contracts/bluefin-desktop.toml`). The contract
is data; one verifier enforces it — `scripts/verify-desktop-contract.py`.

## Where the desktop files come from

The desktop is Bluefin's plumbing with Aurora's Plasma profile on top
(Containerfile comments):

- `ghcr.io/projectbluefin/common` — only `/system_files/shared`: setup
  services and hooks, ujust, Homebrew and uupd integration. Its GNOME profile,
  `/system_files/bluefin`, is not used.
- `ghcr.io/get-aurora-dev/common` (`AURORA_COMMON_IMAGE`, digest-pinned to the
  one get-aurora-dev/aurora pins) — `/system_files/shared`, `/logos` and
  `/wallpapers`: the `dev.getaurora.aurora.desktop` look-and-feel package, KDE
  defaults under `/usr/share/kde-settings/kde-profile/default/xdg`, Plasma
  Login Manager defaults, the system-flatpaks Brewfile and the Flatpak hooks.
  It is applied **after** the package transaction, because it overrides files
  `kde-settings` and `kde-settings-plasmalogin` own; applied earlier, those
  RPMs would silently restore Fedora's versions.
- `system_files/shared` in this repository — Utah's own units and presets,
  plus two files Bluefin's GNOME profile used to supply:
  `bazaar.preinstall` (from get-aurora-dev/aurora) and the
  `90-passkeys-tpm.conf` dracut modules.

The image bundles no GNOME Shell extensions; they were removed as step 3 of
the Plasma migration ([plasma-migration](plasma-migration.md)).

## What the contract asserts

The TOML's sections are the contract's table of contents:

- **`[branding]`** — files that must exist (Aurora's look-and-feel package
  and default layout, the distributor logo, the default background, fastfetch
  and Bazaar count files) plus the os-release identity. The identity fields are exact values:
  `NAME=Utah`, `ID=utah`, `ID_LIKE=fedora`, `VERSION_CODENAME=Utahraptor`,
  `DEFAULT_HOSTNAME=utah`, `IMAGE_ID=utah`, and the projectbluefin.io URLs.
  `[branding.os_release_patterns]` shapes the fields the build generates:
  `PRETTY_NAME` is `Utah (Version: ...)`, `VERSION` carries `(Hummingbird)`,
  `VARIANT_ID` starts with `utah`. The verifier reads `/usr/lib/os-release`.
- **`[branding.image_info]`** — `/usr/share/ublue-os/image-info.json` must
  name image `utah`, vendor `projectbluefin`, base `hummingbird`, with the
  flavor pattern `(main|nvidia|gaming|nvidia-gaming)` and the matching
  `ostree-image-signed` ref pattern.
- **`[configuration]`** — Aurora's KDE defaults must be in place and must
  still be Aurora's: `kdeglobals` names `dev.getaurora.aurora.desktop` as the
  look-and-feel package, `ksplashrc` its splash, and
  `/usr/lib/plasmalogin/defaults.conf` configures the greeter wallpaper. If
  a package transaction ever runs after the Aurora overlay again, these
  `file_contains` checks are what catch Fedora's files coming back.
- **`[flatpak]`** — first-boot policy: the Flathub remote
  (`https://dl.flathub.org/repo/`), the Bazaar preinstall, the
  `99-flatpaks.sh` privileged-setup hook, and the system-flatpaks Brewfile
  whose app list the contract enumerates in Aurora's order (KDE apps,
  Thunderbird, Firefox, Bazaar, Flatseal, Warehouse and a few others).
- **`[services]`** — systemd units the preset must enable: `plasmalogin.service`,
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
enables Plasma Login Manager (`plasmalogin.service`), input-remapper, firmware
updates, Tailscale, uupd, user setup and resolved, and configures authselect
before cleanup (Containerfile RUN comment; originated in `docs/building.md`'s former
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

## The verifier runs twice

The same verifier runs in the Containerfile and on demand, so a local image
or a CI artifact can be checked after the fact (recipe comment, `Justfile`,
`check-desktop-contract`):

- **In the image build** — the desktop RUN step ends with
  `utah-verify-desktop-contract /usr/share/utah/bluefin-desktop.toml`, after
  branding and services are configured; a contract failure fails the build.
- **On demand** — `just check-desktop-contract <ref>` (default
  `localhost/utah:testing`) podman-runs the verifier inside an
  already-composed image, with the verifier and the contract bind-mounted
  from the working tree.
- **Off-image** — `verify-desktop-contract.py --check` validates the contract
  TOML itself in source-only CI and is part of `just check`; it asserts
  nothing about any image.

## Verification

```bash
python3 scripts/verify-desktop-contract.py --check contracts/bluefin-desktop.toml
just check-desktop-contract localhost/utah:testing  # requires a locally built image
```
