import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

Panel {
  id: root
  moduleName: "lucas.resource-usage"
  manageIpc: false
  property var service: bar && bar.shell ? bar.shell.serviceFor("lucas.resource-usage") : null
  readonly property var sample: service ? service.sample : ({})
  readonly property var prefs: service ? service.prefs : ({})
  readonly property var modules: {
    var selected = String(setting("barModules", (prefs.modules || ["cpu", "ram", "temperature"]).join(","))).split(",").filter(m => ["cpu", "ram", "temperature", "network", "disk", "gpu", "fans", "battery", "power"].includes(m))
    selected = selected.filter((m, i) => selected.indexOf(m) === i).slice(0, 9)
    return selected.length ? selected : ["cpu", "ram", "temperature"]
  }
  readonly property bool graphs: setting("barStyle", prefs.style || "text") === "graph"
  property string clientId: "panel-" + Math.random().toString(36).slice(2)
  property string page: "Overview"
  onPageChanged: Qt.callLater(function() { scroll.contentY = 0 })
  property bool showEvents: true
  property var historyMetrics: ["cpu", "ram", "temperature"]
  readonly property var historyChoices: [
    {key: "cpu", title: "CPU", unit: "%"}, {key: "ram", title: "Memory", unit: "%"},
    {key: "temperature", title: "Temperature", unit: "°C"},
    {key: "cpu_pressure", title: "CPU pressure", unit: "%"},
    {key: "memory_pressure", title: "Memory pressure", unit: "%"},
    {key: "io_pressure", title: "I/O pressure", unit: "%"},
    {key: "rx", title: "Download", unit: "B/s"}, {key: "tx", title: "Upload", unit: "B/s"},
    {key: "disk_read", title: "Disk read", unit: "B/s"}, {key: "disk_write", title: "Disk write", unit: "B/s"},
    {key: "gpu", title: "GPU", unit: "%"}]
  implicitWidth: button.implicitWidth
  implicitHeight: bar ? bar.barSize : Style.space(26)
  onOpenedChanged: if (service) service.setViewing(clientId, opened)
  onServiceChanged: if (service && opened) service.setViewing(clientId, true)
  Component.onDestruction: if (service) service.setViewing(clientId, false)
  function percent(v) { return v === null || v === undefined ? "—" : Math.round(v) + "%" }
  function temperatureText(v) { return v === null || v === undefined ? "—" : Math.round(prefs.temperatureUnit === "F" ? v * 1.8 + 32 : v) + "°" + (prefs.temperatureUnit || "C") }
  function rate(v) { return v === null || v === undefined ? "—" : v >= 1048576 ? (v / 1048576).toFixed(1) + "M" : Math.round(v / 1024) + "K" }
  function readout(metric) {
    if (metric === "cpu") return " " + percent(sample.cpu)
    if (metric === "ram") return " " + percent(sample.ram)
    if (metric === "temperature") return " " + temperatureText(sample.temperature)
    if (metric === "network") return "↓" + rate(sample.rx)
    if (metric === "disk") return " " + rate(sample.disk_write)
    if (metric === "gpu") return "GPU " + percent(sample.gpu)
    var hw = sample.hardware || ({})
    if (metric === "fans") { var fan = (hw.fans || []).find(f => f.rpm !== null); return "Fan " + (fan ? Math.round(fan.rpm) : "—") }
    if (metric === "battery") return "Bat " + percent((hw.batteries || [])[0] ? hw.batteries[0].percent : null)
    if (metric === "power") { var battery = (hw.batteries || []).find(b => b.watts !== null); var source = battery || (hw.power || []).find(p => p.watts !== null); return "W " + (source ? source.watts.toFixed(1) : "—") }
    return "—"
  }
  function inspect(start, end) { if (service) service.send({op: "detail", start: start, end: end}) }
  function saveDisplay(changes) {
    if (bar && bar.shell) bar.shell.updateEntryInline(moduleName, Object.assign({}, settings, changes))
  }
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    fixedWidth: Style.space(Math.max(52, root.modules.length * (root.graphs ? 72 : 52)))
    tooltipText: root.modules.map(m => m + ": " + root.readout(m)).join("\n") + (root.sample.incidents && root.sample.incidents.length ? "\nResource pressure active" : "")
    onPressed: function(b) { root.toggle() }
    Row {
      id: readouts
      anchors.centerIn: parent
      spacing: Style.space(8)
      scale: Math.min(1, button.width / Math.max(1, implicitWidth))
      Repeater {
        model: root.modules
        Row {
          required property string modelData
          property string metric: modelData
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(3)
          Text {
            text: root.readout(parent.metric)
            color: button.foreground
            font.family: button.fontFamily
            font.pixelSize: button.fontSize
            font.features: ({"tnum": 1})
          }
          Canvas {
            id: mini
            visible: root.graphs
            width: visible ? Style.space(24) : 0
            height: Style.space(13)
            anchors.verticalCenter: parent.verticalCenter
            property var samples: root.service ? root.service.barPoints : []
            onSamplesChanged: requestPaint()
            onPaint: {
              var ctx = getContext("2d"); ctx.reset(); ctx.strokeStyle = button.foreground; ctx.lineWidth = 1; ctx.beginPath()
              var values = samples.map(p => p[parent.metric]).filter(v => v !== null && v !== undefined)
              var max = ["cpu", "ram", "gpu"].includes(parent.metric) ? 100 : Math.max.apply(null, values.concat([1]))
              for (var i = 0; i < values.length; i++) { var x = width * i / Math.max(1, values.length - 1), y = height - 1 - values[i] / max * (height - 2); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y) }
              ctx.stroke()
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
    contentWidth: panel.fittedContentWidth(Style.space(580))
    contentHeight: panel.fittedContentHeight(Math.min(panelContent.implicitHeight, Style.space(690)))
    FocusScope {
      id: keys
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: root.close()
      Flickable {
        id: scroll
        anchors.fill: parent
        contentHeight: panelContent.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column {
          id: panelContent
          width: parent.width
          spacing: Style.space(10)
          VText { width: parent.width; text: "Vitals"; font.pixelSize: Style.font.heading; font.weight: Font.Medium }
          Flow {
            width: parent.width; spacing: Style.space(5)
            Repeater {
              model: ["Overview", "Apps", "Agents", "Hardware", "History", "Timeline", "Jobs", "Settings"]
              UiButton { required property string modelData; text: modelData; checked: root.page === modelData; onClicked: { root.page = modelData; scroll.contentY = 0 } }
            }
          }
          VText { visible: !root.service; width: parent.width; text: "Waiting for the Vitals service…" }
          VText { visible: !!root.service && !!root.service.errorText; width: parent.width; text: root.service ? root.service.errorText : "" }
          VText { visible: !!root.sample.warning; width: parent.width; text: root.sample.warning || "" }
          Loader {
            width: parent.width
            active: root.opened && !!root.service
            sourceComponent: root.page === "Overview" ? overview : root.page === "Apps" ? apps : root.page === "Agents" ? agents : root.page === "Hardware" ? hardware : root.page === "History" ? history : root.page === "Timeline" ? timeline : root.page === "Jobs" ? jobs : preferences
          }
        }
      }
    }
  }
  Component {
    id: overview
    Column {
      width: parent.width; spacing: Style.space(10)
      VText { width: parent.width; text: "CPU " + root.percent(root.sample.cpu) + " · Memory " + root.percent(root.sample.ram) + " · CPU " + root.temperatureText(root.sample.temperature); font.weight: Font.Medium }
      VText { width: parent.width; muted: true; text: root.sample.used_gib === undefined ? "Collecting…" : root.sample.used_gib.toFixed(1) + " / " + root.sample.total_gib.toFixed(1) + " GiB · " + (root.sample.available_gib || 0).toFixed(1) + " GiB available · " + (root.sample.swap_gib || 0).toFixed(1) + " GiB swap" }
      VText { width: parent.width; text: "Tasks waiting · CPU " + root.percent(root.sample.cpu_pressure) + " · memory " + root.percent(root.sample.memory_pressure) + " · I/O " + root.percent(root.sample.io_pressure) }
      VText { width: parent.width; muted: true; text: "Swap in " + root.rate(root.sample.pswpin) + "/s · swap out " + root.rate(root.sample.pswpout) + "/s. CPU percentages use whole-machine capacity." }
      Repeater {
        model: root.sample.incidents || []
        VText { required property var modelData; width: parent.width; text: modelData.message; color: Commons.Color.accent }
      }
      VText { width: parent.width; text: "Apps"; font.weight: Font.Medium }
      AppList { width: parent.width; service: root.service; compact: true; onShowAll: root.page = "Apps" }
      UiButton { text: "Agents and projects"; onClicked: root.page = "Agents" }
    }
  }
  function reveal(item, top, bottom) {
    var a = item.mapToItem(panelContent, 0, top).y, b = item.mapToItem(panelContent, 0, bottom).y
    if (a < scroll.contentY) scroll.contentY = a
    else if (b > scroll.contentY + scroll.height) scroll.contentY = b - scroll.height
  }
  Component {
    id: apps
    AppList { id: browser; width: parent.width; service: root.service; onRevealRequested: function(top, bottom) { root.reveal(browser, top, bottom) } }
  }
  Component {
    id: agents
    AppList { id: agentBrowser; width: parent.width; service: root.service; agentsOnly: true; onRevealRequested: function(top, bottom) { root.reveal(agentBrowser, top, bottom) } }
  }
  Component { id: hardware; HardwareView { width: parent.width; sample: root.sample; temperatureUnit: root.prefs.temperatureUnit || "C" } }
  Component { id: jobs; JobsView { width: parent.width; service: root.service } }
  Component { id: preferences; SettingsView { width: parent.width; service: root.service; displaySettings: root.settings; onDisplayChanged: function(settings) { root.saveDisplay(settings) } } }
  Component { id: timeline; TimelineView { width: parent.width; service: root.service; onInspect: function(start, end) { root.inspect(start, end); root.page = "History" } } }
  Component {
    id: history
    Column {
      width: parent.width; spacing: Style.space(10)
      Flow {
        width: parent.width; spacing: Style.space(5)
        Repeater {
          model: [{seconds: 3600, label: "1 hour"}, {seconds: 86400, label: "24 hours"}, {seconds: 604800, label: "7 days"}].concat(root.prefs.retentionDays >= 30 ? [{seconds: 2592000, label: "30 days"}] : [])
          UiButton { required property var modelData; text: modelData.label; checked: root.service.historyRange === modelData.seconds; onClicked: root.service.setRange(modelData.seconds) }
        }
        UiButton { text: "Events: " + (root.showEvents ? "on" : "off"); checked: root.showEvents; onClicked: root.showEvents = !root.showEvents }
      }
      Flow {
        width: parent.width; spacing: Style.space(5)
        Repeater {
          model: root.historyChoices
          UiButton {
            required property var modelData
            text: modelData.title; checked: root.historyMetrics.includes(modelData.key)
            onClicked: {
              var next = root.historyMetrics.slice(), index = next.indexOf(modelData.key)
              if (index < 0) next.push(modelData.key); else if (next.length > 1) next.splice(index, 1)
              root.historyMetrics = next
            }
          }
        }
      }
      Repeater {
        model: root.historyChoices.filter(m => root.historyMetrics.includes(m.key))
        HistoryChart {
          required property var modelData
          width: parent.width
          metric: modelData.key; title: modelData.title
          unit: modelData.unit
          current: root.sample[modelData.key]
          temperatureUnit: root.prefs.temperatureUnit || "C"
          points: root.service.points
          events: root.showEvents ? root.service.events : []
          range: root.service.historyRange
          now: root.sample.time || Date.now() / 1000
          onInspect: function(start, end) { root.inspect(start, end) }
        }
      }
      VText { width: parent.width; muted: true; text: "Click a chart interval to inspect sampled CPU, memory and block I/O contributors. Network and GPU charts show system totals. Gaps are left empty; peaks refer to observed samples. Vertical markers identify recorded events." }
      VText { visible: !!root.service.detail.count; width: parent.width; text: "Selected interval · " + new Date((root.service.detail.first || 0) * 1000).toLocaleString() + " · " + (root.service.detail.count || 0) + " samples" }
      Repeater {
        model: root.service.detail.contributors || []
        VText { required property var modelData; width: parent.width; text: (modelData.project ? modelData.project + " / " : "") + modelData.name + " · " + modelData.cpu.toFixed(1) + "% CPU · " + Math.round(modelData.memory_mib) + " MiB · peak " + Math.round(modelData.peak_memory_mib) + " MiB" }
      }
    }
  }
}
