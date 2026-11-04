import unittest
from vitals.pressure import Incidents


class PressureTests(unittest.TestCase):
    def sample(self, timestamp, pressure=0, cpu=99):
        return {'time': timestamp, 'cpu': cpu, 'cpu_pressure': pressure,
                'memory_pressure': None, 'io_pressure': None}

    def test_busy_cpu_alone_and_isolated_spikes_do_not_trigger(self):
        detector = Incidents()
        for t in range(0, 60, 5):
            self.assertEqual(detector.update(self.sample(t)), [])
        detector.update(self.sample(65, 50))
        self.assertEqual(detector.update(self.sample(70, 0)), [])
        self.assertFalse(detector.active)

    def test_elapsed_time_hysteresis_and_missing_data(self):
        detector = Incidents()
        detector.update(self.sample(0, 50))
        detector.update(self.sample(10, 50))
        events = detector.update(self.sample(15, 50))
        self.assertEqual(events[0]['status'], 'Active')
        missing = self.sample(20)
        missing['cpu_pressure'] = None
        detector.update(missing)
        self.assertTrue(detector.active)
        detector.update(self.sample(25))
        self.assertTrue(detector.active)
        events = detector.update(self.sample(40))
        self.assertEqual(events[0]['status'], 'Recovered')

    def test_suspend_interrupts_instead_of_claiming_recovery(self):
        detector = Incidents()
        detector.update(self.sample(0, 50))
        detector.update(self.sample(15, 50))
        events = detector.update(self.sample(200))
        self.assertIn('sampling gap', events[0]['status'])
        self.assertFalse(detector.active)
