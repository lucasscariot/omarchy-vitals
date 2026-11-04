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

    def test_sampling_gap_respects_cadence_and_preserves_cpu_deltas(self):
        for seconds, elapsed, gap in ((30, 30.25, False), (30, 61, True), (2, 31, True), (30, -1, True)):
            with self.subTest(refresh=seconds, elapsed=elapsed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                readings = {'/proc/meminfo': 'MemTotal: 1000 kB\nMemAvailable: 500 kB\n',
                            '/proc/vmstat': 'pswpin 0\npswpout 0\n'}
                with mock.patch.dict(os.environ, XDG_STATE_HOME=str(root / 'state')), \
                     mock.patch.object(collector, 'STATE', root / 'legacy.json'), \
                     mock.patch.object(collector, 'LIVE', root / 'live.json'), \
                     mock.patch.object(collector.time, 'time', return_value=1000) as clock, \
                     mock.patch.object(collector, 'cpu_times', side_effect=[{'cpu': (100, 40)}, {'cpu': (200, 60)}]), \
                     mock.patch.object(collector, 'read', side_effect=lambda path, *_: readings.get(str(path), '')), \
                     mock.patch.object(collector, 'pressure', return_value={'memory': {}, 'cpu': {}, 'io': {}}), \
                     mock.patch.object(collector, 'temperature', return_value=None), \
                     mock.patch.object(collector, 'Hardware') as hardware, \
                     mock.patch.object(collector, 'app_snapshot', return_value=([], {})), \
                     mock.patch.object(collector.Backend, 'emit'):
                    hardware.return_value.snapshot.return_value = {'network': [], 'network_primary': '', 'disks': [], 'gpus': []}
                    backend = collector.Backend()
                    try:
                        backend.settings = validate({'refreshPolicy': 'fixed', 'refreshSeconds': seconds, 'inferredAgents': False})
                        backend.app_state['existing-scope'] = {'cpu': 1}
                        clock.return_value = 1000 + elapsed
                        backend.tick()
                        self.assertEqual(backend.sample['gap'], gap)
                        self.assertEqual(backend.sample['cpu'], None if gap else 80)
                        self.assertEqual(bool(backend.app_state), not gap)
                        history = backend.history.query(0, 2000)
                        self.assertEqual(history['points'][0]['gap_limit'], max(30, 2 * seconds))
                        events = history['events']
                        self.assertEqual(len([event for event in events if event['kind'] == 'gap']), int(gap))
                    finally:
                        backend.history.close()

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
