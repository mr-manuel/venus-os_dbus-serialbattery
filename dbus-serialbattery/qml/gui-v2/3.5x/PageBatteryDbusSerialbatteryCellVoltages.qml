/*
** Copyright (C) 2025 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	//% "dbus-serialbattery - Cell Voltages"
	title: qsTrId("dbus_serialbattery_cell_voltages_title")

	property string bindPrefix

	property real cellVoltagesMean: NaN
	readonly property int cellCount: 32
	readonly property real cellVoltageDiffThreshold: isNaN(cellVoltagesMean) ? NaN : cellVoltagesMean * 0.05 // 5% of mean voltage

	// Arrays to hold references to VeQuickItems
	property var cellVoltageItems: []
	property var cellBalanceItems: []

	function getCellTextColor(cell) {
		if (cell < 1 || cell > cellCount) {
			return Theme.color_font_primary;
		}
		var voltageCellItem = cellVoltageItems[cell - 1];
		var balanceCellItem = cellBalanceItems[cell - 1];
		if (!voltageCellItem || !balanceCellItem) {
			return Theme.color_font_primary;
		}
		if (cellVoltageMin.valid && cellVoltageMax.valid && voltageCellItem.valid && balanceCellItem.valid && balanceCellItem.value == "1") {
			return (cellVoltageMin.value == voltageCellItem.value) ? Theme.color_blue
				: (cellVoltageMax.value == voltageCellItem.value) ? Theme.color_red
				: Theme.color_orange;
		} else {
			return Theme.color_font_primary;
		}
	}

	// Get mean cell voltage by adding all cell voltages and dividing by number of cells
	// since the battery voltage is not accurate enough
	function updateCellVoltagesMean() {
		var sum = 0;
		var count = 0;
		for (var cell = 1; cell <= cellCount; cell++) {
			var cellItem = cellVoltageItems[cell - 1];
			if (cellItem && cellItem.valid && cellItem.value != 0) {
				sum += cellItem.value;
				count += 1;
			}
		}
		cellVoltagesMean = (count > 0) ? (sum / count) : NaN;
	}

	// Use Repeaters to create VeQuickItems for voltages and balances
	Repeater {
		id: voltageRepeater
		model: root.cellCount
		delegate: Item {
			property int cellIndex: index
			VeQuickItem {
				id: voltageItem
				uid: root.bindPrefix + "/Voltages/Cell" + (cellIndex + 1)
				onValidChanged: root.updateCellVoltagesMean()
				onValueChanged: root.updateCellVoltagesMean()
				Component.onCompleted: {
					root.cellVoltageItems[cellIndex] = voltageItem;
					// Trigger a slice to notify that the array has changed
					if (cellIndex === root.cellCount - 1) {
						root.cellVoltageItems = root.cellVoltageItems.slice(0);
					}
				}
			}
		}
	}
	Repeater {
		id: balanceRepeater
		model: root.cellCount
		delegate: Item {
			property int cellIndex: index
			VeQuickItem {
				id: balanceItem
				uid: root.bindPrefix + "/Balances/Cell" + (cellIndex + 1)
				Component.onCompleted: {
					root.cellBalanceItems[cellIndex] = balanceItem;
					// Trigger a slice to notify that the array has changed
					if (cellIndex === root.cellCount - 1) {
						root.cellBalanceItems = root.cellBalanceItems.slice(0);
					}
				}
			}
		}
	}

	VeQuickItem {
		id: cellVoltageSum
		uid: root.bindPrefix + "/Voltages/Sum"
	}
	VeQuickItem {
		id: cellVoltageDiff
		uid: root.bindPrefix + "/Voltages/Diff"
	}
	VeQuickItem {
		id: cellVoltageMin
		uid: root.bindPrefix + "/System/MinCellVoltage"
	}
	VeQuickItem {
		id: cellVoltageMax
		uid: root.bindPrefix + "/System/MaxCellVoltage"
	}

	GradientListView {
		model: ObjectModel {

			ListItem {
				id: cellOverviewItem
				//% "Overview"
				text: qsTrId("dbus_serialbattery_cell_voltages_overview")
				content.children: [
					Row {
						id: contentRowOverview

						readonly property real itemWidth: (width - (spacing * 4)) / 5

						width: cellOverviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellVoltageSum.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 2
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Sum"
								text: qsTrId("dbus_serialbattery_cell_voltages_sum")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellVoltagesMean ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Mean"
								text: "Ø " + qsTrId("dbus_serialbattery_cell_voltages_mean")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellVoltageMin.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Min"
								text: qsTrId("dbus_serialbattery_cell_voltages_min")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellVoltageMax.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Max"
								text: qsTrId("dbus_serialbattery_cell_voltages_max")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellVoltageDiff.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								//% "Diff"
								text: qsTrId("dbus_serialbattery_cell_voltages_diff")
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
					}
				]
			}

			Column {
				width: parent ? parent.width : 0
				spacing: Theme.geometry_gradientList_spacing

				Repeater {
					id: cellRowRepeater
					model: 8
					delegate: ListItem {
						id: cellListItem

						property int outerIndex: model.index

						//% "Cells %1-%2"
						text: qsTrId("dbus_serialbattery_cell_voltages_cells").arg(model.index * 4 + 1).arg(model.index * 4 + 4)
						allowed: defaultAllowed && ((
							root.cellVoltageItems[outerIndex * 4 + 0] && root.cellVoltageItems[outerIndex * 4 + 0].valid
						) || (
							root.cellVoltageItems[outerIndex * 4 + 1] && root.cellVoltageItems[outerIndex * 4 + 1].valid
						) || (
							root.cellVoltageItems[outerIndex * 4 + 2] && root.cellVoltageItems[outerIndex * 4 + 2].valid
						) || (
							root.cellVoltageItems[outerIndex * 4 + 3] && root.cellVoltageItems[outerIndex * 4 + 3].valid
						))
						content.children: [
							Row {
								id: contentRow

								readonly property real itemWidth: (width - (spacing * (cellRepeater.count - 1))) / cellRepeater.count

								width: cellListItem.maximumContentWidth
								// spacing: Theme.geometry_listItem_content_spacing

								Repeater {
									id: cellRepeater
									model: 4
									delegate: Column {
										width: contentRow.itemWidth

										readonly property var cellVoltageRef: root.cellVoltageItems[outerIndex * 4 + model.index]
										readonly property real cellVoltageMeanDiff: cellVoltageRef && cellVoltageRef.valid ? (cellVoltageRef.value - cellVoltagesMean) : NaN

										QuantityLabel {
											width: parent.width
											value: cellVoltageRef && cellVoltageRef.valid ? cellVoltageRef.value : NaN
											unit: VenusOS.Units_Volt_DC
											precision: 3
											font.pixelSize: 22
											valueColor: getCellTextColor(outerIndex * 4 + model.index + 1)
											visible: cellVoltageRef.valid
										}

										Label {
											width: parent.width
											horizontalAlignment: Text.AlignHCenter
											text: isNaN(cellVoltageMeanDiff) ? "" : "Ø " + (cellVoltageMeanDiff > 0 ? "+" : "") + cellVoltageMeanDiff.toFixed(3) + " V"
											color: isNaN(cellVoltageMeanDiff)
												? Theme.color_font_secondary
												: (cellVoltageMeanDiff > cellVoltageDiffThreshold ? Theme.color_red
													: cellVoltageMeanDiff < -cellVoltageDiffThreshold ? Theme.color_blue
													: Theme.color_font_secondary)
											font.pixelSize: Theme.font_size_caption
											visible: cellVoltageRef.valid
										}
									}
								}

							}
						]
					}
				}
			}
		}
	}
}
