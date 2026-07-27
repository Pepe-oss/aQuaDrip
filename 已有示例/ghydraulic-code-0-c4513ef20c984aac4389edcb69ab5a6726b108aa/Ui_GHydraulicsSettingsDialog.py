# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'settings.ui'
#
# Created: Sat Aug 10 08:51:29 2013
#      by: PyQt4 UI code generator 4.10
#
# WARNING! All changes made in this file will be lost!

from PyQt4 import QtCore, QtGui

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    def _fromUtf8(s):
        return s

try:
    _encoding = QtGui.QApplication.UnicodeUTF8
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig, _encoding)
except AttributeError:
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig)

class Ui_GHydraulicsSettingsDialog(object):
    def setupUi(self, GHydraulicsSettingsDialog):
        GHydraulicsSettingsDialog.setObjectName(_fromUtf8("GHydraulicsSettingsDialog"))
        GHydraulicsSettingsDialog.resize(640, 480)
        self.buttonBox = QtGui.QDialogButtonBox(GHydraulicsSettingsDialog)
        self.buttonBox.setGeometry(QtCore.QRect(10, 440, 621, 32))
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtGui.QDialogButtonBox.Cancel|QtGui.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName(_fromUtf8("buttonBox"))
        self.treeWidget = QtGui.QTreeWidget(GHydraulicsSettingsDialog)
        self.treeWidget.setGeometry(QtCore.QRect(0, 0, 631, 331))
        self.treeWidget.setDragDropMode(QtGui.QAbstractItemView.InternalMove)
        self.treeWidget.setObjectName(_fromUtf8("treeWidget"))
        item_0 = QtGui.QTreeWidgetItem(self.treeWidget)
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(_fromUtf8("icons/junction.svg")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item_0.setIcon(0, icon)
        item_0.setFlags(QtCore.Qt.ItemIsDropEnabled|QtCore.Qt.ItemIsEnabled)
        item_0 = QtGui.QTreeWidgetItem(self.treeWidget)
        icon1 = QtGui.QIcon()
        icon1.addPixmap(QtGui.QPixmap(_fromUtf8("icons/pipe.svg")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item_0.setIcon(0, icon1)
        item_0.setFlags(QtCore.Qt.ItemIsDropEnabled|QtCore.Qt.ItemIsEnabled)
        item_0 = QtGui.QTreeWidgetItem(self.treeWidget)
        icon2 = QtGui.QIcon()
        icon2.addPixmap(QtGui.QPixmap(_fromUtf8("icons/reservoir.svg")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item_0.setIcon(0, icon2)
        item_0.setFlags(QtCore.Qt.ItemIsDropEnabled|QtCore.Qt.ItemIsEnabled)
        item_0 = QtGui.QTreeWidgetItem(self.treeWidget)
        icon3 = QtGui.QIcon()
        icon3.addPixmap(QtGui.QPixmap(_fromUtf8("icons/pump.svg")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item_0.setIcon(0, icon3)
        item_0.setFlags(QtCore.Qt.ItemIsDropEnabled|QtCore.Qt.ItemIsEnabled)
        item_0 = QtGui.QTreeWidgetItem(self.treeWidget)
        icon4 = QtGui.QIcon()
        icon4.addPixmap(QtGui.QPixmap(_fromUtf8("icons/valve.svg")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item_0.setIcon(0, icon4)
        item_0.setFlags(QtCore.Qt.ItemIsDropEnabled|QtCore.Qt.ItemIsEnabled)
        item_0 = QtGui.QTreeWidgetItem(self.treeWidget)
        item_0.setToolTip(0, _fromUtf8(""))
        icon5 = QtGui.QIcon()
        icon5.addPixmap(QtGui.QPixmap(_fromUtf8("icons/tank.svg")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item_0.setIcon(0, icon5)
        item_0.setFlags(QtCore.Qt.ItemIsDropEnabled|QtCore.Qt.ItemIsEnabled)
        item_0 = QtGui.QTreeWidgetItem(self.treeWidget)
        item_0.setToolTip(0, _fromUtf8(""))
        icon6 = QtGui.QIcon()
        icon6.addPixmap(QtGui.QPixmap(_fromUtf8("icons/folder.svg")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        item_0.setIcon(0, icon6)
        item_0.setFlags(QtCore.Qt.ItemIsDropEnabled|QtCore.Qt.ItemIsEnabled)
        item_1 = QtGui.QTreeWidgetItem(item_0)
        item_1.setFlags(QtCore.Qt.ItemIsEnabled)
        self.inpFilePushButton = QtGui.QPushButton(GHydraulicsSettingsDialog)
        self.inpFilePushButton.setGeometry(QtCore.QRect(530, 340, 98, 27))
        self.inpFilePushButton.setObjectName(_fromUtf8("inpFilePushButton"))
        self.inpFileLineEdit = QtGui.QLineEdit(GHydraulicsSettingsDialog)
        self.inpFileLineEdit.setGeometry(QtCore.QRect(180, 340, 341, 27))
        self.inpFileLineEdit.setObjectName(_fromUtf8("inpFileLineEdit"))
        self.inpFileLabel = QtGui.QLabel(GHydraulicsSettingsDialog)
        self.inpFileLabel.setGeometry(QtCore.QRect(10, 340, 161, 21))
        self.inpFileLabel.setObjectName(_fromUtf8("inpFileLabel"))
        self.autoLengthCB = QtGui.QCheckBox(GHydraulicsSettingsDialog)
        self.autoLengthCB.setGeometry(QtCore.QRect(180, 370, 441, 22))
        self.autoLengthCB.setObjectName(_fromUtf8("autoLengthCB"))
        self.writeBackdropCB = QtGui.QCheckBox(GHydraulicsSettingsDialog)
        self.writeBackdropCB.setGeometry(QtCore.QRect(180, 390, 441, 22))
        self.writeBackdropCB.setObjectName(_fromUtf8("writeBackdropCB"))

        self.retranslateUi(GHydraulicsSettingsDialog)
        QtCore.QObject.connect(self.buttonBox, QtCore.SIGNAL(_fromUtf8("accepted()")), GHydraulicsSettingsDialog.accept)
        QtCore.QObject.connect(self.buttonBox, QtCore.SIGNAL(_fromUtf8("rejected()")), GHydraulicsSettingsDialog.reject)
        QtCore.QMetaObject.connectSlotsByName(GHydraulicsSettingsDialog)

    def retranslateUi(self, GHydraulicsSettingsDialog):
        GHydraulicsSettingsDialog.setWindowTitle(_translate("GHydraulicsSettingsDialog", "GHydraulics Settings", None))
        self.treeWidget.headerItem().setText(0, _translate("GHydraulicsSettingsDialog", "Model Elements", None))
        __sortingEnabled = self.treeWidget.isSortingEnabled()
        self.treeWidget.setSortingEnabled(False)
        self.treeWidget.topLevelItem(0).setText(0, _translate("GHydraulicsSettingsDialog", "Junctions", None))
        self.treeWidget.topLevelItem(1).setText(0, _translate("GHydraulicsSettingsDialog", "Pipes", None))
        self.treeWidget.topLevelItem(2).setText(0, _translate("GHydraulicsSettingsDialog", "Reservoirs", None))
        self.treeWidget.topLevelItem(3).setText(0, _translate("GHydraulicsSettingsDialog", "Pumps", None))
        self.treeWidget.topLevelItem(4).setText(0, _translate("GHydraulicsSettingsDialog", "Valves", None))
        self.treeWidget.topLevelItem(5).setText(0, _translate("GHydraulicsSettingsDialog", "Tanks", None))
        self.treeWidget.topLevelItem(6).setText(0, _translate("GHydraulicsSettingsDialog", "Unused", None))
        self.treeWidget.topLevelItem(6).child(0).setText(0, _translate("GHydraulicsSettingsDialog", "Add some vector layers to your project. They will appear here.", None))
        self.treeWidget.setSortingEnabled(__sortingEnabled)
        self.inpFilePushButton.setText(_translate("GHydraulicsSettingsDialog", "Select", None))
        self.inpFileLabel.setText(_translate("GHydraulicsSettingsDialog", "Template (INP file)", None))
        self.autoLengthCB.setText(_translate("GHydraulicsSettingsDialog", "Calculate pipe length", None))
        self.writeBackdropCB.setText(_translate("GHydraulicsSettingsDialog", "Write backdrop map", None))

