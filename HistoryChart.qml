import QtQuick
import qs.Commons
import qs.Commons as Commons

Column {
  id: root
  property var points: []
  property string metric: "cpu"
  property string title: "CPU"
  property string unit: "%"
  property real now: Date.now() / 1000
  property int range: 3600
  property var current: undefined
  property color lineColor: Commons.Color.accent
  property string temperatureUnit: "C"
  property var events: []
  signal inspect(real start, real end)
  readonly property var values: points.map(p => p.values[metric]).filter(v => v !== null && v !== undefined && isFinite(v))
  readonly property real ceiling: metric === "temperature" ? Math.max(60, Math.ceil(maximum / 10) * 10) : unit === "%" ? 100 : Math.max(1, maximum)
  readonly property real maximum: Math.max.apply(null, points.map(p => p.peaks[metric]).filter(v => v !== null && v !== undefined).concat([0]))
  readonly property real average: {
    var total = 0, count = 0
    for (var p of points) {
      var v = p.values[metric], n = p.weights[metric] || p.count
      if (v !== null && v !== undefined) { total += v * n; count += n }
    }
    return count ? total / count : 0
  }
  spacing: Style.space(3)
  function value(v) { return metric === "temperature" && temperatureUnit === "F" ? v * 1.8 + 32 : v }
  function formatted(v) {
    if (v === null || v === undefined || !isFinite(v)) return "—"
    if (unit === "B/s") return v >= 1048576 ? (v / 1048576).toFixed(1) + " MiB/s" : (v / 1024).toFixed(1) + " KiB/s"
    return Math.round(value(v)) + (metric === "temperature" ? "°" + temperatureUnit : unit)
  }
  function pointAt(x, width) {
    var t = now - range + range * x / width
    return points.find(p => t >= p.time && t < p.time + p.resolution) || null
  }
  function canConnect(previous, point) {
    return !!previous && point.contiguous && previous.contiguous && point.first - previous.last <= (point.gap_limit || 30)
  }
  onPointsChanged: plot.requestPaint()
  onNowChanged: plot.requestPaint()
  onRangeChanged: plot.requestPaint()
  onLineColorChanged: plot.requestPaint()
  onEventsChanged: plot.requestPaint()
  Row {
    width: parent.width
    VText { width: parent.width / 2; text: root.title + "  " + root.formatted(root.current); font.weight: Font.Medium }
    VText { width: parent.width / 2; horizontalAlignment: Text.AlignRight; muted: true; text: root.values.length ? "avg " + root.formatted(root.average) + " · peak " + root.formatted(root.maximum) : "Collecting history…" }
  }
  Canvas {
    id: plot
    width: parent.width
    height: Style.space(65)
    onWidthChanged: requestPaint()
    onPaint: {
      var ctx = getContext("2d"); ctx.reset()
      ctx.strokeStyle = Qt.alpha(Commons.Color.foreground, 0.12); ctx.lineWidth = 1
      for (var i = 0; i < 3; i++) { var y = i * (height - 1) / 2; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke() }
      ctx.strokeStyle = root.lineColor; ctx.lineWidth = 1.5; ctx.beginPath()
      var previous = null
      for (var p of root.points) {
        var v = p.values[root.metric]
        if (v === null || v === undefined) { previous = null; continue }
        var x = width * (p.first - (root.now - root.range)) / root.range
        var py = height - 1 - Math.max(0, Math.min(root.ceiling, v)) / root.ceiling * (height - 2)
        if (x < 0 || x > width) { previous = null; continue }
        if (!root.canConnect(previous, p)) ctx.moveTo(x, py)
        else ctx.lineTo(x, py)
        previous = p
      }
      ctx.stroke()
      ctx.fillStyle = root.lineColor
      for (var point of root.points) {
        var value = point.values[root.metric]
        if (value === null || value === undefined) continue
        var px = width * (point.first - (root.now - root.range)) / root.range
        if (px < 0 || px > width) continue
        ctx.beginPath(); ctx.arc(px, height - 1 - Math.max(0, Math.min(root.ceiling, value)) / root.ceiling * (height - 2), 1.5, 0, Math.PI * 2); ctx.fill()
      }
      ctx.strokeStyle = Qt.alpha(root.lineColor, 0.25)
      for (var event of root.events) {
        var ex = width * (event.time - (root.now - root.range)) / root.range
        if (ex < 0 || ex > width) continue
        ctx.beginPath(); ctx.moveTo(ex, 0); ctx.lineTo(ex, height); ctx.stroke()
      }
    }
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onPositionChanged: function(mouse) {
        var p = root.pointAt(mouse.x, width)
        caption.text = p ? new Date(p.first * 1000).toLocaleTimeString() + " · " + root.formatted(p.values[root.metric]) + " · peak " + root.formatted(p.peaks[root.metric]) : "No sample"
      }
      onClicked: function(mouse) { var p = root.pointAt(mouse.x, width); if (p) root.inspect(p.time, p.time + p.resolution) }
    }
  }
  Row {
    width: parent.width
    VText { width: parent.width / 2; muted: true; text: root.formatted(0) + "–" + root.formatted(root.ceiling) + " · " + (root.range === 3600 ? "past hour" : root.range === 86400 ? "past day" : root.range === 604800 ? "past week" : "past month") }
    VText { id: caption; width: parent.width / 2; horizontalAlignment: Text.AlignRight; muted: true; font.pixelSize: Style.font.caption }
  }
}
