"""One SQLite writer; bounded, multi-resolution history and event attribution."""
import json
import math
from pathlib import Path
import sqlite3
import time


def dumps(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


def combine(rows, start, resolution):
    """Combine aggregates without losing observed extrema or coverage."""
    keys = set().union(*(r['values'] for r in rows)) if rows else set()
    values, peaks, minima, weights = {}, {}, {}, {}
    for key in keys:
        valid = [r for r in rows if isinstance(r['values'].get(key), (float, int)) and math.isfinite(r['values'][key])]
        if not valid:
            values[key] = None
            continue
        weight = sum(r.get('weights', {}).get(key, r['count']) for r in valid)
        weights[key] = weight
        values[key] = sum(r['values'][key] * r.get('weights', {}).get(key, r['count']) for r in valid) / weight
        peaks[key] = max(r.get('peaks', {}).get(key, r['values'][key]) for r in valid)
        minima[key] = min(r.get('minima', {}).get(key, r['values'][key]) for r in valid)
    contributors = {}
    for row in rows:
        for app in row.get('contributors', []):
            target = contributors.setdefault(app['id'], dict(app, count=0, cpu=0, memory_mib=0, io_bps=0, peak_memory_mib=0))
            n = app.get('count', row['count'])
            target['count'] += n
            for key in ('cpu', 'memory_mib', 'io_bps'):
                target[key] += app.get(key, 0) * n
            target['peak_memory_mib'] = max(target['peak_memory_mib'], app.get('peak_memory_mib', app.get('memory_mib', 0)))
    for app in contributors.values():
        for key in ('cpu', 'memory_mib', 'io_bps'):
            app[key] /= app['count']
    # Retain CPU, memory and I/O leaders, not just CPU leaders.
    chosen = {}
    for key in ('cpu', 'memory_mib', 'io_bps'):
        for app in sorted(contributors.values(), key=lambda a: -a[key])[:12]:
            chosen[app['id']] = app
    ordered = sorted(rows, key=lambda r: r['first'])
    contiguous = all(r.get('contiguous', True) for r in rows) and all(b['first'] - a['last'] <= 30 for a, b in zip(ordered, ordered[1:]))
    return {'time': start, 'resolution': resolution, 'values': values, 'peaks': peaks,
            'minima': minima, 'weights': weights, 'count': sum(r['count'] for r in rows),
            'first': min(r['first'] for r in rows), 'last': max(r['last'] for r in rows),
            'contiguous': contiguous, 'contributors': list(chosen.values())}


class History:
    def __init__(self, path, retention=7, budget_mib=128):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=2)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS samples (resolution INTEGER, time INTEGER, data TEXT,
                PRIMARY KEY(resolution,time));
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, time REAL, kind TEXT, data TEXT);
            CREATE INDEX IF NOT EXISTS event_time ON events(time);
            CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, time REAL, data TEXT);
            CREATE INDEX IF NOT EXISTS report_time ON reports(time);
        ''')
        version = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if version and version[0] != '1':
            self.db.close()
            raise ValueError('Unsupported history database version')
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('schema','1')")
        self.db.commit()
        self.retention = retention
        self.budget_mib = budget_mib
        self.pending = []
        self.bucket = None

    def add(self, timestamp, values, contributors):
        bucket = int(timestamp // 10) * 10
        if self.bucket is not None and bucket != self.bucket:
            self.flush()
        self.bucket = bucket
        self.pending.append({'values': values, 'count': 1, 'first': timestamp,
                             'last': timestamp, 'contributors': contributors})

    def flush(self):
        if not self.pending:
            return
        row = combine(self.pending, self.bucket, 10)
        existing = self.db.execute('SELECT data FROM samples WHERE resolution=10 AND time=?', (self.bucket,)).fetchone()
        if existing:
            row = combine([json.loads(existing[0]), row], self.bucket, 10)
        self.db.execute('INSERT OR REPLACE INTO samples VALUES(?,?,?)', (10, self.bucket, dumps(row)))
        self.db.commit()
        self.pending = []

    def event(self, ident, timestamp, kind, data):
        self.db.execute('INSERT OR REPLACE INTO events VALUES(?,?,?,?)', (ident, timestamp, kind, dumps(data)))
        self.db.commit()

    def report(self, report):
        self.db.execute('INSERT OR REPLACE INTO reports VALUES(?,?,?)', (report['id'], report['ended'], dumps(report)))
        self.db.commit()

    def reconcile_jobs(self, now, active_units):
        """An absent supervisor receipt is unknown, never a successful exit."""
        starts = self.db.execute("SELECT data FROM events WHERE kind='job_start'").fetchall()
        for (encoded,) in starts:
            job = json.loads(encoded)
            if job.get('unit') in active_units or now - job['started'] < 5:
                continue
            if self.db.execute('SELECT 1 FROM reports WHERE id=?', (job['id'],)).fetchone():
                continue
            report = dict(job, ended=now, duration=None, exit_code=None, signal=None,
                          complete=False, cpu_seconds=None, peak_memory_mib=None,
                          read_bytes=None, write_bytes=None, accounting='unavailable',
                          error='Session disappeared without a completion receipt; exit status and end time are unknown.')
            self.report(report)
            self.event(job['id'] + ':job_end', now, 'job_end', dict(report, message='Session no longer observed: ' + job['label']))

    def migrate(self, path, now=None):
        if self.db.execute("SELECT value FROM meta WHERE key='legacy_import'").fetchone():
            return
        now = time.time() if now is None else now
        try:
            source = Path(path)
            if source.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('Legacy history is oversized')
            points = json.loads(source.read_text())
            if not isinstance(points, list):
                raise ValueError('Invalid legacy history')
            valid = []
            for p in points:
                vals = [p[k] for k in ('time', 'cpu', 'ram')]
                if any(type(v) not in (float, int) or not math.isfinite(v) for v in vals):
                    raise ValueError('Invalid legacy sample')
                if not 0 <= p['cpu'] <= 100 or not 0 <= p['ram'] <= 100:
                    raise ValueError('Invalid legacy percentages')
                temp = p.get('temperature')
                if temp is not None and (type(temp) not in (float, int) or not math.isfinite(temp)):
                    raise ValueError('Invalid temperature')
                if now - 86400 * self.retention <= p['time'] <= now:
                    valid.append(p)
            for p in sorted(valid, key=lambda p: p['time']):
                self.add(p['time'], {k: p[k] for k in ('cpu', 'ram', 'temperature')}, [])
            self.flush()
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, OSError):
            return  # Preserve the source and retry rather than claim an import succeeded.
        self.db.execute("INSERT INTO meta VALUES('legacy_import','1')")
        self.db.commit()

    def maintain(self, now):
        self.flush()
        for ident, timestamp, encoded in self.db.execute("SELECT id,time,data FROM events WHERE kind='action' AND time<=?", (now - 60,)).fetchall():
            event = json.loads(encoded)
            if event.get('after_captured'):
                continue
            following = [r for r in self.rows(timestamp, timestamp + 60) if r['first'] > timestamp]
            event['after_captured'] = True
            if following:
                event['after'] = combine(following, timestamp, 60)['values']
            self.event(ident, timestamp, 'action', event)
        for source, target, cutoff in ((10, 60, now - 3600), (60, 300, now - 86400)):
            rows = self.db.execute('SELECT time,data FROM samples WHERE resolution=? AND time+?<=? ORDER BY time', (source, target, int(cutoff // target) * target)).fetchall()
            groups = {}
            for timestamp, data in rows:
                groups.setdefault(timestamp // target * target, []).append(json.loads(data))
            for timestamp, parts in groups.items():
                existing = self.db.execute('SELECT data FROM samples WHERE resolution=? AND time=?', (target, timestamp)).fetchone()
                if existing:
                    parts.append(json.loads(existing[0]))
                row = combine(parts, timestamp, target)
                self.db.execute('INSERT OR REPLACE INTO samples VALUES(?,?,?)', (target, timestamp, dumps(row)))
            self.db.executemany('DELETE FROM samples WHERE resolution=? AND time=?', [(source, r[0]) for r in rows])
        cutoff = now - self.retention * 86400
        self.db.execute('DELETE FROM samples WHERE time<?', (cutoff,))
        self.db.execute('DELETE FROM events WHERE time<?', (cutoff,))
        self.db.execute('DELETE FROM reports WHERE time<?', (cutoff,))
        for table in ('events', 'reports'):
            self.db.execute(f'DELETE FROM {table} WHERE id IN (SELECT id FROM {table} ORDER BY time DESC LIMIT -1 OFFSET 1000)')
        self.db.commit()
        # Prune by actual payload size, then reclaim database/WAL space when needed.
        budget = self.budget_mib * 1024 * 1024
        def payload_size():
            return sum(self.db.execute(f'SELECT coalesce(sum(length(data)),0) FROM {table}').fetchone()[0] for table in ('samples', 'events', 'reports'))
        payload = payload_size()
        while payload > budget * .65:
            oldest = [(self.db.execute(f'SELECT min(time) FROM {table}').fetchone()[0], table) for table in ('samples', 'events', 'reports')]
            _, table = min((timestamp, table) for timestamp, table in oldest if timestamp is not None)
            self.db.execute(f'DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY time LIMIT 100)')
            self.db.commit()
            payload = payload_size()
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        if self.path.stat().st_size > budget:
            self.db.execute('VACUUM')
            self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def rows(self, start, end):
        self.flush()
        return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM samples WHERE time<? AND time+resolution>? ORDER BY time', (end, start))]

    def query(self, start, end):
        rows = self.rows(start, end)
        base = max((r['resolution'] for r in rows), default=10)
        width = max(base, math.ceil((end - start) / 500 / base) * base)
        groups = {}
        for row in rows:
            groups.setdefault(int(row['time'] // width) * width, []).append(row)
        points = []
        for timestamp, parts in sorted(groups.items()):
            row = combine(parts, timestamp, max(width, max(p['resolution'] for p in parts)))
            row.pop('contributors')
            points.append(row)
        events = [{**json.loads(r[3]), 'id': r[0], 'time': r[1], 'kind': r[2]} for r in self.db.execute('SELECT * FROM events WHERE time>=? AND time<=? ORDER BY time DESC LIMIT 200', (start, end))]
        for event in events:
            if event['kind'] == 'action' and 'after' not in event and end >= event['time'] + 30:
                following = [row for row in self.rows(event['time'], min(end, event['time'] + 60)) if row['first'] > event['time']]
                if following:
                    event['after'] = combine(following, event['time'], 60)['values']
        reports = [json.loads(r[0]) for r in self.db.execute('SELECT data FROM reports ORDER BY time DESC LIMIT 50')]
        for report in reports:
            previous = next((p for p in reports if p['id'] != report['id'] and p.get('project_id') == report.get('project_id') and p.get('label') == report.get('label') and p['ended'] < report['ended'] and p.get('complete') and report.get('complete')), None)
            if previous:
                report['previous'] = {k: previous.get(k) for k in ('duration', 'cpu_seconds', 'peak_memory_mib', 'read_bytes', 'write_bytes')}
        return {'points': points, 'events': events, 'reports': reports}

    def detail(self, start, end):
        rows = self.rows(start, end)
        return combine(rows, start, end - start) if rows else {'contributors': [], 'count': 0}

    def close(self):
        self.flush()
        self.db.close()
