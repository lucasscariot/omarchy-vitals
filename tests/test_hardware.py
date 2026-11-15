from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from vitals.hardware import Hardware, bounded, local_volumes, number, pressure


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_pressure_and_nonfinite_values(self):
        self.put('pressure/cpu', 'some avg10=24.5 avg60=2 total=100\nfull avg10=0 avg60=0 total=0\n')
        self.put('pressure/memory', 'some avg10=NaN\n')
        self.assertEqual(pressure(self.root / 'pressure')['cpu']['some'], 24.5)
        self.assertEqual(pressure(self.root / 'pressure')['memory'], {})
        self.assertIsNone(number(self.put('value', 'NaN')))

    def test_network_counter_reset_and_suspended_gpu(self):
        net = self.put('proc/net/dev', 'header\nheader\neth0: 100 0 0 0 0 0 0 0 200 0 0 0\n')
        self.put('sys/class/drm/card0/device/vendor', '0x10de')
        self.put('sys/class/drm/card0/device/power/runtime_status', 'suspended')
        hw = Hardware(self.root / 'sys', self.root / 'proc')
        def helper(argv, **_):
            if argv[0] == 'nvidia-smi':
                raise AssertionError('Must not wake the GPU')
            return '[]'
        with mock.patch('vitals.hardware.bounded', side_effect=helper):
            first = hw.snapshot(100)
            self.assertEqual(first['gpus'][0]['state'], 'Asleep')
            self.assertIsNone(first['network'][0]['rx'])
            net.write_text('header\nheader\neth0: 300 0 0 0 0 0 0 0 400 0 0 0\n')
            self.assertEqual(hw.snapshot(102)['network'][0]['rx'], 100)
            net.write_text('header\nheader\neth0: 1 0 0 0 0 0 0 0 1 0 0 0\n')
            self.assertIsNone(hw.snapshot(104)['network'][0]['rx'])

    def test_helper_timeout_and_output_cap(self):
        self.assertEqual(bounded([sys.executable, '-c', "print('x' * 200000)"], limit=128), '')
        start = time.monotonic()
        self.assertEqual(bounded([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.1), '')
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(bounded([sys.executable, '-c', "print('okay')"]), 'okay\n')

    def test_remote_mounts_are_never_probed(self):
        mountinfo = self.put('mountinfo', '1 0 1:1 / /remote rw - nfs host:/ rw\n2 0 1:2 / /local rw - ext4 /dev/a rw\n')
        with mock.patch('vitals.hardware.os.statvfs', side_effect=PermissionError) as stat:
            self.assertEqual(local_volumes(mountinfo), [{'name': '/local', 'total': None, 'available': None}])
            stat.assert_called_once_with('/local')
