import QtQuick
import Quickshell.Io
import qs.Commons

Column {
  id: root
  property var service: null
  property var bar: null
  property var displaySettings: ({})
  property bool copied: false
  property bool copyFailed: false
  signal displayChanged(var settings)
  spacing: Style.space(8)
  readonly property var prefs: service ? service.prefs : ({})
  readonly property var modules: displaySettings.barModules ? String(displaySettings.barModules).split(",") : prefs.modules || ["cpu", "ram", "temperature"]
  function setPref(key, value) { var changes = ({}); changes[key] = value; service.send({op: "settings", changes: changes}) }
  function cycle(key, values) { var index = values.indexOf(prefs[key]); setPref(key, values[(index + 1) % values.length]) }
  function toggleModule(name) {
    var next = modules.slice(), index = next.indexOf(name)
    if (index >= 0) { if (next.length === 1) return; next.splice(index, 1) } else next.push(name)
    displayChanged({barModules: next.join(",")})
  }
  Flow {
    width: parent.width; spacing: Style.space(5)
    Repeater {
      model: [{key:"cpu",label:"CPU"},{key:"ram",label:"RAM"},{key:"temperature",label:"Temp"},{key:"network",label:"Net"},{key:"disk",label:"Disk"},{key:"gpu",label:"GPU"},{key:"fans",label:"Fans"},{key:"battery",label:"Battery"},{key:"power",label:"Power"}]
      UiButton { required property var modelData; text: modelData.label; checked: root.modules.includes(modelData.key); hint: "Toggle in bar; enabled modules are added at the end"; tooltipHost: root.bar; onClicked: root.toggleModule(modelData.key) }
    }
  }
  Flow {
    width: parent.width; spacing: Style.space(5)
    UiButton { text: "Style: " + (root.displaySettings.barStyle || root.prefs.style || "text"); onClicked: root.displayChanged({barStyle: (root.displaySettings.barStyle || root.prefs.style) === "graph" ? "text" : "graph"}) }
    UiButton { text: "°" + (root.prefs.temperatureUnit || "C"); onClicked: root.cycle("temperatureUnit", ["C", "F"]) }
    UiButton { text: "Refresh: " + (root.prefs.refreshPolicy || "adaptive"); hint: "2s open or under pressure; 5s closed; 10s closed on battery"; tooltipHost: root.bar; onClicked: root.cycle("refreshPolicy", ["adaptive", "fixed"]) }
    UiButton { visible: root.prefs.refreshPolicy === "fixed"; text: (root.prefs.refreshSeconds || 2) + "s"; onClicked: root.cycle("refreshSeconds", [1, 2, 5, 10, 30]) }
    UiButton { text: "History: " + (root.prefs.retentionDays || 7) + "d"; onClicked: root.cycle("retentionDays", [1, 7, 30]) }
    UiButton { text: (root.prefs.storageMiB || 128) + " MiB"; hint: "History storage budget"; tooltipHost: root.bar; onClicked: root.cycle("storageMiB", [16, 64, 128, 256]) }
    UiButton { text: "Alerts: " + (root.prefs.sensitivity || "normal"); onClicked: root.cycle("sensitivity", ["sensitive", "normal", "quiet"]) }
    UiButton { text: "Notifications"; checked: !!root.prefs.notifications; onClicked: root.setPref("notifications", !root.prefs.notifications) }
    UiButton { text: "Detect agents"; checked: !!root.prefs.inferredAgents; hint: "Show unwrapped agent root processes as read-only estimates"; tooltipHost: root.bar; onClicked: root.setPref("inferredAgents", !root.prefs.inferredAgents) }
    UiButton { text: root.copied ? "Copied" : "Copy agent aliases"; available: !!root.service && !aliases.running && !clipboard.running; hint: "Copy optional shell aliases for tracked launches"; tooltipHost: root.bar; onClicked: { root.copyFailed = false; aliases.running = true } }
  }
  VText { visible: root.copyFailed; width: parent.width; text: "Clipboard unavailable" }
  Process {
    id: aliases
    command: root.service ? ["/usr/bin/python3", "-B", root.service.pluginPath + "bin/vitals-run", "--shell-init"] : []
    stdout: StdioCollector { id: aliasOutput; waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode === 0) { clipboard.command = ["wl-copy", "--", aliasOutput.text]; clipboard.running = true }
      else root.copyFailed = true
    }
  }
  Process {
    id: clipboard
    onExited: function(exitCode) { root.copied = exitCode === 0; root.copyFailed = exitCode !== 0; copiedReset.restart() }
  }
  Timer { id: copiedReset; interval: 3000; onTriggered: root.copied = false }
}
