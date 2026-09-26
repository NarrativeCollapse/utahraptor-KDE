#!/usr/bin/env python3
"""Measure what a Plasma desktop would need that Utah's repositories lack.

Utah's GNOME 51 comes from the pinned utah-packages factory because neither
Hummingbird nor a Fedora release ships it. A Plasma desktop is in the same
position, so before any factory work starts this answers one question: which
packages, and which source RPMs, would the factory have to build?

It resolves -- never installs -- in two containers, then subtracts.

On the pinned base image it resolves the package contract, whose [plasma]
section is the desktop, against Utah's own install repositories plus Fedora 44 at the lowest
priority. Because dnf drops any package from a lower-priority repository whose
name a higher-priority one carries, Fedora supplies only what Hummingbird and
the factory do not have. Everything the transaction takes from Fedora is
a first cut of the factory's build list -- but only a first cut, because
Fedora's Qt and KDE binaries are built against Fedora's libraries (ICU 77
where Hummingbird ships ICU 78, for one), so most of them cannot install on
Hummingbird at all and the resolver skips whole subtrees. The same pass
records every source package Hummingbird and the factory already build.

So the requested set is also resolved in a plain Fedora 44 container, where
it installs cleanly, and every package in that closure is mapped to its
source. Those sources minus what Hummingbird and the factory already build
is the build list: srpms.txt.

This is an experiment, not a build input. Fedora is enabled only inside a
throwaway container for the resolve, never in an image; the invariant in
AGENTS.md that Fedora repositories are never enabled at runtime is unchanged.

Outputs, under --out (default output/plasma-closure/):
  srpms.txt             the factory's build list (Fedora closure minus provided)
  summary.md            counts, the build list, solver problems, unmatched names
  closure.tsv           the Hummingbird-side transaction, repository and SRPM
  fedora-closure.tsv    the Fedora-side transaction and each package's SRPM
  provided-sources.txt  sources Hummingbird, the factory and the base carry
  dnf-*.log             the raw resolver output each attempt produced

Needs podman (or --engine docker) and network access to ghcr.io, quay.io,
packages.redhat.com and the Fedora mirrors. See docs/skills/plasma-migration.md.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

# The Plasma set is packages/utah.toml's [plasma] section, the same list the
# image installs; --extra adds names to it for an experiment. A name Fedora
# does not carry is reported as unmatched rather than failing the run.
#
# Bluefin's GNOME-only packages are already left out: utah.toml's
# [not_on_plasma] section drops them from the contract itself.

FEDORA_REPOS = ("fedora-44", "fedora-44-updates")
# The plain Fedora 44 container the Fedora-side closure is resolved in; the
# factory's own build lanes use the same image.
FEDORA_IMAGE = "quay.io/fedora/fedora:44"
FEDORA_PRIORITY = 99

ARCHES = ("x86_64", "noarch", "i686", "aarch64")

HOST_OUT = Path("output/plasma-closure")
IN_OUT = Path("/out")
IN_SRC = Path("/src")


class Row(NamedTuple):
    action: str
    name: str
    arch: str
    evr: str
    repo: str


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Resolver output
# --------------------------------------------------------------------------

SECTION = re.compile(r"^([A-Z][A-Za-z /-]*?):?\s*$")
ROW = re.compile(
    r"^\s+(?P<name>\S+)\s+(?P<arch>" + "|".join(ARCHES) + r")\s+"
    r"(?P<evr>\S+)\s+(?P<repo>\S+)(?:\s|$)"
)
WRAPPED_REST = re.compile(
    r"^\s+(?P<arch>" + "|".join(ARCHES) + r")\s+(?P<evr>\S+)\s+(?P<repo>\S+)(?:\s|$)"
)
NO_MATCH = re.compile(r"No match for argument:?\s*(\S+)")


def parse_transaction(text: str) -> list[Row]:
    """Rows of a dnf4 or dnf5 transaction table, tagged with their section.

    Parsing stops at the summary: dnf5 repeats the section names there
    ("Installing: 123 packages"), which must not read as a second table.
    dnf4 wraps a long package name onto its own line; the next line then
    starts at the arch column, and the two are joined here.
    """
    rows: list[Row] = []
    action = ""
    pending_name = ""
    for line in text.splitlines():
        if line.strip().startswith("Transaction Summary"):
            break
        if not line.strip():
            pending_name = ""
            continue
        if not line.startswith(" "):
            header = SECTION.match(line.strip())
            if header and line.rstrip().endswith(":"):
                action = header.group(1).strip()
            pending_name = ""
            continue
        if not action:
            continue
        match = ROW.match(line)
        if match and match.group("name") != "replacing":
            rows.append(Row(action, match["name"], match["arch"], match["evr"], match["repo"]))
            pending_name = ""
            continue
        if pending_name:
            rest = WRAPPED_REST.match(line)
            if rest:
                rows.append(Row(action, pending_name, rest["arch"], rest["evr"], rest["repo"]))
            pending_name = ""
            continue
        tokens = line.split()
        if len(tokens) == 1 and tokens[0] != "replacing":
            pending_name = tokens[0]
    return rows


def resolved(text: str) -> bool:
    """dnf printed a complete transaction, which --assumeno then declined."""
    return bool(re.search(r"(?m)^Transaction Summary:?\s*$|^Nothing to do\.?\s*$", text))


def problems(text: str) -> list[str]:
    """The solver's own explanation of why the strict transaction failed."""
    out: list[str] = []
    capture = False
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^(Problem\b|Failed to resolve|Error:)", stripped):
            capture = True
        if capture:
            if not stripped:
                capture = False
                continue
            out.append(stripped)
    return out


