import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Panel {
  id: root
  moduleName: "lucas.resource-usage"
  ipcTarget: "lucas.resource-usage"
  property var sample: ({})
  property string errorText: ""
  readonly property string cpuIcon: "" // Nerd Font: microchip
  readonly property string memoryIcon: "" // Nerd Font: Font Awesome memory module
  readonly property string temperatureIcon: "" // Nerd Font: thermometer half
  implicitWidth: button.implicitWidth
  implicitHeight: bar ? bar.barSize : Style.space(26)

  property real clockTime: Date.now() / 1000
  function metricText(value, unit) {
    if (value === undefined) return "…"
    return value === null || !isFinite(value) ? "—" : Math.round(value) + unit
  }
  function readSample() {
    try {
      var data = JSON.parse(live.text())
      if (!isFinite(data.cpu) || !isFinite(data.ram)) throw new Error("Invalid sample")
      root.sample = data
      root.errorText = ""
    } catch (e) { root.errorText = "Waiting for resource collector…" }
  }
  Timer {
    interval: 2000; running: true; repeat: true
    onTriggered: {
      root.clockTime = Date.now() / 1000
      if (root.sample.time && root.clockTime - root.sample.time > 15)
        root.errorText = "Readings paused — waiting for collector"
    }
  }
  FileView {
    id: live
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/omarchy-resource-usage.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.readSample()
    onLoadFailed: root.errorText = "Waiting for resource collector…"
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    // Keep one compact footprint; longer readings fit within it.
    fixedWidth: Style.space(156)
    horizontalMargin: 5
    tooltipText: "CPU: " + root.metricText(root.sample.cpu, "%")
        + "\nRAM: " + root.metricText(root.sample.ram, "%")
        + "\nCPU temperature: " + root.metricText(root.sample.temperature, "°C")
    onPressed: function(b) { root.toggle() }

    Row {
      id: barReadout
      anchors.centerIn: parent
      spacing: 0
      scale: Math.min(1, button.width / Math.max(1, implicitWidth))

      Repeater {
        model: [
          { icon: root.cpuIcon, value: root.metricText(root.sample.cpu, "%") },
          { icon: root.memoryIcon, value: root.metricText(root.sample.ram, "%") },
          { icon: root.temperatureIcon, value: root.metricText(root.sample.temperature, "°C") }
        ]
        delegate: Item {
          id: metric
          required property var modelData
          // Keep the compact padding identical across all readings.
          width: metricContent.implicitWidth + button.scaledHorizontalMargin * 2
          height: button.height

          Row {
            id: metricContent
            x: button.scaledHorizontalMargin
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.labelGap

            OpticalGlyph {
              id: metricIcon
              width: tightWidth
              height: Style.bar.iconCanvas
              text: metric.modelData.icon
              fontFamily: button.fontFamily
              fontSize: Style.bar.iconFont
              color: button.foreground
            }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: metric.modelData.value
              color: button.foreground
              font.family: button.fontFamily
              font.pixelSize: button.fontSize
              font.features: ({ "tnum": 1 })
              renderType: Text.NativeRendering
            }
          }
        }
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keys
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)
    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()
      onMoveRequested: function(dx, dy) { if (dx) root.switchPanel(dx); if (dy) scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, scroll.contentY + dy * Style.space(40))) }
      Flickable {
        id: scroll
        anchors.fill: parent
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
      Column {
        id: content
        width: parent.width
        spacing: Style.space(12)
        Row {
          width: parent.width
          Text {
            width: parent.width / 2
            text: "Vitals"
            color: Commons.Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.weight: Font.Medium
          }
          Text {
            width: parent.width / 2
            anchors.bottom: parent.bottom
            horizontalAlignment: Text.AlignRight
            visible: (root.sample.history || []).length < 6
            text: "collecting history…"
            color: Qt.alpha(Commons.Color.foreground, 0.5)
            font.family: Style.font.family; font.pixelSize: Style.font.caption
          }
        }
        Column {
          width: parent.width
          spacing: Style.space(6)
          HistoryChart { width: parent.width; title: "CPU"; metric: "cpu"; current: root.sample.cpu; points: root.sample.history || []; now: root.clockTime }
          HistoryChart {
            width: parent.width; title: "Memory"; metric: "ram"; current: root.sample.ram
            detail: root.sample.used_gib === undefined ? "" : root.sample.used_gib.toFixed(1) + "/" + root.sample.total_gib.toFixed(0) + " GiB"
            points: root.sample.history || []; now: root.clockTime
            lineColor: Commons.Color.background.hslLightness > 0.5 ? "#237A3B" : "#77E68C"
          }
          HistoryChart { width: parent.width; title: "Temperature"; metric: "temperature"; unit: "°C"; current: root.sample.temperature; points: root.sample.history || []; now: root.clockTime; lineColor: Commons.Color.background.hslLightness > 0.5 ? "#A64B00" : "#FF9F0A" }
        }
        AppList { width: parent.width; apps: root.sample.apps; agents: root.sample.agents }
        Text {
          visible: root.errorText !== ""
          text: root.errorText
          color: Commons.Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }
      }
    }
  }
}
