"""config/identity.json is the single source of the OS identity.

Most consumers read it: configure-branding.sh and configure-live.sh in the
image, the desktop contract through {placeholders}, flavors.py, the Justfile.
A few places cannot -- a Containerfile ARG default, an OCI LABEL -- and carry
a literal copy. These tests hold those copies to the file, so renaming the OS
is an edit to config/identity.json followed by fixing whatever this names.
"""

import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = json.loads((ROOT / "config/identity.json").read_text())


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"),
                                                  ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


identity_py = load("identity")


def arg_default(containerfile, name):
    match = re.search(rf"^ARG {name}=(\S+)$", (ROOT / containerfile).read_text(), re.M)
    return match.group(1) if match else None


def label(name):
    match = re.search(rf'^LABEL org\.opencontainers\.image\.{name}="([^"]*)"$',
                      (ROOT / "Containerfile").read_text(), re.M)
    return match.group(1) if match else None


class IdentityFileTests(unittest.TestCase):
    def test_the_file_is_complete_and_well_formed(self):
        self.assertEqual(identity_py.load(), IDENTITY)

    def test_image_names_and_refs(self):
        self.assertEqual(identity_py.image(IDENTITY), IDENTITY["id"])
        self.assertEqual(identity_py.image(IDENTITY, "nvidia"), f"{IDENTITY['id']}-nvidia")
        self.assertEqual(identity_py.ref(IDENTITY, "main", "stable"),
                         f"ghcr.io/{IDENTITY['vendor']}/{IDENTITY['id']}:stable")

    def test_cli(self):
        out = subprocess.run([sys.executable, str(ROOT / "scripts/identity.py"), "get", "name"],
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, IDENTITY["name"])

    def test_flavor_images_follow_the_id(self):
        out = subprocess.run([sys.executable, str(ROOT / "scripts/flavors.py"), "image", "gaming"],
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, identity_py.image(IDENTITY, "gaming"))


class LiteralCopyTests(unittest.TestCase):
    """The places that cannot read the file must agree with it."""

    def test_containerfile_build_arg_defaults(self):
        self.assertEqual(arg_default("Containerfile", "IMAGE_NAME"), IDENTITY["id"])
        self.assertEqual(arg_default("Containerfile", "IMAGE_ID"), IDENTITY["id"])
        self.assertEqual(arg_default("Containerfile", "IMAGE_VENDOR"), IDENTITY["vendor"])

    def test_containerfile_labels(self):
        self.assertEqual(label("title"), IDENTITY["name"])
        self.assertEqual(label("source"), f"https://github.com/{IDENTITY['repository']}")

    def test_live_iso_containerfile_defaults(self):
        self.assertEqual(arg_default("iso/live/Containerfile", "TARGET_IMAGE"),
                         identity_py.ref(IDENTITY))
        self.assertEqual(arg_default("iso/live/Containerfile", "SOURCE_IMAGE"),
                         f"localhost/{IDENTITY['id']}:testing")

    def test_the_identity_file_is_installed_where_its_readers_look(self):
        containerfile = (ROOT / "Containerfile").read_text()
        self.assertIn("config/identity.json", containerfile)
        self.assertIn("/usr/share/utah/identity.json", containerfile)
        for reader in ("scripts/configure-branding.sh", "iso/live/src/configure-live.sh",
                       "contracts/bluefin-desktop.toml"):
            with self.subTest(reader=reader):
                self.assertIn("/usr/share/utah/identity.json", (ROOT / reader).read_text())


class NoStaleNameTests(unittest.TestCase):
    """Files that read the identity must not also spell it out, or a rename
    would leave the literal behind."""

    READERS = ("scripts/configure-branding.sh", "contracts/bluefin-desktop.toml",
               "iso/live/src/etc/bootc-installer/images.json",
               "iso/live/src/etc/bootc-installer/recipe.json")

    def test_readers_carry_no_literal_name_or_old_identity(self):
        for path in self.READERS:
            text = (ROOT / path).read_text()
            with self.subTest(path=path):
                self.assertNotIn(IDENTITY["name"], text)
                self.assertNotIn("projectbluefin/utah", text)
                self.assertNotRegex(text, r'"Utah"|NAME = "Utah"|ID = "utah"')


if __name__ == "__main__":
    unittest.main()