def unmatched(text: str) -> list[str]:
    return sorted(set(NO_MATCH.findall(text)))


def source_name(sourcerpm: str) -> str:
    """qt6-qtbase-6.9.2-1.fc44.src.rpm -> qt6-qtbase."""
    stem = sourcerpm.removesuffix(".rpm").removesuffix(".src")
    parts = stem.rsplit("-", 2)
    return parts[0] if len(parts) == 3 else stem


def origin(repo: str) -> str:
    if repo in FEDORA_REPOS:
        return "fedora"
    if repo == "utah-packages":
        return "factory"
    if repo.startswith("public-hummingbird"):
        return "hummingbird"
    return repo


# --------------------------------------------------------------------------
# Inside the container
# --------------------------------------------------------------------------

def package_set(src: Path, *, contract_too: bool, extra: list[str]) -> list[str]:
    installer = load_script("install-packages", src / "scripts/install-packages.py")
    overlay = src / "packages/utah.toml"
    if not contract_too:
        return list(dict.fromkeys(installer.section(overlay, "plasma") + extra))
    base = installer.contract(src / "packages/bluefin.toml", overlay, installer.fedora_major())
    return list(dict.fromkeys(base + extra))


def run_dnf(dnf: str, repos: list[str], packages: list[str], *, skip: bool,
            log: Path) -> str:
    args = [dnf, "--assumeno", "--disablerepo=*",
            *(f"--enablerepo={r}" for r in repos),
            *(f"--setopt={r}.priority={FEDORA_PRIORITY}" for r in FEDORA_REPOS),
            "-x", "PackageKit*", "install"]
    if skip:
        if Path(dnf).name == "dnf5":
            args += ["--skip-broken", "--skip-unavailable"]
        else:
            args += ["--skip-broken", "--setopt=strict=False"]
    args += packages
    print("+", " ".join(args[:8]), f"... ({len(packages)} packages)", flush=True)
    env = {**os.environ, "LC_ALL": "C", "COLUMNS": "400"}
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=env, check=False)
    log.write_text(result.stdout)
    return result.stdout


def query_lines(output: str) -> list[list[str]]:
    """Whitespace-split records from repoquery/rpm --queryformat output.

    dnf4 expands a \\n in the format and appends its own newline; dnf5
    expands it; neither is guaranteed to expand \\t -- the first CI run got
    literal backslash-t and parsed nothing. So the format uses a space as the
    field separator, and a literal backslash-n left in the output is treated
    as the line break it was meant to be.
    """
    text = output.replace("\\n", "\n")
    return [line.split() for line in text.splitlines() if line.strip()]


