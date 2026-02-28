/*
** Copyright (C) 2023 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	//% "dbus-serialbattery - General"
	title: qsTrId("dbus_serialbattery_general_title")

	property string bindPrefix

	function getActiveAlarmsText(){
		let result = []
		if (alarmLowBatteryVoltage.valid && alarmLowBatteryVoltage.value !== 0) {
			// "Low battery voltage"
			result.push((alarmLowBatteryVoltage.value === 2 ? "⚠️ " : "") + CommonWords.low_battery_voltage);
		}
		if (alarmHighBatteryVoltage.valid && alarmHighBatteryVoltage.value !== 0) {
			// "High battery voltage"
			result.push((alarmHighBatteryVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_battery_voltage"));
		}
		if (alarmHighCellVoltage.valid && alarmHighCellVoltage.value !== 0) {
			// "High cell voltage"
			result.push((alarmHighCellVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_cell_voltage"));
		}
		if (alarmHighChargeCurrent.valid && alarmHighChargeCurrent.value !== 0) {
			// "High charge current"
			result.push((alarmHighChargeCurrent.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_charge_current"));
		}
		if (alarmHighCurrent.valid && alarmHighCurrent.value !== 0) {
			// "High current"
			result.push((alarmHighCurrent.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_current"));
		}
		if (alarmHighDischargeCurrent.valid && alarmHighDischargeCurrent.value !== 0) {
			// "High discharge current"
			result.push((alarmHighDischargeCurrent.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_discharge_current"));
		}
		if (alarmLowSoc.valid && alarmLowSoc.value !== 0) {
			// "Low SOC"
			result.push((alarmLowSoc.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_soc"));
		}
		if (alarmStateOfHealth.valid && alarmStateOfHealth.value !== 0) {
			// "State of health"
			result.push((alarmStateOfHealth.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_state_of_health"));
		}
		if (alarmLowStarterVoltage.valid && alarmLowStarterVoltage.value !== 0) {
			// "Low starter voltage"
			result.push((alarmLowStarterVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_starter_voltage"));
		}
		if (alarmHighStarterVoltage.valid && alarmHighStarterVoltage.value !== 0) {
			// "High starter voltage"
			result.push((alarmHighStarterVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_starter_voltage"));
		}
		if (alarmLowTemperature.valid && alarmLowTemperature.value !== 0) {
			// "Low temperature"
			result.push((alarmLowTemperature.value === 2 ? "⚠️ " : "") + CommonWords.low_temperature);
		}
		if (alarmHighTemperature.valid && alarmHighTemperature.value !== 0) {
			// "High temperature"
			result.push((alarmHighTemperature.value === 2 ? "⚠️ " : "") + CommonWords.high_temperature);
		}
		if (alarmBatteryTemperatureSensor.valid && alarmBatteryTemperatureSensor.value !== 0) {
			// "Battery temperature sensor"
			result.push((alarmBatteryTemperatureSensor.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_battery_temperature_sensor"));
		}
		if (alarmMidPointVoltage.valid && alarmMidPointVoltage.value !== 0) {
			// "Midpoint voltage"
			result.push((alarmMidPointVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_midpoint_voltage"));
		}
		if (alarmFuseBlown.valid && alarmFuseBlown.value !== 0) {
			// "Fuse blown"
			result.push((alarmFuseBlown.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_fuse_blown"));
		}
		if (alarmHighInternalTemperature.valid && alarmHighInternalTemperature.value !== 0) {
			// "High internal temperature"
			result.push((alarmHighInternalTemperature.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_internal_temperature"));
		}
		if (alarmLowChargeTemperature.valid && alarmLowChargeTemperature.value !== 0) {
			// "Low charge temperature"
			result.push((alarmLowChargeTemperature.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_charge_temperature"));
		}
		if (alarmHighChargeTemperature.valid && alarmHighChargeTemperature.value !== 0) {
			// "High charge temperature"
			result.push((alarmHighChargeTemperature.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_charge_temperature"));
		}
		if (alarmInternalFailure.valid && alarmInternalFailure.value !== 0) {
			// "Internal failure"
			result.push((alarmInternalFailure.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_internal_failure"));
		}
		if (alarmCellImbalance.valid && alarmCellImbalance.value !== 0) {
			// "Cell imbalance"
			result.push((alarmCellImbalance.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_cell_imbalance"));
		}
		if (alarmLowCellVoltage.valid && alarmLowCellVoltage.value !== 0) {
			// "Low cell voltage"
			result.push((alarmLowCellVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_cell_voltage"));
		}
		if (alarmBmsCable.valid && alarmBmsCable.value !== 0) {
			// "BMS cable"
			result.push((alarmBmsCable.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_bms_cable"));
		}
		if (alarmContactor.valid && alarmContactor.value !== 0) {
			// "Bad contactor"
			result.push((alarmContactor.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_contactor"));
		}

		// Sort the alarms alphabetically and join them with a comma
		result.sort()
		return result.join(", ")
	}

	VeQuickItem {
		id: currentItem
		uid: root.bindPrefix + "/Dc/0/Current"
	}
	VeQuickItem {
		id: voltageItem
		uid: root.bindPrefix + "/Dc/0/Voltage"
	}
	VeQuickItem {
		id: currentAvgItem
		uid: root.bindPrefix + "/CurrentAvg"
	}
	VeQuickItem {
		id: cellSumItem
		uid: root.bindPrefix + "/Voltages/Sum"
	}
	VeQuickItem {
		id: cellMinItem
		uid: root.bindPrefix + "/System/MinCellVoltage"
	}
	VeQuickItem {
		id: cellMaxItem
		uid: root.bindPrefix + "/System/MaxCellVoltage"
	}
	VeQuickItem {
		id: socItem
		uid: root.bindPrefix + "/Soc"
	}

	VeQuickItem {
		id: temperatureItem
		uid: root.bindPrefix + "/Dc/0/Temperature"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: temperatureMosItem
		uid: root.bindPrefix + "/System/MOSTemperature"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: temperature1Item
		uid: root.bindPrefix + "/System/Temperature1"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: temperature1NameItem
		uid: root.bindPrefix + "/System/Temperature1Name"
	}
	VeQuickItem {
		id: temperature2Item
		uid: root.bindPrefix + "/System/Temperature2"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: temperature2NameItem
		uid: root.bindPrefix + "/System/Temperature2Name"
	}
	VeQuickItem {
		id: temperature3Item
		uid: root.bindPrefix + "/System/Temperature3"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: temperature3NameItem
		uid: root.bindPrefix + "/System/Temperature3Name"
	}
	VeQuickItem {
		id: temperature4Item
		uid: root.bindPrefix + "/System/Temperature4"
		sourceUnit: Units.unitToVeUnit(VenusOS.Units_Temperature_Celsius)
		displayUnit: Units.unitToVeUnit(Global.systemSettings.temperatureUnit)
	}
	VeQuickItem {
		id: temperature4NameItem
		uid: root.bindPrefix + "/System/Temperature4Name"
	}

	VeQuickItem {
		id: allowToChargeItem
		uid: root.bindPrefix + "/Io/AllowToCharge"
	}
	VeQuickItem {
		id: allowToDischargeItem
		uid: root.bindPrefix + "/Io/AllowToDischarge"
	}
	VeQuickItem {
		id: allowToBalanceItem
		uid: root.bindPrefix + "/Io/AllowToBalance"
	}
	VeQuickItem {
		id: allowToHeatItem
		uid: root.bindPrefix + "/Io/AllowToHeat"
	}

	VeQuickItem {
		id: chargeModeItem
		uid: root.bindPrefix + "/Info/ChargeMode"
	}
	VeQuickItem {
		id: maxChargeVoltageItem
		uid: root.bindPrefix + "/Info/MaxChargeVoltage"
	}
	VeQuickItem {
		id: maxChargeCellVoltageItem
		uid: root.bindPrefix + "/Info/MaxChargeCellVoltage"
	}

	VeQuickItem {
		id: productId
		uid: root.bindPrefix + "/ProductId"
	}

	VeQuickItem {
		id: alarmLowBatteryVoltage
		uid: root.bindPrefix + "/Alarms/LowVoltage"
	}
	VeQuickItem {
		id: alarmHighBatteryVoltage
		uid: root.bindPrefix + "/Alarms/HighVoltage"
	}
	VeQuickItem {
		id: alarmHighCellVoltage
		uid: root.bindPrefix + "/Alarms/HighCellVoltage"
	}
	VeQuickItem {
		id: alarmHighChargeCurrent
		uid: root.bindPrefix + "/Alarms/HighChargeCurrent"
	}
	VeQuickItem {
		id: alarmHighCurrent
		uid: root.bindPrefix + "/Alarms/HighCurrent"
	}
	VeQuickItem {
		id: alarmHighDischargeCurrent
		uid: root.bindPrefix + "/Alarms/HighDischargeCurrent"
	}
	VeQuickItem {
		id: alarmLowSoc
		uid: root.bindPrefix + "/Alarms/LowSoc"
	}
	VeQuickItem {
		id: alarmStateOfHealth
		uid: root.bindPrefix + "/Alarms/StateOfHealth"
	}
	VeQuickItem {
		id: alarmLowStarterVoltage
		uid: root.bindPrefix + "/Alarms/LowStarterVoltage"
	}
	VeQuickItem {
		id: alarmHighStarterVoltage
		uid: root.bindPrefix + "/Alarms/HighStarterVoltage"
	}
	VeQuickItem {
		id: alarmLowTemperature
		uid: root.bindPrefix + "/Alarms/LowTemperature"
	}
	VeQuickItem {
		id: alarmHighTemperature
		uid: root.bindPrefix + "/Alarms/HighTemperature"
	}
	VeQuickItem {
		id: alarmBatteryTemperatureSensor
		uid: root.bindPrefix + "/Alarms/BatteryTemperatureSensor"
	}
	VeQuickItem {
		id: alarmMidPointVoltage
		uid: root.bindPrefix + "/Alarms/MidVoltage"
	}
	VeQuickItem {
		id: alarmFuseBlown
		uid: root.bindPrefix + "/Alarms/FuseBlown"
	}
	VeQuickItem {
		id: alarmHighInternalTemperature
		uid: root.bindPrefix + "/Alarms/HighInternalTemperature"
	}
	VeQuickItem {
		id: alarmLowChargeTemperature
		uid: root.bindPrefix + "/Alarms/LowChargeTemperature"
	}
	VeQuickItem {
		id: alarmHighChargeTemperature
		uid: root.bindPrefix + "/Alarms/HighChargeTemperature"
	}
	VeQuickItem {
		id: alarmInternalFailure
		uid: root.bindPrefix + "/Alarms/InternalFailure"
	}
	VeQuickItem {
		id: alarmCellImbalance
		uid: root.bindPrefix + "/Alarms/CellImbalance"
	}
	VeQuickItem {
		id: alarmLowCellVoltage
		uid: root.bindPrefix + "/Alarms/LowCellVoltage"
	}
	VeQuickItem {
		id: alarmBmsCable
		uid: root.bindPrefix + "/Alarms/BmsCable"
	}
	VeQuickItem {
		id: alarmContactor
		uid: root.bindPrefix + "/Alarms/Contactor"
	}

	GradientListView {
		model: VisibleItemModel {
			ListItem {
				id: cellOverviewItem
				// "Overview"
				text: qsTrId("nav_overview")
				content.children: [
					Row {
						id: contentRowOverview

						readonly property real itemWidth: (width - (spacing * 5)) / 6

						width: cellOverviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: currentItem.value ?? NaN
								unit: VenusOS.Units_Amp
								precision: 2
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								// "Current"
								text: CommonWords.current_amps
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: currentAvgItem.value ?? NaN
								unit: VenusOS.Units_Amp
								precision: 2
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//: Label of the current average in amps
								//% "Current avg"
								text: qsTrId("dbus_serialbattery_general_current_avg")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellSumItem.value ?? voltageItem.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 2
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								// "Voltage"
								text: CommonWords.voltage
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellMaxItem.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								valueColor: (chargeLimitationItem.valid && chargeLimitationItem.value.indexOf("Cell Voltage") !== -1)
									|| (dischargeLimitationItem.valid && dischargeLimitationItem.value.indexOf("Cell Voltage") !== -1)
									|| (maxChargeCellVoltageItem.valid && cellMaxItem.value > maxChargeCellVoltageItem.value)
									? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Cell max"
								text: qsTrId("dbus_serialbattery_general_cell_max")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellMinItem.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								valueColor: (chargeLimitationItem.valid && chargeLimitationItem.value.indexOf("Cell Voltage") !== -1)
									|| (dischargeLimitationItem.valid && dischargeLimitationItem.value.indexOf("Cell Voltage") !== -1)
									? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Cell min"
								text: qsTrId("dbus_serialbattery_general_cell_min")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: socItem.value ?? NaN
								unit: VenusOS.Units_Percentage
								precision: 3
								valueColor: (chargeLimitationItem.valid && chargeLimitationItem.value.indexOf("SoC") !== -1)
									|| (dischargeLimitationItem.valid && dischargeLimitationItem.value.indexOf("SoC") !== -1)
									? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "SoC"
								text: qsTrId("dbus_serialbattery_general_soc")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
					}
				]
			}

			ListItem {
				id: temperaturesOverviewItem
				//% "Temperatures"
				text: qsTrId("dbus_serialbattery_general_temperatures")
				content.children: [
					Row {
						id: temperaturesContentRowOverview

						readonly property real itemWidth: (width - (spacing * 5)) / 6

						width: temperaturesOverviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						Column {
							width: temperaturesContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: temperatureItem.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: (chargeLimitationItem.valid && chargeLimitationItem.value.indexOf("Temp") !== -1)
									|| (dischargeLimitationItem.valid && dischargeLimitationItem.value.indexOf("Temp") !== -1)
									? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								// "Battery"
								text: CommonWords.battery
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: temperaturesContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: temperatureMosItem.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: (chargeLimitationItem.valid && chargeLimitationItem.value.indexOf("MOSFET") !== -1)
									|| (dischargeLimitationItem.valid && dischargeLimitationItem.value.indexOf("MOSFET") !== -1)
									? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "MOSFET"
								text: qsTrId("dbus_serialbattery_general_mosfet")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: temperaturesContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: temperature1Item.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Temp 1"
								text: temperature1NameItem.value ?? qsTrId("dbus_serialbattery_general_temp1")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: temperaturesContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: temperature2Item.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Temp 2"
								text: temperature2NameItem.value ?? qsTrId("dbus_serialbattery_general_temp2")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: temperaturesContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: temperature3Item.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Temp 3"
								text: temperature3NameItem.value ?? qsTrId("dbus_serialbattery_general_temp3")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: temperaturesContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: temperature4Item.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Temp 4"
								text: temperature4NameItem.value ?? qsTrId("dbus_serialbattery_general_temp4")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
					}
				]
			}

			ListText {
				//% "Charge Mode"
				text: qsTrId("dbus_serialbattery_general_charge_mode")
				secondaryText: chargeModeItem.valid ? chargeModeItem.value : "--"
				preferredVisible: chargeModeItem.valid
			}

			ListQuantityGroup {
				id: chargeLimitationFullItem
				// "Charge Voltage Limit (CVL)"
				text: qsTrId("batteryparameters_charge_voltage_limit_cvl")
				model: QuantityObjectModel {
					QuantityObject { object: customDataObject; key: "name" }
					QuantityObject { object: maxChargeVoltageItem; unit: VenusOS.Units_Volt_DC }
				}
				preferredVisible: maxChargeCellVoltageItem.valid

				QtObject {
					id: customDataObject
					//% "V/cell"
					property string name: maxChargeCellVoltageItem.valid ? maxChargeCellVoltageItem.value.toFixed(3) + qsTrId("serialbattery_general_volt_per_cell") : "--"
				}
			}

			ListQuantityGroup {
				// "Charge Voltage Limit (CVL)"
				text: qsTrId("batteryparameters_charge_voltage_limit_cvl")
				model: QuantityObjectModel {
					QuantityObject { object: maxChargeVoltageItem; unit: VenusOS.Units_Volt_DC }
				}
				preferredVisible: !chargeLimitationFullItem.visible
			}

			ListQuantityGroup {
				// "Charge Current Limit (CCL)"
				text: qsTrId("batteryparameters_charge_current_limit_ccl")
				model: QuantityObjectModel {
					QuantityObject { object: chargeLimitationItem; defaultValue: "--" }
					QuantityObject { object: maxChargeCurrentItem; unit: VenusOS.Units_Amp }
				}

				VeQuickItem {
					id: chargeLimitationItem
					uid: root.bindPrefix + "/Info/ChargeLimitation"
				}

				VeQuickItem {
					id: maxChargeCurrentItem
					uid: root.bindPrefix + "/Info/MaxChargeCurrent"
				}
			}

			ListQuantityGroup {
				// "Discharge Current Limit (DCL)"
				text: qsTrId("batteryparameters_discharge_current_limit_dcl")
				model: QuantityObjectModel {
					QuantityObject { object: dischargeLimitationItem; defaultValue: "--" }
					QuantityObject { object: maxDischargeCurrentItem; unit: VenusOS.Units_Amp }
				}

				VeQuickItem {
					id: dischargeLimitationItem
					uid: root.bindPrefix + "/Info/DischargeLimitation"
				}

				VeQuickItem {
					id: maxDischargeCurrentItem
					uid: root.bindPrefix + "/Info/MaxDischargeCurrent"
				}
			}

			ListItem {
				id: allowToOverviewItem
				//% "Allow to"
				text: qsTrId("dbus_serialbattery_general_allow_to")
				preferredVisible: allowToChargeItem.valid || allowToDischargeItem.valid || allowToBalanceItem.valid
				content.children: [
					Row {
						id: allowToContentRowOverview

						readonly property real itemWidth: allowToHeatItem.valid ? (width - (spacing * 3)) / 4 : (width - (spacing * 2)) / 3

						width: allowToOverviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						Column {
							width: allowToContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								valueText: allowToChargeItem.valid ? CommonWords.yesOrNo(allowToChargeItem.value) : "--"
								valueColor: allowToChargeItem.value === 0 ? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//: Allow to ...
								//% "Charge"
								text: qsTrId("dbus_serialbattery_general_charge")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: allowToContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								valueText: allowToDischargeItem.valid ? CommonWords.yesOrNo(allowToDischargeItem.value) : "--"
								valueColor: allowToDischargeItem.value === 0 ? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//: Allow to ...
								//% "Discharge"
								text: qsTrId("dbus_serialbattery_general_discharge")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: allowToContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								valueText: allowToBalanceItem.valid ? CommonWords.yesOrNo(allowToBalanceItem.value) : "--"
								valueColor: allowToBalanceItem.value === 0 ? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//: Allow to ...
								//% "Balance"
								text: qsTrId("dbus_serialbattery_general_balance")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: allowToHeatItem.valid ? allowToContentRowOverview.itemWidth : 0
							visible: allowToHeatItem.valid

							QuantityLabel {
								width: parent.width
								valueText: allowToHeatItem.valid ? CommonWords.yesOrNo(allowToHeatItem.value) : "--"
								valueColor: allowToHeatItem.value === 0 ? "#BF4845" : Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//: Allow to ...
								//% "Heat"
								text: qsTrId("dbus_serialbattery_general_heat")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
					}
				]
			}

			ListItem {
				id: heaterOverviewItem
				//% "Heater"
				text: qsTrId("dbus_serialbattery_general_heater")
				preferredVisible: heatingItem.valid || heatingCurrentItem.valid || heatingPowerItem.valid || heatingTemperatureStartItem.valid || heatingTemperatureStopItem.valid
				content.children: [
					Row {
						id: heaterContentRowOverview

						readonly property real itemWidth: (width - (spacing * 4)) / 5

						width: heaterOverviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						Column {
							width: heaterContentRowOverview.itemWidth

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								text: heatingItem.valid ? (
									heatingItem.value === 1
									//% "Running"
									? qsTrId("dbus_serialbattery_general_heater_running")
									//% "Stopped"
									: qsTrId("dbus_serialbattery_general_heater_stopped")
									) : "--"
								color: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								// "State"
								text: CommonWords.state
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}

							VeQuickItem {
								id: heatingItem
								uid: root.bindPrefix + "/Heating"
							}
						}
						Column {
							width: heaterContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: heatingCurrentItem.value ?? NaN
								unit: VenusOS.Units_Amp
								precision: 1
								//valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								// "Current"
								text: CommonWords.current_amps
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}

							VeQuickItem {
								id: heatingCurrentItem
								uid: root.bindPrefix + "/Info/HeatingCurrent"
							}
						}
						Column {
							width: heaterContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: heatingPowerItem.value ?? NaN
								unit: VenusOS.Units_Watt
								precision: 1
								//valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								// "Power"
								text: CommonWords.power_watts
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}

							VeQuickItem {
								id: heatingPowerItem
								uid: root.bindPrefix + "/Info/HeatingPower"
							}
						}
						Column {
							width: heaterContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: heatingTemperatureStartItem.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//: Temperature at which the heater starts
								//% "Temp start"
								text: qsTrId("dbus_serialbattery_general_temp_start")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}

							VeQuickItem {
								id: heatingTemperatureStartItem
								uid: root.bindPrefix + "/Info/HeatingTemperatureStart"
							}
						}
						Column {
							width: heaterContentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: heatingTemperatureStopItem.value ?? NaN
								unit: Global.systemSettings.temperatureUnit
								precision: 1
								valueColor: Theme.color_font_primary
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//: Temperature at which the heater stops
								//% "Temp stop"
								text: qsTrId("dbus_serialbattery_general_temp_stop")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}

							VeQuickItem {
								id: heatingTemperatureStopItem
								uid: root.bindPrefix + "/Info/HeatingTemperatureStop"
							}
						}
					}
				]
			}

			ListText {
				// "Alarms"
				text: CommonWords.alarms
				secondaryText: getActiveAlarmsText()
				secondaryLabel.color: Theme.color_red
				preferredVisible: secondaryLabel.text !== ""
			}

			SettingsListHeader {
				//% "Support"
				text: qsTrId("dbus_serialbattery_general_support")
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				//% "How to troubleshoot"
				text: qsTrId("dbus_serialbattery_general_how_to_troubleshoot")
				url: "https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/troubleshoot/"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				//% "FAQ (Frequently Asked Questions)"
				text: qsTrId("dbus_serialbattery_general_faq")
				url: "https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/faq/"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				//% "GitHub"
				text: qsTrId("dbus_serialbattery_general_github")
				url: "https://github.com/mr-manuel/venus-os_dbus-serialbattery/"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				//% "Donate to help this project, any amount is appreciated"
				text: qsTrId("dbus_serialbattery_general_donate")
				url: "https://www.paypal.com/donate/?hosted_button_id=3NEVZBDM5KABW"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			SettingsListHeader {
				//% "Driver Debug Data"
				text: qsTrId("dbus_serialbattery_general_driver_debug_data")
				preferredVisible: chargeModeDebug.valid && chargeModeDebug.value !== ""
			}

			ListItem {
				//% "General Values"
				text: qsTrId("dbus_serialbattery_general_values")

				bottomContentChildren: [
					PrimaryListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebug.valid ? chargeModeDebug.value : "--"
						horizontalAlignment: Text.AlignHCenter
					}
				]

				preferredVisible: chargeModeDebug.valid && chargeModeDebug.value !== ""

				VeQuickItem {
					id: chargeModeDebug
					uid: root.bindPrefix + "/Info/ChargeModeDebug"
				}
			}

			ListItem {
				//% "Switch to Float Requirements"
				text: qsTrId("dbus_serialbattery_general_switch_to_float_requirements")

				bottomContentChildren: [
					PrimaryListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebugFloat.valid ? chargeModeDebugFloat.value : "--"
						horizontalAlignment: Text.AlignHCenter
					}
				]

				preferredVisible: chargeModeDebugFloat.valid && chargeModeDebugFloat.value !== ""

				VeQuickItem {
					id: chargeModeDebugFloat
					uid: root.bindPrefix + "/Info/ChargeModeDebugFloat"
				}
			}

			ListItem {
				//% "Switch to Bulk Requirements"
				text: qsTrId("dbus_serialbattery_general_switch_to_bulk_requirements")

				bottomContentChildren: [
					PrimaryListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebugBulk.valid ? chargeModeDebugBulk.value : "--"
						horizontalAlignment: Text.AlignHCenter
					}
				]

				preferredVisible: chargeModeDebugBulk.valid && chargeModeDebugBulk.value !== ""

				VeQuickItem {
					id: chargeModeDebugBulk
					uid: root.bindPrefix + "/Info/ChargeModeDebugBulk"
				}
			}

		}
	}
}
