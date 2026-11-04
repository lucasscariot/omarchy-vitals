import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT / 'collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def unit(root, rel, usage=0, mem=0, freeze=0, weight=100, procs=()):
    path = Path(root) / rel
    path.mkdir(parents=True)
    (path / 'cpu.stat').write_text(f'usage_usec {usage}\nuser_usec 1\n')
    (path / 'memory.current').write_text(f'{mem}\n')
    (path / 'cgroup.freeze').write_text(f'{freeze}\n')
    (path / 'cpu.weight').write_text(f'{weight}\n')
    (path / 'cgroup.procs').write_text(''.join(f'{p}\n' for p in procs))
    return path


def set_usage(path, usage):
    (path / 'cpu.stat').write_text(f'usage_usec {usage}\n')


MIB = 1048576


class NormalizeTests(unittest.TestCase):
    def test_table(self):
        table = {
            'app-Hyprland-chromium-8f4771c8.scope': ('app', 'chromium', 'Chromium'),
            'app-org.chromium.Chromium-7971.scope': ('app', 'chromium', 'Chromium'),
            'app-org.chromium.Chromium-155471.scope': ('app', 'chromium', 'Chromium'),
            'app-ghostty-surface-transient-9897.scope': ('app', 'ghostty', 'Ghostty'),
            'app-Hyprland-herdr-a349b66d.scope': ('app', 'herdr', 'Herdr'),
            'app-com.nousresearch.hermes-88765.scope': ('app', 'hermes', 'Hermes'),
            r'app-Hyprland-gtk\x2dlaunch-09ca0869.scope': ('app', 'gtk-launch', 'Gtk-launch'),
            'agent-claude-1a2b3c.scope': ('agent', 'claude', 'claude'),
            'agent-cargo-test-77.scope': ('agent', 'cargo-test', 'cargo-test'),
            'hc-serve-59b93021.service': ('agent', 'herdr', 'herdr'),
        }
        for name, expected in table.items():
            self.assertEqual(collector.classify_unit(name), expected, name)

    def test_ignored(self):
        for name in ('dbus.service', 'session.slice', 'omarchy-resource-usage.service', 'app-.scope'):
            self.assertIsNone(collector.classify_unit(name), name)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'cg'
        self.root.mkdir()
        self.proc = Path(self.tmp.name) / 'proc'
        self.proc.mkdir()

    def test_missing_root(self):
        self.assertEqual(collector.app_snapshot({}, 1, root=self.root / 'nope'), ([], None))

    def test_grouping_and_cpu_delta(self):
        a = unit(self.root, 'app.slice/app-Hyprland-chromium-8f4771c8.scope', 0, 100 * MIB)
        b = unit(self.root, 'app.slice/app-org.chromium.Chromium-7971.scope', 0, 50 * MIB)
        c = unit(self.root, 'app.slice/app-org.chromium.Chromium-155471.scope', 0, 10 * MIB)
        unit(self.root, 'app.slice/app-org.chromium.Chromium-155471.scope/child.scope', 0, 999 * MIB)
        unit(self.root, 'session.slice/dbus.service', 0, 5 * MIB)
        state = {}
        apps, agents = collector.app_snapshot(state, 100, root=self.root, proc_root=self.proc)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]['cpu'], 0)
        self.assertEqual(apps[0]['memory_mib'], 160)
        self.assertEqual(agents['count'], 0)
        self.assertEqual(agents['jobs'], [])
        set_usage(a, 1_000_000)
        set_usage(b, 500_000)
        set_usage(c, 0)
        apps, _ = collector.app_snapshot(state, 102, root=self.root, proc_root=self.proc)
        self.assertEqual(apps[0]['id'], 'chromium')
        self.assertEqual(apps[0]['name'], 'Chromium')
        self.assertEqual(apps[0]['kind'], 'app')
        self.assertEqual(apps[0]['cpu'], 75.0)
        self.assertEqual(len(apps[0]['units']), 3)
        self.assertIn('app-Hyprland-chromium-8f4771c8.scope', apps[0]['units'])

    def test_new_vanished_and_backwards(self):
        a = unit(self.root, 'app.slice/app-foo-1.scope', 1_000_000)
        b = unit(self.root, 'app.slice/app-bar-2.scope', 5_000_000)
        state = {}
        collector.app_snapshot(state, 0, root=self.root)
        set_usage(a, 500_000)  # went backwards
        import shutil
        shutil.rmtree(b)
        unit(self.root, 'app.slice/app-new-3.scope', 9_000_000)
        apps, _ = collector.app_snapshot(state, 2, root=self.root)
        self.assertEqual({x['id']: x['cpu'] for x in apps}, {'foo': 0.0, 'new': 0.0})
        self.assertNotIn(str(b), state['usage'])

    def test_frozen_calmed_and_ordering(self):
        unit(self.root, 'app.slice/app-idle-1.scope', 0, 1 * MIB)
        unit(self.root, 'app.slice/app-big-2.scope', 0, 90 * MIB, freeze=1, weight=20)
        apps, _ = collector.app_snapshot({}, 0, root=self.root)
        self.assertEqual([a['id'] for a in apps], ['big', 'idle'])
        self.assertTrue(apps[0]['frozen'] and apps[0]['calmed'])
        self.assertFalse(apps[1]['frozen'] or apps[1]['calmed'])

    def test_top_eight(self):
        for i in range(12):
            unit(self.root, f'app.slice/app-x{i}-{i}.scope', 0, i * MIB)
        apps, _ = collector.app_snapshot({}, 0, root=self.root)
        self.assertEqual(len(apps), 8)
        self.assertEqual(apps[0]['id'], 'x11')

    def test_agent_jobs(self):
        for pid, ticks, argv in ((11, (5, 5), b'/usr/bin/claude\0--resume\0x\0'), (12, (500, 100), b'/usr/bin/cargo\0test\0--all\0')):
            d = self.proc / str(pid)
            d.mkdir()
            (d / 'stat').write_text(f'{pid} (we ird) S ' + ' '.join(['0'] * 10) + f' {ticks[0]} {ticks[1]} 0\n')
            (d / 'cmdline').write_bytes(argv)
            (d / 'comm').write_text('x\n')
        j = unit(self.root, 'app.slice/agent-cargo-test-77.scope', 0, 20 * MIB, procs=(11, 12, 99))
        h = unit(self.root, 'app.slice/hc-serve-59b93021.service', 0, 4 * MIB)
        state = {}
        collector.app_snapshot(state, 0, root=self.root, proc_root=self.proc)
        set_usage(j, 1_000_000)
        set_usage(h, 200_000)
        apps, agents = collector.app_snapshot(state, 2, root=self.root, proc_root=self.proc)
        self.assertEqual(agents['count'], 2)
        self.assertEqual(agents['cpu'], 60.0)
        self.assertEqual(agents['memory_mib'], 24)
        job = agents['jobs'][0]
        self.assertEqual((job['unit'], job['name'], job['cpu'], job['memory_mib']),
                         ('agent-cargo-test-77.scope', 'cargo-test', 50.0, 20))
        self.assertEqual(job['command'], 'cargo test')
        self.assertEqual(agents['jobs'][1]['name'], 'herdr')
        self.assertIsNone(agents['jobs'][1]['command'])
        self.assertTrue(all(a['kind'] == 'agent' for a in apps))


if __name__ == '__main__':
    unittest.main()
