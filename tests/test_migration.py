import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('migration_collector', ROOT / 'collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class MigrationTests(unittest.TestCase):
    def test_native_upgrade_retires_only_its_own_unit_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config = home / 'config'
            source = config / 'omarchy/plugins/lucas.resource-usage/collector.py'
            source.parent.mkdir(parents=True)
            source.write_text('')
            unit = config / 'systemd/user/omarchy-resource-usage.service'
            unit.parent.mkdir(parents=True)
            original = f'[Unit]\nDescription=Resource usage and one-hour history for the Omarchy bar\n[Service]\nExecStart=/usr/bin/python3 "{source}"\n'
            unit.write_text(original)
            with mock.patch.dict(os.environ, XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(home / 'state')), \
                    mock.patch.object(collector, '__file__', str(source)), \
                    mock.patch.object(Path, 'home', return_value=home), \
                    mock.patch.object(collector.subprocess, 'run') as run:
                collector.bootstrap()
                collector.bootstrap()
                self.assertEqual(run.call_count, 2)
                self.assertFalse(unit.exists())
                self.assertEqual((home / 'state/omarchy/resource-usage/legacy-service.unit').read_text(), original)
                self.assertTrue((home / '.local/bin/vitals-run').is_symlink())

    def test_customized_unit_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unit = home / 'config/systemd/user/omarchy-resource-usage.service'
            unit.parent.mkdir(parents=True)
            unit.write_text('[Service]\nExecStart=/custom/collector\n')
            with mock.patch.dict(os.environ, XDG_CONFIG_HOME=str(home / 'config')), \
                    mock.patch.object(collector.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'customized'):
                    collector.bootstrap()
                run.assert_not_called()
                self.assertTrue(unit.exists())
