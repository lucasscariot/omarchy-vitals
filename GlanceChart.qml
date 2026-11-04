import QtQuick
import qs.Commons
import qs.Commons as Commons

Item {
  id: root
  property var points: []
  property string metric: "cpu"
  property string title: "CPU"
  property var current: undefined
  property string detail: ""
  property string temperatureUnit: "C"
  property real now: 0
  property color lineColor: Commons.Color.accent
  readonly property real labelWidth: Style.space(118)
  readonly property var values: points.filter(p => p.values[metric] !== null && p.values[metric] !== undefined && isFinite(p.values[metric]))
  readonly property real peak: Math.max.apply(null, values.map(p => p.peaks[metric]).concat([0]))
  readonly property real ceiling: metric === "temperature" ? Math.max(60, Math.ceil(peak / 10) * 10) : 100
  readonly property real average: {
    var sum = 0, count = 0
    for (var p of values) { var n = p.weights[metric] || p.count; sum += p.values[metric] * n; count += n }
    return count ? sum / count : 0
  }
  implicitHeight: Math.max(labels.implicitHeight, Style.space(48))
  function convert(v) { return metric === "temperature" && temperatureUnit === "F" ? v * 1.8 + 32 : v }
  function formatted(v) { return v === undefined ? "…" : v === null || !isFinite(v) ? "—" : Math.round(convert(v)) + (metric === "temperature" ? "°" + temperatureUnit : "%") }
  function canConnect(previous, point) {
    return !!previous && point.contiguous && previous.contiguous && point.first - previous.last <= (point.gap_limit || 30)
  }
  onPointsChanged: plot.requestPaint()
  onNowChanged: plot.requestPaint()
  onLineColorChanged: plot.requestPaint()
  Column {
    id: labels
    width: root.labelWidth
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(1)
    VText { width: parent.width; text: root.title + (root.detail ? " · " + root.detail : ""); muted: true; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: Style.font.caption }
    VText { text: root.formatted(root.current); font.pixelSize: Style.font.heading; font.weight: Font.Medium; font.features: ({"tnum": 1}) }
    VText { muted: true; font.pixelSize: Style.font.caption; text: root.values.length ? "avg " + Math.round(root.convert(root.average)) + " · peak " + Math.round(root.convert(root.peak)) : "—" }
  }
  Canvas {
    id: plot
    x: root.labelWidth + Style.space(8)
    width: root.width - x; height: root.height
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
      var ctx = getContext("2d"); ctx.reset()
      ctx.strokeStyle = Qt.alpha(Commons.Color.foreground, 0.1); ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(0, height - 1.5); ctx.lineTo(width, height - 1.5); ctx.stroke()
      ctx.strokeStyle = root.lineColor; ctx.lineWidth = 1.5; ctx.beginPath()
      var previous = null, lastX = 0, lastY = 0
      for (var p of root.points) {
        var value = p.values[root.metric]
        if (value === null || value === undefined || !isFinite(value)) { previous = null; continue }
        var x = width * (p.first - (root.now - 3600)) / 3600
        if (x < 0 || x > width) { previous = null; continue }
        var y = height - 2 - Math.max(0, Math.min(root.ceiling, value)) / root.ceiling * (height - 4)
        if (!root.canConnect(previous, p)) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
        previous = p; lastX = x; lastY = y
      }
      ctx.stroke()
      if (previous) { ctx.fillStyle = root.lineColor; ctx.beginPath(); ctx.arc(lastX, lastY, 2.5, 0, Math.PI * 2); ctx.fill() }
    }
  }
}
