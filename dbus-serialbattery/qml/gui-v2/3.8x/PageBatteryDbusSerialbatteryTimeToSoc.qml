/*
** Copyright (C) 2023 Victron Energy B.V.
** See LICENSE.txt for license information.
*/

import QtQuick
import Victron.VenusOS

Page {
	id: root

	property string bindPrefix

	function getTimeToSocText(dataItem) {
		if (dataItem.valid && Number.isInteger(Number(dataItem.value)) && dataItem.value > 0) {
			return Utils.secondsToString(dataItem.value);
		} else if (dataItem.valid && dataItem.value !== "") {
			return dataItem.value;
		} else {
			return "--";
		}
	}

	GradientListView {
		model: VisibleItemModel {
			ListText {
				//% "Time-to-SoC 0%"
				text: "Time-to-SoC 0%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/0"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 5%"
				text: "Time-to-SoC 5%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/5"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 10%"
				text: "Time-to-SoC 10%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/10"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 15%"
				text: "Time-to-SoC 15%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/15"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 20%"
				text: "Time-to-SoC 20%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/20"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 25%"
				text: "Time-to-SoC 25%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/25"
				secondaryText: getTimeToSocText(dataItem)
			}
            ListText {
                //% "Time-to-SoC 30%"
                text: "Time-to-SoC 30%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/30"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 35%"
                text: "Time-to-SoC 35%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/35"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 40%"
                text: "Time-to-SoC 40%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/40"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 45%"
                text: "Time-to-SoC 45%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/45"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 50%"
                text: "Time-to-SoC 50%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/50"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 55%"
                text: "Time-to-SoC 55%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/55"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 60%"
                text: "Time-to-SoC 60%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/60"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 65%"
                text: "Time-to-SoC 65%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/65"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 70%"
                text: "Time-to-SoC 70%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/70"
                secondaryText: getTimeToSocText(dataItem)
            }
            ListText {
                //% "Time-to-SoC 75%"
                text: "Time-to-SoC 75%"
                preferredVisible: dataItem.seen
                dataItem.uid: root.bindPrefix + "/TimeToSoC/75"
                secondaryText: getTimeToSocText(dataItem)
            }
			ListText {
				//% "Time-to-SoC 80%"
				text: "Time-to-SoC 80%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/80"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 85%"
				text: "Time-to-SoC 85%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/85"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 90%"
				text: "Time-to-SoC 90%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/90"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 95%"
				text: "Time-to-SoC 95%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/95"
				secondaryText: getTimeToSocText(dataItem)
			}
			ListText {
				//% "Time-to-SoC 100%"
				text: "Time-to-SoC 100%"
				preferredVisible: dataItem.seen
				dataItem.uid: root.bindPrefix + "/TimeToSoC/100"
				secondaryText: getTimeToSocText(dataItem)
			}
        }
    }
}
