"""Tracked launch supervisor. Receipts survive short jobs and a stopped shell."""
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import uuid

from .config import atomic_json, runtime_dir, state_dir
from .hardware import bounded, cgroup_io, number, read


def project_info(cwd=None):
    cwd = Path(cwd or Path.cwd()).resolve()
    try:
        root = bounded(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'], timeout=.5).strip()
    except (OSError, subprocess.SubprocessError):
        root = ''
    path = Path(root) if root else cwd
    # Persist the project label and identity, never its absolute path or arguments.
    return {'project': path.name, 'project_id': hashlib.sha256(os.fsencode(path)).hexdigest()[:24]}


def own_cgroup(proc=Path('/proc'), cgroup=Path('/sys/fs/cgroup')):
    for line in read(proc / 'self/cgroup').splitlines():
        if line.startswith('0::'):
            relative = line[3:].lstrip('/')
            target = (cgroup / relative).resolve()
            if target.is_relative_to(cgroup.resolve()):
                return target
    return None


def counters(path):
    cpu = None
    for line in read(path / 'cpu.stat').splitlines():
        if line.startswith('usage_usec '):
            try:
                cpu = int(line.split()[1]) / 1e6
            except (ValueError, IndexError):
                pass
    return dict(cgroup_io(path), cpu_seconds=cpu, peak_memory_mib=number(path / 'memory.peak', 1048576))


def spool(kind, data):
    inbox = state_dir() / 'inbox'
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Cap disk use even if the shell has not been opened for a long time.
    paths = sorted(inbox.glob('*.json'), key=lambda p: p.name)
    for old in paths[:-999]:
        old.unlink(missing_ok=True)
    atomic_json(inbox / f'{time.time_ns()}-{data["id"]}-{kind}.json', dict(data, event=kind))


def supervise(command, label, ident, project=None):
    caller_umask = os.umask(0o077)
    started = time.time()
    group = own_cgroup()
    unit = group.name if group else None
    scoped = bool(unit and unit == f'agent-{label}-{ident}.scope')
    metadata = dict(project or project_info(), id=ident, label=label, name=label,
                    started=started, command=os.path.basename(command[0]), unit=unit if scoped else None)
    session_path = runtime_dir() / 'sessions' / (unit or ident)
    try:
        if scoped:
            atomic_json(session_path.with_suffix('.json'), metadata)
        spool('job_start', metadata)
    except OSError as exc:
        print(f'vitals-run: unable to record start: {exc}', file=sys.stderr)
    before = counters(group) if scoped else {}
    initial = time.monotonic()
    child = None

    def forward(sig, _frame):
        if child is not None:
            try:
                child.send_signal(sig)
            except ProcessLookupError:
                pass

    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGTERM, signal.SIGHUP)}
    previous[signal.SIGINT] = signal.signal(signal.SIGINT, lambda *_: None)
    error = ''
    try:
        try:
            child = subprocess.Popen(command, umask=caller_umask)
            code = child.wait()
        except OSError as exc:
            code, error = 127, str(exc)
            print(f'vitals-run: {exc}', file=sys.stderr)
        after = counters(group) if scoped else {}
        rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = after.get('cpu_seconds')
        remaining = set(read(group / 'cgroup.procs').split()) - {str(os.getpid())} if scoped else set()
        complete = scoped and not remaining and cpu is not None and after.get('peak_memory_mib') is not None
        report = dict(metadata, ended=time.time(), duration=time.monotonic() - initial,
                      exit_code=code if code >= 0 else 128 - code, signal=-code if code < 0 else None,
                      complete=complete, accounting='scope' if scoped else 'child resource usage',
                      descendants_running=bool(remaining),
                      cpu_seconds=max(0, cpu - before.get('cpu_seconds', 0)) if cpu is not None and before.get('cpu_seconds') is not None else rusage.ru_utime + rusage.ru_stime,
                      peak_memory_mib=after.get('peak_memory_mib') if scoped else rusage.ru_maxrss / 1024,
                      read_bytes=max(0, after['read_bytes'] - before['read_bytes']) if scoped and after.get('read_bytes') is not None and before.get('read_bytes') is not None else None,
                      write_bytes=max(0, after['write_bytes'] - before['write_bytes']) if scoped and after.get('write_bytes') is not None and before.get('write_bytes') is not None else None,
                      error=error)
        try:
            spool('job_end', report)
        except OSError as exc:
            print(f'vitals-run: unable to record completion: {exc}', file=sys.stderr)
        return report['exit_code']
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if scoped:
            try:
                session_path.with_suffix('.json').unlink(missing_ok=True)
            except OSError:
                pass


def consume(history, now):
    """Import at most 100 bounded receipts per tick; one database writer."""
    inbox = state_dir() / 'inbox'
    imported = 0
    for path in sorted(inbox.glob('*.json'))[:100]:
        try:
            if path.stat().st_size > 16384:
                raise ValueError('Oversized job receipt')
            data = json.loads(path.read_text())
            ident, kind = data['id'], data.pop('event')
            if not isinstance(ident, str) or len(ident) > 100 or kind not in ('job_start', 'job_end'):
                raise ValueError('Invalid job receipt')
            if any(not isinstance(data.get(key), str) or len(data[key]) > 512 for key in ('label', 'project', 'project_id')):
                raise ValueError('Invalid job metadata')
            if data.get('unit') is not None and (not isinstance(data['unit'], str) or len(data['unit']) > 256):
                raise ValueError('Invalid job scope')
            if type(data.get('started')) not in (float, int) or not math.isfinite(data['started']):
                raise ValueError('Invalid job start')
            timestamp = data['started'] if kind == 'job_start' else data['ended']
            if not isinstance(timestamp, (int, float)) or not now - history.retention * 86400 <= timestamp <= now + 60:
                raise ValueError('Expired or invalid receipt')
            if kind == 'job_end':
                for key in ('duration', 'cpu_seconds', 'peak_memory_mib', 'read_bytes', 'write_bytes'):
                    value = data.get(key)
                    if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or value < 0):
                        raise ValueError('Invalid job counter')
                if type(data.get('complete')) is not bool:
                    raise ValueError('Invalid accounting status')
                history.report(data)
            history.event(ident + ':' + kind, timestamp, kind, data)
            imported += 1
        except (OSError, ValueError, KeyError, TypeError):
            # Preserve malformed input for diagnosis without retrying it every tick.
            try:
                path.rename(path.with_suffix('.invalid'))
            except FileNotFoundError:
                pass  # A concurrently pruned receipt does not break live readings.
            continue
        path.unlink(missing_ok=True)
    return imported
