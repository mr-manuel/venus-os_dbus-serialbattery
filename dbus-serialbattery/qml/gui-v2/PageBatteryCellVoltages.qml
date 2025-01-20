/*
** Copyright (C) 2025 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	property string bindPrefix

	readonly property string batteryCellVoltageSum: _batteryCellVoltageSum.isValid ? _batteryCellVoltageSum.value.toFixed(2) : "--"
	readonly property string batteryCellVoltageDiff: _batteryCellVoltageDiff.isValid ? _batteryCellVoltageDiff.value.toFixed(3) : "--"
	readonly property string batteryMinCellVoltage: _batteryMinCellVoltage.isValid ? _batteryMinCellVoltage.value.toFixed(3) : "--"
	readonly property string batteryMaxCellVoltage: _batteryMaxCellVoltage.isValid ? _batteryMaxCellVoltage.value.toFixed(3) : "--"


	readonly property VeQuickItem _batteryVoltagesCell_1: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell1" }
	readonly property VeQuickItem _batteryVoltagesCell_2: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell2" }
	readonly property VeQuickItem _batteryVoltagesCell_3: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell3" }
	readonly property VeQuickItem _batteryVoltagesCell_4: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell4" }
	readonly property VeQuickItem _batteryVoltagesCell_5: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell5" }
	readonly property VeQuickItem _batteryVoltagesCell_6: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell6" }
	readonly property VeQuickItem _batteryVoltagesCell_7: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell7" }
	readonly property VeQuickItem _batteryVoltagesCell_8: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell8" }
	readonly property VeQuickItem _batteryVoltagesCell_9: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell9" }
	readonly property VeQuickItem _batteryVoltagesCell_10: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell10" }
	readonly property VeQuickItem _batteryVoltagesCell_11: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell11" }
	readonly property VeQuickItem _batteryVoltagesCell_12: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell12" }
	readonly property VeQuickItem _batteryVoltagesCell_13: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell13" }
	readonly property VeQuickItem _batteryVoltagesCell_14: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell14" }
	readonly property VeQuickItem _batteryVoltagesCell_15: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell15" }
	readonly property VeQuickItem _batteryVoltagesCell_16: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell16" }
	readonly property VeQuickItem _batteryVoltagesCell_17: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell17" }
	readonly property VeQuickItem _batteryVoltagesCell_18: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell18" }
	readonly property VeQuickItem _batteryVoltagesCell_19: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell19" }
	readonly property VeQuickItem _batteryVoltagesCell_20: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell20" }
	readonly property VeQuickItem _batteryVoltagesCell_21: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell21" }
	readonly property VeQuickItem _batteryVoltagesCell_22: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell22" }
	readonly property VeQuickItem _batteryVoltagesCell_23: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell23" }
	readonly property VeQuickItem _batteryVoltagesCell_24: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell24" }
	readonly property VeQuickItem _batteryVoltagesCell_25: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell25" }
	readonly property VeQuickItem _batteryVoltagesCell_26: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell26" }
	readonly property VeQuickItem _batteryVoltagesCell_27: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell27" }
	readonly property VeQuickItem _batteryVoltagesCell_28: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell28" }
	readonly property VeQuickItem _batteryVoltagesCell_29: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell29" }
	readonly property VeQuickItem _batteryVoltagesCell_30: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell30" }
	readonly property VeQuickItem _batteryVoltagesCell_31: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell31" }
	readonly property VeQuickItem _batteryVoltagesCell_32: VeQuickItem { uid: root.bindPrefix + "/Voltages/Cell32" }


	readonly property string batteryVoltagesCell_1: _batteryVoltagesCell_1.isValid ? _batteryVoltagesCell_1.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_2: _batteryVoltagesCell_2.isValid ? _batteryVoltagesCell_2.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_3: _batteryVoltagesCell_3.isValid ? _batteryVoltagesCell_3.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_4: _batteryVoltagesCell_4.isValid ? _batteryVoltagesCell_4.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_5: _batteryVoltagesCell_5.isValid ? _batteryVoltagesCell_5.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_6: _batteryVoltagesCell_6.isValid ? _batteryVoltagesCell_6.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_7: _batteryVoltagesCell_7.isValid ? _batteryVoltagesCell_7.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_8: _batteryVoltagesCell_8.isValid ? _batteryVoltagesCell_8.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_9: _batteryVoltagesCell_9.isValid ? _batteryVoltagesCell_9.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_10: _batteryVoltagesCell_10.isValid ? _batteryVoltagesCell_10.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_11: _batteryVoltagesCell_11.isValid ? _batteryVoltagesCell_11.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_12: _batteryVoltagesCell_12.isValid ? _batteryVoltagesCell_12.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_13: _batteryVoltagesCell_13.isValid ? _batteryVoltagesCell_13.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_14: _batteryVoltagesCell_14.isValid ? _batteryVoltagesCell_14.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_15: _batteryVoltagesCell_15.isValid ? _batteryVoltagesCell_15.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_16: _batteryVoltagesCell_16.isValid ? _batteryVoltagesCell_16.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_17: _batteryVoltagesCell_17.isValid ? _batteryVoltagesCell_17.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_18: _batteryVoltagesCell_18.isValid ? _batteryVoltagesCell_18.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_19: _batteryVoltagesCell_19.isValid ? _batteryVoltagesCell_19.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_20: _batteryVoltagesCell_20.isValid ? _batteryVoltagesCell_20.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_21: _batteryVoltagesCell_21.isValid ? _batteryVoltagesCell_21.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_22: _batteryVoltagesCell_22.isValid ? _batteryVoltagesCell_22.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_23: _batteryVoltagesCell_23.isValid ? _batteryVoltagesCell_23.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_24: _batteryVoltagesCell_24.isValid ? _batteryVoltagesCell_24.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_25: _batteryVoltagesCell_25.isValid ? _batteryVoltagesCell_25.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_26: _batteryVoltagesCell_26.isValid ? _batteryVoltagesCell_26.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_27: _batteryVoltagesCell_27.isValid ? _batteryVoltagesCell_27.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_28: _batteryVoltagesCell_28.isValid ? _batteryVoltagesCell_28.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_29: _batteryVoltagesCell_29.isValid ? _batteryVoltagesCell_29.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_30: _batteryVoltagesCell_30.isValid ? _batteryVoltagesCell_30.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_31: _batteryVoltagesCell_31.isValid ? _batteryVoltagesCell_31.value.toFixed(3) : "--"
	readonly property string batteryVoltagesCell_32: _batteryVoltagesCell_32.isValid ? _batteryVoltagesCell_32.value.toFixed(3) : "--"


	readonly property VeQuickItem _batteryBalancesCell_1: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell1" }
	readonly property VeQuickItem _batteryBalancesCell_2: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell2" }
	readonly property VeQuickItem _batteryBalancesCell_3: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell3" }
	readonly property VeQuickItem _batteryBalancesCell_4: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell4" }
	readonly property VeQuickItem _batteryBalancesCell_5: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell5" }
	readonly property VeQuickItem _batteryBalancesCell_6: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell6" }
	readonly property VeQuickItem _batteryBalancesCell_7: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell7" }
	readonly property VeQuickItem _batteryBalancesCell_8: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell8" }
	readonly property VeQuickItem _batteryBalancesCell_9: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell9" }
	readonly property VeQuickItem _batteryBalancesCell_10: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell10" }
	readonly property VeQuickItem _batteryBalancesCell_11: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell11" }
	readonly property VeQuickItem _batteryBalancesCell_12: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell12" }
	readonly property VeQuickItem _batteryBalancesCell_13: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell13" }
	readonly property VeQuickItem _batteryBalancesCell_14: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell14" }
	readonly property VeQuickItem _batteryBalancesCell_15: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell15" }
	readonly property VeQuickItem _batteryBalancesCell_16: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell16" }
	readonly property VeQuickItem _batteryBalancesCell_17: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell17" }
	readonly property VeQuickItem _batteryBalancesCell_18: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell18" }
	readonly property VeQuickItem _batteryBalancesCell_19: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell19" }
	readonly property VeQuickItem _batteryBalancesCell_20: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell20" }
	readonly property VeQuickItem _batteryBalancesCell_21: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell21" }
	readonly property VeQuickItem _batteryBalancesCell_22: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell22" }
	readonly property VeQuickItem _batteryBalancesCell_23: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell23" }
	readonly property VeQuickItem _batteryBalancesCell_24: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell24" }
	readonly property VeQuickItem _batteryBalancesCell_25: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell25" }
	readonly property VeQuickItem _batteryBalancesCell_26: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell26" }
	readonly property VeQuickItem _batteryBalancesCell_27: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell27" }
	readonly property VeQuickItem _batteryBalancesCell_28: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell28" }
	readonly property VeQuickItem _batteryBalancesCell_29: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell29" }
	readonly property VeQuickItem _batteryBalancesCell_30: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell30" }
	readonly property VeQuickItem _batteryBalancesCell_31: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell31" }
	readonly property VeQuickItem _batteryBalancesCell_32: VeQuickItem { uid: root.bindPrefix + "/Balances/Cell32" }


	readonly property string cellTextColor1: _batteryBalancesCell_1.isValid && _batteryBalancesCell_1.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_1 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor2: _batteryBalancesCell_2.isValid && _batteryBalancesCell_2.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_2 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor3: _batteryBalancesCell_3.isValid && _batteryBalancesCell_3.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_3 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor4: _batteryBalancesCell_4.isValid && _batteryBalancesCell_4.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_4 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor5: _batteryBalancesCell_5.isValid && _batteryBalancesCell_5.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_5 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor6: _batteryBalancesCell_6.isValid && _batteryBalancesCell_6.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_6 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor7: _batteryBalancesCell_7.isValid && _batteryBalancesCell_7.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_7 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor8: _batteryBalancesCell_8.isValid && _batteryBalancesCell_8.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_8 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor9: _batteryBalancesCell_9.isValid && _batteryBalancesCell_9.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_9 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor10: _batteryBalancesCell_10.isValid && _batteryBalancesCell_10.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_10 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor11: _batteryBalancesCell_11.isValid && _batteryBalancesCell_11.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_11 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor12: _batteryBalancesCell_12.isValid && _batteryBalancesCell_12.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_12 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor13: _batteryBalancesCell_13.isValid && _batteryBalancesCell_13.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_13 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor14: _batteryBalancesCell_14.isValid && _batteryBalancesCell_14.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_14 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor15: _batteryBalancesCell_15.isValid && _batteryBalancesCell_15.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_15 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor16: _batteryBalancesCell_16.isValid && _batteryBalancesCell_16.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_16 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor17: _batteryBalancesCell_17.isValid && _batteryBalancesCell_17.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_17 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor18: _batteryBalancesCell_18.isValid && _batteryBalancesCell_18.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_18 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor19: _batteryBalancesCell_19.isValid && _batteryBalancesCell_19.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_19 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor20: _batteryBalancesCell_20.isValid && _batteryBalancesCell_20.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_20 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor21: _batteryBalancesCell_21.isValid && _batteryBalancesCell_21.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_21 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor22: _batteryBalancesCell_22.isValid && _batteryBalancesCell_22.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_22 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor23: _batteryBalancesCell_23.isValid && _batteryBalancesCell_23.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_23 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor24: _batteryBalancesCell_24.isValid && _batteryBalancesCell_24.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_24 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor25: _batteryBalancesCell_25.isValid && _batteryBalancesCell_25.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_25 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor26: _batteryBalancesCell_26.isValid && _batteryBalancesCell_26.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_26 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor27: _batteryBalancesCell_27.isValid && _batteryBalancesCell_27.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_27 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor28: _batteryBalancesCell_28.isValid && _batteryBalancesCell_28.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_28 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor29: _batteryBalancesCell_29.isValid && _batteryBalancesCell_29.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_29 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor30: _batteryBalancesCell_30.isValid && _batteryBalancesCell_30.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_30 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor31: _batteryBalancesCell_31.isValid && _batteryBalancesCell_31.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_31 ? "#387DC5" : "#b80101") : Theme.color_font_primary
	readonly property string cellTextColor32: _batteryBalancesCell_32.isValid && _batteryBalancesCell_32.value == "1" ? (batteryMinCellVoltage == batteryVoltagesCell_32 ? "#387DC5" : "#b80101") : Theme.color_font_primary

	VeQuickItem {
		id: _batteryCellVoltageSum
		uid: root.bindPrefix + "/Voltages/Sum"
	}
	VeQuickItem {
		id: _batteryCellVoltageDiff
		uid: root.bindPrefix + "/Voltages/Diff"
	}
	VeQuickItem {
		id: _batteryMinCellVoltage
		uid: root.bindPrefix + "/System/MinCellVoltage"
	}
	VeQuickItem {
		id: _batteryMaxCellVoltage
		uid: root.bindPrefix + "/System/MaxCellVoltage"
	}

	GradientListView {
		model: ObjectModel {

			ListItem {
				text: "Overview"
				content.children: [
					Column {
						//width: (overviewList.width - (Theme.geometry_page_content_horizontalMargin * 2)) / 5
						width: 110
						Text {
							text: batteryCellVoltageSum != "--" ? batteryCellVoltageSum + "V" : "--"
							color: Theme.color_font_primary
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Sum"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						//width: (overviewList.width - (Theme.geometry_page_content_horizontalMargin * 2)) / 5
						width: 110
						Text {
							text: batteryCellVoltageDiff != "--" ? batteryCellVoltageDiff + "V" : "--"
							color: Theme.color_font_primary
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Diff"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						//width: (overviewList.width - (Theme.geometry_page_content_horizontalMargin * 2)) / 5
						width: 110
						Text {
							text: batteryMaxCellVoltage != "--" ? batteryMaxCellVoltage + "V" : "--"
							color: Theme.color_font_primary
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Max"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						//width: (overviewList.width - (Theme.geometry_page_content_horizontalMargin * 2)) / 5
						width: 110
						Text {
							text: batteryMinCellVoltage != "--" ? batteryMinCellVoltage + "V" : "--"
							color: Theme.color_font_primary
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Min"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]

			}

			ListItem {
				text: "Cells 1-4"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_1 != "--" ? batteryVoltagesCell_1 + "V" : "--"
							color: cellTextColor1
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 1"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_2 != "--" ? batteryVoltagesCell_2 + "V" : "--"
							color: cellTextColor2
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 2"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_3 != "--" ? batteryVoltagesCell_3 + "V" : "--"
							color: cellTextColor3
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 3"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_4 != "--" ? batteryVoltagesCell_4 + "V" : "--"
							color: cellTextColor4
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 4"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

			ListItem {
				text: "Cells 5-8"
				preferredVisible: batteryVoltagesCell_5 != "--"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_5 != "--" ? batteryVoltagesCell_5 + "V" : "--"
							color: cellTextColor5
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 5"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_6 != "--" ? batteryVoltagesCell_6 + "V" : "--"
							color: cellTextColor6
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 6"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_7 != "--" ? batteryVoltagesCell_7 + "V" : "--"
							color: cellTextColor7
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 7"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_8 != "--" ? batteryVoltagesCell_8 + "V" : "--"
							color: cellTextColor8
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 8"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

			ListItem {
				text: "Cells 9-12"
				preferredVisible: batteryVoltagesCell_9 != "--"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_9 != "--" ? batteryVoltagesCell_9 + "V" : "--"
							color: cellTextColor9
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 9"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_10 != "--" ? batteryVoltagesCell_10 + "V" : "--"
							color: cellTextColor10
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 10"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_11 != "--" ? batteryVoltagesCell_11 + "V" : "--"
							color: cellTextColor11
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 11"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_12 != "--" ? batteryVoltagesCell_12 + "V" : "--"
							color: cellTextColor12
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 12"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

			ListItem {
				text: "Cells 13-16"
				preferredVisible: batteryVoltagesCell_13 != "--"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_13 != "--" ? batteryVoltagesCell_13 + "V" : "--"
							color: cellTextColor13
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 13"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_14 != "--" ? batteryVoltagesCell_14 + "V" : "--"
							color: cellTextColor14
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 14"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_15 != "--" ? batteryVoltagesCell_15 + "V" : "--"
							color: cellTextColor15
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 15"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_16 != "--" ? batteryVoltagesCell_16 + "V" : "--"
							color: cellTextColor16
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 16"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

			ListItem {
				text: "Cells 17-20"
				preferredVisible: batteryVoltagesCell_17 != "--"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_17 != "--" ? batteryVoltagesCell_17 + "V" : "--"
							color: cellTextColor17
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 17"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_18 != "--" ? batteryVoltagesCell_18 + "V" : "--"
							color: cellTextColor18
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 18"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_19 != "--" ? batteryVoltagesCell_19 + "V" : "--"
							color: cellTextColor19
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 19"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_20 != "--" ? batteryVoltagesCell_20 + "V" : "--"
							color: cellTextColor20
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 20"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

			ListItem {
				text: "Cells 21-24"
				preferredVisible: batteryVoltagesCell_21 != "--"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_21 != "--" ? batteryVoltagesCell_21 + "V" : "--"
							color: cellTextColor21
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 21"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_22 != "--" ? batteryVoltagesCell_22 + "V" : "--"
							color: cellTextColor22
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 22"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_23 != "--" ? batteryVoltagesCell_23 + "V" : "--"
							color: cellTextColor23
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 23"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_24 != "--" ? batteryVoltagesCell_24 + "V" : "--"
							color: cellTextColor24
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 24"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

			ListItem {
				text: "Cells 25-28"
				preferredVisible: batteryVoltagesCell_25 != "--"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_25 != "--" ? batteryVoltagesCell_25 + "V" : "--"
							color: cellTextColor25
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 25"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_26 != "--" ? batteryVoltagesCell_26 + "V" : "--"
							color: cellTextColor26
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 26"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_27 != "--" ? batteryVoltagesCell_27 + "V" : "--"
							color: cellTextColor27
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 27"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_28 != "--" ? batteryVoltagesCell_28 + "V" : "--"
							color: cellTextColor28
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 28"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

			ListItem {
				text: "Cells 29-32"
				preferredVisible: batteryVoltagesCell_29 != "--"
				content.children: [
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_29 != "--" ? batteryVoltagesCell_29 + "V" : "--"
							color: cellTextColor29
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 29"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_30 != "--" ? batteryVoltagesCell_30 + "V" : "--"
							color: cellTextColor30
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 30"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_31 != "--" ? batteryVoltagesCell_31 + "V" : "--"
							color: cellTextColor31
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 31"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					},
					Column {
						width: 110
						Text {
							text: batteryVoltagesCell_32 != "--" ? batteryVoltagesCell_32 + "V" : "--"
							color: cellTextColor32
							font.pixelSize: 22
							anchors.horizontalCenter: parent.horizontalCenter
						}
						Text {
							text: "Cell 32"
							color: Theme.color_font_secondary
							font.pixelSize: 16
							anchors.horizontalCenter: parent.horizontalCenter
						}
					}
				]
			}

		}
	}
}
