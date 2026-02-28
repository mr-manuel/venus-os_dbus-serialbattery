/*
** Copyright (C) 2023 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	property string bindPrefix

	VeQuickItem {
		id: hasSettingsItem
		uid: root.bindPrefix + "/Settings/HasSettings"
	}

	GradientListView {
		model: ObjectModel {

			ListLabel {
				text: "IO"
			}

			ListTextItem {
				text: CommonWords.allow_to_charge
				dataItem.uid: root.bindPrefix + "/Io/AllowToCharge"
				allowed: dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListTextItem {
				text: CommonWords.allow_to_discharge
				dataItem.uid: root.bindPrefix + "/Io/AllowToDischarge"
				allowed: dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListTextItem {
				text: "Allow to balance"
				dataItem.uid: root.bindPrefix + "/Io/AllowToBalance"
				allowed: dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListTextItem {
				text: "Allow to heat"
				dataItem.uid: root.bindPrefix + "/Io/AllowToHeat"
				allowed: dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListLabel {
				text: "Settings"
				allowed: hasSettingsItem.isValid && hasSettingsItem.value === 1
			}

			ListSwitch {
				text: "Force charging off"
				dataItem.uid: root.bindPrefix + "/Settings/ForceChargingOff"
				allowed: dataItem.isValid
			}

			ListSwitch {
				text: "Force discharging off"
				dataItem.uid: root.bindPrefix + "/Settings/ForceDischargingOff"
				allowed: dataItem.isValid
			}

			ListSwitch {
				text: "Turn balancing off"
				dataItem.uid: root.bindPrefix + "/Settings/TurnBalancingOff"
				allowed: dataItem.isValid
			}

			ListSwitch {
				text: "Turn heating off"
				dataItem.uid: root.bindPrefix + "/Settings/TurnHeatingOff"
				allowed: dataItem.isValid
			}

			ListSpinBox {
				text: "Reset SoC to"
				dataItem.uid: root.bindPrefix + "/Settings/ResetSocTo"
				allowed: dataItem.isValid
				suffix: "%"
				from: 0
				to: 100
				stepSize: 1
			}

			ListButton {
				text: "Apply \"Reset SoC to\""
				secondaryText: "Apply"
				onClicked: resetSocToApplyItem.setValue(1)
				allowed: resetSocToApplyItem.isValid

				VeQuickItem {
					id: resetSocToApplyItem
					uid: root.bindPrefix + "/Settings/ResetSocToApply"
				}
			}
		}
	}
}
