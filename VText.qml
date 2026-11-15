import QtQuick
import qs.Commons
import qs.Commons as Commons

Text {
  textFormat: Text.PlainText
  property bool muted: false
  color: muted ? Qt.alpha(Commons.Color.foreground, 0.62) : Commons.Color.foreground
  font.family: Style.font.family
  font.pixelSize: Style.font.bodySmall
  wrapMode: Text.Wrap
  renderType: Text.NativeRendering
}
