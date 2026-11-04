# Omarchy Vitals

CPU, memory and temperature in the Omarchy bar, with app and agent readings,
optional hardware modules, local history and completed-job reports.

## Install

```sh
omarchy plugin add https://github.com/lucasscariot/omarchy-vitals.git --enable
```

The native plugin service starts one collector for all monitors. No separate
installer, root access or pip packages are required. Collection continues while
the popup is closed. Disabling/removing the plugin or stopping the shell stops
collection; the next session leaves a gap rather than inventing readings.

Update and remove with the normal plugin commands:

```sh
omarchy plugin update lucas.resource-usage
omarchy plugin remove lucas.resource-usage
```

The plugin ID remains `lucas.resource-usage` for existing installations. The
first native startup retires the old `omarchy-resource-usage.service`, saves its
unit under the Vitals state directory, imports the old JSON history once, and
preserves the bar position/options. A customized legacy service is left alone:
disable it yourself before starting the native collector. The original JSON
history is retained. Historical CPU totals remain comparable; app percentages
now use whole-machine capacity.

The service links `~/.local/bin/vitals-run` to its launcher if that path is free;
it never replaces an unrelated file. Removing the plugin can leave that dangling
link, which can be removed manually. `install.py` remains available for local
checkouts and backs up configuration before changing it. `--no-start` installs
files without running desktop commands. It no longer creates a systemd service.

## Readings and views

Click the bar to open the native popup. Escape or a click outside closes it.
The popup follows Omarchy's theme, fonts, borders and transparency.

| View | Contents |
| --- | --- |
| Overview | CPU, RAM, temperature, memory headroom, swap activity, pressure and leading apps. |
| Apps | All observed user app scopes; search, CPU/memory/I/O sorting, keyboard controls and child-process details. |
| Agents | Separate tracked sessions with project labels and session IDs, including their builds and tests. |
| Hardware | Network rates, disk I/O and space, detected GPUs, temperatures, fans, battery and available power domains. |
| History | Selectable CPU, memory, temperature, pressure, network, disk and GPU charts. Click an interval for observed CPU/memory/block-I/O contributors. |
| Timeline | Tracked starts/exits, sustained pressure, collection gaps and user actions. Actions include observed conditions before and after, when available. |
| Jobs | Recent completed tracked commands and comparisons with the previous complete run of the same project and label. |
| Settings | Bar modules/order/style, units, refresh policy, retention, storage and alert preferences. |

CPU percentages use the machine's logical CPUs as the denominator: four busy
cores on an eight-core machine show 50%, with “4 cores used” in app details.
RAM is total minus available memory, so reclaimable cache is excluded. CPU
package sensors are preferred; GPU or disk temperatures never substitute for CPU
temperature. A dash means unavailable. First app/process readings need a second
sample before a CPU delta is known. Scope memory includes its kernel-accounted
memory, including page cache, and does not necessarily sum to the system RAM
figure.

Apps are grouped using systemd user scopes. System processes and processes
outside recognizable app scopes are not an exhaustive task-manager listing;
**Open btop** provides a full process view. The live scope list is limited to
512 rows, with a notice if truncated. Detailed child views show at most 128
processes. Selection stays attached to the app identity while sorting changes.
Tab moves between controls; **Keyboard**, then Up/Down selects rows, C toggles
Calm/Restore, and F toggles Freeze/Thaw. Search fields retain normal text editing.

**Calm** sets relative CPU priority to `CPUWeight=20`; **Restore** sets it to 100.
This is a scheduling preference, not a CPU cap. **Freeze** pauses the whole scope,
including audio and calls; **Thaw** resumes it. Actions are restricted to observed
app/agent scopes and recheck their identities before execution. Partial failures
are shown and recorded. Frozen/calmed apps stay reachable in the compact list.

## Track agents and jobs

```sh
vitals-run -- codex
vitals-run -- claude
vitals-run --name build -- cargo test
```

Each launch gets its own systemd scope and session identity. Its children stay
attributed to that scope unless they deliberately escape it, for example by
starting a separate systemd service. Project identity comes from the local Git
root, falling back to the working directory. Stored metadata contains the
project basename and a hash of its path, not the absolute path or command
arguments. Give repeated jobs the same explicit `--name` for comparisons.

Optional aliases can be reviewed with:

```sh
vitals-run --shell-init
```

Add the printed aliases to your shell configuration if wanted. No shell
configuration is edited automatically. The launcher can also be called directly
from `~/.config/omarchy/plugins/lucas.resource-usage/bin/vitals-run`.

Unwrapped `claude`, `codex`, `opencode` and `gemini` root processes can be shown as
**inferred**. This is best-effort discovery, does not claim their whole process
tree, is excluded from tracked totals, and offers no scope actions. Disable this
in Settings if unwanted. Agents hosted by another executable may not be inferred.

The launcher preserves the command's terminal, working directory, arguments,
exit code and signals. It records resource counters before its scope disappears,
so short commands can get reports between collector samples and while the shell
is stopped. Reports cover the scoped command and supervisor overhead. Disk
figures are block-I/O bytes, not every logical file read/write. Unsupported
counters are unavailable. Commands leaving background descendants, non-scoped
fallbacks and missing completion receipts are marked partial/unknown; a missing
receipt never implies success. If systemd's user manager is unavailable, the
command still runs with partial child resource accounting. Recording failures
warn without replacing the command's exit status.

## History, pressure and events

History offers one hour, 24 hours and seven days, plus 30 days when that retention
is enabled. It stores every observed measurement in ten-second aggregates for
an hour, one-minute aggregates through a day, and five-minute aggregates beyond
that. Aggregates retain sampled minima, maxima, counts and observation times.
Averages are sample averages, not a continuous measurement. Spikes shorter than
the sampling interval can be missed.

