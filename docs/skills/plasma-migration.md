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
2. **Plasma package factory** (in progress). The fork
   `NarrativeCollapse/utah-packages` (branch `claude/vibrant-goodall-h3kfvk`)
   imports each source in step 1's build list from Fedora dist-git `f44`,
   locks every Source0 to an upstream release, and generates the repacks
   Fedora made by hand (7zip, opencv, qtwebengine). Four sources with no
   upstream release at all (desktop-backgrounds, f44-backgrounds,
   redhat-menus, poly2tri) and assimp are trimmed out: the recipes that
   required them carry marked edits instead. Its own skill,
   `docs/skills/plasma-recipes.md` there, has the details. Remaining: merge
   the branch to the fork's `main`, enable its "Build verified upstream RPMs"
   workflow, work through build failures (missing BuildRequires surface
   there), then pin `PACKAGE_IMAGE_SHA` here.
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

The same run happens in CI: `.github/workflows/plasma-closure.yml` runs on
every push to a `claude/**` branch that touches the script, the manifests or
the Containerfile, and on demand. It writes `summary.md` and `srpms.txt` to
the job summary and uploads `output/plasma-closure/` as the `plasma-closure`
artifact -- the way to get the build list when the sandbox cannot reach the
repositories. It needs Actions enabled on the repository; a fork has it off
until the owner turns it on.

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
  It also records every source package the install repositories and the base
  image already carry (`provided-sources.txt`).
- Resolves the same requested set in a plain `quay.io/fedora/fedora:44`
  container, where it installs cleanly, and maps every package in that
  closure -- the container's own packages included -- to its source.
- Subtracts the provided sources from the Fedora closure's sources. What is
  left is `srpms.txt`, the factory's build list.

Why two resolves. The first CI run (2026-09-26) showed the Hummingbird-side
resolve alone cannot produce the list: Fedora 44's Qt 6 and KDE binaries are
built against ICU 77 and Hummingbird ships ICU 78 (and Hummingbird carries
its own `qt6-qtbase` 6.11 built against 78), so nearly every Fedora Qt/KDE
package conflicts and `--skip-broken` drops whole subtrees -- kwin,
plasma-workspace, plasma-login-manager and everything under them. That run
is still worth reading for its solver problems: they name the ABI skews the
factory rebuild absorbs. It also exposed that dnf5 does not expand `\t` in
`--queryformat`; formats use a space separator now and `query_lines()`
tolerates a literal `\n`.

The Fedora-side resolve counts **hard dependencies only**
(`install_weak_deps=False`) and carries **no PackageKit exclusion**. With weak
dependencies counted, the third run asked for 430 sources, including qemu,
xen, vlc and most of KDE Frameworks 5; the image skips an unavailable weak
dependency, so the factory need not build them. The exclusion is the image's
policy, and Fedora's `kf6-frameworkintegration-libs` links
`libpackagekitqt6`, so with it nothing from Breeze up resolved.

First usable result (run 36215510576, commit 9ae5c9c): the requested set
pulls 843 sources in Fedora 44; Hummingbird, the factory and the base carry
547; **296** remain. `fedora-release` is among them only because the plain
Fedora container ships it -- drop it by hand. That list, minus
`fedora-release`, is the factory fork's `config/plasma-sources.txt`
(NarrativeCollapse/utah-packages, branch `claude/vibrant-goodall-h3kfvk`).
A rerun lists five sources the fork deliberately trims (assimp,
desktop-backgrounds, f44-backgrounds, poly2tri, redhat-menus); leave them out
of the list again.

**First boot check (trim):** without redhat-menus, Kickoff's categories rely
on Plasma's own `plasma-applications.menu`; confirm category names and icons
render (redhat-menus also shipped `/usr/share/desktop-directories`).

**PackageKit (resolved):** Bluefin's `-x PackageKit*` also hid
`PackageKit-Qt6`, which `kf6-frameworkintegration-libs` links, so nothing
from Breeze up could install. `install-packages.py` now excludes the daemon
and its tools by name (`PACKAGEKIT_EXCLUDES`) and lets the Qt client library
through; it only Recommends the daemon, so the daemon stays out.
`tests/test_package_resolution.py` holds both halves.

Results land in `output/plasma-closure/` (git-ignored; in CI, the
`plasma-closure` artifact and the job summary):

| file | read it for |
|---|---|
| `summary.md` | counts, the build list, solver problems, unmatched names |
| `srpms.txt` | the factory build list, one source package per line |
| `fedora-closure.tsv` | every package in the Fedora-side closure and its SRPM |
| `provided-sources.txt` | sources Hummingbird, the factory and the base carry |
| `closure.tsv`, `srpms-first-cut.txt` | the Hummingbird-side resolve |
| `dnf-strict.log`, `dnf-skip-broken.log`, `dnf-fedora.log` | raw resolver output |

Reading the result:

- **`srpms.txt`** is runtime closure only. Build-only dependencies
  (BuildRequires) are not in it; the factory's wave solver surfaces them when
  a recipe cannot build.
- **Solver problems** in the Hummingbird-side resolve name Fedora packages
  whose dependencies Hummingbird cannot satisfy (version skew). The factory
  rebuild absorbs these.
- **Upgrading or Replacing rows** mean Fedora would replace a base package.
  Priority should prevent it; if one appears, the factory needs that package
  too, or the pin is wrong.
- **Unmatched names** mean `[plasma]` names something Fedora 44 does
  not carry (for example a login-manager rename). Fix the list, rerun.

The parser reads dnf4 and dnf5 tables; its cases are pinned in
`tests/test_plasma_closure.py`. If a dnf update changes the table format and
the summary looks empty while the log is not, extend those tests first.
