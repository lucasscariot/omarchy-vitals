#!/usr/bin/env python3
"""Native service backend: live resources, attributed history and tracked jobs."""
import json
import math
import os
from pathlib import Path
import re
import signal
import time
import argparse
import fcntl
import select
import subprocess
import sys
import uuid

from vitals.config import atomic_json, interval, load_settings, runtime_dir, state_dir, validate
from vitals.hardware import Hardware, bounded, cgroup_io, number, pressure, read
from vitals.history import History
from vitals.jobs import consume
from vitals.pressure import Incidents

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'omarchy/resource-usage/history.json'
LIVE = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'omarchy-resource-usage.json'


def cpu_times():
    result = {}
    for line in Path('/proc/stat').read_text().splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith('cpu'):
            continue
        values = list(map(int, fields[1:9]))
        result[fields[0]] = (sum(values), values[3] + values[4])
    return result


def utilization(before, after):
    total = after[0] - before[0]
    idle = after[1] - before[1]
    if total <= 0 or idle < 0:
        return 0.0
    return round(max(0, min(100, 100 * (1 - idle / total))), 1)


def temperature(hwmon_root=Path('/sys/class/hwmon'), thermal_root=Path('/sys/class/thermal')):
    """Prefer CPU package sensors; never substitute GPU or disk temperatures."""
    packages, cores, fallback = [], [], []
    for sensor in sorted(hwmon_root.glob('hwmon*')):
        try:
            driver = (sensor / 'name').read_text().strip()
        except OSError:
            continue
        if driver not in ('k10temp', 'zenpower', 'coretemp', 'k8temp', 'cpu_thermal'):
            continue
        for value_file in sensor.glob('temp*_input'):
            try:
                value = int(value_file.read_text()) / 1000
                if not 0 <= value <= 150:
                    continue
                label_file = value_file.with_name(value_file.name.replace('_input', '_label'))
                label = label_file.read_text().strip() if label_file.exists() else ''
                if label == 'Tctl' or label.startswith('Package id'):
                    packages.append(value)
                elif label == 'Tdie' or label.startswith('Core '):
                    cores.append(value)
                elif not label:
                    fallback.append(value)
            except (OSError, ValueError):
                continue
    for candidates in (packages, cores, fallback):
        if candidates:
            return max(candidates)
    for zone in sorted(thermal_root.glob('thermal_zone*')):
        try:
            kind = (zone / 'type').read_text().strip().lower()
            if kind not in ('x86_pkg_temp', 'cpu-thermal', 'cpu_thermal', 'soc_thermal'):
                continue
            value = int((zone / 'temp').read_text()) / 1000
            if 0 <= value <= 150:
                fallback.append(value)
        except (OSError, ValueError):
            continue
    return max(fallback) if fallback else None


CGROUP_ROOT = Path(f'/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service')
LAUNCHERS = ('hyprland', 'niri', 'sway', 'gnome', 'kde', 'river', 'labwc', 'wayfire', 'i3', 'openbox', 'uwsm')
UNIT_SUFFIX = re.compile(r'-(?:\d+|[0-9a-fA-F]{8})$')


def unescape_unit(name):
    return re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), name)


def classify_unit(unit):
    """Return (kind, id, display name) for an app/agent unit, or None to ignore it."""
    name = unescape_unit(unit)
    if name.startswith('agent-') and name.endswith('.scope'):
        label = name[len('agent-'):-len('.scope')]
        if '-' in label:
            label = label.rsplit('-', 1)[0]
        return ('agent', label.lower(), label) if label else None
    if name.startswith('hc-') and name.endswith('.service'):
        return ('agent', 'herdr', 'herdr')
    if name.startswith('app-') and name.endswith('.scope'):
        ident = name[len('app-'):-len('.scope')]
        ident = UNIT_SUFFIX.sub('', ident)
        head, _, rest = ident.partition('-')
        if rest and head.lower() in LAUNCHERS:
            ident = rest
        ident = ident.replace('-surface-transient', '')
        if '.' in ident:
            ident = ident.rsplit('.', 1)[1]
        if not ident:
            return None
        return ('app', ident.lower(), ident[0].upper() + ident[1:])
    return None


