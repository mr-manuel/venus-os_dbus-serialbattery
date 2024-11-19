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
				text: "Charge Mode"
				dataItem.uid: root.bindPrefix + "/Info/ChargeMode"
				allowed: defaultAllowed && dataItem.isValid
			}

			ListQuantityItem {
				//% "Charge Voltage Limit (CVL)"
				text: qsTrId("batteryparameters_charge_voltage_limit_cvl")
				dataItem.uid: root.bindPrefix + "/Info/MaxChargeVoltage"
				unit: VenusOS.Units_Volt_DC
			}

			ListTextItem {
				text: "Charge Limitation"
				dataItem.uid: root.bindPrefix + "/Info/ChargeLimitation"
				allowed: defaultAllowed && dataItem.isValid
			}

			ListQuantityItem {
				//% "Charge Current Limit (CCL)"
				text: qsTrId("batteryparameters_charge_current_limit_ccl")
				dataItem.uid: root.bindPrefix + "/Info/MaxChargeCurrent"
				unit: VenusOS.Units_Amp
			}

			ListTextItem {
				text: "Discharge Limitation"
				dataItem.uid: root.bindPrefix + "/Info/DischargeLimitation"
				allowed: defaultAllowed && dataItem.isValid
			}

			ListQuantityItem {
				//% "Discharge Current Limit (DCL)"
				text: qsTrId("batteryparameters_discharge_current_limit_dcl")
				dataItem.uid: root.bindPrefix + "/Info/MaxDischargeCurrent"
				unit: VenusOS.Units_Amp
			}

			ListQuantityItem {
				//% "Low Voltage Disconnect (always ignored)"
				text: qsTrId("batteryparameters_low_voltage_disconnect_always_ignored")
				dataItem.uid: root.bindPrefix + "/Info/BatteryLowVoltage"
				showAccessLevel: VenusOS.User_AccessType_Service
				unit: VenusOS.Units_Volt_DC
			}

			ListItem {
				text: "Driver Debug"

				VeQuickItem {
					id: chargeModeDebug
					uid: root.bindPrefix + "/Info/ChargeModeDebug"
				}

				bottomContentChildren: [
					ListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebug.value
						horizontalAlignment: Text.AlignHCenter
					}
				]

				allowed: chargeModeDebug.value !== undefined && chargeModeDebug.value !== ""
			}

			ListItem {
				text: "Driver Debug - Float"

				VeQuickItem {
					id: chargeModeDebugFloat
					uid: root.bindPrefix + "/Info/ChargeModeDebugFloat"
				}

				bottomContentChildren: [
					ListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebugFloat.value
						horizontalAlignment: Text.AlignHCenter
					}
				]

				allowed: chargeModeDebugFloat.value !== undefined && chargeModeDebugFloat.value !== ""
			}

			ListItem {
				text: "Driver Debug - Bulk"

				VeQuickItem {
					id: chargeModeDebugBulk
					uid: root.bindPrefix + "/Info/ChargeModeDebugBulk"
				}

				bottomContentChildren: [
					ListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebugBulk.value
						horizontalAlignment: Text.AlignHCenter
					}
				]

				allowed: chargeModeDebugBulk.value !== undefined && chargeModeDebugBulk.value !== ""
			}

		}
	}
}
