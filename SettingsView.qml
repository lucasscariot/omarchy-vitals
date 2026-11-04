import QtQuick
import qs.Commons

Column {
  id: root
  property var service: null
  property var displaySettings: ({})
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
  VText { width: parent.width; text: "Bar modules · selection order is display order"; font.weight: Font.Medium }
  Flow {
    width: parent.width; spacing: Style.space(5)
    Repeater {
      model: ["cpu", "ram", "temperature", "network", "disk", "gpu", "fans", "battery", "power"]
      UiButton { required property string modelData; text: modelData; checked: root.modules.includes(modelData); onClicked: root.toggleModule(modelData) }
    }
  }
  VText { width: parent.width; muted: true; text: "Selected: " + root.modules.join(" → ") + ". Toggle a module off and on to move it to the end." }
  Flow {
    width: parent.width; spacing: Style.space(5)
    UiButton { text: "Style: " + (root.displaySettings.barStyle || root.prefs.style || "text"); onClicked: root.displayChanged({barStyle: (root.displaySettings.barStyle || root.prefs.style) === "graph" ? "text" : "graph"}) }
    UiButton { text: "°" + (root.prefs.temperatureUnit || "C"); onClicked: root.cycle("temperatureUnit", ["C", "F"]) }
    UiButton { text: "Refresh: " + (root.prefs.refreshPolicy || "adaptive"); onClicked: root.cycle("refreshPolicy", ["adaptive", "fixed"]) }
    UiButton { text: "Fixed: " + (root.prefs.refreshSeconds || 2) + "s"; onClicked: root.cycle("refreshSeconds", [1, 2, 5, 10, 30]) }
    UiButton { text: "History: " + (root.prefs.retentionDays || 7) + " days"; onClicked: root.cycle("retentionDays", [1, 7, 30]) }
    UiButton { text: "Storage: " + (root.prefs.storageMiB || 128) + " MiB"; onClicked: root.cycle("storageMiB", [16, 64, 128, 256]) }
    UiButton { text: "Alerts: " + (root.prefs.sensitivity || "normal"); onClicked: root.cycle("sensitivity", ["sensitive", "normal", "quiet"]) }
    UiButton { text: "Notifications: " + (root.prefs.notifications ? "on" : "off"); onClicked: root.setPref("notifications", !root.prefs.notifications) }
    UiButton { text: "Inferred agents: " + (root.prefs.inferredAgents ? "on" : "off"); onClicked: root.setPref("inferredAgents", !root.prefs.inferredAgents) }
  }
  VText { width: parent.width; muted: true; text: "Collection preferences apply to every monitor. Adaptive refresh: 2s while open or under pressure, 5s closed, 10s closed on battery. History contains sampled measurements; shorter spikes can be missed." }
  VText { width: parent.width; text: "Track your next command"; font.weight: Font.Medium }
  VText { width: parent.width; text: "vitals-run --name build -- cargo test\nvitals-run -- claude\nvitals-run -- codex" }
  VText { width: parent.width; muted: true; text: "Optional shell integration: run vitals-run --shell-init, review the aliases, then add them to your shell configuration. No shell configuration is changed automatically.\n\nCalm lowers relative CPU priority. Restore sets it to 100. Freeze pauses the entire app, including audio and calls; Thaw resumes it." }
}