def find_units(root):
    units = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return units
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if entry.name.endswith(('.scope', '.service')):
            if classify_unit(entry.name):
                units.append(Path(entry.path))
        else:
            units.extend(find_units(entry.path))
    return units


def read_int(path, default=None):
    try:
        return int(Path(path).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return default


def read_usage(path):
    try:
        for line in (Path(path) / 'cpu.stat').read_text().splitlines():
            if line.startswith('usage_usec'):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def busiest_command(unit, proc_root=Path('/proc')):
    """Best-effort short command of the unit's most CPU-hungry process."""
    try:
        pids = (unit / 'cgroup.procs').read_text().split()
    except OSError:
        return None
    best, best_ticks = None, -1
    for pid in pids:
        try:
            fields = (proc_root / pid / 'stat').read_text().rsplit(')', 1)[1].split()
            ticks = int(fields[11]) + int(fields[12])
        except (OSError, ValueError, IndexError):
            continue
        if ticks > best_ticks:
            best, best_ticks = pid, ticks
    if best is None:
        return None
    try:
        words = [w for w in read(proc_root / best / 'cmdline', 4096).split('\0') if w][:2]
        if words:
            words[0] = os.path.basename(words[0]) or words[0]
            return ' '.join(words)[:60]
    except OSError:
        pass
    try:
        return (proc_root / best / 'comm').read_text().strip() or None
    except OSError:
        return None


def app_snapshot(state, now, root=None, proc_root=Path('/proc'), cpu_count=None, detailed=True):
    """Per-app and per-agent usage from systemd user cgroups. `state` carries usage between calls."""
    root = Path(CGROUP_ROOT if root is None else root)
    if not root.is_dir():
        state.clear()
        return [], None
    previous, previous_time = state.get('usage', {}), state.get('time')
    elapsed = now - previous_time if previous_time is not None else 0
    usage, apps, agent_units = {}, {}, []
    cpu_count = max(1, cpu_count or os.cpu_count() or 1)
    io_state = state.get('io', {})
    next_io = {}
    for path in find_units(root):
        kind, ident, display = classify_unit(path.name)
        current = read_usage(path)
        cpu = 0.0
        if current is not None:
            usage[str(path)] = current
            before = previous.get(str(path))
            if before is not None and elapsed > 0 and current >= before:
                cpu = (current - before) / (elapsed * 1e6 * cpu_count) * 100
        memory = (read_int(path / 'memory.current', 0) or 0) / 1048576
        weight = read_int(path / 'cpu.weight')
        frozen = read_int(path / 'cgroup.freeze', 0) == 1
        calmed = weight is not None and weight < 100
        session = {}
        if kind == 'agent':
            try:
                meta = (runtime_dir() / 'sessions' / path.name).with_suffix('.json')
                if meta.stat().st_size <= 16384:
                    value = json.loads(meta.read_text())
                    if isinstance(value, dict):
                        session = {key: str(value.get(key, ''))[:256] for key in ('id', 'project', 'project_id', 'command')}
                        started = value.get('started')
                        session['started'] = started if type(started) in (float, int) and math.isfinite(started) else None
            except (OSError, ValueError, TypeError):
                pass
            ident = path.name
        app = apps.setdefault((kind, ident), {'id': ident, 'name': display, 'kind': kind, 'cpu': 0.0,
                                              'mem': 0.0, 'units': [], 'frozen': False, 'calmed': False,
                                              'io_bps': 0, 'session': session, 'identities': {}})
        try:
            app['identities'][path.name] = str(path.stat().st_ino)
        except OSError:
            continue
        counts = cgroup_io(path)
        total_io = sum(v for v in counts.values() if v is not None)
        if all(v is not None for v in counts.values()):
            next_io[str(path)] = total_io
        if str(path) in next_io and str(path) in io_state and elapsed > 0:
            app['io_bps'] += max(0, total_io - io_state[str(path)]) / elapsed
        app['cpu'] += cpu
        app['mem'] += memory
        app['units'].append(path.name)
        app['frozen'] = app['frozen'] or frozen
        app['calmed'] = app['calmed'] or calmed
        if kind == 'agent':
            agent_units.append((cpu, memory, path, session))
    state['usage'], state['time'], state['io'] = usage, now, next_io
    ordered = sorted(apps.values(), key=lambda a: (-a['cpu'], -a['mem']))
    ranked = ordered
    out_apps = [{'id': a['id'], 'name': a['name'], 'kind': a['kind'], 'cpu': round(min(100, a['cpu']), 1),
                 'memory_mib': int(a['mem']), 'units': sorted(a['units']), 'frozen': a['frozen'],
                 'calmed': a['calmed'], 'cores_used': round(min(100, a['cpu']) * cpu_count / 100, 2),
                 'io_bps': a['io_bps'], 'project': a['session'].get('project', ''),
                 'project_id': a['session'].get('project_id', ''),
                 'session_id': a['session'].get('id', a['id']),
                 'started': a['session'].get('started'), 'unit_identity': a['identities'],
                 'inferred': False} for a in ranked]
    agent_units.sort(key=lambda u: (-u[0], -u[1]))
    jobs = []
    for cpu, memory, path, session in agent_units:
        kind, ident, display = classify_unit(path.name)
        jobs.append({'unit': path.name, 'name': 'herdr' if path.name.startswith('hc-') else display,
                     'cpu': round(cpu, 1), 'memory_mib': int(memory),
                     'command': busiest_command(path, proc_root) if detailed else session.get('command'), 'session': session})
    agents = {'cpu': round(min(100, sum(u[0] for u in agent_units)), 1),
              'memory_mib': int(sum(u[1] for u in agent_units)),
              'count': len(agent_units), 'jobs': jobs}
    return out_apps, agents


def trim(history, now):
    return [p for p in history if now - 3600 <= p['time'] <= now][-361:]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, separators=(',', ':'), allow_nan=False))
    temporary.replace(path)


