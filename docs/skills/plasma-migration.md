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
4. **The swap, atomically**: `[gnome]` becomes `[plasma]` in `utah.toml`, the
   new `PACKAGE_IMAGE` pin, `contracts/bluefin-desktop.toml` (dconf and
   gschema become `kdeglobals` and a look-and-feel package; `org.gnome.*`
   Flatpaks become KDE ones; `gdm.service` becomes `sddm.service`), the
   preset, `configure-services.sh`, `configure-branding.sh`, and the
   `COPY --from=common /system_files/bluefin` line. `just check` asserts
   `enable gdm.service`, so a partial swap fails the gate.
5. **Live ISO and e2e**: SDDM autologin in `iso/live/src/configure-live.sh`;
   `iso/scripts/luks-e2e.sh` and `luks-unlock.py` drive GDM screens.
6. **Parity target**: move `packages/bluefin.toml` parity to Aurora's
   manifest. This changes an `AGENTS.md` invariant; do it deliberately.
7. **Rename and rebrand**: os-release, `projectbluefin/utah` image refs, URLs.

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
- Composes Utah's contract via `install-packages.py`'s `contract()`, drops
  `[gnome]` (keeping `glibc-all-langpacks`) and Bluefin's GNOME-only
  `[fedora]` entries (`GNOME_EXTRAS`), and adds `PLASMA_PACKAGES`.
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
- **Unmatched names** mean `PLASMA_PACKAGES` names something Fedora 44 does
  not carry (for example a login-manager rename). Fix the list, rerun.

The parser reads dnf4 and dnf5 tables; its cases are pinned in
`tests/test_plasma_closure.py`. If a dnf update changes the table format and
the summary looks empty while the log is not, extend those tests first.
