import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT / 'collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def test_cpu_deltas_and_resets(self):
        self.assertEqual(collector.utilization((100, 40), (200, 60)), 80)
        self.assertEqual(collector.utilization((100, 40), (100, 40)), 0)
        self.assertEqual(collector.utilization((200, 60), (100, 40)), 0)

    def sensor(self, root, number, driver, readings):
        sensor = root / f'hwmon{number}'
        sensor.mkdir()
        (sensor / 'name').write_text(driver)
        for i, (label, value) in enumerate(readings, 1):
            (sensor / f'temp{i}_label').write_text(label)
            (sensor / f'temp{i}_input').write_text(str(value))

    def test_intel_packages_preferred_and_gpu_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.sensor(root, 0, 'amdgpu', [('edge', 99000)])
            self.sensor(root, 1, 'coretemp', [('Core 0', 80000), ('Package id 0', 51000)])
            self.sensor(root, 2, 'coretemp', [('Package id 1', 57000)])
            self.assertEqual(collector.temperature(root, root), 57)

    def test_amd_control_sensor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.sensor(root, 3, 'k10temp', [('Tctl', 62000), ('Tdie', 42000)])
            self.assertEqual(collector.temperature(root, root), 62)

    def test_missing_and_cpu_thermal_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(collector.temperature(root, root))
            zone = root / 'thermal_zone0'
            zone.mkdir()
            (zone / 'type').write_text('cpu-thermal')
            (zone / 'temp').write_text('47000')
            self.assertEqual(collector.temperature(root, root), 47)
            (zone / 'temp').write_text('broken')
            self.assertIsNone(collector.temperature(root, root))

    def test_history_validation_retention_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            point = {'cpu': 20, 'ram': 50, 'temperature': None}
            collector.write_json(path, [dict(point, time=t) for t in (0, 2000, 4001)])
            self.assertEqual(collector.load_history(path, 4000), [dict(point, time=2000)])
            for invalid in ('[null]', '[{"time":"broken"}]', '{', '[{"time":1,"cpu":NaN,"ram":50,"temperature":null}]'):
                path.write_text(invalid)
                self.assertEqual(collector.load_history(path, 4000), [])


class InstallerTests(unittest.TestCase):
    def test_install_update_uninstall_preserve_other_settings(self):
        with tempfile.TemporaryDirectory(prefix='resource test ') as tmp:
            config = Path(tmp) / 'config % with spaces'
            shell = config / 'omarchy/shell.json'
            shell.parent.mkdir(parents=True)
            unrelated = {'id': 'omarchy.clock', 'format': 'HH:mm'}
            original = {'version': 1, 'idle': {'lock': 300}, 'bar': {'layout': {'left': [], 'center': [unrelated], 'right': [{'id': 'omarchy.network'}]}}}
            shell.write_text(json.dumps(original))
            env = dict(os.environ, XDG_CONFIG_HOME=str(config))
            command = [sys.executable, str(ROOT / 'install.py'), '--no-start']
            for _ in range(2):
                subprocess.run(command, env=env, check=True, capture_output=True)
            data = json.loads(shell.read_text())
            self.assertEqual(data['idle'], original['idle'])
            self.assertEqual(data['bar']['layout']['center'], [unrelated])
            self.assertEqual(data['bar']['layout']['right'], [{'id': 'lucas.resource-usage'}, {'id': 'omarchy.network'}])
            unit = config / 'systemd/user/omarchy-resource-usage.service'
            self.assertIn('%%', unit.read_text())
            self.assertIn('ExecStart=/usr/bin/python3 "', unit.read_text())
            target = config / 'omarchy/plugins/lucas.resource-usage'
            self.assertTrue((target / 'collector.py').is_file())
            self.assertFalse((target / '__pycache__').exists())
            subprocess.run(command + ['--uninstall'], env=env, check=True, capture_output=True)
            self.assertEqual(json.loads(shell.read_text()), original)
            self.assertFalse(unit.exists())
            self.assertTrue((target / 'collector.py').exists())


if __name__ == '__main__':
    unittest.main()
