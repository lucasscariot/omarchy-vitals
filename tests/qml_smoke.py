"""Render all views with private XDG roots; substitute only the layer-shell surface."""
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vitals.history import History

HARNESS = '''import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons
import "./plugin" as Vitals
ShellRoot {
  Vitals.Service { id: backend; migrateLegacy: false }
  Window {
    visible: true; width: 680; height: 900; color: "#1e1e2e"
    Rectangle {
      id: stage; anchors.fill: parent; color: "#1e1e2e"
      Vitals.Panel { id: panel; x: 20; y: 20; service: backend }
    }
  }
  property var pages: ["Overview", "Apps", "Agents", "Hardware", "History", "Timeline", "Jobs", "Settings"]
  property int pageIndex: -1
  Timer {
    interval: 1500; running: true; repeat: true
    onTriggered: {
      if (pageIndex === -1) {
        if (!backend.sample.time) { console.error("SMOKE_NO_SAMPLE " + backend.errorText); Qt.quit(); return }
        panel.open(); backend.refreshHistory()
      }
      pageIndex++
      if (pageIndex >= pages.length) { console.log("SMOKE_PAGES_OK"); Qt.quit(); return }
      panel.page = pages[pageIndex]
      if (panel.page === "Agents") {
        backend.sample = Object.assign({}, backend.sample, {apps: backend.sample.apps.concat([
          {id: "demo-session", session_id: "demo-session", project: "demo", name: "codex", kind: "agent", cpu: 20,
           memory_mib: 250, cores_used: 2, io_bps: 0, inferred: false, units: [], unit_identity: {}, frozen: false, calmed: false, started: Date.now()/1000}])})
      }
      if (panel.page === "History") backend.send({op: "detail", start: Date.now()/1000 - 90, end: Date.now()/1000})
      if (panel.page === "Settings") panel.settings = {barModules: "cpu,ram,network,gpu", barStyle: "graph"}
      capture.restart()
    }
  }
  Timer {
    id: capture; interval: 500
    onTriggered: stage.grabToImage(function(result) {
      result.saveToFile(Quickshell.env("VITALS_SMOKE_OUTPUT") + "/" + pages[pageIndex].toLowerCase() + ".png")
    })
  }
}
'''

SURFACE = '''import QtQuick
Item {
  required property Item anchorItem
  required property QtObject bar
  property var owner: null
  property bool open: false
  property Item focusTarget: null
  property int contentWidth: 600
  property int contentHeight: 650
  x: 0; y: 40; width: contentWidth; height: contentHeight
  visible: open
  function fittedContentWidth(value) { return value }
  function fittedContentHeight(value) { return value }
}
'''


def main():
    shell = Path('/usr/share/omarchy/shell')
    if not shell.is_dir() or not shutil.which('qs'):
        raise SystemExit('The QML smoke check needs Omarchy and Quickshell installed')
    output = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='vitals-previews-')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vitals-render-') as temp:
        root = Path(temp)
        plugin = root / 'plugin'
        plugin.mkdir()
        for source in ROOT.glob('*.qml'):
            shutil.copy2(source, plugin / source.name)
        shutil.copy2(ROOT / 'collector.py', plugin / 'collector.py')
        shutil.copytree(ROOT / 'vitals', plugin / 'vitals', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(shell / 'Commons', root / 'Commons')
        shutil.copytree(shell / 'Ui', root / 'Ui')
        (root / 'Ui/KeyboardPanel.qml').write_text(SURFACE)
        (root / 'qs').mkdir()
        (root / 'qs/Commons').symlink_to(root / 'Commons')
        (root / 'qs/Ui').symlink_to(root / 'Ui')
        (root / 'shell.qml').write_text(HARNESS)
        (root / 'run').mkdir(mode=0o700)
        now = time.time()
        history = History(root / 'state/omarchy/resource-usage/history.sqlite3')
        for delta in range(3590, 0, -10):
            cpu = 35 + 25 * math.sin(delta / 180)
            history.add(now - delta, {'cpu': cpu, 'ram': 55, 'temperature': 48},
                        [{'id': 'demo-build', 'name': 'build', 'project': 'demo', 'cpu': cpu, 'memory_mib': 250, 'io_bps': 0}])
        for i in (1, 2):
            report = dict(id=f'demo-{i}', label='build', project='demo', project_id='demo',
                          started=now-300+i, ended=now-280+i, duration=20, cpu_seconds=8+i,
                          peak_memory_mib=256+i*10, read_bytes=1048576, write_bytes=2097152,
                          complete=True, exit_code=0, signal=None)
            history.report(report)
            history.event(f'start-{i}', report['started'], 'job_start', report)
            history.event(f'end-{i}', report['ended'], 'job_end', report)
        history.event('demo-action', now-120, 'action', {'message': 'Calm: demo build', 'before': {'cpu': 70, 'memory_pressure': 10}})
        history.event('demo-incident', now-200, 'incident', {'message': 'Tasks waited for memory', 'peak': 15, 'status': 'Recovered'})
        history.close()
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='generic',
                   QT_QUICK_CONTROLS_STYLE='Basic', QML_IMPORT_PATH=str(root), DISPLAY='', WAYLAND_DISPLAY='',
                   XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'),
                   XDG_CACHE_HOME=str(root / 'cache'), XDG_RUNTIME_DIR=str(root / 'run'),
                   VITALS_SMOKE_OUTPUT=str(output))
        result = subprocess.run(['qs', '-p', str(root / 'shell.qml'), '--no-color'], env=env,
                                capture_output=True, text=True, timeout=25)
        log = result.stdout + result.stderr
        (output / 'render.log').write_text(log)
        errors = [line for line in log.splitlines() if ('ERROR' in line and 'Failed to start IPC server' not in line) or 'WARN scene:' in line]
        if result.returncode or 'SMOKE_PAGES_OK' not in log or errors:
            raise SystemExit('\n'.join(errors) or log)
        if len(list(output.glob('*.png'))) != 8:
            raise SystemExit('Not every view produced a preview')
    print(f'Eight views rendered without QML runtime errors. Previews: {output}')
    print('The layer-shell surface is substituted; real compositor placement/key routing require a desktop check.')


if __name__ == '__main__':
    main()
