/*
** Copyright (C) 2023 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	// "dbus-serialbattery - Settings"
	title: "dbus-serialbattery - Settings"

	property string bindPrefix

	VeQuickItem {
		id: hasSettingsItem
		uid: root.bindPrefix + "/Settings/HasSettings"
	}

	GradientListView {
		model: VisibleItemModel {

			SettingsListHeader {
				// "IO"
				text: "IO"
			}

			ListText {
				text: CommonWords.allow_to_charge
				dataItem.uid: root.bindPrefix + "/Io/AllowToCharge"
				preferredVisible: dataItem.valid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListText {
				text: CommonWords.allow_to_discharge
				dataItem.uid: root.bindPrefix + "/Io/AllowToDischarge"
				preferredVisible: dataItem.valid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListText {
				// "Allow to balance"
				text: "Allow to balance"
				dataItem.uid: root.bindPrefix + "/Io/AllowToBalance"
				preferredVisible: dataItem.valid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListText {
				// "Allow to heat"
				text: "Allow to heat"
				dataItem.uid: root.bindPrefix + "/Io/AllowToHeat"
				preferredVisible: dataItem.valid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			SettingsListHeader {
				// "Settings"
				text: "Settings"
				preferredVisible: hasSettingsItem.valid && hasSettingsItem.value === 1
			}

			ListSwitch {
				// "Force charging off"
				text: "Force charging off"
				dataItem.uid: root.bindPrefix + "/Settings/ForceChargingOff"
				preferredVisible: dataItem.valid
			}

			ListSwitch {
				// "Force discharging off"
				text: "Force discharging off"
				dataItem.uid: root.bindPrefix + "/Settings/ForceDischargingOff"
				preferredVisible: dataItem.valid
			}

			ListSwitch {
				// "Turn balancing off"
				text: "Turn balancing off"
				dataItem.uid: root.bindPrefix + "/Settings/TurnBalancingOff"
				preferredVisible: dataItem.valid
			}

			ListSwitch {
				// "Turn heating off"
				text: "Turn heating off"
				dataItem.uid: root.bindPrefix + "/Settings/TurnHeatingOff"
				preferredVisible: dataItem.valid
			}

			ListButton {
				// "Reset SoC to"
				text: "Reset SoC to"
				secondaryText: Units.getCombinedDisplayText(VenusOS.Units_Percentage, resetSocToItem.value)
				preferredVisible: resetSocToItem.valid
				onClicked: Global.dialogLayer.open(resetSocToDialogComponent)

				Component {
					id: resetSocToDialogComponent

					ModalDialog {

						property int resetSocTo: resetSocToItem.value

						// "Reset SoC to"
						title: "Reset SoC to"

						onAccepted: {
							resetSocToItem.setValue(resetSocTo)
							resetSocToApplyItem.setValue(1)
						}

						contentItem: ModalDialog.FocusableContentItem {
							Column {
								width: parent.width

								Label {
									anchors.horizontalCenter: parent.horizontalCenter
									font.pixelSize: Theme.font_size_h3
									text: "%1%".arg(resetSocTo)
								}

								Item {
									width: 1
									height: Theme.geometry_modalDialog_content_margins / 2
								}

								Slider {
									id: resetToSocSlider

									anchors.horizontalCenter: parent.horizontalCenter
									width: parent.width - (2 * Theme.geometry_modalDialog_content_horizontalMargin)
									value: resetSocTo
									from: 0
									to: 100
									stepSize: 1
									focus: true
									onMoved: resetSocTo = value

									KeyNavigationHighlight {
										anchors {
											fill: parent
											leftMargin: -Theme.geometry_listItem_flat_content_horizontalMargin
											rightMargin: -Theme.geometry_listItem_flat_content_horizontalMargin
											topMargin: -Theme.geometry_listItem_content_verticalMargin
											bottomMargin: -Theme.geometry_listItem_content_verticalMargin
										}
										active: parent.activeFocus
									}
								}
							}
						}
					}

				}

				VeQuickItem {
					id: resetSocToItem
					uid: root.bindPrefix + "/Settings/ResetSocTo"
				}

				VeQuickItem {
					id: resetSocToApplyItem
					uid: root.bindPrefix + "/Settings/ResetSocToApply"
				}
			}
		}
	}
}