def load_history(path, now):
    try:
        history = json.loads(path.read_text())
        if not isinstance(history, list):
            return []
        for point in history:
            for key in ('time', 'cpu', 'ram', 'temperature'):
                value = point[key]
                if key == 'temperature' and value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    return []
            if not 0 <= point['cpu'] <= 100 or not 0 <= point['ram'] <= 100:
                return []
        return trim(sorted(history, key=lambda p: p['time']), now)
    except (OSError, ValueError, TypeError, KeyError):
        return []


def inferred_agents(previous, now, proc=Path('/proc'), cpu_count=None):
    """Root processes only: never pretend an inferred process owns a whole job."""
    cpu_count = max(1, cpu_count or os.cpu_count() or 1)
    result, next_state = [], {}
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            name = read(path / 'comm', 256)
            if name not in ('claude', 'codex', 'opencode', 'gemini'):
                continue
            group = read(path / 'cgroup')
            if '/agent-' in group or '/hc-' in group:
                continue
            fields = read(path / 'stat').rsplit(')', 1)[1].split()
            ticks = int(fields[11]) + int(fields[12])
            ident = f'process:{path.name}:{fields[19]}'
            old = previous.get(ident)
            cpu = max(0, (ticks - old[0]) / os.sysconf('SC_CLK_TCK') / (now - old[1]) * 100 / cpu_count) if old and now > old[1] else 0
            next_state[ident] = (ticks, now)
            result.append({'id': ident, 'name': name, 'kind': 'agent', 'cpu': cpu,
                           'memory_mib': max(0, int(fields[21])) * os.sysconf('SC_PAGE_SIZE') / 1048576,
                           'units': [], 'unit_identity': {}, 'inferred': True, 'project': '',
                           'cores_used': cpu * cpu_count / 100, 'io_bps': 0})
        except (OSError, ValueError, IndexError):
            continue
        if len(result) >= 128:
            break
    return result, next_state


def process_rows(units, state, now, proc=Path('/proc')):
    result, alive = [], {}
    for unit in units:
        paths = [unit] + list(unit.glob('**/cgroup.procs'))[:128]
        pids = set()
        for path in paths:
            pids.update(read(path / 'cgroup.procs' if path.is_dir() else path, 65536).split())
        for pid in list(pids)[:512]:
            try:
                fields = read(proc / pid / 'stat').rsplit(')', 1)[1].split()
                ident = pid + ':' + fields[19]
                ticks = int(fields[11]) + int(fields[12])
                old = state.get(ident)
                cpu = max(0, (ticks - old[0]) / os.sysconf('SC_CLK_TCK') / (now - old[1]) * 100 / max(1, os.cpu_count() or 1)) if old and now > old[1] else 0
                alive[ident] = (ticks, now)
                result.append({'id': ident, 'pid': pid, 'name': read(proc / pid / 'comm', 256),
                               'cpu': cpu, 'memory_mib': max(0, int(fields[21])) * os.sysconf('SC_PAGE_SIZE') / 1048576})
            except (ValueError, IndexError, OSError):
                continue
    state.clear()
    state.update(alive)
    return sorted(result, key=lambda row: (-row['cpu'], -row['memory_mib']))[:128]


