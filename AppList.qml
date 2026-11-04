import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

// Agents summary + a compact apps table with Calm/Freeze icon actions.
// Renders nothing when the collector does not provide "apps"/"agents" (older collectors).
Column {
  id: root
  property var apps: null
  property var agents: null
  property string errorText: ""
  property string hint: ""
  property var pending: ({})   // optimistic overrides keyed by kind:id
  property var queue: []       // queued argv arrays, run one at a time
  readonly property int maxRows: 5
  readonly property string calmGlyph: ""    // Nerd Font: leaf
  readonly property string freezeGlyph: ""  // Nerd Font: snowflake
  readonly property real cpuColumn: Style.space(44)
  readonly property real memColumn: Style.space(58)
  readonly property real actionSize: Style.space(22)

  // Agents have their own row above, so the table lists apps only. Frozen or
  // calmed apps stay listed so Thaw/Uncalm remains reachable.
  readonly property var appList: {
    var all = Array.isArray(apps) ? apps.filter(a => a.kind !== "agent") : []
    var top = all.slice(0, maxRows)
    return top.concat(all.slice(maxRows).filter(a => stateOf(a).frozen || stateOf(a).calmed))
  }
  readonly property bool hasAgents: agents !== null && agents !== undefined && agents.count > 0
  readonly property var busiestJob: {
    var jobs = hasAgents && Array.isArray(agents.jobs) ? agents.jobs : []
    var best = null
    for (var i = 0; i < jobs.length; i++)
      if (best === null || (jobs[i].cpu || 0) > (best.cpu || 0)) best = jobs[i]
    return best
  }
  readonly property var unitPattern: /^((app|agent)-.+\.scope|hc-.+\.service)$/

  visible: hasAgents || appList.length > 0
  spacing: Style.space(10)

  onAppsChanged: pending = ({})

  function mem(mib) {
    if (mib === undefined || mib === null || !isFinite(mib)) return "—"
    return mib >= 1024 ? (mib / 1024).toFixed(1) + " GB" : Math.round(mib) + " MB"
  }
  function pct(v) { return v === undefined || v === null || !isFinite(v) ? "—" : Math.round(v) + "%" }
  function stateOf(app) {
    var o = pending[app.kind + ':' + app.id] || {}
    return {
      frozen: o.frozen !== undefined ? o.frozen : app.frozen === true,
      calmed: o.calmed !== undefined ? o.calmed : app.calmed === true
    }
  }
  function validUnits(app) {
    // Repeater hands delegates a converted list, not a JS Array, so copy by index.
    var source = app && app.units ? app.units : [], units = []
    for (var i = 0; i < (source.length || 0); i++) {
      var u = String(source[i])
      if (!unitPattern.test(u)) return []
      units.push(u)
    }
    return units
  }
  function act(app, action) {
    var units = validUnits(app)
    if (units.length === 0) { errorText = "Refusing: unsupported unit for " + app.name; errorClear.restart(); return }
    var q = queue.slice()
    for (var i = 0; i < units.length; i++) {
      var u = units[i], argv
      if (action === "calm") argv = ["systemctl", "--user", "set-property", "--runtime", u, "CPUWeight=20"]
      else if (action === "uncalm") argv = ["systemctl", "--user", "set-property", "--runtime", u, "CPUWeight=100"]
      else if (action === "freeze") argv = ["systemctl", "--user", "freeze", u]
      else if (action === "thaw") argv = ["systemctl", "--user", "thaw", u]
      else return
      q.push(argv)
    }
    var p = Object.assign({}, pending), key = app.kind + ':' + app.id, o = Object.assign({}, p[key] || {})
    if (action === "calm") o.calmed = true
    if (action === "uncalm") o.calmed = false
    if (action === "freeze") o.frozen = true
    if (action === "thaw") o.frozen = false
    p[key] = o
    pending = p
    queue = q
    next()
  }
  function next() {
    if (runner.running || queue.length === 0) return
    var q = queue.slice()
    runner.command = q.shift()
    queue = q
    runner.running = true
  }

  Timer { id: errorClear; interval: 6000; onTriggered: root.errorText = "" }

  Process {
    id: runner
    stderr: StdioCollector { id: errOut }
    onExited: function(exitCode, exitStatus) {
      if (exitCode !== 0) {
        var msg = errOut.text.trim().split("\n")[0]
        root.errorText = "systemctl failed (" + exitCode + ")" + (msg ? ": " + msg : "")
        root.pending = ({})
        root.queue = []
        errorClear.restart()
      } else {
        root.next()
      }
    }
  }

  // Thin divider between the metrics and the per-app section.
  Rectangle { width: parent.width; height: 1; color: Qt.alpha(Commons.Color.foreground, 0.1) }

  // Agents: one line, busiest job underneath.
  Column {
    visible: root.hasAgents
    width: parent.width
    spacing: Style.space(2)
    Item {
      width: parent.width
      height: agentsLabel.implicitHeight
      Text {
        id: agentsLabel
        text: "Agents"
        color: Commons.Color.foreground
        font.family: Style.font.family; font.pixelSize: Style.font.body; font.weight: Font.Medium
      }
      Text {
        anchors.right: parent.right
        width: parent.width - agentsLabel.width - Style.space(12)
        horizontalAlignment: Text.AlignRight
        elide: Text.ElideLeft
        text: root.hasAgents ? root.pct(root.agents.cpu) + "  ·  " + root.mem(root.agents.memory_mib) + "  ·  " + root.agents.count + " running" : ""
        color: Commons.Color.accent
        font.family: Style.font.family; font.pixelSize: Style.font.body; font.weight: Font.Medium
        font.features: ({ "tnum": 1 })
      }
    }
    Text {
      visible: root.busiestJob !== null
      width: parent.width
      elide: Text.ElideRight
      text: root.busiestJob === null ? "" : "busiest: " + (root.busiestJob.command || root.busiestJob.name) + (root.busiestJob.command && root.busiestJob.name ? " (" + root.busiestJob.name + ")" : "") + "  " + root.pct(root.busiestJob.cpu)
      color: Qt.alpha(Commons.Color.foreground, 0.6)
      font.family: Style.font.family; font.pixelSize: Style.font.caption
    }
  }

  // Apps table.
  Column {
    visible: root.appList.length > 0
    width: parent.width
    spacing: Style.space(2)

    Item {
      width: parent.width
      height: appsHeader.implicitHeight + Style.space(2)
      Text {
        id: appsHeader
        text: "Apps"
        color: Commons.Color.foreground
        font.family: Style.font.family; font.pixelSize: Style.font.body; font.weight: Font.Medium
      }
      Text {
        anchors.right: parent.right
        anchors.baseline: appsHeader.baseline
        visible: root.hint !== ""
        text: root.hint
        color: Qt.alpha(Commons.Color.foreground, 0.85)
        font.family: Style.font.family; font.pixelSize: Style.font.caption
      }
    }

    Repeater {
      model: root.appList
      delegate: Item {
        id: row
        required property var modelData
        readonly property var st: root.stateOf(modelData)
        readonly property bool actionable: root.validUnits(modelData).length > 0
        readonly property bool showActions: actionable && (rowHover.hovered || st.frozen || st.calmed)
        width: parent.width
        height: root.actionSize + Style.space(2)

        HoverHandler { id: rowHover }
        Rectangle {
          anchors.fill: parent
          radius: Style.space(5)
          color: rowHover.hovered ? Qt.alpha(Commons.Color.foreground, 0.06) : "transparent"
        }

        Text {
          anchors.left: parent.left
          anchors.leftMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width - root.cpuColumn - root.memColumn - root.actionSize * 2 - Style.space(16)
          elide: Text.ElideRight
          text: row.modelData.name || row.modelData.id
          color: row.st.frozen ? Qt.alpha(Commons.Color.foreground, 0.5) : Commons.Color.foreground
          font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
        }
        Row {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          Text {
            width: root.cpuColumn
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            text: row.st.frozen ? "frozen" : root.pct(row.modelData.cpu)
            color: row.st.frozen ? Commons.Color.accent : Qt.alpha(Commons.Color.foreground, 0.8)
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            font.features: ({ "tnum": 1 })
          }
          Text {
            width: root.memColumn
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            text: root.mem(row.modelData.memory_mib)
            color: Qt.alpha(Commons.Color.foreground, 0.6)
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            font.features: ({ "tnum": 1 })
          }
          Item { width: Style.space(8); height: 1 }
          Repeater {
            model: [
              { glyph: root.calmGlyph, active: row.st.calmed, action: row.st.calmed ? "uncalm" : "calm",
                tip: (row.st.calmed ? "Restore CPU priority for " : "Calm (low CPU priority) ") + (row.modelData.name || row.modelData.id) },
              { glyph: root.freezeGlyph, active: row.st.frozen, action: row.st.frozen ? "thaw" : "freeze",
                tip: (row.st.frozen ? "Thaw " : "Freeze ") + (row.modelData.name || row.modelData.id) }
            ]
            delegate: Rectangle {
              id: btn
              required property var modelData
              width: root.actionSize
              height: root.actionSize
              radius: Style.space(5)
              opacity: row.showActions ? 1 : 0
              color: btn.modelData.active ? Qt.alpha(Commons.Color.accent, 0.22)
                   : area.containsMouse ? Qt.alpha(Commons.Color.foreground, 0.16) : "transparent"
              Text {
                anchors.centerIn: parent
                text: btn.modelData.glyph
                color: btn.modelData.active ? Commons.Color.accent : Qt.alpha(Commons.Color.foreground, area.containsMouse ? 1 : 0.7)
                font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
              }
              MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                enabled: row.showActions
                cursorShape: Qt.PointingHandCursor
                onContainsMouseChanged: root.hint = containsMouse ? btn.modelData.tip : (root.hint === btn.modelData.tip ? "" : root.hint)
                onClicked: root.act(row.modelData, btn.modelData.action)
              }
            }
          }
        }
      }
    }
  }

  Text {
    visible: root.errorText !== ""
    width: parent.width
    wrapMode: Text.WordWrap
    text: root.errorText
    color: Commons.Color.foreground
    font.family: Style.font.family; font.pixelSize: Style.font.caption
  }
}
