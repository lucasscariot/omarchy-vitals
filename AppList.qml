import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons

// Agents summary + per-app Calm/Freeze controls. Renders nothing when the
// collector does not provide "apps"/"agents" (older collectors).
Column {
  id: root
  property var apps: null
  property var agents: null
  property string errorText: ""
  property var pending: ({})   // optimistic overrides keyed by kind:id
  property var queue: []       // queued argv arrays, run one at a time

  readonly property var appList: Array.isArray(apps) ? apps : []
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
    var units = Array.isArray(app.units) ? app.units : []
    if (units.length === 0) return []
    for (var i = 0; i < units.length; i++)
      if (typeof units[i] !== "string" || !unitPattern.test(units[i])) return []
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

  // Agents summary
  Column {
    visible: root.hasAgents
    width: parent.width
    spacing: Style.space(4)
    Row {
      width: parent.width
      Text {
        width: parent.width * 0.3
        text: "Agents"
        color: Commons.Color.foreground
        font.family: Style.font.family; font.pixelSize: Style.font.title; font.weight: Font.Medium
      }
      Text {
        width: parent.width * 0.7
        horizontalAlignment: Text.AlignRight
        text: root.hasAgents ? root.pct(root.agents.cpu) + "  ·  " + root.mem(root.agents.memory_mib) + "  ·  " + root.agents.count + " running" : ""
        color: Commons.Color.accent
        font.family: Style.font.family; font.pixelSize: Style.font.title; font.weight: Font.Medium
        font.features: ({ "tnum": 1 })
        elide: Text.ElideLeft
      }
    }
    Text {
      visible: root.busiestJob !== null
      width: parent.width
      elide: Text.ElideRight
      text: root.busiestJob === null ? "" : (root.busiestJob.command || root.busiestJob.name) + (root.busiestJob.command && root.busiestJob.name ? " (" + root.busiestJob.name + ")" : "") + " " + root.pct(root.busiestJob.cpu)
      color: Qt.alpha(Commons.Color.foreground, 0.75)
      font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
    }
  }

  // Apps
  Column {
    visible: root.appList.length > 0
    width: parent.width
    spacing: Style.space(8)
    Text { text: "Apps"; color: Commons.Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.title; font.weight: Font.Medium }
    Repeater {
      model: root.appList
      delegate: Row {
        id: row
        required property var modelData
        readonly property var st: root.stateOf(modelData)
        readonly property bool actionable: root.validUnits(modelData).length > 0
        width: parent.width
        spacing: Style.space(8)
        Row {
          width: parent.width - buttons.width - row.spacing
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(8)
          Text {
            width: parent.width - stats.implicitWidth - (frozenBadge.visible ? frozenBadge.width : 0) - parent.spacing * (frozenBadge.visible ? 2 : 1)
            elide: Text.ElideRight
            text: row.modelData.name || row.modelData.id
            color: Commons.Color.foreground
            font.family: Style.font.family; font.pixelSize: Style.font.body
          }
          Text {
            id: frozenBadge
            visible: row.st.frozen
            text: "Frozen"
            color: Commons.Color.accent
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall; font.weight: Font.Medium
          }
          Text {
            id: stats
            text: root.pct(row.modelData.cpu) + "  ·  " + root.mem(row.modelData.memory_mib)
            color: Qt.alpha(Commons.Color.foreground, 0.75)
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            font.features: ({ "tnum": 1 })
          }
        }
        Row {
          id: buttons
          spacing: Style.space(6)
          Repeater {
            model: [
              { label: row.st.calmed ? "Uncalm" : "Calm", action: row.st.calmed ? "uncalm" : "calm" },
              { label: row.st.frozen ? "Thaw" : "Freeze", action: row.st.frozen ? "thaw" : "freeze" }
            ]
            delegate: Rectangle {
              id: btn
              required property var modelData
              width: label.implicitWidth + Style.space(16)
              height: label.implicitHeight + Style.space(8)
              radius: Style.space(6)
              opacity: row.actionable ? 1 : 0.4
              color: area.containsMouse && row.actionable ? Qt.alpha(Commons.Color.foreground, 0.2) : Qt.alpha(Commons.Color.foreground, 0.1)
              Text {
                id: label
                anchors.centerIn: parent
                text: btn.modelData.label
                color: Commons.Color.foreground
                font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
              }
              MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                enabled: row.actionable
                cursorShape: Qt.PointingHandCursor
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
    font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
  }
}
