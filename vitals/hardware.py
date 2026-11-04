"""Optional hardware telemetry. Direct kernel reads, bounded helpers, no root."""
import os
import math
import json
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time


def read(path, limit=4096):
    try:
        with Path(path).open() as source:
            return source.read(limit).strip()
    except (OSError, ValueError):
        return ''


def number(path, divisor=1):
    try:
        value = float(read(path)) / divisor
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def bounded(argv, timeout=1, limit=65536):
    """Cap output before buffering, and reap descendants even on a timeout."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=dict(os.environ, LC_ALL='C'))
    output = bytearray()
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while time.monotonic() < deadline:
            for key, _ in selector.select(max(0, deadline - time.monotonic())):
                chunk = os.read(key.fileobj.fileno(), min(8192, limit + 1 - len(output)))
                if not chunk:
                    return output.decode(errors='replace') if proc.wait(timeout=.2) == 0 else ''
                output.extend(chunk)
                if len(output) > limit:
                    return ''
        return ''
    finally:
        selector.close()
        proc.stdout.close()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            pass  # A kernel-blocked helper cannot hold up the collector.


def pressure(root=Path('/proc/pressure')):
    result = {}
    for resource in ('cpu', 'memory', 'io'):
        values = {}
        for line in read(root / resource).splitlines():
            fields = line.split()
            try:
                parts = dict(p.split('=', 1) for p in fields[1:])
                value = float(parts['avg10'])
                if math.isfinite(value) and 0 <= value <= 100:
                    values[fields[0]] = value
            except (ValueError, KeyError, IndexError):
                continue
        result[resource] = values
    return result


def cgroup_io(path):
    counts = {'read_bytes': 0, 'write_bytes': 0}
    try:
        with (Path(path) / 'io.stat').open() as source:
            content = source.read(65537)
        if len(content) > 65536:
            raise ValueError('Oversized I/O counters')
    except (OSError, ValueError):
        return {'read_bytes': None, 'write_bytes': None}
    for line in content.splitlines():
        try:
            parts = dict(p.split('=', 1) for p in line.split()[1:])
            counts['read_bytes'] += int(parts.get('rbytes', 0))
            counts['write_bytes'] += int(parts.get('wbytes', 0))
        except ValueError:
            continue
    return counts


def local_volumes(mountinfo):
    volumes = []
    for line in read(mountinfo, 131072).splitlines():
        try:
            before, after = line.split(' - ', 1)
            fields, kind = before.split(), after.split()[0]
            mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])
            if kind not in ('ext4', 'ext3', 'xfs', 'btrfs', 'vfat', 'exfat', 'f2fs', 'zfs'):
                continue
            if len(volumes) >= 32:
                break
            try:
                stat = os.statvfs(mount)
                volumes.append({'name': mount, 'total': stat.f_blocks * stat.f_frsize,
                                'available': stat.f_bavail * stat.f_frsize})
            except OSError:
                volumes.append({'name': mount, 'total': None, 'available': None})
        except (ValueError, IndexError):
            continue
    return volumes


class Hardware:
    def __init__(self, sys_root=Path('/sys'), proc_root=Path('/proc')):
        self.sys = Path(sys_root)
        self.proc = Path(proc_root)
        self.previous = {}
        self.inventory_at = 0
        self.sensors = []
        self.gpus = []
        self.power = []
        self.gpu_cache = {}
        self.card_cache = {}
        self.nvidia_at = 0
        self.volumes = []
        self.volumes_at = 0
        self.volumes_stale = False

    def rate(self, key, value, now):
        old = self.previous.get(key)
        self.previous[key] = (value, now)
        if old is None or now <= old[1] or now - old[1] > 60 or value < old[0]:
            return None
        return (value - old[0]) / (now - old[1])

    def discover(self, now):
        if now - self.inventory_at < 60 and self.inventory_at:
            return
        self.inventory_at = now
        self.sensors = list((self.sys / 'class/hwmon').glob('hwmon*'))[:128]
        self.gpus = [p for p in (self.sys / 'class/drm').glob('card[0-9]*') if re.fullmatch(r'card\d+', p.name)][:16]
        self.power = list((self.sys / 'class/power_supply').glob('*'))[:32]

    def snapshot(self, now, detailed=True):
        self.discover(now)
        net = []
        for line in read(self.proc / 'net/dev', 65536).splitlines()[2:]:
            try:
                name, data = line.split(':', 1)
                name = name.strip()
                if name == 'lo':
                    continue
                fields = data.split()
                net.append({'name': name, 'rx': self.rate('rx:' + name, int(fields[0]), now),
                            'tx': self.rate('tx:' + name, int(fields[8]), now)})
            except (ValueError, IndexError):
                continue
        routes = []
        for line in read(self.proc / 'net/route', 32768).splitlines()[1:]:
            fields = line.split()
            try:
                if fields[1] == '00000000' and int(fields[3], 16) & 1:
                    routes.append((int(fields[6]), fields[0]))
            except (ValueError, IndexError):
                continue
        names = {n['name'] for n in net}
        primary = next((name for _, name in sorted(routes) if name in names), None)
        if primary is None:
            primary = next((n['name'] for n in net if (self.sys / 'class/net' / n['name'] / 'device').exists()), net[0]['name'] if net else '')
        disks = []
        for line in read(self.proc / 'diskstats', 65536).splitlines():
            fields = line.split()
            if len(fields) < 14:
                continue
            name = fields[2]
            # Whole physical devices, so partitions are not counted twice.
            if not (self.sys / 'block' / name / 'device').exists():
                continue
            try:
                disks.append({'name': name, 'read': self.rate('dr:' + name, int(fields[5]) * 512, now),
                              'write': self.rate('dw:' + name, int(fields[9]) * 512, now)})
            except ValueError:
                continue
        # Probe space separately so a stalled local drive cannot stall live metrics.
        if detailed and now - self.volumes_at >= 30:
            self.volumes_at = now
            try:
                output = bounded([sys.executable, '-B', str(Path(__file__).resolve()), '--volumes', str(self.proc / 'self/mountinfo')], timeout=.5)
                self.volumes = json.loads(output)
                self.volumes_stale = False
            except (OSError, ValueError, subprocess.SubprocessError):
                self.volumes_stale = True
        fans, temperatures, watts = [], [], []
        for chip in self.sensors:
            driver = read(chip / 'name')
            if driver in ('amdgpu', 'nouveau', 'i915', 'xe'):
                continue  # GPU telemetry has a separate suspend-aware cadence below.
            for path in list(chip.glob('fan*_input'))[:32]:
                fans.append({'name': driver + ' ' + (read(path.with_name(path.name.replace('_input', '_label'))) or path.stem),
                             'rpm': number(path)})
            for path in list(chip.glob('temp*_input'))[:32]:
                temperatures.append({'name': driver + ' ' + (read(path.with_name(path.name.replace('_input', '_label'))) or path.stem),
                                     'celsius': number(path, 1000)})
            for path in list(chip.glob('power*_average'))[:8]:
                value = number(path, 1e6)
                if value is not None:
                    watts.append({'name': driver, 'watts': value})
        # RAPL zones are reported individually; do not add nested domains together.
        for path in list((self.sys / 'class/powercap').glob('intel-rapl:*/energy_uj'))[:32]:
            energy = number(path)
            if energy is not None:
                value = self.rate('energy:' + str(path), energy, now)
                watts.append({'name': read(path.parent / 'name') or path.parent.name,
                              'watts': value / 1e6 if value is not None else None})
        batteries = []
        for supply in self.power:
            if read(supply / 'type') != 'Battery':
                continue
            draw = number(supply / 'power_now', 1e6)
            if draw is None:
                current, voltage = number(supply / 'current_now', 1e6), number(supply / 'voltage_now', 1e6)
                draw = abs(current * voltage) if current is not None and voltage is not None else None
            full, design = number(supply / 'energy_full'), number(supply / 'energy_full_design')
            batteries.append({'name': supply.name, 'percent': number(supply / 'capacity'),
                              'status': read(supply / 'status'), 'watts': draw,
                              'health': 100 * full / design if full is not None and design else None})
        gpu_data = []
        nvidia = {}
        awake_nvidia = [c for c in self.gpus if read(c / 'device/vendor') == '0x10de' and read(c / 'device/power/runtime_status') != 'suspended']
        # Do not run a global nvidia-smi query while any NVIDIA device is asleep.
        all_nvidia = [c for c in self.gpus if read(c / 'device/vendor') == '0x10de']
        if awake_nvidia and len(awake_nvidia) == len(all_nvidia) and now - self.nvidia_at >= 10:
            self.nvidia_at = now
            try:
                output = bounded(['nvidia-smi', '--query-gpu=pci.bus_id,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw', '--format=csv,noheader,nounits'])
                for line in output.splitlines()[:16]:
                    p = [v.strip() for v in line.split(',')]
                    if len(p) == 7:
                        def val(index):
                            try:
                                value = float(p[index])
                                return value if math.isfinite(value) and value >= 0 else None
                            except ValueError:
                                return None
                        nvidia[p[0].lower().split(':', 1)[-1]] = {'name': p[1], 'usage': val(2), 'memory_mib': val(3), 'total_mib': val(4), 'temperature': val(5), 'watts': val(6)}
                self.gpu_cache = nvidia
            except (OSError, subprocess.SubprocessError):
                self.gpu_cache = {}
        else:
            nvidia = self.gpu_cache if awake_nvidia and len(awake_nvidia) == len(all_nvidia) else {}
        for card in self.gpus:
            device = card / 'device'
            vendor = read(device / 'vendor')
            pci = device.resolve().name
            gpu = {'id': pci, 'name': {'0x1002': 'AMD', '0x8086': 'Intel', '0x10de': 'NVIDIA'}.get(vendor, 'GPU') + ' ' + pci,
                   'usage': None, 'memory_mib': None, 'total_mib': None, 'temperature': None, 'watts': None}
            if read(device / 'power/runtime_status') == 'suspended':
                gpu['state'] = 'Asleep'
            else:
                gpu['state'] = 'Awake'
                previous = self.card_cache.get(pci)
                if vendor != '0x10de' and read(device / 'power/control') == 'auto' and previous and now - previous[0] < 10:
                    gpu_data.append(dict(previous[1]))
                    continue
                gpu.update(nvidia.get(pci.split(':', 1)[-1].lower(), {}) if vendor == '0x10de' else {})
                if vendor != '0x10de':
                    gpu['usage'] = number(device / 'gpu_busy_percent')
                    gpu['memory_mib'] = number(device / 'mem_info_vram_used', 1048576)
                    gpu['total_mib'] = number(device / 'mem_info_vram_total', 1048576)
                    hwmon = next(iter((device / 'hwmon').glob('hwmon*')), None)
                    if hwmon:
                        gpu['temperature'] = number(hwmon / 'temp1_input', 1000)
                        gpu['watts'] = number(hwmon / 'power1_average', 1e6)
                self.card_cache[pci] = (now, dict(gpu))
            gpu_data.append(gpu)
        return {'network': net, 'network_primary': primary, 'disks': disks, 'volumes': self.volumes, 'volumes_stale': self.volumes_stale, 'fans': fans[:128],
                'temperatures': temperatures[:128], 'power': watts, 'batteries': batteries, 'gpus': gpu_data}


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--volumes':
    print(json.dumps(local_volumes(Path(sys.argv[2])), allow_nan=False))
