import QtQuick
import qs.Commons

Column {
  id: root
  property var points: []
  property string metric: "cpu"
  property string title: "CPU"
  property string unit: "%"
  property real now: 0
  property color lineColor: Color.accent
  readonly property var values: points.map(p => p[metric]).filter(v => v !== null && v !== undefined && isFinite(v))
  readonly property real maximum: values.length ? Math.max.apply(null, values) : 0
  readonly property real minimum: values.length ? Math.min.apply(null, values) : 0
  readonly property real average: values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0
  readonly property real ceiling: metric === "temperature" ? Math.max(60, Math.ceil(maximum / 10) * 10) : 100
  spacing: Style.space(5)
  onPointsChanged: plot.requestPaint()
  onNowChanged: plot.requestPaint()
  onLineColorChanged: plot.requestPaint()
  Row {
    width: parent.width
    Text { width: parent.width * 0.32; text: root.title; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; font.weight: Font.Medium }
    Text { width: parent.width * 0.68; horizontalAlignment: Text.AlignRight; text: root.values.length ? "Avg " + Math.round(root.average) + root.unit + "  ·  Peak " + Math.round(root.maximum) + root.unit : "Collecting data…"; color: Qt.alpha(Color.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.font.bodySmall }
  }
  Canvas {
    id: plot
    width: parent.width
    height: Style.space(52)
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.strokeStyle = Qt.alpha(Color.foreground, 0.12)
      ctx.lineWidth = 1
      for (var i = 0; i <= 2; i++) {
        var y = 2 + (height - 4) * i / 2
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
      }
      ctx.strokeStyle = root.lineColor
      ctx.fillStyle = root.lineColor
      ctx.lineWidth = 2
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
  Text {
    text: "0–" + root.ceiling + root.unit
    color: Qt.alpha(Color.foreground, 0.5)
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
}
