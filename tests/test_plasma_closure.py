"""`just plasma-closure` reads dnf's human output, so the parser is the risk.

The resolver runs only with network access to Hummingbird and Fedora, which
CI's static gate does not have. These tests pin the parsing of dnf5 and dnf4
transaction tables, the solver-problem and unmatched-name extraction, and the
package-set composition, so a malformed report cannot pass as a measurement.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"),
                                                  ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


closure = load("plasma-closure")

DNF5 = """\
Updating and loading repositories:
 Fedora 44 - x86_64                     100% |  10.0 MiB/s |  20.0 MiB |  00m02s
Repositories loaded.
Package                     Arch   Version              Repository                      Size
Installing:
 plasma-desktop             x86_64 6.4.5-1.fc44         fedora-44                   23.4 MiB
 glibc-all-langpacks        x86_64 2.42-4.hum1          public-hummingbird-x86_64-rpms  1.0 GiB
Installing dependencies:
 qt6-qtbase                 x86_64 6.9.2-1.fc44         fedora-44-updates           12.0 MiB
 gtk3                       x86_64 3.24.51-1.hum1.bfin  utah-packages               21.0 MiB
Upgrading:
 libfoo                     x86_64 2.0-1.fc44           fedora-44                    1.0 MiB
   replacing libfoo         x86_64 1.0-1.hum1           public-hummingbird-x86_64-rpms  1.0 MiB
Skipping packages with broken dependencies:
 kwin                       x86_64 6.4.5-1.fc44         fedora-44                    9.0 MiB

Transaction Summary:
 Installing:         4 packages
 Upgrading:          1 package
 Replacing:          1 package

Total size of inbound packages is 1 GiB.
Operation aborted by the user.
"""

DNF4 = """\
Dependencies resolved.
================================================================================
 Package                            Arch    Version        Repository     Size
================================================================================
Installing:
 plasma-workspace                   x86_64  6.4.5-1.fc44   fedora-44      20 M
Installing dependencies:
 kf6-a-package-name-long-enough-to-wrap-the-table-column
                                    x86_64  6.18.0-1.fc44  fedora-44     1.2 M

Transaction Summary
================================================================================
Install  2 Packages
"""

PROBLEMS = """\
Updating and loading repositories:
Repositories loaded.
Failed to resolve the transaction:
Problem 1: package kwin-6.4.5-1.fc44.x86_64 requires libdisplay-info.so.3, but none of the providers can be installed
  - conflicting requests
No match for argument: plasma-workspace-wayland
No match for argument: sddm-wayland-plasma