def sourcerpms(dnf: str, names: list[str], repos: tuple[str, ...] | None = FEDORA_REPOS
               ) -> dict[str, str]:
    """Map binary package names to their source RPM file names."""
    if not names:
        return {}
    repo_args = ["--disablerepo=*", *(f"--enablerepo={r}" for r in repos)] if repos else []
    result = subprocess.run(
        [dnf, "repoquery", *repo_args, "--latest-limit=1", "--arch=x86_64,noarch",
         "--queryformat", "%{name} %{sourcerpm}\\n", *names],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env={**os.environ, "LC_ALL": "C"}, check=False,
    )
    found: dict[str, str] = {}
    for fields in query_lines(result.stdout):
        if len(fields) == 2 and fields[1].endswith(".rpm"):
            found.setdefault(fields[0], fields[1])
    return found


def provided_sources(dnf: str, repos: list[str]) -> set[str]:
    """Source package names Hummingbird, the factory and the base already carry.

    Everything the install repositories offer, plus everything installed in
    the base image: a source in this set needs no factory recipe.
    """
    names: set[str] = set()
    available = subprocess.run(
        [dnf, "repoquery", "--disablerepo=*", *(f"--enablerepo={r}" for r in repos),
         "--queryformat", "%{sourcerpm}\\n"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env={**os.environ, "LC_ALL": "C"}, check=False,
    ).stdout
    installed = subprocess.run(
        ["rpm", "-qa", "--queryformat", "%{SOURCERPM}\\n"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False,
    ).stdout
    for fields in query_lines(available + "\n" + installed):
        for field in fields:
            if field.endswith(".rpm"):
                names.add(source_name(field))
    return names


def build_list(fedora_sources: set[str], provided: set[str]) -> list[str]:
    """What the factory has to build: the Fedora closure's sources it lacks."""
    return sorted(fedora_sources - provided)


def summarize(rows: list[Row], srpm: dict[str, str], *, strict_ok: bool,
              strict_problems: list[str], missing: list[str], requested: int) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[origin(row.repo)] = counts.get(origin(row.repo), 0) + 1
    fedora = [r for r in rows if origin(r.repo) == "fedora"]
    sources = sorted({source_name(srpm[r.name]) for r in fedora if r.name in srpm})
    changed = [r for r in rows if not r.action.startswith("Install")]
    lines = [
        "# Plasma closure on Utah's pinned base",
        "",
        f"- Requested packages: {requested}",
        f"- Strict transaction resolved: {'yes' if strict_ok else 'no'}",
        f"- Packages in transaction: {len(rows)}",
        f"- Fedora-origin sources in this resolve (first cut): {len(sources)}",
        "",
        "| origin | packages |",
        "| --- | ---: |",
        *(f"| {k} | {v} |" for k, v in sorted(counts.items())),
        "",
    ]
    if missing:
        lines += ["## Names no repository carries", "",
                  *(f"- `{name}`" for name in missing), ""]
    if changed:
        lines += ["## Not plain installs (skipped, upgraded, replaced)", "",
                  "These touch Hummingbird's base or could not be resolved at all:", "",
                  *(f"- {r.action}: `{r.name}` {r.evr} ({r.repo})" for r in changed), ""]
    if strict_problems:
        lines += ["## Solver problems in the strict attempt", "",
                  "Each is a Fedora package whose dependencies Hummingbird cannot "
                  "satisfy as-is: a version skew the factory rebuild has to absorb.", "",
                  "```", *strict_problems, "```", ""]
    return "\n".join(lines)


def inside(args: argparse.Namespace) -> int:
    installer = load_script("install-packages", IN_SRC / "scripts/install-packages.py")
    dnf = installer.dnf_path()
    repos = list(installer.install_repos(Path("/etc/yum.repos.d"))) + list(FEDORA_REPOS)
    packages = package_set(IN_SRC, contract_too=not args.plasma_only, extra=args.extra)
    IN_OUT.mkdir(parents=True, exist_ok=True)
    (IN_OUT / "requested.txt").write_text("".join(f"{p}\n" for p in packages))

    strict = run_dnf(dnf, repos, packages, skip=False, log=IN_OUT / "dnf-strict.log")
    strict_ok = resolved(strict) and not problems(strict) and not unmatched(strict)
    text = strict
    if not strict_ok:
        print("strict transaction did not resolve; retrying with broken and "
              "unavailable packages skipped to measure the rest", flush=True)
        text = run_dnf(dnf, repos, packages, skip=True, log=IN_OUT / "dnf-skip-broken.log")
        if not resolved(text):
            print("the resolver failed even with --skip-broken; the end of dnf-skip-broken.log:",
                  file=sys.stderr)
            print("\n".join(text.splitlines()[-40:]), file=sys.stderr)
            return 1

    rows = parse_transaction(text)
    fedora_names = sorted({r.name for r in rows if origin(r.repo) == "fedora"})
    srpm = sourcerpms(dnf, fedora_names)
    with (IN_OUT / "closure.tsv").open("w") as out:
        out.write("action\tname\tarch\tevr\trepo\torigin\tsourcerpm\n")
        for r in sorted(rows, key=lambda r: (origin(r.repo), r.name)):
            out.write(f"{r.action}\t{r.name}\t{r.arch}\t{r.evr}\t{r.repo}\t"
                      f"{origin(r.repo)}\t{srpm.get(r.name, '')}\n")
    sources = sorted({source_name(srpm[n]) for n in fedora_names if n in srpm})
    (IN_OUT / "srpms-first-cut.txt").write_text("".join(f"{s}\n" for s in sources))
    provided = provided_sources(dnf, list(installer.install_repos(Path("/etc/yum.repos.d"))))
    (IN_OUT / "provided-sources.txt").write_text("".join(f"{s}\n" for s in sorted(provided)))
    summary = summarize(rows, srpm, strict_ok=strict_ok,
                        strict_problems=problems(strict),
                        missing=sorted(set(unmatched(strict)) | set(unmatched(text))),
                        requested=len(packages))
    (IN_OUT / "summary.md").write_text(summary + "\n")
    print(summary)
    return 0


def inside_fedora() -> int:
    """Resolve the requested set in plain Fedora 44 and map it to sources."""
    dnf = shutil.which("dnf5") or shutil.which("dnf")
    packages = [p for p in (IN_OUT / "requested.txt").read_text().split() if p]
    args = [dnf, "--assumeno", "-x", "PackageKit*", "install"]
    args += (["--skip-unavailable"] if Path(dnf).name == "dnf5" else ["--setopt=strict=False"])
    print("+", " ".join(args), f"... ({len(packages)} packages)", flush=True)
    result = subprocess.run(args + packages, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env={**os.environ, "LC_ALL": "C", "COLUMNS": "400"},
                            check=False)
    (IN_OUT / "dnf-fedora.log").write_text(result.stdout)
    if not resolved(result.stdout):
        # CI surfaces the job log, not the artifact, first: say why here.
        print("the Fedora-side resolve failed; the end of dnf-fedora.log:", file=sys.stderr)
        print("\n".join(result.stdout.splitlines()[-40:]), file=sys.stderr)
        return 1
    rows = parse_transaction(result.stdout)
    # Packages already in the container are part of the closure too.
    installed = subprocess.run(["rpm", "-qa", "--queryformat", "%{NAME} %{SOURCERPM}\\n"],
                               stdout=subprocess.PIPE, text=True, check=False).stdout
    srpm = {f[0]: f[1] for f in query_lines(installed) if len(f) == 2 and f[1].endswith(".rpm")}
    srpm.update(sourcerpms(dnf, sorted({r.name for r in rows}), repos=None))
    with (IN_OUT / "fedora-closure.tsv").open("w") as out:
        out.write("name\tevr\trepo\tsourcerpm\n")
        for r in sorted(rows, key=lambda r: r.name):
            out.write(f"{r.name}\t{r.evr}\t{r.repo}\t{srpm.get(r.name, '')}\n")
    sources = sorted({source_name(v) for v in srpm.values()})
    (IN_OUT / "fedora-sources.txt").write_text("".join(f"{s}\n" for s in sources))
    (IN_OUT / "fedora-unmatched.txt").write_text(
        "".join(f"{n}\n" for n in unmatched(result.stdout)))
    print(f"Fedora closure: {len(rows)} packages to install, {len(sources)} source packages")
    return 0


def combine(out: Path) -> int:
    """Subtract what Hummingbird and the factory carry from the Fedora closure."""
    read = lambda name: {l for l in (out / name).read_text().split() if l}
    fedora, provided = read("fedora-sources.txt"), read("provided-sources.txt")
    build = build_list(fedora, provided)
    (out / "srpms.txt").write_text("".join(f"{s}\n" for s in build))
    unmatched_names = sorted(read("fedora-unmatched.txt"))
    section = [
        "",
        "## Factory build list",
        "",
        f"The requested set resolved in plain Fedora 44 pulls in {len(fedora)} source",
        f"packages. Hummingbird, the factory and the base image already carry",
        f"{len(fedora & provided)} of them, which leaves **{len(build)}** for the factory",
        "to import and build (`srpms.txt`). Build-only dependencies are not in this",
        "list; the factory's build order surfaces them.",
        "",
    ]
    if unmatched_names:
        section += ["Names Fedora 44 does not carry at all:", "",
                    *(f"- `{n}`" for n in unmatched_names), ""]
    section += ["```", *build, "```", ""]
    with (out / "summary.md").open("a") as summary:
        summary.write("\n".join(section))
    print("\n".join(section))
    return 0


# --------------------------------------------------------------------------
# On the host
# --------------------------------------------------------------------------

def host(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parent.parent
    if not shutil.which(args.engine):
        print(f"{args.engine} not found; pass --engine docker to use Docker", file=sys.stderr)
        return 125
    checker = load_script("check-repo-availability", root / "scripts/check-repo-availability.py")
    base, packages = checker.pinned_inputs(root / "Containerfile")
    out = (root / args.out).resolve() if not args.out.is_absolute() else args.out
    out.mkdir(parents=True, exist_ok=True)
    print(f"Resolving Plasma on {base}\n  with factory metadata from {packages}", flush=True)
    passthrough = []
    if args.plasma_only:
        passthrough.append("--plasma-only")
    for name in args.extra:
        passthrough += ["--extra", name]
    with tempfile.TemporaryDirectory(prefix="utah-repodata-") as tmp:
        # Resolution needs only repodata; the factory's metadata layer is the
        # digest-verified subset check-repos already uses.
        checker.repository_metadata(packages, Path(tmp))
        rc = subprocess.run([
            args.engine, "run", "--rm", "--platform", "linux/amd64",
            "-v", f"{tmp}:/etc/utah-packages:ro,Z",
            "-v", f"{root / 'packages'}:/etc/yum.repos.d:ro,Z",
            "-v", f"{root}:{IN_SRC}:ro,Z",
            "-v", f"{out}:{IN_OUT}:rw,Z",
            base, "python3", f"{IN_SRC}/scripts/plasma-closure.py", "--inside",
            *passthrough,
        ], check=False).returncode
    if rc:
        return rc
    print(f"Resolving the same set in {FEDORA_IMAGE}", flush=True)
    rc = subprocess.run([
        args.engine, "run", "--rm", "--platform", "linux/amd64",
        "-v", f"{root}:{IN_SRC}:ro,Z",
        "-v", f"{out}:{IN_OUT}:rw,Z",
        # A plain Fedora container need not carry Python; install it if not.
        FEDORA_IMAGE, "bash", "-c",
        "command -v python3 >/dev/null || dnf -y -q install python3 >/dev/null; "
        f"exec python3 {IN_SRC}/scripts/plasma-closure.py --inside-fedora",
    ], check=False).returncode
    return rc or combine(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", default="podman")
    parser.add_argument("--out", type=Path, default=HOST_OUT)
    parser.add_argument("--plasma-only", action="store_true",
                        help="resolve the Plasma set alone, without Utah's package contract")
    parser.add_argument("--extra", action="append", default=[], metavar="PKG",
                        help="add a package to the transaction (repeatable)")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--inside-fedora", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside_fedora:
        return inside_fedora()
    return inside(args) if args.inside else host(args)


if __name__ == "__main__":
    raise SystemExit(main())
