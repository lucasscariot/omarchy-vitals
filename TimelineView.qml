import QtQuick
import qs.Commons

Column {
  id: root
  property var service: null
  signal inspect(real start, real end)
  spacing: Style.space(9)
  function pct(v) { return v === null || v === undefined ? "—" : v.toFixed(1) + "%" }
  Flow {
    width: parent.width; spacing: Style.space(5)
    Repeater {
      model: [{seconds: 3600, label: "1 hour"}, {seconds: 86400, label: "24 hours"}, {seconds: 604800, label: "7 days"}].concat(root.service && root.service.prefs.retentionDays >= 30 ? [{seconds: 2592000, label: "30 days"}] : [])
      UiButton { required property var modelData; text: modelData.label; checked: root.service && root.service.historyRange === modelData.seconds; onClicked: root.service.setRange(modelData.seconds) }
    }
  }
  VText { visible: !root.service || root.service.events.length === 0; width: parent.width; text: "No events" }
  Repeater {
    model: root.service ? root.service.events : []
    Column {
      required property var modelData
      width: root.width; spacing: Style.space(3)
      VText { width: parent.width; font.weight: Font.Medium; text: new Date(modelData.time * 1000).toLocaleString() + " · " + (modelData.message || (modelData.kind === "job_start" ? "Started " : "Exited ") + modelData.project + " / " + modelData.label) }
      VText { width: parent.width; visible: modelData.kind === "incident"; text: (modelData.status || "") + " · peak pressure " + root.pct(modelData.peak) }
      VText { width: parent.width; visible: !!modelData.error; text: modelData.error || "" }
      VText { width: parent.width; visible: !!modelData.before; text: "Before: CPU " + root.pct(modelData.before ? modelData.before.cpu : null) + " · memory pressure " + root.pct(modelData.before ? modelData.before.memory_pressure : null) + "\nAfter: CPU " + root.pct(modelData.after ? modelData.after.cpu : null) + " · memory pressure " + root.pct(modelData.after ? modelData.after.memory_pressure : null) + (modelData.after ? "" : modelData.after_captured ? " · unavailable" : " · pending") }
      UiButton { text: "Inspect"; onClicked: root.inspect(modelData.time - 30, modelData.time + 30) }
    }
  }
}
