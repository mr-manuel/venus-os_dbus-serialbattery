/*
** Copyright (C) 2023 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	property string bindPrefix

	function getActiveAlarmsText(){
		let result = []
		if (alarmLowBatteryVoltage.valid && alarmLowBatteryVoltage.value !== 0) {
			//% "Low battery voltage"
			result.push((alarmLowBatteryVoltage.value === 2 ? "⚠️ " : "") + CommonWords.low_battery_voltage);
		}
		if (alarmHighBatteryVoltage.valid && alarmHighBatteryVoltage.value !== 0) {
			//% "High battery voltage"
			result.push((alarmHighBatteryVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_battery_voltage"));
		}
		if (alarmHighCellVoltage.valid && alarmHighCellVoltage.value !== 0) {
			//% "High cell voltage"
			result.push((alarmHighCellVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_cell_voltage"));
		}
		if (alarmHighChargeCurrent.valid && alarmHighChargeCurrent.value !== 0) {
			//% "High charge current"
			result.push((alarmHighChargeCurrent.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_charge_current"));
		}
		if (alarmHighCurrent.valid && alarmHighCurrent.value !== 0) {
			//% "High current"
			result.push((alarmHighCurrent.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_current"));
		}
		if (alarmHighDischargeCurrent.valid && alarmHighDischargeCurrent.value !== 0) {
			//% "High discharge current"
			result.push((alarmHighDischargeCurrent.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_discharge_current"));
		}
		if (alarmLowSoc.valid && alarmLowSoc.value !== 0) {
			//% "Low SOC"
			result.push((alarmLowSoc.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_soc"));
		}
		if (alarmStateOfHealth.valid && alarmStateOfHealth.value !== 0) {
			//% "State of health"
			result.push((alarmStateOfHealth.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_state_of_health"));
		}
		if (alarmLowStarterVoltage.valid && alarmLowStarterVoltage.value !== 0) {
			//% "Low starter voltage"
			result.push((alarmLowStarterVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_starter_voltage"));
		}
		if (alarmHighStarterVoltage.valid && alarmHighStarterVoltage.value !== 0) {
			//% "High starter voltage"
			result.push((alarmHighStarterVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_starter_voltage"));
		}
		if (alarmLowTemperature.valid && alarmLowTemperature.value !== 0) {
			//% "Low temperature"
			result.push((alarmLowTemperature.value === 2 ? "⚠️ " : "") + CommonWords.low_temperature);
		}
		if (alarmHighTemperature.valid && alarmHighTemperature.value !== 0) {
			//% "High temperature"
			result.push((alarmHighTemperature.value === 2 ? "⚠️ " : "") + CommonWords.high_temperature);
		}
		if (alarmBatteryTemperatureSensor.valid && alarmBatteryTemperatureSensor.value !== 0) {
			//% "Battery temperature sensor"
			result.push((alarmBatteryTemperatureSensor.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_battery_temperature_sensor"));
		}
		if (alarmMidPointVoltage.valid && alarmMidPointVoltage.value !== 0) {
			//% "Midpoint voltage"
			result.push((alarmMidPointVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_midpoint_voltage"));
		}
		if (alarmFuseBlown.valid && alarmFuseBlown.value !== 0) {
			//% "Fuse blown"
			result.push((alarmFuseBlown.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_fuse_blown"));
		}
		if (alarmHighInternalTemperature.valid && alarmHighInternalTemperature.value !== 0) {
			//% "High internal temperature"
			result.push((alarmHighInternalTemperature.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_internal_temperature"));
		}
		if (alarmLowChargeTemperature.valid && alarmLowChargeTemperature.value !== 0) {
			//% "Low charge temperature"
			result.push((alarmLowChargeTemperature.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_charge_temperature"));
		}
		if (alarmHighChargeTemperature.valid && alarmHighChargeTemperature.value !== 0) {
			//% "High charge temperature"
			result.push((alarmHighChargeTemperature.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_high_charge_temperature"));
		}
		if (alarmInternalFailure.valid && alarmInternalFailure.value !== 0) {
			//% "Internal failure"
			result.push((alarmInternalFailure.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_internal_failure"));
		}
		if (alarmCellImbalance.valid && alarmCellImbalance.value !== 0) {
			//% "Cell imbalance"
			result.push((alarmCellImbalance.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_cell_imbalance"));
		}
		if (alarmLowCellVoltage.valid && alarmLowCellVoltage.value !== 0) {
			//% "Low cell voltage"
			result.push((alarmLowCellVoltage.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_low_cell_voltage"));
		}
		if (alarmBmsCable.valid && alarmBmsCable.value !== 0) {
			//% "BMS cable"
			result.push((alarmBmsCable.value === 2 ? "⚠️ " : "") + qsTrId("batteryalarms_bms_cable"));
		}
		if (alarmContactor.valid && alarmContactor.value !== 0) {
			//% "Bad contactor"
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
				text: "Overview"
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
								text: "Current"
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
								text: "Current avg"
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
								text: "Voltage"
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
								text: "Cell max"
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
								text: "Cell min"
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
								text: "SoC"
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
					}
				]
			}

			ListItem {
				id: temperaturesOverviewItem
				text: "Temperatures"
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
								text: "Battery"
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
								text: "MOSFET"
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
								text: temperature1NameItem.value ?? "Temp 1"
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
								text: temperature2NameItem.value ?? "Temp 2"
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
								text: temperature3NameItem.value ?? "Temp 3"
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
								text: temperature4NameItem.value ?? "Temp 4"
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
					}
				]
			}

			ListText {
				//% "Charge Mode"
				text: "Charge Mode"
				secondaryText: chargeModeItem.valid ? chargeModeItem.value : "--"
				preferredVisible: chargeModeItem.valid
			}

			ListQuantityGroup {
				id: chargeLimitationFullItem
				//% "Charge Voltage Limit (CVL)"
				text: qsTrId("batteryparameters_charge_voltage_limit_cvl")
				model: QuantityObjectModel {
					QuantityObject { object: customDataObject; key: "name" }
					QuantityObject { object: maxChargeVoltageItem; unit: VenusOS.Units_Volt_DC }
				}
				preferredVisible: maxChargeCellVoltageItem.valid

				QtObject {
					id: customDataObject
					property string name: maxChargeCellVoltageItem.valid ? maxChargeCellVoltageItem.value.toFixed(3) + "V/cell" : "--"
				}
			}

			ListQuantityGroup {
				//% "Charge Voltage Limit (CVL)"
				text: qsTrId("batteryparameters_charge_voltage_limit_cvl")
				model: QuantityObjectModel {
					QuantityObject { object: maxChargeVoltageItem; unit: VenusOS.Units_Volt_DC }
				}
				preferredVisible: !chargeLimitationFullItem.visible
			}

			ListQuantityGroup {
				//% "Charge Current Limit (CCL)"
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
				//% "Discharge Current Limit (DCL)"
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
				text: "Allow to"
				preferredVisible: allowToChargeItem.valid || allowToDischargeItem.valid || allowToBalanceItem.valid
				content.children: [
					Row {
						id: allowToContentRowOverview

						readonly property real itemWidth: (width - (spacing * 2)) / 3

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
								text: "Charge"
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
								text: "Discharge"
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
								text: "Balance"
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
					}
				]
			}

			ListText {
				text: "Alarms"
				secondaryText: getActiveAlarmsText()
				secondaryLabel.color: Theme.color_red
				preferredVisible: secondaryLabel.text !== ""
			}

			SettingsListHeader {
				text: "Support"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				text: "How to troubleshoot"
				url: "https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/troubleshoot/"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				text: "FAQ (Frequently Asked Questions)"
				url: "https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/faq/"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				text: "GitHub"
				url: "https://github.com/mr-manuel/venus-os_dbus-serialbattery/"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			ListLink {
				text: "Donate to help this project, any amount is appreciated"
				url: "https://www.paypal.com/donate/?hosted_button_id=3NEVZBDM5KABW"
				// show only for mr-manuel/dbus-serialbattery (productId registered at Victron)
				preferredVisible: productId.value === 0xBA77
			}

			SettingsListHeader {
				text: "Driver Debug Data"
                preferredVisible: chargeModeDebug.valid
			}

			ListItem {
				text: "General Values"

				VeQuickItem {
					id: chargeModeDebug
					uid: root.bindPrefix + "/Info/ChargeModeDebug"
				}

				bottomContentChildren: [
					PrimaryListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebug.valid ? chargeModeDebug.value : "--"
						horizontalAlignment: Text.AlignHCenter
					}
				]

				preferredVisible: chargeModeDebug.valid
			}

			ListItem {
				text: "Switch to Float Requirements"

				VeQuickItem {
					id: chargeModeDebugFloat
					uid: root.bindPrefix + "/Info/ChargeModeDebugFloat"
				}

				bottomContentChildren: [
					PrimaryListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebugFloat.valid ? chargeModeDebugFloat.value : "--"
						horizontalAlignment: Text.AlignHCenter
					}
				]

				preferredVisible: chargeModeDebugFloat.valid
			}

			ListItem {
				text: "Switch to Bulk Requirements"

				VeQuickItem {
					id: chargeModeDebugBulk
					uid: root.bindPrefix + "/Info/ChargeModeDebugBulk"
				}

				bottomContentChildren: [
					PrimaryListLabel {
						topPadding: 0
						bottomPadding: 0
						color: Theme.color_font_secondary
						text: chargeModeDebugBulk.valid ? chargeModeDebugBulk.value : "--"
						horizontalAlignment: Text.AlignHCenter
					}
				]

				preferredVisible: chargeModeDebugBulk.valid
			}

		}
	}
}