def bootstrap():
    """One-time upgrade of our own legacy unit; never touch another service."""
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    unit = config / 'systemd/user/omarchy-resource-usage.service'
    source = Path(__file__).resolve()
    if unit.exists():
        text = unit.read_text()
        installed = config / 'omarchy/plugins/lucas.resource-usage/collector.py'
        if source != installed.resolve() or 'Description=Resource usage and one-hour history for the Omarchy bar' not in text or str(source) not in text:
            raise ValueError('Legacy collector unit is customized; disable it before enabling the native collector')
        subprocess.run(['systemctl', '--user', 'disable', '--now', unit.name], check=True, timeout=5, stdout=subprocess.DEVNULL)
        backup = state_dir() / 'legacy-service.unit'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_text(text)
        unit.unlink()
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=5)
    link = Path.home() / '.local/bin/vitals-run'
    if not link.exists() and not link.is_symlink():
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(source.parent / 'bin/vitals-run')


class Backend:
    def __init__(self):
        self.settings, self.warning = load_settings()
        self.history = History(state_dir() / 'history.sqlite3', self.settings['retentionDays'], self.settings['storageMiB'])
        self.history.migrate(STATE)
        self.hardware = Hardware()
        self.incidents = Incidents()
        self.previous = cpu_times()
        self.app_state, self.inferred_state, self.children_state = {}, {}, {}
        self.inferred, self.clients = [], set()
        self.inferred_at = 0
        self.last_vm = {}
        self.last_time = time.time()
        self.sample = {}
        self.inspected = ''
        self.last_maintenance = 0

    def emit(self, kind, **data):
        encoded = json.dumps(dict(type=kind, **data), allow_nan=False, separators=(',', ':'))
        if len(encoded) > 2 * 1024 * 1024:
            raise ValueError('Collector response exceeds its size limit')
        print(encoded, flush=True)

    def tick(self):
        now, mono = time.time(), time.monotonic()
        current = cpu_times()
        gap = now < self.last_time or now - self.last_time > 30
        cpu = utilization(self.previous['cpu'], current['cpu']) if not gap else None
        if gap:
            self.history.event(uuid.uuid4().hex, now, 'gap', {'message': 'Collection resumed after a clock change or sampling gap', 'previous_time': self.last_time})
        self.previous = current
        memory = {}
        for line in read('/proc/meminfo', 32768).splitlines():
            fields = line.split()
            if len(fields) >= 2:
                memory[fields[0].rstrip(':')] = int(fields[1])
        total = memory['MemTotal']
        used = total - memory['MemAvailable']
        ps = pressure()
        if gap:
            self.app_state.clear()
        apps, agents = app_snapshot(self.app_state, mono, cpu_count=max(1, len(current) - 1), detailed=bool(self.clients))
        if len(apps) > 512:
            apps = apps[:512]
            self.warning = 'Showing the 512 busiest scopes; attribution is limited.'
        if self.settings['inferredAgents'] and mono - self.inferred_at >= 10:
            self.inferred, self.inferred_state = inferred_agents(self.inferred_state, mono, cpu_count=max(1, len(current) - 1))
            self.inferred_at = mono
        if not self.settings['inferredAgents']:
            self.inferred = []
        hw = self.hardware.snapshot(mono, detailed=bool(self.clients))
        vm = {}
        for line in read('/proc/vmstat', 32768).splitlines():
            key, value = line.split()
            if key in ('pswpin', 'pswpout'):
                vm[key] = int(value)
        dt = now - self.last_time
        values = {'cpu': cpu, 'ram': used / total * 100, 'temperature': temperature(),
                  'memory_pressure': ps['memory'].get('some'), 'cpu_pressure': ps['cpu'].get('some'),
                  'io_pressure': ps['io'].get('some'), 'memory_full': ps['memory'].get('full'),
                  'available_gib': memory['MemAvailable'] / 1048576,
                  'swap_gib': (memory.get('SwapTotal', 0) - memory.get('SwapFree', 0)) / 1048576}
        for key in ('pswpin', 'pswpout'):
            values[key] = max(0, vm.get(key, 0) - self.last_vm[key]) * os.sysconf('SC_PAGE_SIZE') / dt if key in self.last_vm and dt > 0 and not gap else None
        self.last_vm = vm
        followed_network = [n for n in hw['network'] if n['name'] == hw['network_primary']]
        for name, items, field in (('rx', followed_network, 'rx'), ('tx', followed_network, 'tx'),
                                   ('disk_read', hw['disks'], 'read'), ('disk_write', hw['disks'], 'write')):
            valid = [item[field] for item in items if item.get(field) is not None]
            values[name] = sum(valid) if valid else None
        valid_gpu = [g['usage'] for g in hw['gpus'] if g['usage'] is not None]
        values['gpu'] = max(valid_gpu) if valid_gpu else None
        contributions = [dict(id=a['kind'] + ':' + a['id'], name=a['name'], kind=a['kind'],
                              project=a['project'], project_id=a['project_id'], cpu=a['cpu'],
                              memory_mib=a['memory_mib'], io_bps=a['io_bps']) for a in apps]
        self.history.add(now, values, contributions)
        for incident in self.incidents.update(dict(values, time=now), self.settings['sensitivity']):
            self.history.event(incident['id'], incident['time'], 'incident', incident)
            if self.settings['notifications'] and incident['status'] == 'Active' and not incident.get('_notified'):
                # The active record owns deduplication; changing a peak must not notify again.
                active = self.incidents.active.get(incident['resource'])
                if active and not active.get('_notified'):
                    try:
                        bounded(['notify-send', '--app-name=Omarchy Vitals', 'Resource pressure', incident['message']], timeout=.5)
                    except OSError:
                        pass
                    active['_notified'] = True
        consume(self.history, now)
        if not next((state_dir() / 'inbox').glob('*.json'), None):
            self.history.reconcile_jobs(now, {u for a in apps for u in a['units']})
        self.last_time = now
        if now - self.last_maintenance > 60:
            self.history.maintain(now)
            self.last_maintenance = now
        children = []
        inspected = next((a for a in apps if a['id'] == self.inspected), None)
        if inspected and self.clients:
            paths = {p.name: p for p in find_units(CGROUP_ROOT)}
            children = process_rows([paths[u] for u in inspected['units'] if u in paths], self.children_state, mono)
        self.sample = dict(values, time=now, apps=apps, inferred=self.inferred, agents=agents,
                           used_gib=used / 1048576, total_gib=total / 1048576,
                           hardware=hw, incidents=list(self.incidents.active.values()), children=children,
                           inspected=self.inspected, warning=self.warning, gap=gap)
        # Retain a small live file for scripts; history is queried on demand.
        atomic_json(LIVE, self.sample)
        self.emit('sample', sample=self.sample)

    def action(self, request):
        app = next((a for a in self.sample.get('apps', []) if a['id'] == request.get('id') and a['kind'] == request.get('kind')), None)
        if not app or request.get('identities') != app['unit_identity']:
            raise ValueError('App changed since selection; select it again')
        action = request.get('action')
        operations = {'calm': ['set-property', '--runtime'], 'uncalm': ['set-property', '--runtime'],
                      'freeze': ['freeze'], 'thaw': ['thaw']}
        if action not in operations:
            raise ValueError('Unsupported action')
        paths = {p.name: p for p in find_units(CGROUP_ROOT)}
        done, error = [], ''
        for unit in app['units']:
            path = paths.get(unit)
            if not path or str(path.stat().st_ino) != app['unit_identity'].get(unit) or not classify_unit(unit):
                error = 'Scope exited or changed; remaining actions cancelled'
                break
            command = ['systemctl', '--user'] + operations[action] + [unit]
            if action in ('calm', 'uncalm'):
                command.append('CPUWeight=20' if action == 'calm' else 'CPUWeight=100')
            result = subprocess.run(command, capture_output=True, text=True, timeout=3)
            if result.returncode:
                error = result.stderr[:512] or f'systemctl exited {result.returncode}'
                break
            done.append(unit)
        now = time.time()
        event = {'name': app['name'], 'action': action, 'completed_units': done,
                 'project': app.get('project', ''), 'session_id': app.get('session_id', ''),
                 'error': error, 'message': f'{action}: ' + ((app['project'] + ' / ') if app.get('project') else '') + app['name'],
                 'before_time': self.sample.get('time'), 'before': {
                     k: self.sample.get(k) for k in ('cpu', 'memory_pressure', 'cpu_pressure', 'io_pressure')}}
        self.history.event(uuid.uuid4().hex, now, 'action', event)
        if error:
            raise ValueError(error)

    def command(self, request):
        if not isinstance(request, dict):
            raise ValueError('Expected a command object')
        op = request.get('op')
        if op == 'visible':
            client = str(request.get('client', 'default'))[:100]
            self.clients.add(client) if request.get('open') else self.clients.discard(client)
        elif op == 'settings':
            if 'changes' in request:
                if not isinstance(request['changes'], dict):
                    raise ValueError('Expected a settings patch')
                settings = validate(dict(self.settings, **request['changes']))
            else:
                settings = validate(request['settings'])
            atomic_json(state_dir() / 'settings.json', settings)
            self.settings = settings
            if self.warning.startswith('Invalid saved preferences'):
                self.warning = ''
            self.history.retention, self.history.budget_mib = settings['retentionDays'], settings['storageMiB']
            self.emit('settings', settings=settings)
            self.history.maintain(time.time())
        elif op == 'history':
            span = request.get('range', 3600)
            if type(span) is not int or span not in (3600, 86400, 604800, 2592000):
                raise ValueError('Unsupported history range')
            end = time.time()
            self.emit('history', range=span, **self.history.query(end - span, end))
        elif op == 'detail':
            start, end = request['start'], request['end']
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)) or not 0 < end - start <= 604800:
                raise ValueError('Invalid history interval')
            self.emit('detail', detail=self.history.detail(start, end))
        elif op == 'inspect':
            self.inspected = str(request.get('id', ''))[:256]
            self.children_state.clear()
        elif op == 'action':
            self.action(request)
            self.emit('action', ok=True)
        elif op == 'status':
            self.emit('settings', settings=self.settings)
        else:
            raise ValueError('Unknown collector command')


