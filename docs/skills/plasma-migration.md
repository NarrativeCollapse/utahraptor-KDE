---
name: plasma-migration
version: "1.0"
last_updated: "2026-09-25"
id: plasma-migration
one_line_purpose: Plan and measure the migration of Utah's desktop from GNOME to KDE Plasma.
entry_point: docs/skills/plasma-migration.md
category: contracts
mcp_compliance_level: partial
optimization_status: draft
status: active
dependencies: [package-contract, desktop-contract]
tags: [plasma, kde, migration, packages, closure]
description: >-
  The GNOME-to-Plasma migration plan, its step order, and the Plasma closure
  experiment (just plasma-closure) that sizes the package factory work. Use
  when working on any step of the Plasma migration.
metadata:
  type: runbook
---

# Plasma Migration

This fork replaces Utah's GNOME 51 desktop with KDE Plasma. The file edits
are mechanical; the hard constraint is package supply. Hummingbird ships no
desktop, and Utah's GNOME comes from the pinned `utah-packages` factory, not
from Fedora (`AGENTS.md`: Fedora repositories are never enabled at runtime).
The current image carries Qt 5 only -- no Qt 6, KDE Frameworks 6 or Plasma
(`baselines/utah/rpms.tsv`). A Plasma image therefore needs a factory that
builds Qt 6, KF6 and Plasma 6 against Hummingbird, the way `utah-packages`
builds GNOME.

## Step order

One logical change per PR:

1. **Measure the closure** (`just plasma-closure`, below). Produces the
   factory build list. Not merged into any image.
2. **Plasma package factory.** Build the source packages from step 1 against
   Hummingbird and publish a digest-pinned OCI repository, as `utah-packages`
   does for GNOME.
3. **Remove the GNOME Shell extensions** (done): the `.gitmodules`
   submodules, `build-gnome-extensions.sh`, `verify-gnome-extensions.py`, the
   `[build]` toolchain section in `utah.toml` and its removal in
   `configure-services.sh`, the custom-command-list dconf file, their tests,
   and the Containerfile and `just check` lines. `just check` no longer needs
   `git submodule update`.
4. **The swap** (done, except the `PACKAGE_IMAGE` pin): `[gnome]` became
   `[plasma]` in `utah.toml`; Bluefin's GNOME profile
   (`/system_files/bluefin`) was replaced by Aurora's common image, applied
   after the package transaction (see [desktop-contract](desktop-contract.md));
   the contract asserts Aurora's KDE defaults and Flatpak set; `gdm.service`
   became `plasmalogin.service` -- Fedora 44 ships Plasma Login Manager, not
   SDDM. **The image cannot build until the factory publishes Plasma and
   `PACKAGE_IMAGE_SHA` points at it**: no enabled repository carries it.
5. **Live ISO and e2e** (done, unrun): Plasma Login Manager autologin and
   liveuser's no-lock/no-sleep KDE settings in
   `iso/live/src/configure-live.sh`; tacklebox gets `"desktop": "kde"`;
   `luks-e2e.sh` checks `plasmalogin.service` and `plasmashell` (overridable,
   see [local-testing](local-testing.md)) and no longer checks GNOME
   extensions; `luks-unlock.py` keys boot completion off the greeter unit.
   The Ghostty flatpak stays only because the e2e harness drives it.
6. **Parity target** (done): Aurora has no manifest to copy -- it installs
   Plasma from its Kinoite base and lists its additions in a shell script
   (`build_files/base/01-packages.sh`) -- so `packages/bluefin.toml` stays the
   verbatim Bluefin parity copy and the AGENTS.md invariant is unchanged.
   Bluefin entries that only serve GNOME are recorded, each with its reason,
   in `utah.toml`'s `[not_on_plasma]`, which the installer and verifier skip
   and `install-packages.py --check` keeps honest (a name no longer in
   Bluefin's manifest fails). Aurora's KDE-specific additions (kate,
   ksshaskpass, ksystemlog, plasma-firewall, plasma-wallpapers-dynamic) are in
   `[plasma]`.
7. **Rename and rebrand** (done): the OS is Absolution Linux. Its identity
   -- name, id, codename (still Utahraptor), registry namespace
   (`narrativecollapse`), URLs -- is `config/identity.json`, read by
   `scripts/identity.py`, `flavors.py`, the Justfile, `configure-branding.sh`,
   `configure-live.sh`, the installer JSON (as `{name}` placeholders) and the
   desktop contract (as `{name}`/`{id}`/... placeholders the verifier fills).
   The cosign identity in the release workflows follows
   `${{ github.repository }}`. Internal `utah` names stay. Renaming again is
   an edit to `config/identity.json`; `tests/test_identity.py` names any
   literal copy left behind. The look-and-feel, logos and wallpapers are
   still Aurora's.

Leave `Containerfile.kernel`, `install-ogc-kernel.sh`, `install-nvidia.sh`
and the `.repo` files alone unless the task is about them: they key the
kernel cache (see [kernel-cache](kernel-cache.md)).

## Step 1: the closure experiment

```bash
just plasma-closure                       # podman
just plasma-closure --engine docker
just plasma-closure --plasma-only         # Plasma set without Utah's contract
just plasma-closure --extra kate          # add names to the Plasma set
```

It needs network access to `ghcr.io`, `quay.io`, `packages.redhat.com` and
`dl.fedoraproject.org`. Claude Code web sessions with the default network
policy deny the last three; run it locally or widen the environment's policy.

What it does (`scripts/plasma-closure.py`):

- Starts the pinned `BASE_IMAGE` with the pinned factory's repodata (the same
  digest-verified metadata layer `just check-repos` uses) and `packages/` as
  `/etc/yum.repos.d`.
- Composes Utah's contract via `install-packages.py`'s `contract()` -- which
  includes `utah.toml`'s `[plasma]` section and already leaves out
  `[not_on_plasma]`. `--plasma-only` resolves `[plasma]` alone.
- Runs `dnf --assumeno install` over Utah's install repositories plus
  `fedora-44` and `fedora-44-updates` at priority 99. dnf drops a
  lower-priority package whose name a higher-priority repository carries, so
  Fedora contributes only what Hummingbird and the factory lack.
- If the strict transaction fails, saves the solver problems and retries with
  broken and unavailable packages skipped, so the rest is still measured.

Results land in `output/plasma-closure/` (git-ignored):

| file | read it for |
|---|---|
| `summary.md` | counts by origin, number of Fedora source packages, problems |
| `srpms.txt` | the factory build list, one source package per line |
| `closure.tsv` | every package, its repository, origin and Fedora SRPM |
| `dnf-strict.log`, `dnf-skip-broken.log` | raw resolver output |

Reading the result:

- **`fedora` origin rows** are what the factory must build; `srpms.txt`
  collapses them to source packages, which is the unit of factory work.
- **Solver problems** name Fedora packages whose dependencies Hummingbird
  cannot satisfy (version skew). The factory rebuild absorbs these; they also
  flag where a rebuilt Hummingbird library may be needed.
- **Upgrading or Replacing rows** mean Fedora would replace a base package.
  Priority should prevent it; if one appears, the factory needs that package
  too, or the pin is wrong.
- **Unmatched names** mean `[plasma]` names something Fedora 44 does
  not carry (for example a login-manager rename). Fix the list, rerun.

The parser reads dnf4 and dnf5 tables; its cases are pinned in
`tests/test_plasma_closure.py`. If a dnf update changes the table format and
the summary looks empty while the log is not, extend those tests first.