Each interval retains the leading twelve CPU, memory and I/O contributors
(up to 36 distinct entries), rather than just the current top processes.
Contributor averages describe the samples in which the entry was observed;
these rows are not an additive accounting of all system usage. Network and GPU
history are system totals; they are not attributed to individual apps. Old
readings and events can be pruned earlier to respect the storage budget.

Vertical chart markers indicate timeline events. Actions record the latest
before sample and, once available, following samples within the next minute.
These observations do not prove the action caused the change. Sleep, shutdown,
counter resets and missing measurements do not become artificial recovery data.

Pressure comes from Linux PSI, alongside headroom and swap counters. Normal
incident thresholds are memory `some avg10 >= 10%`, I/O `some avg10 >= 15%`, or
CPU `some avg10 >= 20%` together with at least 90% CPU usage. Conditions must
persist for 15 seconds; recovery also needs 15 clear seconds. Sensitive halves
the pressure thresholds; quiet doubles them. Missing pressure is not recovery.
CPU utilization alone and swap usage alone do not trigger incidents. Optional
notifications are off by default and use the normal desktop notification service.

## Hardware and efficiency

Network bar/history rates follow the IPv4 default-route interface, then a physical
interface or the first available interface as fallback. Interfaces are shown
separately in Hardware rather than summed, avoiding VPN/bridge double counting.
Kernel counters provide network rates, whole-device disk I/O, local filesystem
space, AMD GPU counters, readable sensors, battery and power readings. Remote
and FUSE mounts are not queried for filesystem space. Sensor/device discovery
is cached. Missing tools or unreadable counters leave related metrics unavailable.

NVIDIA telemetry uses optional `nvidia-smi`, with output and runtime limits.
Sleeping GPUs are not queried. Runtime-suspendable AMD cards and NVIDIA helpers
refresh at most once per ten seconds to allow suspend between reads. If some
NVIDIA cards are asleep, the global query is skipped. Intel cards remain visible
but load is unavailable when their driver exposes no unprivileged load counter.
No privileged GPU tools are installed automatically. RAPL readings require
existing read permission; power domains are displayed separately and never added
into an invented whole-machine total.

Adaptive sampling uses two seconds while any popup is open or an incident is
active, five seconds while closed, and ten seconds while closed on battery.
Fixed sampling can be selected instead. Detailed child enumeration is requested while a popup is open; filesystem
space uses a bounded helper and a 30-second cache. Hidden page content is unloaded;
bar graphs retain only a small set of recent numeric readings.

The engineering targets are under 1% of one CPU core and under 50 MiB collector
memory during normal closed-panel use. These are targets, not cross-hardware
performance guarantees. See [validation notes](docs/validation.md) for measured
results and the limits of the rendering checks.

## Preferences and files

Display choices are saved through Omarchy in the widget's own bar entry:

```json
{"id":"lucas.resource-usage","barModules":"cpu,ram,temperature,network","barStyle":"graph"}
```

Modules are `cpu`, `ram`, `temperature`, `network`, `disk`, `gpu`, `fans`,
`battery`, `power`. Toggle a module off/on to move it to the end. Bar values retain
a fixed footprint for the selected modules. Collector preferences apply to every
monitor and are saved separately. Units can be Celsius or Fahrenheit. Retention
can be 1–30 days, storage 16–512 MiB, and fixed refresh 1–30 seconds. The Settings
view offers common presets. Invalid persisted preferences fall back to defaults
with a visible notice; saving valid preferences replaces them.

| File | Location |
| --- | --- |
| Live readings for scripts | `$XDG_RUNTIME_DIR/omarchy-resource-usage.json` |
| Collector lock and tracked-session metadata | `$XDG_RUNTIME_DIR/omarchy-vitals/` |
| History, settings and job receipt inbox | `$XDG_STATE_HOME/omarchy/resource-usage/` |
| Default state root | `~/.local/state/omarchy/resource-usage/` |

History uses `history.sqlite3` with a single collector writer. Tracked launches
write bounded private receipts that the collector imports. Data stays local;
the collector makes no network requests. Project labels, executable/app names,
resource readings and event times are saved; full command lines, environment
variables and conversation content are not. Removing the plugin retains history
and preferences. Delete its state directory manually to erase that data.

## Requirements and troubleshooting

Omarchy's Quickshell plugin system with native services, `qs.Ui.KeyboardPanel`
and the service lookup/settings APIs; Linux with cgroups v2; Python 3.10+; and a Nerd
Font for bar glyphs. Waybar is unsupported. App controls and exact tracked scopes
need the systemd user manager. GPU and power availability vary by driver/kernel.

Open directly with `omarchy-shell lucas.resource-usage open`. A collector failure
is shown in the panel and retried after five seconds. Restart the shell after
updating QML if the host retains old service code. History from a newer,
unsupported schema is preserved and reported instead of silently overwritten.

Run the collector in a separate temporary XDG state/runtime directory for
standalone diagnostics. Avoid running a second collector against your real
session: a lock rejects duplicate instances.

## Development

```sh
python3 -m unittest discover -s tests -v
omarchy plugin validate .
python3 tests/qml_smoke.py
```

Unit tests use temporary roots and synthetic counters; integration tests preserve
exit/signal/TTY behavior and exercise the streaming collector. The optional QML
smoke check needs installed Omarchy/Quickshell and renders all views offscreen
with private XDG directories. It substitutes the compositor popup surface, so it
does not validate real layer-shell positioning or desktop key routing.

Licensed under the [MIT license](LICENSE).
