import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('vitals_run', str(ROOT / 'bin/vitals-run'))
spec = importlib.util.spec_from_loader('vitals_run', loader)
launcher = importlib.util.module_from_spec(spec)
loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_label_sanitization(self):
        self.assertEqual(launcher.sanitize_label('Claude'), 'claude')
        self.assertEqual(launcher.sanitize_label('my app_v2!'), 'my-app-v2')
        self.assertEqual(launcher.sanitize_label('--//--'), 'app')
        self.assertEqual(launcher.sanitize_label(''), 'app')
        long = launcher.sanitize_label('a' * 10 + '-' * 20 + 'b' * 30)
        self.assertLessEqual(len(long), 24)
        self.assertRegex(long, r'^[a-z0-9]+(-[a-z0-9]+)*$')

    def test_argv(self):
        argv = launcher.build_argv('Cargo Test', ['cargo', 'test', '--', '-q'], suffix='abc123')
        self.assertEqual(argv[:6], ['systemd-run', '--user', '--scope', '--quiet', '--collect',
                                    '--unit=agent-cargo-test-abc123'])
        self.assertEqual(argv[argv.index('--') + 1:], ['cargo', 'test', '--', '-q'])
        random = launcher.build_argv('x', ['true'])
        self.assertRegex(random[5], r'^--unit=agent-x-[0-9a-f]{6}$')

    def test_parse(self):
        self.assertEqual(launcher.parse(['--name', 'b', '--', 'cargo', 'test']), ('b', ['cargo', 'test']))
        self.assertEqual(launcher.parse(['--name=b', 'cargo']), ('b', ['cargo']))
        self.assertEqual(launcher.parse(['claude', '--name', 'x']), (None, ['claude', '--name', 'x']))
        self.assertEqual(launcher.parse([]), (None, []))

    def test_default_label_and_scope(self):
        with mock.patch.object(launcher.shutil, 'which', return_value='/usr/bin/systemd-run'), \
                mock.patch.object(launcher, 'manager_available', return_value=True), \
                mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1'}), \
                mock.patch.object(launcher.os, 'execvp') as execvp:
            launcher.main(['/opt/bin/Claude', '--resume'])
        argv = execvp.call_args[0][1]
        self.assertEqual(argv[0], '/usr/bin/systemd-run')
        self.assertTrue(argv[5].startswith('--unit=agent-claude-'))
        self.assertEqual(argv[-2:], ['/opt/bin/Claude', '--resume'])

    def test_fallback_without_systemd_run(self):
        with mock.patch.object(launcher.shutil, 'which', return_value=None), \
                mock.patch.object(launcher, 'supervise', return_value=0) as supervise:
            launcher.main(['echo', 'hi'])
        self.assertEqual(supervise.call_args.args[:2], (['echo', 'hi'], 'echo'))

    def test_usage_error(self):
        self.assertEqual(launcher.main([]), 2)

    def test_fallback_end_to_end(self):
        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ, PATH=empty, XDG_STATE_HOME=empty, XDG_RUNTIME_DIR=empty)
            result = subprocess.run([sys.executable, str(ROOT / 'bin/vitals-run'), '--', sys.executable, '-c', 'raise SystemExit(7)'],
                                    env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 7)
        self.assertIn('without a scope', result.stderr)


if __name__ == '__main__':
    unittest.main()