def run(serve=False, migrate=False):
    os.umask(0o077)
    if migrate:
        bootstrap()
    runtime_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime_dir() / 'collector.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another Vitals collector is already running')
        backend = Backend()
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        backend.emit('settings', settings=backend.settings)
        due, buffer = time.monotonic() + 1, bytearray()
        if serve:
            os.set_blocking(sys.stdin.fileno(), False)
        try:
            while not stopping:
                now = time.monotonic()
                if now >= due:
                    try:
                        backend.tick()
                    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                        backend.emit('error', error=str(exc)[:512])
                    on_battery = any(b['status'] == 'Discharging' for b in backend.sample.get('hardware', {}).get('batteries', []))
                    due = time.monotonic() + interval(backend.settings, bool(backend.clients), bool(backend.incidents.active), on_battery)
                timeout = max(0, due - time.monotonic())
                if not serve:
                    time.sleep(min(timeout, .5))
                    continue
                ready, _, _ = select.select([sys.stdin], [], [], min(timeout, .5))
                if ready:
                    chunk = os.read(sys.stdin.fileno(), 16384)
                    if not chunk:
                        break  # Owner disappeared; do not orphan a collector.
                    buffer.extend(chunk)
                    if len(buffer) > 65536:
                        raise ValueError('Collector command exceeds 64 KiB')
                    while b'\n' in buffer:
                        line, _, rest = buffer.partition(b'\n')
                        buffer = bytearray(rest)
                        try:
                            backend.command(json.loads(line))
                            due = min(due, time.monotonic() + .1)
                        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                            backend.emit('error', error=str(exc)[:512])
        finally:
            backend.history.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help='Stream JSON and accept commands on stdin')
    parser.add_argument('--migrate', action='store_true', help='Retire our legacy service and link vitals-run')
    args = parser.parse_args()
    run(args.serve, args.migrate)
