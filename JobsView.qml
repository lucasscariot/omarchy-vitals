import QtQuick
import qs.Commons

Column {
  id: root
  property var service: null
  spacing: Style.space(8)
  function val(v, unit) { return v === undefined || v === null ? "unavailable" : v.toFixed(1) + unit }
  function change(current, previous) { return previous > 0 && current !== null ? " (" + ((current / previous - 1) * 100).toFixed(0) + "% vs previous)" : "" }
  VText { width: parent.width; muted: true; text: "Recent tracked jobs. Comparisons use the same project and label. Scope accounting includes the supervisor and child processes; disk counters describe block I/O, not all file writes." }
  VText { visible: !root.service || root.service.reports.length === 0; width: parent.width; text: "No completed tracked jobs yet. Start one with vitals-run." }
  Repeater {
    model: root.service ? root.service.reports : []
    Column {
      required property var modelData
      width: root.width; spacing: Style.space(3)
      VText { width: parent.width; font.weight: Font.Medium; text: modelData.project + " / " + modelData.label + " · exit " + (modelData.exit_code === null ? "unknown" : modelData.exit_code) + (modelData.complete ? "" : " · partial accounting") }
      VText { width: parent.width; text: root.val(modelData.duration, "s elapsed") + root.change(modelData.duration, modelData.previous ? modelData.previous.duration : 0) + " · " + root.val(modelData.cpu_seconds, " CPU seconds") + root.change(modelData.cpu_seconds, modelData.previous ? modelData.previous.cpu_seconds : 0) }
      VText { width: parent.width; text: "Peak " + root.val(modelData.peak_memory_mib, " MiB") + root.change(modelData.peak_memory_mib, modelData.previous ? modelData.previous.peak_memory_mib : 0) + " · read " + root.val(modelData.read_bytes === null ? null : modelData.read_bytes / 1048576, " MiB") + root.change(modelData.read_bytes, modelData.previous ? modelData.previous.read_bytes : 0) + " · written " + root.val(modelData.write_bytes === null ? null : modelData.write_bytes / 1048576, " MiB") + root.change(modelData.write_bytes, modelData.previous ? modelData.previous.write_bytes : 0) }
      VText { width: parent.width; muted: true; text: new Date(modelData.ended * 1000).toLocaleString() }
      VText { width: parent.width; visible: !!modelData.error; muted: true; text: modelData.error || "" }
    }
  }
}
