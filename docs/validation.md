# Validation of the resource/history expansion

Checked on 4 November 2026 against the installed Omarchy shell sources. The
installation's version file reports `4.0.0.alpha`; Quickshell reports `0.3.2`
(revision `2b4501a282689792b62e94f3fb30d8f512324fe6`). Python is 3.14.9.
This is an API check against that installation, not a release compatibility matrix.

## Automated checks

- Python unit/integration suite: collector normalization, app grouping, unique
  agent sessions, counter resets, stale scope rejection, history migration,
  rollups, extrema, sampling gaps, storage budgets, action observations,
  missing completion receipts, settings and legacy service migration.
- Launcher checks exercise actual exit codes, terminal inheritance, signal
  forwarding, short jobs and recording failures in temporary state directories.
- `omarchy plugin validate .` passes.
- `qmllint` with the installed shell import tree exits successfully. Its remaining
  notices concern the shell's dynamically typed `Style.font` fields. They are
  checked by rendering as well.
- `python3 tests/qml_smoke.py` renders Overview, Apps, Agents, Hardware, History,
  Timeline, Jobs and Settings without QML runtime errors. It uses synthetic
  historical/job fixtures, live read-only system readings and private XDG roots.

The offscreen renderer substitutes only `KeyboardPanel`'s compositor surface.
Real layer-shell placement, outside-click dismissal, multi-monitor focus and
desktop key routing still require an Omarchy desktop acceptance check. No real
desktop configuration or running applications were changed by these checks.

## Short performance measurement

`python3 tests/benchmark.py 15`, after the first sample:

| Measurement | Observed |
| --- | --- |
| Duration | 15.03 seconds |
| Samples, including initial | 2 |
| CPU, relative to one core | 0.067% |
| Collector peak resident memory | 24.5 MiB |

CPU accounting includes reaped helper CPU time. Memory is the collector's high
water RSS, not aggregate helper RSS. Collection used a private, fresh database
with the popup closed and the machine on battery. This short smoke measurement
does not establish performance across different hardware, large histories or
open detailed views. The benchmark script can repeat the measurement for up to
300 seconds.

## Remaining hardware checks

Fixtures exercise NVIDIA suspend avoidance, unavailable pressure/sensor fields,
network counter resets and helper time/output limits. Live readings on this
machine exercised AMD GPU, battery, CPU and other hwmon sensors. NVIDIA and Intel
machines, additional power domains and multiple physical monitors were not
available for live validation.
