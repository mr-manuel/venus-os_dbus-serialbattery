/*
** Copyright (C) 2023 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	property var battery

	readonly property bool isFiamm48TL: productId.value === ProductInfo.ProductId_Battery_Fiamm48TL
	readonly property bool isParallelBms: nrOfBmses.dataItem.isValid

	title: battery.name

	GradientListView {
		model: ObjectModel {
			ListRadioButtonGroup {
				text: CommonWords.switch_mode
				dataItem.uid: root.battery.serviceUid + "/Mode"
				allowed: defaultAllowed && dataItem.isValid
				optionModel: [
					{ display: CommonWords.off, value: 4, readOnly: true },
					{ display: CommonWords.standby, value: 0xfc },
					{ display: CommonWords.on, value: 3 },
				]
			}

			ListText {
				text: CommonWords.state
				dataItem.uid: root.battery.serviceUid + "/State"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: {
					if (!dataItem.isValid) {
						return ""
					}
					if (dataItem.value >= 0 && dataItem.value <= 8) {
						//% "Initializing"
						return qsTrId("devicelist_battery_initializing")
					}
					switch (dataItem.value) {
					case VenusOS.Battery_State_Running:
						return CommonWords.running_status
					case VenusOS.Battery_State_Error:
						return CommonWords.error
					// case Battery_State_Unknown is omitted
					case VenusOS.Battery_State_Shutdown:
						//: Status is 'Shutdown'
						//% "Shutdown"
						return qsTrId("devicelist_battery_shutdown")
					case VenusOS.Battery_State_Updating:
						//: Status is 'Updating'
						//% "Updating"
						return qsTrId("devicelist_battery_updating")
					case VenusOS.Battery_State_Standby:
						return CommonWords.standby
					case VenusOS.Battery_State_GoingToRun:
						//: Status is 'Going to run'
						//% "Going to run"
						return qsTrId("devicelist_battery_going_to_run")
					case VenusOS.Battery_State_Precharging:
						//: Status is 'Pre-Charging'
						//% "Pre-Charging"
						return qsTrId("devicelist_battery_pre_charging")
					case VenusOS.Battery_State_ContactorCheck:
						//: Status is 'Contactor check'
						//% "Contactor check"
						return qsTrId("devicelist_battery_contactor_check")
					case VenusOS.Battery_State_Pending:
						return CommonWords.pending
					default:
						return ""
					}
				}
			}

			ListText {
				text: CommonWords.error
				dataItem.uid: root.battery.serviceUid + "/ErrorCode"
				allowed: defaultAllowed && dataItem.isValid
				secondaryText: BmsError.description(dataItem.value)
			}

			ListText {
				//% "Battery bank error"
				text: qsTrId("battery_bank_error")
				dataItem.uid: root.battery.serviceUid + "/ErrorCode"
				allowed: defaultAllowed && (errorComm.isValid || errorVoltage.isValid || errorNrOfBatteries.isValid || errorInvalidConfig.isValid)
				secondaryText: {
					if (errorComm.isValid && errorComm.value) {
						//% "Communication error"
						return qsTrId("battery_bank_error_communication")
					} else if (errorVoltage.isValid && errorVoltage.value) {
						//% "Battery voltage not supported"
						return qsTrId("battery_bank_error_voltage_not_supported")
					} else if (errorNrOfBatteries.isValid && errorNrOfBatteries.value) {
						//% "Incorrect number of batteries"
						return qsTrId("battery_bank_error_incorrect_number_of_batteries")
					} else if (errorInvalidConfig.isValid && errorInvalidConfig.value) {
						//% "Invalid battery configuration"
						return qsTrId("battery_bank_error_invalid_configuration")
					} else {
						return CommonWords.none_errors
					}
				}

				VeQuickItem { id: errorComm; uid: root.battery.serviceUid + "/Errors/SmartLithium/Communication" }
				VeQuickItem { id: errorVoltage; uid: root.battery.serviceUid + "/Errors/SmartLithium/Voltage" }
				VeQuickItem { id: errorNrOfBatteries; uid: root.battery.serviceUid + "/Errors/SmartLithium/NrOfBatteries" }
				VeQuickItem { id: errorInvalidConfig; uid: root.battery.serviceUid + "/Errors/SmartLithium/InvalidConfiguration" }
			}

			ListQuantityGroup {
				text: CommonWords.battery
				textModel: [
					{ value: root.battery.voltage, unit: VenusOS.Units_Volt_DC },
					{ value: root.battery.current, unit: VenusOS.Units_Amp },
					{ value: root.battery.power, unit: VenusOS.Units_Watt }
				]
			}

			ListQuantity {
				text: "Current (last 5 minutes avg.)"
				dataItem.uid: root.battery.serviceUid + "/CurrentAvg"
				allowed: defaultAllowed && dataItem.isValid
				unit: VenusOS.Units_Amp
			}

			ListQuantity {
				//% "Total Capacity"
				text: qsTrId("devicelist_battery_total_capacity")
				dataItem.uid: root.battery.serviceUid + "/Capacity"
				allowed: defaultAllowed && root.isParallelBms
				unit: VenusOS.Units_AmpHour
			}

			ListQuantity {
				readonly property VeQuickItem _n2kDeviceInstance: VeQuickItem {
					uid: battery.serviceUid + "/N2kDeviceInstance"
				}

				//% "System voltage"
				text: qsTrId("devicelist_battery_system_voltage")
				dataItem.uid: BackendConnection.serviceUidFromName("com.victronenergy.battery.lynxparallel" + _n2kDeviceInstance.value, _n2kDeviceInstance.value) + "/Dc/0/Voltage"
				allowed: defaultAllowed && !root.isParallelBms && root.battery.state === VenusOS.Battery_State_Pending
				unit: VenusOS.Units_Volt_DC
			}

			ListText {
				id: nrOfBmses
				//% "Number of BMSes"
				text: qsTrId("devicelist_battery_number_of_bmses")
				dataItem.uid: root.battery.serviceUid + "/NumberOfBmses"
				allowed: defaultAllowed && root.isParallelBms
			}

			ListQuantity {
				text: CommonWords.state_of_charge
				value: root.battery.stateOfCharge
				unit: VenusOS.Units_Percentage
			}

			ListQuantity {
				//% "State of health"
				text: qsTrId("battery_state_of_health")
				dataItem.uid: root.battery.serviceUid + "/Soh"
				allowed: defaultAllowed && dataItem.isValid
				unit: VenusOS.Units_Percentage
			}

			ListTemperature {
				text: CommonWords.battery_temperature
				dataItem.uid: root.battery.serviceUid + "/Dc/0/Temperature"
				allowed: defaultAllowed && dataItem.isValid
				unit: Global.systemSettings.temperatureUnit
			}

			ListTemperature {
				text: "MOSFET Temperature"
				dataItem.uid: root.battery.serviceUid + "/System/MOSTemperature"
				allowed: defaultAllowed && dataItem.isValid
				unit: Global.systemSettings.temperatureUnit
			}

			ListTemperature {
				//% "Air temperature"
				text: qsTrId("battery_air_temp")
				dataItem.uid: root.battery.serviceUid + "/AirTemperature"
				allowed: defaultAllowed && dataItem.isValid
			}

			ListQuantity {
				//% "Starter voltage"
				text: qsTrId("battery_starter_voltage")
				dataItem.uid: root.battery.serviceUid + "/Dc/1/Voltage"
				allowed: defaultAllowed && dataItem.isValid
				unit: VenusOS.Units_Volt_DC
			}

			ListQuantity {
				//% "Bus voltage"
				text: qsTrId("battery_bus_voltage")
				dataItem.uid: root.battery.serviceUid + "/BusVoltage"
				allowed: defaultAllowed && dataItem.isValid
				unit: VenusOS.Units_Volt_DC
			}

			ListQuantity {
				//% "Top section voltage"
				text: qsTrId("battery_top_section_voltage")
				allowed: midVoltage.isValid
				value: midVoltage.isValid && !isNaN(root.battery.voltage) ? root.battery.voltage - midVoltage.value : NaN
				unit: VenusOS.Units_Volt_DC
			}

			ListQuantity {
				//% "Bottom section voltage"
				text: qsTrId("battery_bottom_section_voltage")
				value: midVoltage.value === undefined ? NaN : midVoltage.value
				allowed: midVoltage.isValid
				unit: VenusOS.Units_Volt_DC
			}

			ListQuantity {
				//% "Mid-point deviation"
				text: qsTrId("battery_mid_point_deviation")
				dataItem.uid: root.battery.serviceUid + "/Dc/0/MidVoltageDeviation"
				allowed: defaultAllowed && dataItem.isValid
				unit: VenusOS.Units_Percentage
			}

			ListQuantity {
				//% "Consumed AmpHours"
				text: qsTrId("battery_consumed_amphours")
				dataItem.uid: root.battery.serviceUid + "/ConsumedAmphours"
				allowed: defaultAllowed && dataItem.isValid
				unit: VenusOS.Units_AmpHour
			}

			ListQuantity {
				//% "Bus voltage"
				text: qsTrId("battery_buss_voltage")
				dataItem.uid: root.battery.serviceUid + "/BussVoltage"
				allowed: defaultAllowed && dataItem.isValid
				unit: VenusOS.Units_Volt_DC
			}

			ListText {
				//% "Time-to-go"
				text: qsTrId("battery_time_to_go")
				dataItem.uid: root.battery.serviceUid + "/TimeToGo"
				allowed: defaultAllowed && dataItem.seen
				secondaryText: Utils.secondsToString(root.battery.timeToGo)
			}

			ListText {
				//% "Time-to-SoC 0%"
				text: "Time-to-SoC 0%"
				allowed: defaultAllowed && dataItem.seen
				dataItem.uid: root.battery.serviceUid + "/TimeToSoC/0"
				secondaryText: dataItem.isValid && dataItem.value != "" > 0 ? dataItem.value : "--"
			}

			ListText {
				//% "Time-to-SoC 10%"
				text: "Time-to-SoC 10%"
				allowed: defaultAllowed && dataItem.seen
				dataItem.uid: root.battery.serviceUid + "/TimeToSoC/10"
				secondaryText: dataItem.isValid && dataItem.value != "" > 0 ? dataItem.value : "--"
			}

			ListText {
				//% "Time-to-SoC 20%"
				text: "Time-to-SoC 20%"
				allowed: defaultAllowed && dataItem.seen
				dataItem.uid: root.battery.serviceUid + "/TimeToSoC/20"
				secondaryText: dataItem.isValid && dataItem.value != "" > 0 ? dataItem.value : "--"
			}

			ListText {
				//% "Time-to-SoC 80%"
				text: "Time-to-SoC 80%"
				allowed: defaultAllowed && dataItem.seen
				dataItem.uid: root.battery.serviceUid + "/TimeToSoC/80"
				secondaryText: dataItem.isValid && dataItem.value != "" > 0 ? dataItem.value : "--"
			}

			ListText {
				//% "Time-to-SoC 90%"
				text: "Time-to-SoC 90%"
				allowed: defaultAllowed && dataItem.seen
				dataItem.uid: root.battery.serviceUid + "/TimeToSoC/90"
				secondaryText: dataItem.isValid && dataItem.value != "" > 0 ? dataItem.value : "--"
			}

			ListText {
				//% "Time-to-SoC 100%"
				text: "Time-to-SoC 100%"
				allowed: defaultAllowed && dataItem.seen
				dataItem.uid: root.battery.serviceUid + "/TimeToSoC/100"
				secondaryText: dataItem.isValid && dataItem.value != "" > 0 ? dataItem.value : "--"
			}

			ListRelayState {
				dataItem.uid: root.battery.serviceUid + "/Relay/0/State"
			}

			ListAlarmState {
				dataItem.uid: root.battery.serviceUid + "/Alarms/Alarm"
			}

			ListNavigation {
				//% "Details"
				text: qsTrId("battery_details")
				allowed: defaultAllowed && batteryDetails.hasAllowedItem
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageBatteryDetails.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid, "details": batteryDetails })
				}

				BatteryDetails {
					id: batteryDetails
					bindPrefix: root.battery.serviceUid
				}
			}

			ListNavigation {
				text: "Cell Voltages"
				allowed: defaultAllowed && cell3Voltage.isValid
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageBatteryCellVoltages.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}

				VeQuickItem {
					id: cell3Voltage
					uid: root.battery.serviceUid + "/Voltages/Cell3"
				}
			}

			ListNavigation {
				text: CommonWords.alarms
				allowed: !root.isParallelBms
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageBatteryAlarms.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}
			}

			ListNavigation {
				//% "Module level alarms"
				text: qsTrId("battery_module_level_alarms")
				allowed: moduleAlarmModel.rowCount > 0
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageBatteryModuleAlarms.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid, alarmModel: moduleAlarmModel })
				}
			}

			ListNavigation {
				text: CommonWords.history
				allowed: !isFiamm48TL && batteryHistory.hasAllowedItem
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageBatteryHistory.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid, "history": batteryHistory })
				}

				BatteryHistory {
					id: batteryHistory
					bindPrefix: root.battery.serviceUid
				}
			}

			ListNavigation {
				text: CommonWords.settings
				allowed: hasSettings.value === 1
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageBatterySettings.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}
			}

			ListNavigation {
				id: lynxIonDiagnostics

				//% "Diagnostics"
				text: qsTrId("battery_settings_diagnostics")
				allowed: lastError.isValid
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageLynxIonDiagnostics.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}

				VeQuickItem {
					id: lastError
					uid: root.battery.serviceUid + "/Diagnostics/LastErrors/1/Error"
				}
			}

			ListNavigation {
				text: lynxIonDiagnostics.text
				allowed: isFiamm48TL

				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/Page48TlDiagnostics.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}
			}

			ListNavigation {
				//% "Fuses"
				text: qsTrId("battery_settings_fuses")
				allowed: nrOfDistributors.isValid && nrOfDistributors.value > 0

				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageLynxDistributorList.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}

				VeQuickItem {
					id: nrOfDistributors
					uid: root.battery.serviceUid + "/NrOfDistributors"
				}
			}

			ListNavigation {
				//% "IO"
				text: qsTrId("battery_settings_io")
				allowed: allowToCharge.isValid
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageLynxIonIo.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}

				VeQuickItem {
					id: allowToCharge
					uid: root.battery.serviceUid + "/Io/AllowToCharge"
				}
			}

			ListNavigation {
				//% "System"
				text: qsTrId("battery_settings_system")
				allowed: nrOfBatteries.isValid
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageLynxIonSystem.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}

				VeQuickItem {
					id: nrOfBatteries
					uid: root.battery.serviceUid +"/System/NrOfBatteries"
				}
			}

			ListNavigation {
				text: CommonWords.device_info_title
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/PageDeviceInfo.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}
			}

			ListNavigation {
				//% "Parameters"
				text: qsTrId("battery_settings_parameters")
				allowed: cvl.isValid || ccl.isValid || dcl.isValid
				onClicked: {
					Global.pageManager.pushPage("/pages/settings/devicelist/battery/PageBatteryParameters.qml",
							{ "title": text, "bindPrefix": root.battery.serviceUid })
				}

				VeQuickItem {
					id: cvl
					uid: root.battery.serviceUid + "/Info/MaxChargeVoltage"
				}

				VeQuickItem {
					id: ccl
					uid: root.battery.serviceUid + "/Info/MaxChargeCurrent"
				}

				VeQuickItem {
					id: dcl
					uid: root.battery.serviceUid + "/Info/MaxDischargeCurrent"
				}
			}

			ListButton {
				//% "Redetect Battery"
				text: qsTrId("battery_redetect_battery")
				//% "Press to redetect"
				secondaryText: qsTrId("battery_press_to_redetect")
				enabled: redetect.value === 0
				allowed: redetect.isValid
				writeAccessLevel: VenusOS.User_AccessType_User
				onClicked: {
					redetect.setValue(1)
					//% "Redetecting the battery may take up time 60 seconds. Meanwhile the name of the battery may be incorrect."
					Global.showToastNotification(VenusOS.Notification_Info, qsTrId("battery_redetecting_the_battery_note"), 10000)
				}

				VeQuickItem {
					id: redetect
					uid: root.battery.serviceUid + "/Redetect"
				}
			}
		}
	}

	VeQuickItem {
		id: midVoltage
		uid: root.battery.serviceUid + "/Dc/0/MidVoltage"
	}

	VeQuickItem {
		id: productId
		uid: root.battery.serviceUid + "/ProductId"
	}

	VeQuickItem {
		id: hasSettings
		uid: root.battery.serviceUid + "/Settings/HasSettings"
	}

	VeQItemSortTableModel {
		id: moduleAlarmModel

		filterRegExp: "\/Module[0-9]\/Id$"
		filterFlags: VeQItemSortTableModel.FilterInvalid
		model: VeQItemTableModel {
			uids: [root.battery.serviceUid + "/Diagnostics"]
		}
	}
}
