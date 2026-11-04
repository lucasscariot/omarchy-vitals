import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons

Column {
  id: root
  property var service: null
  property bool agentsOnly: false
  property bool compact: false
  property string query: ""
  property string sortKey: "cpu"
  property string selected: ""
  signal showAll()
  signal revealRequested(real top, real bottom)
  readonly property var rows: {
    var sample = service ? service.sample : ({})
    var list = (sample.apps || []).concat(agentsOnly ? sample.inferred || [] : []).filter(a => (a.kind === "agent") === agentsOnly)
    list = list.filter(a => ((a.name || "") + " " + (a.project || "")).toLowerCase().includes(query.toLowerCase()))
    list.sort((a, b) => (b[sortKey] || 0) - (a[sortKey] || 0) || a.id.localeCompare(b.id))
    return compact ? list.slice(0, 5).concat(list.slice(5).filter(a => a.frozen || a.calmed)) : list
  }
  spacing: Style.space(5)
  activeFocusOnTab: !compact
  onSelectedChanged: Qt.callLater(function() {
    var index = rows.findIndex(a => a.id === selected), item = appRows.itemAt(index)
    if (item) revealRequested(item.y, item.y + item.height)
  })
  function mem(mib) { return mib === undefined || mib === null ? "—" : mib >= 1024 ? (mib / 1024).toFixed(1) + " GiB" : Math.round(mib) + " MiB" }
  function choose(delta) {
    var index = rows.findIndex(a => a.id === selected)
    if (rows.length) selected = rows[Math.max(0, Math.min(rows.length - 1, index + delta))].id
  }
  function selectedAction(action) {
    var app = rows.find(a => a.id === selected)
    if (app && !app.inferred && service) service.act(app, action)
  }
  Keys.onDownPressed: choose(1)
  Keys.onUpPressed: choose(-1)
  Keys.onPressed: function(event) {
    var app = rows.find(a => a.id === selected)
    if (event.key === Qt.Key_C && app) { selectedAction(app.calmed ? "uncalm" : "calm"); event.accepted = true }
    if (event.key === Qt.Key_F && app) { selectedAction(app.frozen ? "thaw" : "freeze"); event.accepted = true }
  }
  Rectangle {
    visible: !root.compact
    width: parent.width
    height: Style.space(32)
    radius: Style.space(5)
    color: Qt.alpha(Commons.Color.foreground, 0.06)
    TextInput {
      anchors.fill: parent; anchors.margins: Style.space(6)
      color: Commons.Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
      selectByMouse: true; clip: true
      activeFocusOnTab: true
      onTextChanged: root.query = text
      VText { visible: !parent.text && !parent.activeFocus; text: "Search " + (root.agentsOnly ? "agents or projects…" : "apps…"); muted: true }
    }
  }
  Flow {
    visible: !root.compact
    width: parent.width; spacing: Style.space(5)
    Repeater {
      model: [{key: "cpu", label: "CPU"}, {key: "memory_mib", label: "Memory"}, {key: "io_bps", label: "I/O"}]
      UiButton { required property var modelData; text: modelData.label; checked: root.sortKey === modelData.key; onClicked: root.sortKey = modelData.key }
    }
    UiButton { text: "Keyboard"; onClicked: root.forceActiveFocus() }
    UiButton { text: "Open btop"; onClicked: Quickshell.execDetached(["omarchy-launch-or-focus-tui", "btop"]) }
  }
  VText { visible: !root.compact; width: parent.width; muted: true; text: "↑/↓ select · C Calm/restore · F Freeze/thaw · Tab moves between controls" }
  VText { visible: root.rows.length === 0; width: parent.width; muted: true; text: root.agentsOnly ? "No tracked agents. Use vitals-run to track the next launch." : "No matching app scopes." }
  Repeater {
    id: appRows
    model: root.rows
    delegate: Rectangle {
      id: row
      required property var modelData
      width: root.width
      height: body.implicitHeight + Style.space(12)
      color: root.selected === modelData.id ? Qt.alpha(Commons.Color.accent, 0.1) : "transparent"
      radius: Style.space(5)
      Column {
        id: body
        x: Style.space(6); y: Style.space(6); width: parent.width - Style.space(12)
        spacing: Style.space(3)
        Row {
          width: parent.width
          VText { width: parent.width * .62; text: (row.modelData.project ? row.modelData.project + " / " : "") + row.modelData.name + (row.modelData.inferred ? " · inferred root process" : ""); font.weight: Font.Medium }
          VText { width: parent.width * .38; horizontalAlignment: Text.AlignRight; text: row.modelData.cpu.toFixed(1) + "% · " + root.mem(row.modelData.memory_mib) }
        }
        VText { width: parent.width; muted: true; text: (row.modelData.cores_used || 0).toFixed(2) + " cores used" + (row.modelData.session_id ? " · " + row.modelData.session_id.slice(0, 8) : "") + (row.modelData.frozen ? " · frozen" : "") + (row.modelData.calmed ? " · low priority" : "") + (row.modelData.started ? " · started " + new Date(row.modelData.started * 1000).toLocaleTimeString() : "") }
        Flow {
          visible: !root.compact
          width: parent.width; spacing: Style.space(5)
          UiButton { text: "Details"; available: !row.modelData.inferred; checked: root.selected === row.modelData.id; onClicked: { root.selected = row.modelData.id; if (root.service) root.service.send({op: "inspect", id: row.modelData.id}) } }
          UiButton { text: row.modelData.calmed ? "Restore" : "Calm"; checked: !!row.modelData.calmed; available: !row.modelData.inferred && root.service && !root.service.actionPending; onClicked: root.service.act(row.modelData, row.modelData.calmed ? "uncalm" : "calm") }
          UiButton { text: row.modelData.frozen ? "Thaw" : "Freeze"; checked: !!row.modelData.frozen; available: !row.modelData.inferred && root.service && !root.service.actionPending; onClicked: root.service.act(row.modelData, row.modelData.frozen ? "thaw" : "freeze") }
        }
        Column {
          width: parent.width
          visible: root.service && root.service.sample.inspected === row.modelData.id
          Repeater {
            model: parent.visible ? root.service.sample.children || [] : []
            VText { required property var modelData; width: body.width; muted: true; text: "  " + modelData.name + " · PID " + modelData.pid + " · " + modelData.cpu.toFixed(1) + "% · " + root.mem(modelData.memory_mib) }
          }
        }
      }
    }
  }
  UiButton { visible: root.compact; text: "Show all apps"; onClicked: root.showAll() }
}
