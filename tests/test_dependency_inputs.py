"""Audit coverage includes all direct shipping/build inputs, without duplicates."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dependency_inputs", ROOT / "tools/dependency-inputs.py")
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


class DependencyInputsTests(unittest.TestCase):
    def test_checked_in_inputs_have_no_drift(self):
        text = inputs.render()
        self.assertEqual((ROOT / "portable/security-audit-requirements.txt").read_text(), text)
        for dependency in ("cryptography==50.0.2", "keyring==25.7.0", "Pillow==13.0.0", "setuptools==84.1.0"):
            self.assertIn(dependency, text)
        self.assertIn("sentence-transformers", inputs.render(semantic=True))
        self.assertNotIn("sentence-transformers", text)

    def test_new_direct_dependency_cannot_be_silently_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "portable").mkdir()
            source = (ROOT / "portable/pyproject.toml").read_text()
            source = source.replace('"psutil==7.2.2"', '"psutil==7.2.2", "synthetic-new-input==1.0"')
            (root / "portable/pyproject.toml").write_text(source)
            self.assertIn("synthetic-new-input==1.0", inputs.render(root))
            self.assertNotEqual(inputs.render(root), inputs.render())

    def test_workflow_blocks_release_and_retains_audit_evidence(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn("needs: [dependency-audit, portable-bundles", workflow)
        self.assertIn("--disable-pip --require-hashes --strict", workflow)
        self.assertIn('path: "*dependency-audit.json"', workflow)
        for lock in ("requirements.lock", "runtime-requirements.lock", "audit-requirements.lock"):
            contents = (ROOT / "packaging" / lock).read_text()
            self.assertIn("--hash=sha256:", contents)
        self.assertIn("cryptography==50.0.2", (ROOT / "packaging/requirements.lock").read_text())
        self.assertIn("pillow==13.0.0", (ROOT / "packaging/runtime-requirements.lock").read_text())


if __name__ == "__main__":
    unittest.main()
