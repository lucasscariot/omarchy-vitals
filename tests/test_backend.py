import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from vitals.config import interval, load_settings, validate
from vitals.history import History

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backend_collector', ROOT / 'collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class BackendTests(unittest.TestCase):
    def test_validated_preferences_and_adaptive_cadence(self):
        prefs = validate({})
        self.assertEqual(interval(prefs), 5)
        self.assertEqual(interval(prefs, battery=True), 10)
        self.assertEqual(interval(prefs, incident=True, battery=True), 2)
        for invalid in ({'modules': []}, {'refreshSeconds': True}, {'retentionDays': -1}, {'style': 'bad'}, {'unknown': 1}):
            with self.assertRaises(ValueError):
                validate(invalid)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text('{')
            self.assertTrue(load_settings(path)[1])

    def test_reused_scope_cannot_be_controlled(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = Path(tmp) / 'app-demo-1.scope'
            scope.mkdir()
            backend = collector.Backend.__new__(collector.Backend)
            backend.history = mock.Mock()
            backend.sample = {'apps': [{'id': 'demo', 'kind': 'app', 'name': 'Demo', 'units': [scope.name], 'unit_identity': {scope.name: 'old'}}]}
            with mock.patch.object(collector, 'find_units', return_value=[scope]), mock.patch.object(collector.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    backend.action({'id': 'demo', 'kind': 'app', 'identities': {scope.name: 'old'}, 'action': 'freeze'})
                run.assert_not_called()

    def test_stream_commands_parent_eof_and_single_collector_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, XDG_STATE_HOME=tmp + '/state', XDG_RUNTIME_DIR=tmp + '/run')
            Path(env['XDG_RUNTIME_DIR']).mkdir()
            argv = [sys.executable, str(ROOT / 'collector.py'), '--serve']
            proc = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(json.loads(proc.stdout.readline())['type'], 'settings')
                sample = json.loads(proc.stdout.readline())
                self.assertEqual(sample['type'], 'sample', sample)
                duplicate = subprocess.run(argv, env=env, input='', capture_output=True, text=True, timeout=3)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn('already running', duplicate.stderr)
                proc.stdin.write('{"op":"history","range":3600}\n')
                proc.stdin.flush()
                response = json.loads(proc.stdout.readline())
                self.assertEqual(response['type'], 'history')
                self.assertTrue(response['points'])
                proc.stdin.close()
                self.assertEqual(proc.wait(timeout=5), 0, proc.stderr.read())
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.wait()
                proc.stdout.close(); proc.stderr.close()
