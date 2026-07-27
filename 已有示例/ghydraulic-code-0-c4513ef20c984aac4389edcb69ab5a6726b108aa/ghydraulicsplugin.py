#
# This file is part of GHydraulics
#
# ghydraulicsplugin.py - The GHydraulics plugin
#
# Copyright 2007 - 2014 Steffen Macke <sdteffen@sdteffen.de>
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

import os
import tempfile
from pickle import *
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from qgis.gui import *
from ghyeconomicdiameter import *
from EpanetModel import *
from GHydraulicsModel import *
from GHydraulicsModelChecker import *
from GHydraulicsModelMaker import *
from GHydraulicsModelRunner import *
from GHydraulicsException import *
from GHydraulicsInpWriter import *
from GHydraulicsResultDialog import *
from GHydraulicsSettingsDialog import *

# initialize Qt resources from file resouces.py
import resources

class GHydraulicsPlugin:
    # Store settings in QGIS projects under this key
    SETTINGS = "ghydraulics"

    VERSION = "2.1.8"

    def __init__(self, iface):
        # save reference to the QGIS interface
        self.iface = iface

    def initGui(self):
        # create actions
        self.action = QAction(QIcon(":/python/plugins/ghydraulic/icon.xpm"), "Calculate economic diameters", self.iface.mainWindow())
        self.action.setWhatsThis("Calculate economic pipe diameters based on flow data.")
        self.settingsAction = QAction(QIcon(':/python/plugins/ghydraulic/icon.xpm'), 'Settings', self.iface.mainWindow())
        self.makeModelAction = QAction(QIcon(':/python/plugins/ghydraulic/icon.xpm'), 'Make EPANET Model', self.iface.mainWindow())
        self.writeInpAction = QAction(QIcon(':/python/plugins/ghydraulic/icon.xpm'), 'Write EPANET INP file', self.iface.mainWindow())
        self.runEpanetAction = QAction(QIcon(':/python/plugins/ghydraulic/icon.xpm'), 'Run EPANET simulation', self.iface.mainWindow())
        self.aboutAction = QAction(QIcon(":/plugins/ghydraulic/about_icon.png"), QCoreApplication.translate('GHydraulics', "&About"), self.iface.mainWindow())
        QObject.connect(self.action, SIGNAL("triggered()"), self.run)
        QObject.connect(self.settingsAction, SIGNAL('triggered()'), self.showSettings)
        QObject.connect(self.makeModelAction, SIGNAL('triggered()'), self.makeModel)
        QObject.connect(self.writeInpAction, SIGNAL('triggered()'), self.writeInpFile)
        QObject.connect(self.runEpanetAction, SIGNAL('triggered()'), self.runEpanet)
        QObject.connect(self.aboutAction, SIGNAL("triggered()"), self.about)

        # add toolbar button and menu item
        self.iface.addToolBarIcon(self.settingsAction)
        self.iface.addPluginToMenu("&GHydraulics", self.settingsAction)
        self.iface.addPluginToMenu('&GHydraulics', self.makeModelAction)
        self.iface.addPluginToMenu("&GHydraulics", self.writeInpAction)
        self.iface.addPluginToMenu('&GHydraulics', self.runEpanetAction)
        self.iface.addPluginToMenu("&GHydraulics", self.action)

        # Projects submenu
        self.project_menu = QMenu('&Projects')

        self.newProjectAction = QAction(self.iface.actionNewProject().icon(), 'New Project', self.iface.mainWindow())
        QObject.connect(self.newProjectAction, SIGNAL('triggered()'), self.newProject)
        self.project_menu.addAction(self.newProjectAction)

        self.sampleDwCmdAction = QAction(QIcon(':/python/plugins/ghydraulic/icon.xpm'), 'Sample Darcy-Weisbach, cubic meters/day', self.iface.mainWindow())
        QObject.connect(self.sampleDwCmdAction, SIGNAL('triggered()'), self.openDwCmdSample)
        self.project_menu.addAction(self.sampleDwCmdAction)

        self.sampleDwLpsAction = QAction(QIcon(':/python/plugins/ghydraulic/icon.xpm'), 'Sample Darcy-Weisbach, liters/second', self.iface.mainWindow())
        QObject.connect(self.sampleDwLpsAction, SIGNAL('triggered()'), self.openDwLpsSample)
        self.project_menu.addAction(self.sampleDwLpsAction)

        self.sampleHwGpmAction = QAction(QIcon(':/python/plugins/ghydraulic/icon.xpm'), 'Sample Hazen-Williams, gallons/min', self.iface.mainWindow())
        QObject.connect(self.sampleHwGpmAction, SIGNAL('triggered()'), self.openHwGpmSample)
        self.project_menu.addAction(self.sampleHwGpmAction)

        # Back in main menu
        self.iface.addPluginToMenu("&GHydraulics", self.project_menu.menuAction())
        self.iface.addPluginToMenu("&GHydraulics", self.aboutAction)

    def unload(self):
        # remove the plugin menu item and icon
        self.iface.removePluginMenu("&GHydraulics", self.aboutAction)
        self.iface.removePluginMenu('&GHydraulics', self.runEpanetAction)
        self.iface.removePluginMenu("&GHydraulics", self.writeInpAction)
        self.iface.removePluginMenu('&GHydraulics', self.makeModelAction)
        self.iface.removePluginMenu("&GHydraulics", self.settingsAction)
        self.iface.removePluginMenu("&GHydraulics", self.action)
        self.iface.removePluginMenu("&GHydraulics", self.project_menu.menuAction())
        self.iface.removeToolBarIcon(self.settingsAction)

    # Calculate economic diameters
    def run(self):
        # Check for "LPS" flow units
        dlg = GHydraulicsSettingsDialog()
        template = dlg.getTemplate()
        inp = GHydraulicsInpReader(template)
        inpunits = inp.getValue('OPTIONS', 'Units').upper()
        if inpunits != EpanetModel.LPS:
            self.warning('"Calculate economic diameters" requires "LPS" flow units instead of "'+inpunits+'". Please change the template INP file.')
            return

        maker = GHydraulicsModelMaker(template)
        self.checkModel(maker)

        # Let user agree to the change
        selectedbutton = QMessageBox.question(self.iface.mainWindow(), "GHydraulics", "This will overwrite all DIAMETER field values. Do you want to continue?", QMessageBox.Ok|QMessageBox.Cancel, QMessageBox.Cancel)
        if QMessageBox.Cancel == selectedbutton:
            return

        # Execute the action
        ecodia = GhyEconomicDiameter(GHydraulicsModel.RESULT_FLO, EpanetModel.DIAMETER)
        maker.beginEditCommand('Calculate economic diameters')
        try:
            maker.eachLayer(ecodia.commitEconomicDiametersForLayer, [EpanetModel.PIPES])
        except GHydraulicsException as e:
            self.warning(str(e))
        maker.endEditCommand()

    # Display the About dialog
    def about(self):
        infoString = QCoreApplication.translate('GHydraulics', "GHydraulics Plugin "+self.VERSION+"<br />This plugin integrates EPANET with QGIS.<br />Copyright (c) 2007 - 2014 Steffen Macke<br /><a href=\"http://epanet.de/ghydraulics\">epanet.de/ghydraulics</a>\n")
        QMessageBox.information(self.iface.mainWindow(), "About GHydraulics", infoString)

    # Display the settings dialog
    def showSettings(self):
        dlg = GHydraulicsSettingsDialog()
        layers = QgsMapLayerRegistry.instance().mapLayers()
        proj = QgsProject.instance()
        hasVectorLayers = False
        # Restore selected layers
        for layer_id,layer in layers.iteritems():
            if layer.type() == QgsMapLayer.VectorLayer:
                item = dlg.UNUSED_ITEM
                name = layer.name()
                hasVectorLayers = True
                for i in range(0,dlg.UNUSED_ITEM):
                    pickle_list = str(proj.readEntry(GHydraulicsPlugin.SETTINGS, EpanetModel.GIS_SECTIONS[i], "")[0])
                    if '' != pickle_list:
                        # Windows QGIS injects some carriage returns here
                        pickle_list = pickle_list.replace('\r','')
                        try:
                            l = loads(pickle_list)
                            if name in l:
                                item = i
                                break
                        except(KeyError):
                            continue
                num_layers = dlg.ui.treeWidget.topLevelItem(item).childCount()
                QtGui.QTreeWidgetItem(dlg.ui.treeWidget.topLevelItem(item))
                treeItem = dlg.ui.treeWidget.topLevelItem(item).child(num_layers)
                treeItem.setText(0, name)
                treeItem.setFlags(QtCore.Qt.ItemIsSelectable|QtCore.Qt.ItemIsDragEnabled|QtCore.Qt.ItemIsEnabled)
        if hasVectorLayers:
            dlg.ui.treeWidget.topLevelItem(dlg.UNUSED_ITEM).child(0).setHidden(True)
        # Restore template inp file
        template = dlg.getTemplate()
        dlg.ui.inpFileLineEdit.setText(template)
        # Restore auto length checkbox
        dlg.ui.autoLengthCB.setChecked(dlg.getAutoLength())
        # Restore backdrop checkbox
        dlg.ui.writeBackdropCB.setChecked(dlg.getWriteBackdrop())

        # Show dialog
        dlg.show()
        for i in range(0, dlg.UNUSED_ITEM+1):
            dlg.ui.treeWidget.topLevelItem(i).setExpanded(True)
        result = dlg.exec_()

    # Display a message once
    def explainOnce(self, key, title, message):
        proj = QgsProject.instance()
        if GHydraulicsModel.STRING_TRUE == str(proj.readEntry(GHydraulicsPlugin.SETTINGS, key)[0]):
            return True
        reply = QtGui.QMessageBox.question(self.iface.mainWindow(), title,
                                            message, QtGui.QMessageBox.Yes |
                                            QtGui.QMessageBox.No, QtGui.QMessageBox.Yes)
        if QtGui.QMessageBox.Yes == reply:
            proj.writeEntry(GHydraulicsPlugin.SETTINGS, key, GHydraulicsModel.STRING_TRUE);
            return True
        return False

    # Check if all fields are in place
    def checkModel(self, maker):
        checker = maker.checker
        if 0 == checker.getLayerCount(EpanetModel.JUNCTIONS) or 0 == checker.getLayerCount(EpanetModel.PIPES):
            question = 'Your junction and/or pipe layer configuration is incomplete. Do you want configure the layers now?'
            reply = QtGui.QMessageBox.question(self.iface.mainWindow(), GHydraulicsModelChecker.TITLE, question, QtGui.QMessageBox.Yes|QtGui.QMessageBox.No,
                                               QtGui.QMessageBox.Yes)
            if reply == QtGui.QMessageBox.Yes:
                self.showSettings()
            if 0 == checker.getLayerCount(EpanetModel.JUNCTIONS) or 0 == checker.getLayerCount(EpanetModel.PIPES):
                return False
        self.checkForModifications(checker)
        missing = checker.checkFields()
        if 0 < len(missing):
            fieldlist = []
            for name in missing.keys():
                fieldlist.append('<br/>Layer "'+name+'": '+ ', '.join(missing[name]))
            message = 'Your model is missing some fields.'+''.join(fieldlist)+'<br/>Would you like to add them?'
            reply = QtGui.QMessageBox.question(self.iface.mainWindow(), GHydraulicsModelChecker.TITLE,
                                                       message, QtGui.QMessageBox.Yes |
                                                       QtGui.QMessageBox.No, QtGui.QMessageBox.Yes)
            if QtGui.QMessageBox.Yes != reply:
                return False
            if not checker.addFields(missing):
                QtGui.QMessageBox.critical(self.iface.mainWindow(), GHydraulicsModelChecker.TITLE,
                                      'Not all fields could be added.', QtGui.QMessageBox.Ok)
                return False
        crss = checker.getCrsDictionary()
        if 1 != len(crss):
            message = 'Your model uses more than one coordinate reference system. Please use only one.'
            QtGui.QMessageBox.critical(self.iface.mainWindow(), GHydraulicsModelChecker.TITLE,
                                    message, QtGui.QMessageBox.Ok, QtGui.QMessageBox.Ok)
            return False

        missing = checker.checkIds()
        if 0 < len(missing):
            question = 'There are '+str(len(missing))+' duplicate '+GHydraulicsModel.ID_FIELD+' values. Do want to fix this automatically now?'
            reply = QtGui.QMessageBox.question(self.iface.mainWindow(), GHydraulicsModelChecker.TITLE,
                                               question, QtGui.QMessageBox.Yes|QtGui.QMessageBox.No, QtGui.QMessageBox.Yes)
            if QtGui.QMessageBox.Yes != reply:
                return False
            if not maker.enforceUniqueIds():
                return False
        multis = checker.getMultipartCount()
        if 0 < multis:
            question = 'There are '+str(multis)+' pipes with multipart geometries possibly causing problems. Do you want to explode them now?'
            reply = QtGui.QMessageBox.question(self.iface.mainWindow(), GHydraulicsModelChecker.TITLE, question,
                                                QtGui.QMessageBox.Yes|QtGui.QMessageBox.No, QtGui.QMessageBox.Yes)
            if QtGui.QMessageBox.Yes == reply:
                maker.explodeMultipartPipes()

    # Fill the node1, node2 fields
    def makeModel(self):
        dlg = GHydraulicsSettingsDialog()
        template = dlg.getTemplate()
        maker = GHydraulicsModelMaker(template)
        self.iface.mainWindow().statusBar().showMessage('Checking EPANET model')
        self.checkModel(maker)
        question = 'Overwrite the fields NODE1 and NODE2 in all line tables?'
        self.iface.mainWindow().statusBar().showMessage("Making EPANET model")
        autolength = dlg.getAutoLength()
        if autolength:
            question = 'Overwrite the fields NODE1, NODE2 and LENGTH in all line tables?'
        if self.explainOnce('makeModelExplanation', 'Make EPANET Model', question):
            vcount = maker.make()
            if 0 < vcount:
                reply = QtGui.QMessageBox.question(self.iface.mainWindow(), GHydraulicsModelChecker.TITLE,
                                           'Your model is missing '+str(vcount)+' junctions. Would you like to add them now?',
                                           QtGui.QMessageBox.Yes|QtGui.QMessageBox.No, QtGui.QMessageBox.No)
                if QtGui.QMessageBox.Yes == reply:
                    self.iface.mainWindow().statusBar().showMessage('Adding missing junctions to EPANET model')
                    maker.addMissingJunctions()
            dlg = GHydraulicsSettingsDialog()
            if autolength:
                self.iface.mainWindow().statusBar().showMessage('Pipe length calculation')
                maker.calculateLength()
            maker.cleanup()
        self.iface.mainWindow().statusBar().showMessage('')

    # Prevent problems with unsaved data
    def checkForModifications(self, checker):
        modified = checker.getModifiedLayers()
        if 0 < len(modified):
            message = 'Some of your model layers have not been saved (' + ', '.join(modified) + ').<br/>Do you want to save them now?'
            reply = QtGui.QMessageBox.question(self.iface.mainWindow(), GHydraulicsInpWriter.TITLE,
                                               message, QtGui.QMessageBox.Yes|
                                               QtGui.QMessageBox.No, QtGui.QMessageBox.Yes)
            if QtGui.QMessageBox.Yes == reply:
                checker.commitChanges()

    # Write out a file in EPANET INP format
    # returns True on success, False on failure
    def writeInpFile(self):
        # Modified layers may not be exprted correctly
        checker = GHydraulicsModelChecker()
        self.checkForModifications(checker)
        # select a file
        f =  QFileDialog.getSaveFileName(self.iface.mainWindow(), GHydraulicsInpWriter.TITLE,
                                '',
                                'EPANET INP file (*.inp)');

        if 0 < len(f):
            dlg = GHydraulicsSettingsDialog()
            template = dlg.getTemplate()
            try:
                writer = GHydraulicsInpWriter(template, self.iface)
                writeBackdrop = dlg.getWriteBackdrop()
                if writeBackdrop:
                    backdropfile = writer.getBackdropFromInp(str(f))
                    question = 'Overwrite ' + os.path.basename(backdropfile) + '?'
                    if os.path.exists(backdropfile) and not self.explainOnce('overwriteBackdrop', GHydraulicsInpWriter.TITLE, question):
                        writeBackdrop = False
                writer.write(f, writeBackdrop)
            except GHydraulicsException as e:
                self.warning('Saving an INP file failed: '+str(e))
                return False
            return True
        return False

    # Open CMD sample project
    def openDwCmdSample(self):
        self.iface.addProject(os.path.dirname(__file__)+'/samples/d-w/cmd/ghydraulics.qgs')

    # Open LPS sample project
    def openDwLpsSample(self):
        self.iface.addProject(os.path.dirname(__file__)+'/samples/d-w/lps/ghydraulics.qgs')

    # Open Net1 sample project
    def openHwGpmSample(self):
        self.iface.addProject(os.path.dirname(__file__)+'/samples/h-w/gpm/Net1.qgs')

    # Display warning message
    def warning(self, message):
        self.iface.messageBar().pushMessage('GHydraulics', message, level=QgsMessageBar.WARNING)

    # Create a new project, save and configure layers
    def newProject(self):
        self.iface.newProject()
        crs = None
        project = QgsProject.instance()
        for name in EpanetModel.GIS_SECTIONS:
            lname = name.lower()
            f = QFileDialog.getSaveFileName(self.iface.mainWindow(), 'Save new ' + lname + ' layer', lname + '.shp', 'ESRI Shapefile (*.shp)')
            if 0 == len(f):
                continue
            fields = QgsFields()
            for i in range(0,len(EpanetModel.COLUMNS[name])):
                field = EpanetModel.COLUMNS[name][i]
                fields.append(QgsField(field, GHydraulicsModel.COLUMN_TYPES[field]))
            geometrytype = QGis.WKBLineString if EpanetModel.PIPES == name else QGis.WKBPoint
            writer = QgsVectorFileWriter(f, 'System', fields, geometrytype, crs, 'ESRI Shapefile')
            if writer.hasError() != QgsVectorFileWriter.NoError:
                self.warning('Error creating shapefile: ' + str(writer.hasError()))
                continue
            del writer
            layer = self.iface.addVectorLayer(f, lname, 'ogr')
            if not layer.isValid():
                self.warning('Failed to load layer!')
                continue
            if not crs:
                crs = layer.crs()
            layers = [lname]
            project.writeEntry("ghydraulics", name, dumps(layers))
        self.showSettings()

    def runEpanet(self):
        # Get a temporary file
        t = tempfile.mkstemp(suffix='.inp')
        os.close(t[0])
        dlg = GHydraulicsSettingsDialog()
        template = dlg.getTemplate()
        try:
            writer = GHydraulicsInpWriter(template, self.iface)
            writer.write(t[1], False)
        except GHydraulicsException as e:
            self.warning('Saving an INP fille failed :' + str(e))
            return
        try:
            runner = GHydraulicsModelRunner()
            output, report, steps = runner.run(t[1])
            dlg = GHydraulicsResultDialog(runner.setStep)
            dlg.ui.textOutput.setText(output)
            dlg.ui.textReport.setText(report)
            dlg.ui.comboStep.clear()
            dlg.ui.comboStep.addItems([str(x) for x in range(1, steps+1)])
            dlg.show()
            result = dlg.exec_()
        except GHydraulicsException as e:
            self.warning('Running a simulation failed :' + str(e))
        os.unlink(t[1])
