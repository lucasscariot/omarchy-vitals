# Omarchy Vitals

A CPU, memory, and temperature widget for the Omarchy bar. Click it to open
a native panel with all logical CPUs and rolling one-hour history charts.
The panel follows your Omarchy theme, including its fonts, corners, and popup
transparency. Frost requires your Hyprland layer blur configuration.

## Features

- Live CPU, RAM, and CPU temperature in the bar, updated every two seconds.
- Usage meters for every online logical CPU (hardware thread).
- One-hour CPU, memory, and temperature charts with average and sampled peak.
- Ten-second history samples, saved every 30 seconds and on clean shutdown.
- Native popup positioning, outside-click dismissal, and Escape to close.
- Background collection while the popup is closed; no network access.

## Requirements

- Omarchy with its Quickshell-based shell and `qs.Ui.KeyboardPanel` plugin API.
  Tested on the Omarchy v4 desktop installed in September 2026; older Waybar
  installations are unsupported. These shell APIs can change between releases.
- Linux, Python 3.10+, systemd user services, and an active graphical session.
- Read access to `/proc/stat`, `/proc/meminfo`, and optional CPU temperature
  sensors under `/sys`. No root access or pip dependencies are needed.

## Install

Clone or download this repository, then run from its directory:

```sh
git clone https://github.com/lucasscariot/omarchy-vitals.git
cd omarchy-vitals
python3 install.py
```

The installer copies the plugin into
`$XDG_CONFIG_HOME/omarchy/plugins/lucas.resource-usage` (default `~/.config`),
installs its user service, and adds the widget to the right side of the bar.
An existing entry keeps its position. It backs up the affected configuration,
starts the collector, and restarts the shell. Existing plugin settings for this
widget are replaced by its native entry; other widgets are preserved.

The directory and manifest ID must remain `lucas.resource-usage`.
This stable internal ID preserves existing installations; the project and
display name are Omarchy Vitals.
For an update, pull the repository and rerun the installer.

`python3 install.py --no-start` writes files without starting services or
restarting the shell, for offline setup. Afterward, run:

```sh
systemctl --user daemon-reload
systemctl --user enable --now omarchy-resource-usage.service
omarchy restart shell
```

## Data and interpretation

CPU use comes from deltas in `/proc/stat`; RAM is total minus available memory,
so reclaimable cache is not counted as used. CPU meters represent logical CPUs,
not separate physical cores.

Temperature prefers AMD `k10temp`/`zenpower` package readings or Intel
`coretemp` package readings, falling back to core readings and recognized CPU/SoC
thermal zones. Multiple package sensors use the hottest reading. Unknown or
unreadable sensors display `—`; GPU and disk temperatures are not substituted.

Charts begin collecting at installation. CPU history samples reflect a
two-second measurement taken every ten seconds, so very short spikes can be
missed. Average and peak refer to available samples, not a complete continuous
measurement. CPU/RAM scales are 0–100%; temperature has a labeled dynamic scale.
Sleep and shutdown leave gaps. No historical data is invented.

Live data: `$XDG_RUNTIME_DIR/omarchy-resource-usage.json`.
History: `$XDG_STATE_HOME/omarchy/resource-usage/history.json`
(default `~/.local/state`). Only the most recent hour is loaded and retained.
On an abrupt shutdown, up to 30 seconds of unsaved history can be lost.

## Uninstall

```sh
python3 install.py --uninstall
```

This removes the bar entry and disables/removes the service. It keeps the
plugin source, configuration backups, and history so nothing personal is
silently deleted. You can remove those directories afterward if desired.

## Troubleshooting

```sh
systemctl --user status omarchy-resource-usage.service
journalctl --user -u omarchy-resource-usage.service -n 30
omarchy-shell lucas.resource-usage open
```

The first live reading takes about two seconds. A missing temperature alone
does not prevent CPU, RAM, or history collection.

## Development

```sh
python3 -m unittest discover -s tests -v
```

The collector uses the Python standard library. Tests use synthetic sensor
directories and temporary installation roots; they do not change desktop
settings or start services. Visual validation still requires an Omarchy session.

Licensed under the MIT license.
