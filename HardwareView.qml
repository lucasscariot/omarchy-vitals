import QtQuick
import qs.Commons

Column {
  id: root
  property var sample: ({})
  property string temperatureUnit: "C"
  spacing: Style.space(8)
  function value(v, unit) { return v === null || v === undefined ? "unavailable" : v.toFixed(1) + unit }
  function bytes(v) { return v === null || v === undefined ? "unavailable" : v >= 1048576 ? (v / 1048576).toFixed(1) + " MiB/s" : (v / 1024).toFixed(1) + " KiB/s" }
  function temp(v) { return value(v === null || v === undefined ? null : temperatureUnit === "F" ? v * 1.8 + 32 : v, "°" + temperatureUnit) }
  VText { width: parent.width; muted: true; text: "Readings depend on driver support and permissions. Missing readings are unavailable; sleeping GPUs are left asleep. Power readings cover their named domain and are not a whole-machine total." }
  VText { width: parent.width; visible: !!root.sample.hardware && !!root.sample.hardware.network_primary; muted: true; text: "Bar and network history follow " + (root.sample.hardware ? root.sample.hardware.network_primary : "") + "; interfaces below are shown separately." }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.network : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · ↓ " + root.bytes(modelData.rx) + " · ↑ " + root.bytes(modelData.tx) }
  }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.disks : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · read " + root.bytes(modelData.read) + " · write " + root.bytes(modelData.write) }
  }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.volumes : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · " + (modelData.available === null ? "space unavailable" : (modelData.available / 1073741824).toFixed(1) + " / " + (modelData.total / 1073741824).toFixed(1) + " GiB available") }
  }
  VText { visible: !!root.sample.hardware && !!root.sample.hardware.volumes_stale; width: parent.width; muted: true; text: "Space probe unavailable; any space readings shown are from the previous successful probe." }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.gpus : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · " + modelData.state + "\nLoad " + root.value(modelData.usage, "%") + " · VRAM " + root.value(modelData.memory_mib, " MiB") + " / " + root.value(modelData.total_mib, " MiB") + " · " + root.temp(modelData.temperature) + " · " + root.value(modelData.watts, " W") }
  }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.temperatures : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · " + root.temp(modelData.celsius) }
  }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.fans : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · " + root.value(modelData.rpm, " RPM") }
  }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.batteries : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · " + root.value(modelData.percent, "%") + " · " + modelData.status + " · " + root.value(modelData.watts, " W") + " · health " + root.value(modelData.health, "%") }
  }
  Repeater {
    model: root.sample.hardware ? root.sample.hardware.power : []
    VText { required property var modelData; width: root.width; text: modelData.name + " · " + root.value(modelData.watts, " W") }
  }
}
