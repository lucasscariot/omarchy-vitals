#!/usr/bin/env python3
"""Two-second live metrics, ten-second samples, a rolling hour of history."""
import json
import math
import os
from pathlib import Path
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
        write_json(LIVE, dict(point, cores=cores, history=history,
                             used_gib=used / 1048576, total_gib=memory['MemTotal'] / 1048576,
                             text=f'CPU {cpu:.0f}%  RAM {ram:.0f}%  TEMP {temp_text}'))
        if now - last_save >= 30:
            write_json(STATE, history)
            last_save = now
    write_json(STATE, history)


if __name__ == '__main__':
    run()
