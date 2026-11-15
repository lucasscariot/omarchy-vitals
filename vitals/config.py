"""Validated preferences and private XDG paths. No desktop settings are edited."""
import json
import math
import os
from pathlib import Path


def state_dir():
    return Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'omarchy/resource-usage'


def runtime_dir():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'omarchy-vitals'


DEFAULTS = {
    'modules': ['cpu', 'ram', 'temperature'], 'style': 'text', 'temperatureUnit': 'C',
    'refreshPolicy': 'adaptive', 'refreshSeconds': 2, 'retentionDays': 7,
    'storageMiB': 128, 'sensitivity': 'normal', 'notifications': False,
    'inferredAgents': True,
}
MODULES = ('cpu', 'ram', 'temperature', 'network', 'disk', 'gpu', 'fans', 'battery', 'power')
CHOICES = {'style': ('text', 'graph'), 'temperatureUnit': ('C', 'F'),
           'refreshPolicy': ('adaptive', 'fixed'), 'sensitivity': ('sensitive', 'normal', 'quiet')}


def validate(values):
    if not isinstance(values, dict):
        raise ValueError('Settings must be an object')
    out = dict(DEFAULTS, modules=list(DEFAULTS['modules']))
    for key, value in values.items():
        if key not in DEFAULTS:
            raise ValueError(f'Unknown setting: {key}')
        if key == 'modules':
            if not isinstance(value, list) or not 1 <= len(value) <= len(MODULES) or any(v not in MODULES for v in value) or len(set(value)) != len(value):
                raise ValueError('Choose at least one distinct bar module')
            out[key] = list(value)
        elif key in CHOICES:
            if value not in CHOICES[key]:
                raise ValueError(f'Invalid {key}')
            out[key] = value
        elif key in ('notifications', 'inferredAgents'):
            if type(value) is not bool:
                raise ValueError(f'{key} must be true or false')
            out[key] = value
        else:
            lo, hi = {'refreshSeconds': (1, 30), 'retentionDays': (1, 30), 'storageMiB': (16, 512)}[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not lo <= value <= hi or int(value) != value:
                raise ValueError(f'{key} must be an integer from {lo} to {hi}')
            out[key] = int(value)
    return out


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with temp.open('w') as output:
            os.chmod(temp, 0o600)
            json.dump(data, output, allow_nan=False, separators=(',', ':'))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_settings(path=None):
    path = path or state_dir() / 'settings.json'
    try:
        return validate(json.loads(Path(path).read_text())), ''
    except FileNotFoundError:
        return validate({}), ''
    except (OSError, ValueError, TypeError):
        return validate({}), 'Invalid saved preferences; using defaults. Save settings to replace them.'


def interval(settings, opened=False, incident=False, battery=False):
    if settings['refreshPolicy'] == 'fixed':
        return settings['refreshSeconds']
    return 2 if opened or incident else 10 if battery else 5
