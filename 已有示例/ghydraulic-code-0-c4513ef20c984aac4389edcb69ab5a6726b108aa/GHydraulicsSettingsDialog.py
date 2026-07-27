#
# This file is part of GHydraulics
#
# GHydraulicsSettingsDialog.py - Manage settings for projects
#
# Copyright 2007 - 2013 Steffen Macke <sdteffen@sdteffen.de>
#
# GHydraulics is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2, or (at your option) any later version.
#
# GHydraulics is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with program; see the file COPYING. If not,
# write to the Free Software Foundation, Inc., 59 Temple Place
# - Suite 330, Boston, MA 02111-1307, USA.
#
# QGIS 2.0.0 or better required to run this file
#
from pickle import *
import os
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from qgis.gui import *
from EpanetModel import *
from Ui_GHydraulicsSettingsDialog import *

class GHydraulicsSettingsDialog(QDialog):
    # Store all configuration data under this key
    SETTINGS = 'ghydraulics'
    # Store auto length configuration under this key
    AUTO_LENGTH = 'autolength'
        # Store backdrop map configuration under this key
    WRITE_BACKDROP = 'writebackdrop'

    STRING_TRUE = '1'
    STRING_FALSE = '0'
    UNUSED_ITEM = 6
    UNUSED = 'Unused'

    def accepted(self):
        # Store layers
        proj = QgsProject.instance()
        treewidget = self.ui.treeWidget
        parent = None
        for i in range(0, treewidget.topLevelItemCount()):
            item = treewidget.topLevelItem(i)
            if item.text(0) == self.UNUSED:
                parent = item
        i = 0
        while i < treewidget.topLevelItemCount():
            item = treewidget.topLevelItem(i)
            if item.toolTip(0) == '':
                item = treewidget.takeTopLevelItem(i)
                parent.insertChild(0, item)
            else:
                parent = item
            i = i+1

        for i in range(0,self.UNUSED_ITEM):
            treeitem = treewidget.topLevelItem(i)
            layers = []
            for j in range(0,treeitem.childCount()):
                layers.append(str(treeitem.child(j).text(0)))
            proj.writeEntry("ghydraulics",EpanetModel.GIS_SECTIONS[i], dumps(layers))
        # Store Inp file
        templatedir = os.path.join(os.path.dirname(__file__), 'etc')
        template = str(self.ui.inpFileLineEdit.text()).replace(templatedir+os.path.sep, '')
        proj.writeEntry("ghydraulics","templateinpfile", template)
        # Store auto length configuration
        autoLength = self.STRING_FALSE
        if self.ui.autoLengthCB.isChecked():
            autoLength = self.STRING_TRUE
        proj.writeEntry(self.SETTINGS, self.AUTO_LENGTH, autoLength)
                # Store backdrop configuration
        writeBackdrop = self.STRING_FALSE
        if self.ui.writeBackdropCB.isChecked():
            writeBackdrop = self.STRING_TRUE
        proj.writeEntry(self.SETTINGS, self.WRITE_BACKDROP, writeBackdrop)

    def selectInpFile(self):
        f = QFileDialog.getOpenFileName()
        if 0 < len(f):
            self.ui.inpFileLineEdit.setText(f)

    def getTemplate(self):
        project = QgsProject.instance()
        template = str(project.readEntry("ghydraulics", "templateinpfile")[0])
        if os.path.isfile(template):
            return template
        templatedir = os.path.join(os.path.dirname(__file__), 'etc')
        templatepath = os.path.join(templatedir, template)
        if os.path.isfile(templatepath):
            return templatepath
        return os.path.join(templatedir, 'template_d-w_cmd.inp')

    # True if length should be calculated automatically, otherwise false
    def getAutoLength(self):
        project = QgsProject.instance()
        return  self.STRING_TRUE == str(project.readEntry(self.SETTINGS, self.AUTO_LENGTH)[0])

        # True if backdrop map should be written, otherwise false
    def getWriteBackdrop(self):
        project = QgsProject.instance()
        return self.STRING_TRUE == str(project.readEntry(self.SETTINGS, self.WRITE_BACKDROP)[0])

    def __init__(self):
        QDialog.__init__(self)
        self.ui = Ui_GHydraulicsSettingsDialog()
        self.ui.setupUi(self)
        QObject.connect(self.ui.buttonBox, SIGNAL("accepted()"), self.accepted)
        QObject.connect(self.ui.inpFilePushButton, SIGNAL("clicked()"), self.selectInpFile)
        treeWidget = self.ui.treeWidget
        treeWidget.topLevelItem(self.UNUSED_ITEM).setToolTip(0, 'Drag vector layers from here to configure your model.')
        for i in range(0,self.UNUSED_ITEM):
            item = treeWidget.topLevelItem(i)
            item.setToolTip(0, 'Drop vector layers with '+item.text(0)+' here to configure your model.')
