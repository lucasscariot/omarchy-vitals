"""Elapsed-time incident detection; missing samples never mean recovery."""
import uuid


class Incidents:
    def __init__(self):
        self.pending = {}
        self.active = {}
        self.clear_since = {}
        self.previous = None

    def update(self, sample, sensitivity='normal'):
        now = sample['time']
        events = []
        if self.previous is not None and (now < self.previous or now - self.previous > 30):
            for incident in self.active.values():
                events.append(dict(incident, ended=now, status='Interrupted by a sampling gap'))
            self.pending.clear()
            self.active.clear()
            self.clear_since.clear()
        self.previous = now
        factor = {'sensitive': .5, 'normal': 1, 'quiet': 2}[sensitivity]
        for key, threshold, message in (
            ('memory_pressure', 10, 'Tasks are waiting for memory; inspect memory users and swap activity.'),
            ('cpu_pressure', 20, 'Tasks are waiting for CPU time; inspect active builds and agents.'),
            ('io_pressure', 15, 'Tasks are waiting for I/O; inspect disk activity and active jobs.'),
        ):
            value = sample.get(key)
            if value is None:
                self.pending.pop(key, None)
                self.clear_since.pop(key, None)
                continue
            high = value >= threshold * factor and (key != 'cpu_pressure' or sample.get('cpu') is not None and sample['cpu'] >= 90)
            if high:
                self.clear_since.pop(key, None)
                self.pending.setdefault(key, now)
                if key not in self.active and now - self.pending[key] >= 15:
                    self.active[key] = {'id': uuid.uuid4().hex, 'time': self.pending[key], 'resource': key,
                                        'message': message, 'peak': value, 'status': 'Active', 'evidence': dict(sample)}
                    events.append(dict(self.active[key]))
                elif key in self.active:
                    self.active[key]['peak'] = max(self.active[key]['peak'], value)
                    events.append(dict(self.active[key]))
            else:
                self.pending.pop(key, None)
                if key in self.active:
                    self.clear_since.setdefault(key, now)
                    if now - self.clear_since[key] >= 15:
                        incident = self.active.pop(key)
                        events.append(dict(incident, ended=now, status='Recovered'))
                        self.clear_since.pop(key, None)
        return events
