"""Native build configuration uses synthetic library paths, no live changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_build", ROOT / "packaging/configure-native-build.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeBuildTests(unittest.TestCase):
    def test_github_environment_is_applied_in_the_next_step(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertEqual(workflow.count("- name: Configure native source build"), 2)
        self.assertEqual(workflow.count("run: python packaging/configure-native-build.py"), 2)
        self.assertNotIn("          python packaging/configure-native-build.py", workflow)

    def test_other_platforms_are_unchanged(self):
        for system, machine in [("Linux", "x86_64"), ("Windows", "AMD64"), ("Darwin", "arm64")]:
            with mock.patch.object(native.platform, "system", return_value=system), mock.patch.object(
                    native.platform, "machine", return_value=machine), mock.patch.object(native.subprocess, "check_output") as brew:
                self.assertEqual(native.configure(environment={}), {})
                brew.assert_not_called()

    def test_intel_requires_static_libraries_and_disables_cached_dynamic_wheels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            env = {"GITHUB_ENV": str(root / "github.env")}
            with mock.patch.object(native.platform, "system", return_value="Darwin"), mock.patch.object(
                    native.platform, "machine", return_value="x86_64"), mock.patch.object(
                    native.subprocess, "check_output", return_value=str(root)):
                with self.assertRaises(RuntimeError):
                    native.configure(environment=env)
                for name in ("libssl.a", "libcrypto.a"):
                    (root / "lib" / name).write_bytes(b"synthetic")
                configured = native.configure(environment=env)
                self.assertEqual(configured["OPENSSL_STATIC"], "1")
                self.assertEqual(configured["PIP_NO_BINARY"], "cryptography")
                self.assertEqual(configured["PIP_NO_CACHE_DIR"], "1")
                self.assertIn(f"OPENSSL_DIR={root}", (root / "github.env").read_text())


if __name__ == "__main__":
    unittest.main()
