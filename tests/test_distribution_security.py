#!/usr/bin/python3
"""No live restore, capture, signals or user-directory changes in these tests."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('distribution_test_app', str(ROOT / 'app/sessionsifu'))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


class DistributionTests(unittest.TestCase):
    def test_ownership_and_debian_versions(self):
        self.assertEqual(app.install_reconciliation({}, {'installed': False}), 'legacy')
        self.assertEqual(app.install_reconciliation({'mode': 'standalone'}, {'installed': False}), 'standalone')
        self.assertEqual(app.install_reconciliation({'mode': 'apt-backed'}, {'installed': False}), 'system-removed')
        self.assertEqual(app.install_reconciliation({'mode': 'apt-backed'}, {'installed': None}), 'unknown')
        self.assertEqual(app.install_reconciliation({'mode': 'apt-backed'}, {'installed': True}, newer=True), 'system-newer')
        with mock.patch.object(app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(app.install_reconciliation({'mode': 'apt-backed', 'version': '3.5.35'},
                                                        {'installed': True, 'version': '1:3.5.35-1'}), 'system-newer')
            self.assertEqual(run.call_args.args[0][1], '--compare-versions')
        with mock.patch.object(app.subprocess, 'run', side_effect=subprocess.TimeoutExpired('synthetic', 2)):
            self.assertIsNone(app.system_install_info()['installed'])

    def test_legacy_adoption_requires_explicit_valid_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(app.GLib, 'get_user_data_dir', return_value=directory):
                with mock.patch.object(app, 'system_install_info', return_value={'installed': False}):
                    with self.assertRaises(ValueError):
                        app.set_install_ownership('apt-backed')
                    self.assertEqual(app.read_install_receipt(), {})
                    app.set_install_ownership('standalone')
                    self.assertEqual(app.read_install_receipt()['mode'], 'standalone')
                with mock.patch.object(app, 'system_install_info', return_value={'installed': True}):
                    app.set_install_ownership('apt-backed')
                    self.assertEqual(app.read_install_receipt()['mode'], 'apt-backed')

    def test_program_retirement_preserves_recovery_bytes_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, config, binary = root / 'data', root / 'config', root / 'bin'
            recovery = config / 'sessionsifu/currentSession/manualRecovery/old.json'
            recall = config / 'sessionsifu/recall/private.ssrec'
            settings = config / 'sessionsifu/preferences.json'
            for path in [recovery, recall, settings]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'original exact bytes\x00\xff')
                path.chmod(0o600)
            paths = app.user_install_targets(data, config, binary)
            for index, path in enumerate(paths):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f'program-{index}'.encode())
            original = {path: path.read_bytes() for path in paths}
            args = dict(user_data_dir=data, user_config_dir=config, user_bin_dir=binary)
            preview = app.remove_user_install(dry_run=True, **args)
            self.assertTrue(preview['dry_run'])
            self.assertTrue(all(path.exists() for path in paths))
            with mock.patch.object(app, 'shell_settings') as shell:
                shell.return_value.get_strv.side_effect = [['other@local', app.UUID], []]
                result = app.remove_user_install(dry_run=False, **args)
                self.assertEqual(shell.return_value.set_strv.call_args_list[0].args,
                                 ('enabled-extensions', ['other@local']))
            mapping = json.loads((Path(result['backup']) / 'manifest.json').read_text())
            for entry in mapping['paths']:
                self.assertEqual(Path(entry['backup']).read_bytes(), original[Path(entry['original'])])
            for path in [recovery, recall, settings]:
                self.assertEqual(path.read_bytes(), b'original exact bytes\x00\xff')
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(all(not path.exists() for path in paths))

    def test_removal_rolls_back_on_failure_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = dict(user_data_dir=root / 'data', user_config_dir=root / 'config', user_bin_dir=root / 'bin')
            paths = app.user_install_targets(**args)[:2]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'keep')
            real_replace = os.replace
            calls = []
            def replace(source, target):
                calls.append(source)
                if len(calls) == 2:
                    raise OSError('synthetic interrupted retirement')
                return real_replace(source, target)
            with mock.patch.object(app.os, 'replace', side_effect=replace):
                with self.assertRaises(OSError):
                    app.remove_user_install(dry_run=False, disable=False, **args)
            self.assertTrue(all(path.read_bytes() == b'keep' for path in paths))
            paths[0].unlink()
            paths[0].symlink_to(root / 'unrelated')
            with self.assertRaises(ValueError):
                app.remove_user_install(dry_run=False, disable=False, **args)

    def test_release_url_validation(self):
        version = '3.5.35'
        url = f'https://github.com/tpluharik/SessionSifu/releases/download/v{version}/sessionsifu_{version}_all.deb'
        self.assertTrue(app.allowed_update_url(url, version))
        self.assertTrue(app.allowed_update_url(url.replace('github.com/', 'raw.githubusercontent.com/').replace('releases/download/v3.5.35', 'main/updates'), version))
        for bad in [url.replace('tpluharik', 'attacker'), url.replace('https:', 'http:'),
                    url + '?token=abc', url.replace('github.com', 'github.com.evil.example'),
                    url.replace('v3.5.35/', 'v3.5.34/'), url.replace('github.com', 'user@github.com')]:
            self.assertFalse(app.allowed_update_url(bad, version), bad)

    def test_ci_has_no_build_secrets_and_signer_has_no_build_code(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        jobs = workflow['jobs']
        self.assertNotIn('environment', jobs['windows-bundle'])
        sign = jobs['windows-sign']
        self.assertIn('refs/tags/v', sign['if'])
        self.assertEqual(sign['environment'], 'release')
        encoded = json.dumps(sign)
        self.assertNotIn('actions/checkout', encoded)
        self.assertNotIn('pip install', encoded)
        self.assertNotIn('PFX', (ROOT / '.github/workflows/release.yml').read_text().replace('PFX fallback', 'fallback'))
        self.assertNotIn('SNAPCRAFT_STORE_CREDENTIALS', json.dumps(yaml.safe_load(
            (ROOT / '.github/workflows/snapcraft-publish.yml').read_text())['jobs']['snap']))
        snap = yaml.safe_load((ROOT / 'snap/snapcraft.yaml').read_text())
        self.assertEqual(snap['parts']['sessionsifu']['python-requirements'], ['requirements-release.lock'])
        self.assertIn('runtime-requirements.lock', snap['parts']['sessionsifu']['override-pull'])
        self.assertFalse((ROOT / 'extension/sessionsifu@local/template/60-sessionsifu-ydotool-uinput.rules').exists())


if __name__ == '__main__':
    unittest.main()