"""


class ParseTransaction(unittest.TestCase):
    def test_dnf5_rows_sections_and_summary_cutoff(self):
        rows = closure.parse_transaction(DNF5)
        self.assertEqual(
            [(r.action, r.name, r.repo) for r in rows],
            [
                ("Installing", "plasma-desktop", "fedora-44"),
                ("Installing", "glibc-all-langpacks", "public-hummingbird-x86_64-rpms"),
                ("Installing dependencies", "qt6-qtbase", "fedora-44-updates"),
                ("Installing dependencies", "gtk3", "utah-packages"),
                ("Upgrading", "libfoo", "fedora-44"),
                ("Skipping packages with broken dependencies", "kwin", "fedora-44"),
            ],
        )
        self.assertTrue(closure.resolved(DNF5))

    def test_dnf4_joins_a_wrapped_name(self):
        rows = closure.parse_transaction(DNF4)
        self.assertEqual(
            [(r.name, r.evr) for r in rows],
            [
                ("plasma-workspace", "6.4.5-1.fc44"),
                ("kf6-a-package-name-long-enough-to-wrap-the-table-column", "6.18.0-1.fc44"),
            ],
        )
        self.assertTrue(closure.resolved(DNF4))

    def test_failed_resolve_reports_problems_and_names(self):
        self.assertFalse(closure.resolved(PROBLEMS))
        self.assertEqual(closure.parse_transaction(PROBLEMS), [])
        found = closure.problems(PROBLEMS)
        self.assertEqual(found[0], "Failed to resolve the transaction:")
        self.assertIn("- conflicting requests", found)
        self.assertEqual(closure.unmatched(PROBLEMS),
                         ["plasma-workspace-wayland", "sddm-wayland-plasma"])


class Classification(unittest.TestCase):
    def test_origin(self):
        self.assertEqual(closure.origin("fedora-44"), "fedora")
        self.assertEqual(closure.origin("fedora-44-updates"), "fedora")
        self.assertEqual(closure.origin("utah-packages"), "factory")
        self.assertEqual(closure.origin("public-hummingbird-x86_64-rpms"), "hummingbird")

    def test_source_name(self):
        self.assertEqual(closure.source_name("qt6-qtbase-6.9.2-1.fc44.src.rpm"), "qt6-qtbase")
        self.assertEqual(closure.source_name("kf6-kio-6.18.0-2.fc44.src.rpm"), "kf6-kio")

    def test_summary_counts_fedora_sources(self):
        rows = closure.parse_transaction(DNF5)
        srpm = {"plasma-desktop": "plasma-desktop-6.4.5-1.fc44.src.rpm",
                "qt6-qtbase": "qt6-qtbase-6.9.2-1.fc44.src.rpm",
                "libfoo": "libfoo-2.0-1.fc44.src.rpm",
                "kwin": "kwin-6.4.5-1.fc44.src.rpm"}
        text = closure.summarize(rows, srpm, strict_ok=False, strict_problems=["Problem 1: x"],
                                 missing=["sddm-wayland-plasma"], requested=2)
        self.assertIn("Fedora-origin sources in this resolve (first cut): 4", text)
        self.assertIn("| fedora | 4 |", text)
        self.assertIn("| factory | 1 |", text)
        self.assertIn("Upgrading: `libfoo`", text)
        self.assertIn("`sddm-wayland-plasma`", text)


class QueryOutput(unittest.TestCase):
    def test_real_and_literal_newlines_both_split_records(self):
        # The first CI run: dnf5 left the format's escapes unexpanded.
        self.assertEqual(closure.query_lines("a a-1-1.fc44.src.rpm\\nb b-2-1.fc44.src.rpm\\n"),
                         [["a", "a-1-1.fc44.src.rpm"], ["b", "b-2-1.fc44.src.rpm"]])
        self.assertEqual(closure.query_lines("a a-1-1.src.rpm\n\n(none)\n"),
                         [["a", "a-1-1.src.rpm"], ["(none)"]])


class BuildList(unittest.TestCase):
    def test_the_build_list_is_the_fedora_closure_minus_what_is_provided(self):
        self.assertEqual(closure.build_list({"kwin", "qt6-qtbase", "glibc"}, {"glibc", "qt6-qtbase"}),
                         ["kwin"])

    def test_combine_writes_srpms_and_appends_the_list_to_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "fedora-sources.txt").write_text("kwin\nplasma-workspace\nglibc\n")
            (out / "provided-sources.txt").write_text("glibc\n")
            (out / "fedora-unmatched.txt").write_text("sddm-wayland-plasma\n")
            (out / "summary.md").write_text("# first\n")
            self.assertEqual(closure.combine(out), 0)
            self.assertEqual((out / "srpms.txt").read_text(), "kwin\nplasma-workspace\n")
            summary = (out / "summary.md").read_text()
            self.assertIn("leaves **2** for the factory", summary)
            self.assertIn("`sddm-wayland-plasma`", summary)


class PackageSet(unittest.TestCase):
    OVERLAY = ROOT / "packages/utah.toml"

    def test_plasma_only_is_the_overlay_section(self):
        installer = load("install-packages")
        plasma = installer.section(self.OVERLAY, "plasma")
        got = closure.package_set(ROOT, contract_too=False, extra=["kcalc", "dolphin"])
        self.assertEqual(got[: len(plasma)], plasma)
        self.assertEqual(got[-1], "kcalc")
        self.assertEqual(len(got), len(set(got)))

    def test_contract_includes_plasma_and_drops_not_on_plasma(self):
        installer = load("install-packages")
        got = self._package_set_with_major("44")
        self.assertIn("glibc-all-langpacks", got)
        self.assertIn("plasma-workspace", got)
        self.assertIn("cryptsetup", got)
        self.assertFalse(set(installer.section(self.OVERLAY, "not_on_plasma")) & set(got))
        self.assertTrue(set(installer.section(self.OVERLAY, "plasma")) <= set(got))

    def _package_set_with_major(self, major):
        real_load = closure.load_script

        def patched(name, path):
            module = real_load(name, path)
            if name == "install-packages":
                # rpm is not on every host; pin the release [fedora_vNN] uses.
                module.fedora_major = lambda: major
            return module

        closure.load_script = patched
        try:
            return closure.package_set(ROOT, contract_too=True, extra=[])
        finally:
            closure.load_script = real_load


if __name__ == "__main__":
    unittest.main()
