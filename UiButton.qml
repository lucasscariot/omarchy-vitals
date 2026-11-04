import QtQuick
import qs.Commons
import qs.Commons as Commons

Rectangle {
  id: root
  property string text: ""
  property bool checked: false
  property bool available: true
  signal clicked()
  implicitWidth: caption.implicitWidth + Style.space(16)
  implicitHeight: Style.space(28)
  radius: Style.space(5)
  activeFocusOnTab: available
  opacity: available ? 1 : 0.4
  color: checked ? Qt.alpha(Commons.Color.accent, 0.22) : area.containsMouse ? Qt.alpha(Commons.Color.foreground, 0.12) : Qt.alpha(Commons.Color.foreground, 0.05)
  border.width: activeFocus ? 1 : 0
  border.color: Commons.Color.accent
  VText { id: caption; anchors.centerIn: parent; text: root.text; color: root.checked ? Commons.Color.accent : Commons.Color.foreground; wrapMode: Text.NoWrap }
  MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; enabled: root.available; cursorShape: Qt.PointingHandCursor; onClicked: { root.forceActiveFocus(); root.clicked() } }
  Keys.onReturnPressed: if (available) clicked()
  Keys.onEnterPressed: if (available) clicked()
  Keys.onSpacePressed: if (available) clicked()
}
