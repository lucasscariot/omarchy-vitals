#!/usr/bin/env python3
"""Install for the current user; no root privileges or Python packages needed."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess

PLUGIN_ID = 'lucas.resource-usage'
SERVICE = 'omarchy-resource-usage.service'
FILES = ('Panel.qml', 'HistoryChart.qml', 'collector.py', 'manifest.json',
         'install.py', 'omarchy-resource-usage.service.in', 'README.md', 'LICENSE', '.gitignore',
         'tests/test_plugin.py', 'bin/vitals-run', 'tests/test_launcher.py',
         'AppList.qml', 'tests/test_apps.py')


def bin_dir(config):
    explicit = os.environ.get('VITALS_BIN_DIR')
    if explicit:
        return Path(explicit)
    return Path.home() / '.local/bin'


def link_launcher(link, launcher):
    if link.is_symlink() or link.exists():
        if not (link.is_symlink() and link.resolve() == launcher.resolve()):
            return False  # Never replace a user's own file.
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(launcher)
    return True


def unlink_launcher(link, launcher):
    if link.is_symlink() and link.resolve() == launcher.resolve():
        link.unlink()


def systemd_argument(path):
    # systemd ExecStart is not a shell. Escape its own specifiers and quoting.
    value = str(path).replace('%', '%%').replace('$', '$$').replace('\\', '\\\\').replace('"', '\\"')
    return '"' + value + '"'


def configure_bar(path, remove=False):
    data = json.loads(path.read_text())
    layout = data.get('bar', {}).get('layout')
    if not isinstance(layout, dict) or not isinstance(layout.get('right'), list):
        raise ValueError('Expected an Omarchy shell.json with bar.layout.right')
    found = False
    for section, entries in layout.items():
        if not isinstance(entries, list):
            raise ValueError('Bar layout sections must be lists')
        updated = []
        for entry in entries:
            if isinstance(entry, dict) and entry.get('id') == PLUGIN_ID:
                found = True
                if not remove:
                    updated.append(entry)
            else:
                updated.append(entry)
        layout[section] = updated
    if not found and not remove:
        layout['right'].insert(0, {'id': PLUGIN_ID})
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true', help='Remove bar entry and service; keep source and history')
    parser.add_argument('--no-start', action='store_true', help='Write configuration without calling systemctl or restarting the shell')
    args = parser.parse_args()
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    shell = config / 'omarchy/shell.json'
    data = configure_bar(shell, args.uninstall)  # Validate before making changes.
    target = config / 'omarchy/plugins' / PLUGIN_ID
    unit = config / 'systemd/user' / SERVICE
    source = Path(__file__).resolve().parent
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_root = config / 'omarchy/backups' / ('resource-usage-' + stamp)
    backup_root.mkdir(parents=True)
    shutil.copy2(shell, backup_root / 'shell.json')
    if unit.exists():
        shutil.copy2(unit, backup_root / SERVICE)
    if args.uninstall:
        if not args.no_start:
            subprocess.run(['systemctl', '--user', 'disable', '--now', SERVICE], check=True)
        unit.unlink(missing_ok=True)
        unlink_launcher(bin_dir(config) / 'vitals-run', target / 'bin/vitals-run')
    else:
        target.mkdir(parents=True, exist_ok=True)
        if source != target.resolve():
            for name in FILES:
                if (target / name).exists():
                    (backup_root / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target / name, backup_root / name)
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, target / name)
        (target / 'bin/vitals-run').chmod(0o755)
        if not link_launcher(bin_dir(config) / 'vitals-run', target / 'bin/vitals-run'):
            print('Left existing ' + str(bin_dir(config) / 'vitals-run') + ' alone.')
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text((target / 'omarchy-resource-usage.service.in').read_text().replace('@COLLECTOR@', systemd_argument(target / 'collector.py')))
    temporary = shell.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(shell)
    if not args.no_start:
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        if not args.uninstall:
            subprocess.run(['systemctl', '--user', 'enable', SERVICE], check=True)
            subprocess.run(['systemctl', '--user', 'restart', SERVICE], check=True)
        subprocess.run(['omarchy', 'restart', 'shell'], check=True)
    print(('Uninstalled service and bar entry.' if args.uninstall else 'Installed ' + PLUGIN_ID + '.'))
    print('Backup: ' + str(backup_root))


if __name__ == '__main__':
    main()
