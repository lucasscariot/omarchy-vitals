import QtQuick
import qs.Commons
import qs.Commons as Commons

// One compact metric row: live value on the left, past-hour sparkline on the right.
Item {
  id: root
  property var points: []
  property string metric: "cpu"
  property string title: "CPU"
  property string unit: "%"
  property var current: undefined
  property string detail: ""
  property real now: 0
  property color lineColor: Commons.Color.accent
  readonly property real labelWidth: Style.space(118)
  readonly property var values: points.map(p => p[metric]).filter(v => v !== null && v !== undefined && isFinite(v))
  readonly property real maximum: values.length ? Math.max.apply(null, values) : 0
  readonly property real average: values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0
  readonly property real ceiling: metric === "temperature" ? Math.max(60, Math.ceil(maximum / 10) * 10) : 100
  implicitHeight: Math.max(labels.implicitHeight, Style.space(44))
  onPointsChanged: plot.requestPaint()
  onNowChanged: plot.requestPaint()
  onLineColorChanged: plot.requestPaint()

  Column {
    id: labels
    width: root.labelWidth
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(1)
    Text {
      width: parent.width
      elide: Text.ElideRight
      text: root.title + (root.detail ? "  ·  " + root.detail : "")
      color: Qt.alpha(Commons.Color.foreground, 0.65)
      font.family: Style.font.family; font.pixelSize: Style.font.caption
    }
    Text {
      text: root.current === undefined ? "…" : root.current === null || !isFinite(root.current) ? "—" : Math.round(root.current) + root.unit
      color: Commons.Color.foreground
      font.family: Style.font.family; font.pixelSize: Style.font.heading; font.weight: Font.Medium
      font.features: ({ "tnum": 1 })
    }
    Text {
      text: root.values.length ? "avg " + Math.round(root.average) + "  ·  peak " + Math.round(root.maximum) : "collecting…"
      color: Qt.alpha(Commons.Color.foreground, 0.5)
      font.family: Style.font.family; font.pixelSize: Style.font.caption
      font.features: ({ "tnum": 1 })
    }
  }

  Canvas {
    id: plot
    x: root.labelWidth + Style.space(8)
    width: root.width - x
    height: root.height
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.strokeStyle = Qt.alpha(Commons.Color.foreground, 0.1)
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(0, height - 1.5); ctx.lineTo(width, height - 1.5); ctx.stroke()
      ctx.strokeStyle = root.lineColor
      ctx.fillStyle = root.lineColor
      ctx.lineWidth = 1.5
      ctx.beginPath()
      var previousTime = 0
      var connected = false
      for (var p of root.points) {
        var v = p[root.metric]
        if (v === null || v === undefined || !isFinite(v)) { connected = false; continue }
        var x = width * (p.time - (root.now - 3600)) / 3600
        var py = height - 2 - Math.max(0, Math.min(root.ceiling, v)) / root.ceiling * (height - 4)
        if (x < 0 || x > width) { connected = false; continue }
        if (!connected || p.time - previousTime > 30) ctx.moveTo(x, py)
        else ctx.lineTo(x, py)
        connected = true; previousTime = p.time
      }
      ctx.stroke()
      if (root.points.length) {
        var last = root.points[root.points.length - 1]
        var value = last[root.metric]
        if (value !== null && value !== undefined) {
          ctx.beginPath()
          ctx.arc(width * (last.time - (root.now - 3600)) / 3600, height - 2 - Math.max(0, Math.min(root.ceiling, value)) / root.ceiling * (height - 4), 2.5, 0, Math.PI * 2)
          ctx.fill()
        }
      }
    }
  }
}
