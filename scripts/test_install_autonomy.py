"""Adverse cases for staging and preserving an operator's installation."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("installer", Path(__file__).with_name("install-autonomy.py"))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        for name in ["curllm_core/autonomy.py", "curllm_core/cli/autonomy.py", "tests/test_autonomy.py"]:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.sha)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def test_export_excludes_dirty_primary_and_detects_source_drift(self):
        source = self.repo / "curllm_core/autonomy.py"
        source.write_text("# foreign uncommitted work\n")
        release = self.root / "release"
        installer.export_release(self.repo, self.sha, release)
        self.assertEqual((release / "curllm_core/autonomy.py").read_text(), "# fixture\n")
        self.assertEqual(source.read_text(), "# foreign uncommitted work\n")
        (release / "curllm_core/autonomy.py").write_text("# changed\n")
        with self.assertRaisesRegex(ValueError, "digest"):
            installer.verify_release(release)

    def test_unmerged_revision_is_not_admitted(self):
        self.git("checkout", "-b", "ticket/feature")
        (self.repo / "new").touch()
        self.git("add", "new")
        self.git("commit", "-m", "unmerged")
        with self.assertRaises(subprocess.CalledProcessError):
            installer.merged_revision(self.repo, "HEAD")
        self.assertEqual(installer.merged_revision(self.repo, self.sha), self.sha)

    def test_existing_operator_file_is_not_replaced(self):
        path = self.root / "config.json"
        path.write_text("foreign")
        with self.assertRaisesRegex(ValueError, "retained"):
            installer.put_owned(path, "different")
        self.assertEqual(path.read_text(), "foreign")
        installer.put_owned(path, "foreign")

    def test_symlinked_operator_path_is_rejected(self):
        target = self.root / "foreign"
        target.write_text("preserve")
        link = self.root / "config"
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            installer.put_owned(link, "changed")
        self.assertEqual(target.read_text(), "preserve")

    def test_venv_executable_spelling_is_preserved(self):
        python = self.root / "venv/bin/python"
        service, timer = installer.descriptors(self.root / "release", python, self.root / "config", 300)
        self.assertIn(str(python), service)
        self.assertIn(f"WorkingDirectory={self.root / 'release'}\n", service)
        self.assertIn("sha256sum", service)
        self.assertIn("OnUnitInactiveSec=300s", timer)

    def test_systemd_arguments_escape_specifiers_and_quotes(self):
        self.assertEqual(installer.systemd_quote('/a b/"%h'), '"/a b/\\"%%h"')
        with self.assertRaises(ValueError):
            installer.systemd_quote("path\nExecStart=foreign")

    def test_default_probes_require_repeated_observation_without_inferred_repair(self):
        config = installer.default_config(self.root / "release", self.root / "venv/bin/python", self.root / "state")
        self.assertEqual(len(config["probes"]), 3)
        self.assertTrue(all(p["failure_threshold"] == 2 and "repair" not in p for p in config["probes"]))
        self.assertNotEqual(config["planfile_project"], str(self.repo))


if __name__ == "__main__":
    unittest.main()
