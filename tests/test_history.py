from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from vitals.history import History, combine


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.history = History(Path(self.tmp.name) / 'history.db')
        self.addCleanup(self.history.close)

    def add(self, t, cpu, name='build', memory=100):
        self.history.add(t, {'cpu': cpu, 'ram': 20, 'temperature': None},
                         [{'id': name, 'name': name, 'cpu': cpu, 'memory_mib': memory, 'io_bps': 0}])

    def test_bucket_preserves_every_observed_peak_and_contributors(self):
        self.add(100, 5)
        self.add(102, 95, memory=300)
        self.add(104, 20)
        result = self.history.query(90, 120)
        point = result['points'][0]
        self.assertEqual(point['count'], 3)
        self.assertEqual(point['peaks']['cpu'], 95)
        self.assertEqual(point['values']['cpu'], 40)
        detail = self.history.detail(100, 110)
        self.assertEqual(detail['contributors'][0]['peak_memory_mib'], 300)

    def test_reopen_in_same_bucket_and_late_metadata_migrate_idempotently(self):
        self.add(100, 20)
        self.history.flush()
        self.add(102, 40)
        self.history.flush()
        self.assertEqual(self.history.detail(100, 110)['values']['cpu'], 30)
        legacy = Path(self.tmp.name) / 'legacy.json'
        legacy.write_text(json.dumps([{'time': 200, 'cpu': 10, 'ram': 20, 'temperature': None}]))
        self.history.migrate(legacy, now=300)
        self.history.migrate(legacy, now=300)
        self.assertEqual(self.history.detail(200, 210)['count'], 1)

    def test_rollups_keep_extrema_and_leave_gaps(self):
        self.add(10, 95)
        self.add(12, 5)
        self.add(7200, 20, name='editor')
        self.history.maintain(10000)
        rows = self.history.rows(0, 10001)
        self.assertEqual([r['resolution'] for r in rows], [60, 10])
        self.assertEqual(rows[0]['peaks']['cpu'], 95)
        self.assertEqual(rows[0]['last'], 12)
        self.history.maintain(100000)
        rows = self.history.rows(0, 100001)
        self.assertEqual(rows[0]['resolution'], 300)
        self.assertEqual(rows[0]['peaks']['cpu'], 95)

    def test_events_job_comparisons_and_action_observations(self):
        self.add(100, 80)
        self.history.event('action', 110, 'action', {'message': 'calm', 'before': {'cpu': 80}})
        self.add(120, 20)
        self.add(130, 10)
        self.history.event('start', 100, 'job_start', {'id': 'job', 'time': 100, 'label': 'build'})
        for i in (1, 2):
            self.history.report({'id': str(i), 'ended': 100 + i, 'project_id': 'p', 'label': 'build', 'complete': True, 'cpu_seconds': i * 2})
        result = self.history.query(0, 200)
        action = next(e for e in result['events'] if e['kind'] == 'action')
        self.assertEqual(action['after']['cpu'], 15)
        self.assertEqual(result['reports'][0]['previous']['cpu_seconds'], 2)

    def test_retention_and_unknown_schema(self):
        self.add(100, 30)
        self.history.maintain(8 * 86400)
        self.assertEqual(self.history.query(0, 8 * 86400)['points'], [])
        self.history.db.execute("UPDATE meta SET value='999' WHERE key='schema'")
        self.history.db.commit()
        with self.assertRaises(ValueError):
            History(self.history.path)

    def test_missing_completion_is_unknown_and_live_sessions_stay_open(self):
        self.history.event('a:job_start', 100, 'job_start', {'id': 'a', 'label': 'build', 'started': 100, 'unit': 'agent-a.scope'})
        self.history.reconcile_jobs(120, {'agent-a.scope'})
        self.assertEqual(self.history.query(0, 200)['reports'], [])
        self.history.reconcile_jobs(130, set())
        report = self.history.query(0, 200)['reports'][0]
        self.assertIsNone(report['exit_code'])
        self.assertIsNone(report['duration'])
        self.assertFalse(report['complete'])

    def test_aggregation_keeps_sampling_gaps_and_chart_buckets_do_not_overlap(self):
        self.add(10, 20)
        self.add(200, 30)
        self.add(400, 40)
        self.add(5000, 50)
        self.add(7000, 60)
        self.history.maintain(100000)
        result = self.history.query(0, 604800)
        self.assertFalse(result['points'][0]['contiguous'])
        points = result['points']
        self.assertGreaterEqual(len(points), 3)
        self.assertTrue(all(a['time'] + a['resolution'] <= b['time'] for a, b in zip(points, points[1:])))

    def test_following_action_readings_survive_coarsening(self):
        self.history.event('action', 100, 'action', {'before': {'cpu': 90}, 'message': 'Calm'})
        self.add(110, 20)
        self.add(120, 10)
        self.history.maintain(200)
        self.history.maintain(100000)
        event = self.history.query(0, 100001)['events'][0]
        self.assertEqual(event['after']['cpu'], 15)
        self.assertTrue(event['after_captured'])

    def test_slow_sampling_keeps_cadence_through_storage_and_rollups(self):
        for i in range(8):
            self.history.add(100 + i * 30.25, {'cpu': 20 + i}, [], gap_limit=60)
        self.history.flush()
        with closing(History(self.history.path)) as reopened:
            points = reopened.query(0, 500)['points']
            self.assertEqual(len(points), 8)
            self.assertTrue(all(p['gap_limit'] == 60 for p in points))
            self.assertTrue(all(p['contiguous'] for p in points))
            reopened.maintain(100000)
            points = reopened.query(0, 100001)['points']
            self.assertTrue(all(p['contiguous'] for p in points))
            self.assertTrue(all(p['gap_limit'] == 60 for p in points))

    def test_slow_sampling_still_retains_real_gaps_after_rollup(self):
        for timestamp in (100, 130.25, 191.25):
            self.history.add(timestamp, {'cpu': 20}, [], gap_limit=60)
        self.history.maintain(100000)
        point = self.history.query(0, 100001)['points'][0]
        self.assertFalse(point['contiguous'])
        self.assertEqual(point['count'], 3)

    def test_cadence_changes_use_the_following_samples_limit_and_legacy_default(self):
        def sample(timestamp, limit=None):
            row = dict(first=timestamp, last=timestamp, count=1, values={'cpu': 20})
            if limit is not None:
                row['gap_limit'] = limit
            return row
        # An older fast sample can connect to a later slow sample. The rolled
        # up row keeps the limit of its first sample for its incoming edge.
        combined = combine([sample(100), sample(130.25, 60)], 100, 60)
        self.assertTrue(combined['contiguous'])
        self.assertEqual(combined['gap_limit'], 30)
        self.assertFalse(combine([sample(100, 60), sample(130.25, 30)], 100, 60)['contiguous'])
        self.assertFalse(combine([sample(100), sample(130.25)], 100, 60)['contiguous'])

    def test_storage_budget_includes_reports_and_events(self):
        self.history.budget_mib = 1  # Small synthetic budget to force pruning quickly.
        for i in range(20):
            self.history.event(str(i), i, 'test', {'message': 'x' * 100000})
            self.history.report({'id': str(i), 'ended': i, 'label': 'x' * 100000})
        self.history.maintain(100)
        self.assertLessEqual(self.history.path.stat().st_size, 1024 * 1024)
