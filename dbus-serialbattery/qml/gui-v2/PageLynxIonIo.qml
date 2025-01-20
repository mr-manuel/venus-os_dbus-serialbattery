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
			ListText {
				//% "System Switch"
				text: qsTrId("lynxionio_system_switch")
				dataItem.uid: root.bindPrefix + "/SystemSwitch"
				preferredVisible: dataItem.isValid
				secondaryText: CommonWords.enabledOrDisabled(dataItem.value)
			}

			ListText {
				text: CommonWords.allow_to_charge
				dataItem.uid: root.bindPrefix + "/Io/AllowToCharge"
				preferredVisible: dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListText {
				text: CommonWords.allow_to_discharge
				dataItem.uid: root.bindPrefix + "/Io/AllowToDischarge"
				preferredVisible: dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListText {
				text: "Allow to balance"
				dataItem.uid: root.bindPrefix + "/Io/AllowToBalance"
				preferredVisible: dataItem.isValid
				secondaryText: CommonWords.yesOrNo(dataItem.value)
			}

			ListSwitch {
				text: "Force charging off"
				dataItem.uid: root.bindPrefix + "/Io/ForceChargingOff"
				preferredVisible: dataItem.isValid
			}

			ListSwitch {
				text: "Force discharging off"
				dataItem.uid: root.bindPrefix + "/Io/ForceDischargingOff"
				preferredVisible: dataItem.isValid
			}

			ListSwitch {
				text: "Turn balancing off"
				dataItem.uid: root.bindPrefix + "/Io/TurnBalancingOff"
				preferredVisible: dataItem.isValid
			}

			ListText {
				//% "External relay"
				text: qsTrId("lynxionio_external_relay")
				dataItem.uid: root.bindPrefix + "/Io/ExternalRelay"
				preferredVisible: dataItem.isValid
				secondaryText: CommonWords.activeOrInactive(dataItem.value)
			}

			ListText {
				//% "Programmable Contact"
				text: qsTrId("lynxionio_programmable_contact")
				dataItem.uid: root.bindPrefix + "/Io/ProgrammableContact"
				preferredVisible: dataItem.isValid
				secondaryText: CommonWords.activeOrInactive(dataItem.value)
			}
		}
	}
}
