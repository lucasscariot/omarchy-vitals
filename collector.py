#!/usr/bin/env python3
"""Two-second live metrics, ten-second samples, a rolling hour of history."""
import json
import math
import os
from pathlib import Path
import re
import signal
import time

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
        words = [w for w in (proc_root / best / 'cmdline').read_text().split('\0') if w][:2]
        if words:
            words[0] = os.path.basename(words[0]) or words[0]
            return ' '.join(words)[:60]
    except OSError:
        pass
    try:
        return (proc_root / best / 'comm').read_text().strip() or None
    except OSError:
        return None


def app_snapshot(state, now, root=None, proc_root=Path('/proc')):
    """Per-app and per-agent usage from systemd user cgroups. `state` carries usage between calls."""
    root = Path(CGROUP_ROOT if root is None else root)
    if not root.is_dir():
        state.clear()
        return [], None
    previous, previous_time = state.get('usage', {}), state.get('time')
    elapsed = now - previous_time if previous_time is not None else 0
    usage, apps, agent_units = {}, {}, []
    for path in find_units(root):
        kind, ident, display = classify_unit(path.name)
        current = read_usage(path)
        cpu = 0.0
        if current is not None:
            usage[str(path)] = current
            before = previous.get(str(path))
            if before is not None and elapsed > 0 and current >= before:
                cpu = (current - before) / (elapsed * 1e6) * 100
        memory = (read_int(path / 'memory.current', 0) or 0) / 1048576
        weight = read_int(path / 'cpu.weight')
        frozen = read_int(path / 'cgroup.freeze', 0) == 1
        calmed = weight is not None and weight < 100
        app = apps.setdefault((kind, ident), {'id': ident, 'name': display, 'kind': kind, 'cpu': 0.0,
                                              'mem': 0.0, 'units': [], 'frozen': False, 'calmed': False})
        app['cpu'] += cpu
        app['mem'] += memory
        app['units'].append(path.name)
        app['frozen'] = app['frozen'] or frozen
        app['calmed'] = app['calmed'] or calmed
        if kind == 'agent':
            agent_units.append((cpu, memory, path))
    state['usage'], state['time'] = usage, now
    ordered = sorted(apps.values(), key=lambda a: (-a['cpu'], -a['mem']))
    # Frozen or calmed apps stay listed past the top eight so Thaw/Uncalm remains reachable.
    ranked = ordered[:8] + [a for a in ordered[8:] if a['frozen'] or a['calmed']]
    out_apps = [{'id': a['id'], 'name': a['name'], 'kind': a['kind'], 'cpu': round(a['cpu'], 1),
                 'memory_mib': int(a['mem']), 'units': sorted(a['units']), 'frozen': a['frozen'],
                 'calmed': a['calmed']} for a in ranked]
    agent_units.sort(key=lambda u: (-u[0], -u[1]))
    jobs = []
    for cpu, memory, path in agent_units[:5]:
        kind, ident, display = classify_unit(path.name)
        jobs.append({'unit': path.name, 'name': 'herdr' if path.name.startswith('hc-') else display,
                     'cpu': round(cpu, 1), 'memory_mib': int(memory),
                     'command': busiest_command(path, proc_root)})
    agents = {'cpu': round(sum(u[0] for u in agent_units), 1),
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


def run():
    history = load_history(STATE, time.time())
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous = cpu_times()
    last_history = 0
    last_save = 0
    previous_time = time.time()
    app_state = {}
    while not stopping:
        time.sleep(2)
        now = time.time()
        current = cpu_times()
        if now - previous_time > 10 or now < previous_time:
            previous, previous_time = current, now
            continue
        cpu = utilization(previous['cpu'], current['cpu'])
        cores = [{'id': int(name[3:]), 'usage': utilization(previous.get(name, ticks), ticks)}
                 for name, ticks in current.items() if name != 'cpu']
        cores.sort(key=lambda c: c['id'])
        previous, previous_time = current, now
        memory = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        used = memory['MemTotal'] - memory['MemAvailable']
        ram = round(100 * used / memory['MemTotal'], 1)
        temp = temperature()
        point = {'time': now, 'cpu': cpu, 'ram': ram, 'temperature': temp}
        history = trim(history, now)
        if now - last_history >= 10:
            history.append(point)
            last_history = now
        temp_text = f'{temp:.0f}°C' if temp is not None else '—'
        try:
            apps, agents = app_snapshot(app_state, now)
        except Exception:
            apps, agents = [], None
        write_json(LIVE, dict(point, cores=cores, apps=apps, agents=agents, history=history,
                             used_gib=used / 1048576, total_gib=memory['MemTotal'] / 1048576,
                             text=f'CPU {cpu:.0f}%  RAM {ram:.0f}%  TEMP {temp_text}'))
        if now - last_save >= 30:
            write_json(STATE, history)
            last_save = now
    write_json(STATE, history)


if __name__ == '__main__':
    run()
