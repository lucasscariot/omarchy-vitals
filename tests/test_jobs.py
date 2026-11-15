import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from vitals import jobs
from vitals.history import History

ROOT = Path(__file__).resolve().parents[1]


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patch = mock.patch.dict(os.environ, XDG_STATE_HOME=str(self.root / 'state'), XDG_RUNTIME_DIR=str(self.root / 'run'))
        patch.start()
        self.addCleanup(patch.stop)

    def test_short_scoped_job_receipt_and_single_writer_import(self):
        group = self.root / 'agent-build-abc.scope'
        group.mkdir()
        (group / 'cpu.stat').write_text('usage_usec 1000000\n')
        (group / 'memory.peak').write_text('1048576')
        (group / 'io.stat').write_text('8:0 rbytes=1 wbytes=2\n')
        (group / 'cgroup.procs').write_text(str(os.getpid()))
        script = "from pathlib import Path; import sys; p=Path(sys.argv[1]); (p/'cpu.stat').write_text('usage_usec 9000000\\n'); (p/'memory.peak').write_text('3145728'); (p/'io.stat').write_text('8:0 rbytes=101 wbytes=202\\n'); raise SystemExit(7)"
        with mock.patch.object(jobs, 'own_cgroup', return_value=group):
            code = jobs.supervise([sys.executable, '-c', script, str(group)], 'build', 'abc', {'project': 'demo', 'project_id': 'project'})
        self.assertEqual(code, 7)
        history = History(self.root / 'history.db')
        try:
            self.assertEqual(jobs.consume(history, __import__('time').time()), 2)
            self.assertEqual(jobs.consume(history, __import__('time').time()), 0)
            result = history.query(0, __import__('time').time())
            report = result['reports'][0]
            self.assertEqual(report['cpu_seconds'], 8)
            self.assertEqual(report['peak_memory_mib'], 3)
            self.assertEqual(report['read_bytes'], 100)
            self.assertEqual(report['write_bytes'], 200)
            self.assertTrue(report['complete'])
            self.assertEqual({e['kind'] for e in result['events']}, {'job_start', 'job_end'})
            self.assertNotIn(str(self.root), json.dumps(report))
        finally:
            history.close()

    def test_recording_failure_does_not_prevent_command_or_change_exit(self):
        with mock.patch.object(jobs, 'own_cgroup', return_value=None), mock.patch.object(jobs, 'spool', side_effect=OSError('full disk')):
            self.assertEqual(jobs.supervise([sys.executable, '-c', 'raise SystemExit(7)'], 'test', 'abc', {'project': 'demo', 'project_id': 'p'}), 7)

    def test_launcher_preserves_child_umask_and_private_receipts(self):
        for worker in (False, True):
            for mask in (0o022, 0o027):
                with self.subTest(worker=worker, umask=oct(mask)):
                    root = self.root / f'{worker}-{mask}'
                    root.mkdir()
                    env = dict(os.environ, PATH='', XDG_STATE_HOME=str(root / 'state'), XDG_RUNTIME_DIR=str(root / 'run'))
                    script = "from pathlib import Path; import sys; root=Path(sys.argv[1]); (root/'artifact').write_text('build'); (root/'output').mkdir()"
                    args = ['--worker', 'abc', 'build', 'p', 'demo', '--'] if worker else ['--']
                    result = subprocess.run([sys.executable, str(ROOT / 'bin/vitals-run'), *args, sys.executable, '-c', script, str(root)],
                                            env=env, capture_output=True, text=True, umask=mask, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((root / 'artifact').stat().st_mode & 0o777, 0o666 & ~mask)
                    self.assertEqual((root / 'output').stat().st_mode & 0o777, 0o777 & ~mask)
                    inbox = root / 'state/omarchy/resource-usage/inbox'
                    receipts = list(inbox.glob('*.json'))
                    self.assertEqual(len(receipts), 2)
                    self.assertEqual(inbox.stat().st_mode & 0o777, 0o700)
                    for receipt in receipts:
                        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_termination_is_forwarded_and_recorded(self):
        env = dict(os.environ, PATH='')
        proc = subprocess.Popen([sys.executable, str(ROOT / 'bin/vitals-run'), '--', sys.executable, '-u', '-c', "import time; print('READY', flush=True); time.sleep(20)"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), 'READY')
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=5), 143)
            receipts = [json.loads(p.read_text()) for p in (jobs.state_dir() / 'inbox').glob('*.json')]
            ended = next(r for r in receipts if r['event'] == 'job_end')
            self.assertEqual(ended['signal'], signal.SIGTERM)
            self.assertFalse(ended['complete'])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def test_interactive_terminal_is_inherited(self):
        master, slave = os.openpty()
        try:
            env = dict(os.environ, PATH='')
            result = subprocess.run([sys.executable, str(ROOT / 'bin/vitals-run'), '--', sys.executable, '-c', 'import os; raise SystemExit(0 if os.isatty(0) and os.isatty(1) else 3)'], env=env, stdin=slave, stdout=slave, stderr=slave, timeout=5)
            self.assertEqual(result.returncode, 0)
        finally:
            os.close(master)
            os.close(slave)
