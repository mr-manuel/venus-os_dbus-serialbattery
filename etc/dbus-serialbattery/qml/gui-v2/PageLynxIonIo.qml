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
		model: ObjectModel {
			ListTextItem {
				//% "System Switch"
				text: qsTrId("lynxionio_system_switch")
				dataItem.uid: root.bindPrefix + "/SystemSwitch"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: CommonWords.enabledOrDisabled(dataItem.value)
			}

			ListTextItem {
				text: CommonWords.allow_to_charge
				dataItem.uid: root.bindPrefix + "/Io/AllowToCharge"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListTextItem {
				text: CommonWords.allow_to_discharge
				dataItem.uid: root.bindPrefix + "/Io/AllowToDischarge"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListTextItem {
				text: "Allow to balance"
				dataItem.uid: root.bindPrefix + "/Io/AllowToBalance"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListSwitch {
				text: "Force charging off"
				dataItem.uid: root.bindPrefix + "/Io/ForceChargingOff"
				allowed: defaultAllowed && dataItem.isValid
			}

			ListSwitch {
				text: "Force discharging off"
				dataItem.uid: root.bindPrefix + "/Io/ForceDischargingOff"
				allowed: defaultAllowed && dataItem.isValid
			}

			ListSwitch {
				text: "Turn balancing off"
				dataItem.uid: root.bindPrefix + "/Io/TurnBalancingOff"
				allowed: defaultAllowed && dataItem.isValid
			}

			ListTextItem {
				//% "External relay"
				text: qsTrId("lynxionio_external_relay")
				dataItem.uid: root.bindPrefix + "/Io/ExternalRelay"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: CommonWords.activeOrInactive(dataItem.value)
			}

			ListTextItem {
				//% "Programmable Contact"
				text: qsTrId("lynxionio_programmable_contact")
				dataItem.uid: root.bindPrefix + "/Io/ProgrammableContact"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: CommonWords.activeOrInactive(dataItem.value)
			}
		}
	}
}
