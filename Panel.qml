import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "lucas.resource-usage"
  ipcTarget: "lucas.resource-usage"
  property var sample: ({})
  property string errorText: ""
  implicitWidth: button.implicitWidth
  implicitHeight: bar ? bar.barSize : Style.space(26)

  property real clockTime: Date.now() / 1000
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
    text: root.sample.text || "CPU …  RAM …  TEMP …"
    horizontalMargin: 8
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keys
    contentWidth: panel.fittedContentWidth(Style.space(480))
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
        spacing: Style.space(18)
        Text {
          text: "Vitals"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.heading
          font.weight: Font.Medium
        }
        Repeater {
          model: [
            { name: "CPU", value: root.sample.cpu === undefined ? "—" : Math.round(root.sample.cpu) + "%", detail: "Across all cores", fraction: (root.sample.cpu || 0) / 100 },
            { name: "Memory", value: root.sample.ram === undefined ? "—" : Math.round(root.sample.ram) + "%", detail: root.sample.used_gib === undefined ? "Waiting for data" : root.sample.used_gib.toFixed(1) + " / " + root.sample.total_gib.toFixed(1) + " GiB used", fraction: (root.sample.ram || 0) / 100 },
            { name: "CPU temperature", value: root.sample.temperature == null ? "—" : Math.round(root.sample.temperature) + "°C", detail: "CPU package sensor", fraction: -1 }
          ]
          delegate: Column {
            required property var modelData
            width: content.width
            spacing: Style.space(6)
            Row {
              width: parent.width
              Text { width: parent.width * 0.7; text: modelData.name; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body }
              Text { width: parent.width * 0.3; horizontalAlignment: Text.AlignRight; text: modelData.value; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; font.weight: Font.Medium }
            }
            Rectangle {
              width: parent.width; height: Style.space(4); radius: height / 2
              visible: modelData.fraction >= 0
              color: Qt.alpha(Color.foreground, 0.12)
              Rectangle { width: parent.width * Math.max(0, Math.min(1, modelData.fraction)); height: parent.height; radius: height / 2; color: Color.accent }
            }
            Text { text: modelData.detail; color: Qt.alpha(Color.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.font.bodySmall }
          }
        }
        Column {
          width: parent.width
          spacing: Style.space(12)
          Text { text: "Past hour"; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.title; font.weight: Font.Medium }
          HistoryChart { width: parent.width; title: "CPU"; metric: "cpu"; points: root.sample.history || []; now: root.clockTime }
          HistoryChart { width: parent.width; title: "Memory"; metric: "ram"; points: root.sample.history || []; now: root.clockTime; lineColor: Color.background.hslLightness > 0.5 ? "#237A3B" : "#77E68C" }
          HistoryChart { width: parent.width; title: "Temperature"; metric: "temperature"; unit: "°C"; points: root.sample.history || []; now: root.clockTime; lineColor: Color.background.hslLightness > 0.5 ? "#A64B00" : "#FF9F0A" }
          Row {
            width: parent.width
            Repeater {
              model: ["60 min ago", "30 min", "Now"]
              Text { required property string modelData; required property int index; width: content.width / 3; text: modelData; horizontalAlignment: index === 0 ? Text.AlignLeft : index === 1 ? Text.AlignHCenter : Text.AlignRight; color: Qt.alpha(Color.foreground, 0.6); font.family: Style.font.family; font.pixelSize: Style.font.bodySmall }
            }
          }
          Text {
            width: parent.width
            wrapMode: Text.WordWrap
            text: (root.sample.history || []).length < 6 ? "Collecting history — charts fill as time passes." : "10-second samples · gaps indicate missing readings"
            color: Qt.alpha(Color.foreground, 0.6); font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
          }
        }
        Text {
          visible: root.errorText !== ""
          text: root.errorText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }
      }
    }
  }
}
