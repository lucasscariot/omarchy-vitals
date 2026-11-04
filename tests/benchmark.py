"""Measure a closed collector in private state; include reaped helper CPU time."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def usage(pid):
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    ticks = sum(int(stat[i]) for i in (11, 12, 13, 14))
    status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    return ticks / os.sysconf('SC_CLK_TCK'), int(status['VmHWM'].split()[0]) / 1024


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    if not 5 <= duration <= 300:
        raise SystemExit('Choose a duration from 5 to 300 seconds')
    with tempfile.TemporaryDirectory(prefix='vitals-benchmark-') as tmp:
        env = dict(os.environ, XDG_STATE_HOME=tmp + '/state', XDG_RUNTIME_DIR=tmp + '/run')
        Path(env['XDG_RUNTIME_DIR']).mkdir(mode=0o700)
        proc = subprocess.Popen([sys.executable, str(ROOT / 'collector.py'), '--serve'], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        buffer = bytearray()
        started = None
        first_cpu, peak, samples = 0, 0, 0
        deadline = time.monotonic() + duration + 10
        try:
            while time.monotonic() < deadline:
                for key, _ in selector.select(.5):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError('Collector exited during benchmark')
                    buffer.extend(chunk)
                    while b'\n' in buffer:
                        line, _, rest = buffer.partition(b'\n')
                        buffer = bytearray(rest)
                        message = json.loads(line)
                        if message['type'] == 'error':
                            raise RuntimeError(message['error'])
                        if message['type'] == 'sample':
                            samples += 1
                            if started is None:
                                started = time.monotonic()
                                first_cpu, peak = usage(proc.pid)
                if started is not None:
                    cpu, memory = usage(proc.pid)
                    peak = max(peak, memory)
                    elapsed = time.monotonic() - started
                    if elapsed >= duration:
                        result = {'duration_seconds': round(elapsed, 2), 'samples': samples,
                                  'cpu_percent_one_core_including_reaped_helpers': round((cpu - first_cpu) / elapsed * 100, 3),
                                  'collector_peak_rss_mib': round(peak, 2)}
                        print(json.dumps(result, indent=2))
                        return
            raise RuntimeError('Collector never produced a sample')
        finally:
            selector.close()
            proc.stdin.close()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
            proc.stdout.close(); proc.stderr.close()


if __name__ == '__main__':
    main()
