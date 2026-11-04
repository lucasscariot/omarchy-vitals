import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

Item {
  id: root
  property var shell: null
  property var sample: ({})
  property var barPoints: []
  property bool migrateLegacy: true
  property var prefs: ({})
  property var points: []
  property var events: []
  property var reports: []
  property var detail: ({})
  property string errorText: ""
  property int historyRange: 3600
  property bool actionPending: false
  property var clients: ({})
  property double receivedAt: 0
  readonly property bool viewing: Object.keys(clients).some(k => clients[k])
  readonly property string pluginPath: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, ""))
  function send(request) {
    if (!backend.running) { errorText = "Collector is restarting…"; return false }
    backend.write(JSON.stringify(request) + "\n")
    return true
  }
  function setViewing(client, open) {
    var next = Object.assign({}, clients)
    if (open) next[client] = true; else delete next[client]
    clients = next
    send({op: "visible", client: client, open: open})
    if (open) refreshHistory()
  }
  function refreshHistory() { send({op: "history", range: historyRange}) }
  function setRange(seconds) { historyRange = seconds; detail = ({}); refreshHistory() }
  function act(app, action) {
    if (actionPending) return
    actionPending = true
    if (!send({op: "action", id: app.id, kind: app.kind, identities: app.unit_identity, action: action})) actionPending = false
  }
  function accept(line) {
    if (line.length > 2097152) { errorText = "Collector output exceeded its limit"; backend.running = false; return }
    try {
      var message = JSON.parse(line)
      if (message.type === "sample") {
        sample = message.sample; receivedAt = Date.now()
        var hw = sample.hardware || ({})
        var bat = (hw.batteries || [])[0], power = (hw.power || [])[0], fan = (hw.fans || [])[0]
        barPoints = (sample.gap ? [] : barPoints).concat([{cpu: sample.cpu, ram: sample.ram, temperature: sample.temperature,
          network: sample.rx, disk: sample.disk_write, gpu: sample.gpu, fans: fan ? fan.rpm : null,
          battery: bat ? bat.percent : null, power: bat && bat.watts !== null ? bat.watts : power ? power.watts : null}]).slice(-60)
        if (errorText.indexOf("Readings paused") === 0) errorText = ""
      }
      else if (message.type === "settings") { prefs = message.settings; errorText = "" }
      else if (message.type === "history" && message.range === historyRange) { points = message.points; events = message.events; reports = message.reports }
      else if (message.type === "detail") detail = message.detail
      else if (message.type === "action") { actionPending = false; errorText = ""; refreshHistory() }
      else if (message.type === "error") { errorText = message.error; actionPending = false }
    } catch (e) { errorText = "Invalid collector response" }
  }
  Process {
    id: backend
    command: ["/usr/bin/python3", "-B", root.pluginPath + "collector.py", "--serve"].concat(root.migrateLegacy ? ["--migrate"] : [])
    running: true
    stdinEnabled: true
    stdout: SplitParser { onRead: function(data) { root.accept(data) } }
    stderr: SplitParser { onRead: function(data) { root.errorText = data.slice(0, 512) } }
    onExited: { root.actionPending = false; root.errorText = "Collector stopped. " + root.errorText; restart.start() }
    onStarted: { for (var client in root.clients) root.send({op: "visible", client: client, open: true}) }
  }
  Timer { id: restart; interval: 5000; onTriggered: backend.running = true }
  Timer { interval: 10000; running: root.viewing; repeat: true; onTriggered: root.refreshHistory() }
  Timer {
    interval: 5000; running: true; repeat: true
    onTriggered: {
      if (root.receivedAt && Date.now() - root.receivedAt > Math.max(45000, (root.prefs.refreshSeconds || 2) * 3000)) root.errorText = "Readings paused — waiting for collector"
    }
  }
  ShellIpc {
    target: "lucas.resource-usage"
    function open(): void { if (root.shell) root.shell.summon("lucas.resource-usage", "") }
    function close(): void { if (root.shell) root.shell.hide("lucas.resource-usage") }
    function toggle(): void { if (root.shell) root.shell.toggle("lucas.resource-usage", "") }
  }
  Component.onDestruction: { restart.stop(); backend.running = false }
}
