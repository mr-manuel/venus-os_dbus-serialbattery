/*
** Copyright (C) 2025 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	property string bindPrefix

    function getCellTextColor(cell) {
        if (cell < 1 || cell > 32) {
            return Theme.color_font_primary;
        }

        var balanceCellItem = Qt.createQmlObject('import Victron.VenusOS; VeQuickItem { uid: "' + root.bindPrefix + "/Balances/Cell" + cell + '" }', root);
        var voltageCellItem = Qt.createQmlObject('import Victron.VenusOS; VeQuickItem { uid: "' + root.bindPrefix + "/Voltages/Cell" + cell + '" }', root);

        if (cellMin.valid && cellMax.valid && voltageCellItem.valid && balanceCellItem.valid && balanceCellItem.value == "1") {
            return (cellMin.value == voltageCellItem.value) ? "#295C91"
				: (cellMax.value == voltageCellItem.value) ? "#BF4845"
				: "#BD7624";
        } else {
            return Theme.color_font_primary;
        }
    }

	VeQuickItem {
		id: cellSum
		uid: root.bindPrefix + "/Voltages/Sum"
	}
	VeQuickItem {
		id: cellDiff
		uid: root.bindPrefix + "/Voltages/Diff"
	}
	VeQuickItem {
		id: cellMin
		uid: root.bindPrefix + "/System/MinCellVoltage"
	}
	VeQuickItem {
		id: cellMax
		uid: root.bindPrefix + "/System/MaxCellVoltage"
	}

	GradientListView {
		model: VisibleItemModel {

			ListItem {
				id: cellOverviewItem
				text: "Overview"
				content.children: [
					Row {
						id: contentRowOverview

						readonly property real itemWidth: (width - (spacing * 3)) / 4

						width: cellOverviewItem.maximumContentWidth
						spacing: Theme.geometry_listItem_content_spacing

						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellSum.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 2
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								text: "Sum"
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellDiff.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								text: "Diff"
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellMax.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								text: "Max"
								color: Theme.color_font_secondary
								font.pixelSize: Theme.font_size_caption
							}
						}
						Column {
							width: contentRowOverview.itemWidth

							QuantityLabel {
								width: parent.width
								value: cellMin.value ?? NaN
								unit: VenusOS.Units_Volt_DC
								precision: 3
								font.pixelSize: 22
							}

							Label {
								width: parent.width
								horizontalAlignment: Text.AlignHCenter
								text: "Min"
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

						text: "Cells %1-%2".arg(model.index * 4 + 1).arg(model.index * 4 + 4)
						preferredVisible: firstColumnCellVoltage.valid ||
							secondColumnCellVoltage.valid ||
							thirdColumnCellVoltage.valid ||
							fourthColumnCellVoltage.valid
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

										QuantityLabel {
											width: parent.width
											value: cellVoltage.value ?? NaN
											unit: VenusOS.Units_Volt_DC
											precision: 3
											font.pixelSize: 22
											valueColor: getCellTextColor(outerIndex * 4 + model.index + 1)
										}

										Label {
											width: parent.width
											horizontalAlignment: Text.AlignHCenter
											text: "Cell %1".arg(outerIndex * 4 + model.index + 1)
											color: Theme.color_font_secondary
											font.pixelSize: Theme.font_size_caption
										}

										VeQuickItem {
											id: cellVoltage
											uid: root.bindPrefix + "/Voltages/Cell%1".arg(outerIndex * 4 + model.index + 1)
										}
									}
								}

								VeQuickItem {
									id: firstColumnCellVoltage
									uid: root.bindPrefix + "/Voltages/Cell%1".arg(outerIndex * 4 + 1)
								}

								VeQuickItem {
									id: secondColumnCellVoltage
									uid: root.bindPrefix + "/Voltages/Cell%1".arg(outerIndex * 4 + 2)
								}

								VeQuickItem {
									id: thirdColumnCellVoltage
									uid: root.bindPrefix + "/Voltages/Cell%1".arg(outerIndex * 4 + 3)
								}

								VeQuickItem {
									id: fourthColumnCellVoltage
									uid: root.bindPrefix + "/Voltages/Cell%1".arg(outerIndex * 4 + 4)
								}
							}
						]
					}
				}
			}
		}
	}
}
