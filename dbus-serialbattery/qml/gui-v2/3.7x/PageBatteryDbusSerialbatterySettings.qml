/*
** Copyright (C) 2023 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	property string bindPrefix

	GradientListView {
		model: VisibleItemModel {

			SettingsListHeader {
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
				text: "Allow to balance"
				dataItem.uid: root.bindPrefix + "/Io/AllowToBalance"
				preferredVisible: dataItem.valid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListSwitch {
				text: "Force charging off"
				dataItem.uid: root.bindPrefix + "/Io/ForceChargingOff"
				preferredVisible: dataItem.valid
			}

			ListSwitch {
				text: "Force discharging off"
				dataItem.uid: root.bindPrefix + "/Io/ForceDischargingOff"
				preferredVisible: dataItem.valid
			}

			ListSwitch {
				text: "Turn balancing off"
				dataItem.uid: root.bindPrefix + "/Io/TurnBalancingOff"
				preferredVisible: dataItem.valid
			}

			SettingsListHeader {
				text: "Settings"
				preferredVisible: resetSocSpinBoxItem.visible
			}

			ListSpinBox {
				id: resetSocSpinBoxItem
				//% "Reset SoC to"
				text: "Reset SoC to"
				dataItem.uid: root.bindPrefix + "/Settings/ResetSoc"
				preferredVisible: dataItem.valid
				suffix: "%"
				from: 0
				to: 100
				stepSize: 1
			}
		}
	}
}
