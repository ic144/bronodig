# -*- coding: utf-8 -*-
"""
/***************************************************************************
 BroDownloadPlot
                                 A QGIS plugin
 Plugin om BRO data te downloaden en plotten
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2024-08-19
        git sha              : $Format:%H$
        copyright            : (C) 2024 by Thomas van der Linden
        email                : t.van.der.linden@amsterdam.nl
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from qgis.PyQt.QtCore import pyqtSignal, QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QVBoxLayout, QWidget

# Initialize Qt resources from file resources.py
from .resources import *
# Import the code for the dialog
from .bro_download_plot_dockwidget import BroDownloadPlotDockWidget
import os.path

from .coordinate_capture_map_tool import CoordinateCaptureMapTool

from qgis.core import QgsPointXY
from qgis.gui import QgsMapTool, QgsMapToolEmitPoint
from qgis.utils import iface

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

import xml.etree.ElementTree as ET
import requests
from requests.structures import CaseInsensitiveDict

from shapely.geometry import Point
from pyproj import CRS, Transformer
import json
import re
from datetime import datetime
from shapely.wkt import loads

from .gefxml_reader import Cpt, Bore
from .geotechnisch_lengteprofiel import Cptverzameling, Boreverzameling, GeotechnischLengteProfiel


class MatplotlibWidget(QWidget):
    def __init__(self, parent=None):
       super(MatplotlibWidget, self).__init__(parent)

       # Create a Matplotlib figure and canvas
       self.figure, self.ax = plt.subplots()
       self.canvas = FigureCanvas(self.figure)

       # Create a QVBoxLayout and add the Matplotlib canvas and QPushButton to it
       layout = QVBoxLayout()
       layout.addWidget(self.canvas)
       self.setLayout(layout)


class BroDownloadPlot:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'BroDownloadPlot_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&BRO Downloaden Plotten')

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.first_start = None
        self.mapTool = CoordinateCaptureMapTool(self.iface.mapCanvas())
        self.mapTool.mouseClicked.connect(self.mouseClicked)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('BroDownloadPlot', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/bro_download_plot/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'BRO Download & Plot'),
            callback=self.run,
            parent=self.iface.mainWindow())

        # will be set False in run()
        self.first_start = True


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&BRO Downloaden Plotten'),
                action)
            self.iface.removeToolBarIcon(action)


    def run(self):
        """Run method that performs all the real work"""

        # Create the dialog with elements (after translation) and keep reference
        # Only create GUI ONCE in callback, so that it will only load when the plugin is started
        if self.first_start == True:
            self.first_start = False
            self.dockwidget = BroDownloadPlotDockWidget()

            self.dockwidget.pushButton.clicked.connect(self.startCapturing) # TODO: dit moet een andere knop worden
            self.dockwidget.pushButtonEenvoudig.clicked.connect(self.eenvoudig_tab)
            self.dockwidget.pushButtonComplex.clicked.connect(self.complex_tab)
    
        self.mc = self.iface.mapCanvas()
        # self.dlg.doubleSpinBoxX.setValue(self.mc.center().x())
        # self.dlg.doubleSpinBoxY.setValue(self.mc.center().y())
        
        matplotlib_widget = MatplotlibWidget()

        # show the dialog
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.show()
        # Run the dialog event loop
        # result = self.dlg.exec_()
        # See if OK was pressed
        # if result:
            # Do something useful here - delete the line containing pass and
            # substitute with your code.
            # pass


    def eenvoudig_tab(self):

        do_cpt = self.dockwidget.radioButtonCpt.isChecked()
        do_boring = self.dockwidget.radioButtonBoring.isChecked()

        show_plot = True

        x = self.mc.center().x()
        y = self.mc.center().y()

        self.plotDataBro_eenvoudig([x, y], do_cpt, do_boring, show_plot)

    def complex_tab(self):

        do_cpt = self.dockwidget.checkBoxCpt.isChecked()
        do_boring = self.dockwidget.checkBoxBoring.isChecked()

        save_xml = self.dockwidget.checkBoxXml.isChecked()
        save_png = self.dockwidget.checkBoxPng.isChecked()
        save_pdf = self.dockwidget.checkBoxPdf.isChecked()
        if any([save_pdf, save_png, save_xml]):
            folder = self.dockwidget.mQgsFileWidget.filePath()
        else:
            folder = ""

        show_plot = self.dockwidget.checkBoxShow.isChecked()

        selected_layer = self.dockwidget.mMapLayerComboBox.currentLayer()

        self.plotDataBro_complex(do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder, selected_layer)

    def plotDataBro_eenvoudig(self, point, do_cpt, do_boring, show_plot):
        # maak een bounding box in lat, lon -> gebruiken we niet
        # maak een center met radius in lat, lon -> gebruiken we wel
        latlon = CRS.from_epsg(4326)  # TODO: volgens BRO API 4258
        rd = CRS.from_epsg(28992)
        transformer = Transformer.from_crs(rd, latlon)

        save_xml, save_png, save_pdf = False, False, False
        folder = ''

        marge = 1
        bbox = (int(point[0])-marge,int(point[1])-marge, int(point[0]+marge),int(point[1]+marge))          
        miny, minx = transformer.transform(bbox[0], bbox[1])
        maxy, maxx = transformer.transform(bbox[2], bbox[3])
        self.haal_en_plot(minx, maxx, miny, maxy, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder)

    def plotDataBro_complex(self, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder, selected_layer):
        # maak een bounding box in lat, lon -> gebruiken we niet
        # maak een center met radius in lat, lon -> gebruiken we wel
        latlon = CRS.from_epsg(4326)  # TODO: volgens BRO API 4258
        rd = CRS.from_epsg(28992)
        transformer = Transformer.from_crs(rd, latlon)

        for feature in selected_layer.getFeatures():
            geometry = feature.geometry()
            if geometry.asWkt().lower().startswith('polygon'):
                # maak een bounding box voor het ophalen van data
                bbox = geometry.boundingBox()
                minx, maxx, miny, maxy = bbox.xMinimum(), bbox.xMaximum(), bbox.yMinimum(), bbox.yMaximum()
                miny, minx = transformer.transform(minx, miny)
                maxy, maxx = transformer.transform(maxx, maxy)
                self.haal_en_plot(minx, maxx, miny, maxy, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder)

        # maak een profiel als er een lijn is opgegeven        
            elif geometry.asWkt().lower().startswith('linestring'):
                # maak een bounding box voor het ophalen van data
                bbox = geometry.boundingBox()
                minx, maxx, miny, maxy = bbox.xMinimum(), bbox.xMaximum(), bbox.yMinimum(), bbox.yMaximum()
                miny, minx = transformer.transform(minx, miny)
                maxy, maxx = transformer.transform(maxx, maxy)
                geometry = geometry.asWkt()
                geometry = loads(geometry)
                
                self.maak_profiel(geometry, minx, miny, maxx, maxy)
        
    def maak_profiel(self, geometry, minx, miny, maxx, maxy):
        test_types = ['cpt', 'bhrgt']
        
        for test_type in test_types:
            if test_type == 'cpt':
                url = "https://publiek.broservices.nl/sr/cpt/v1/characteristics/searches"
                multicpt = Cptverzameling()

            elif test_type == 'bhrgt':
                url = "https://publiek.broservices.nl/sr/bhrgt/v2/characteristics/searches"
                multibore = Boreverzameling()
                
            headers = CaseInsensitiveDict()
            headers["Accept"] = "application/json"
            headers["Content-Type"] = "application/json"

            # maak een request om mee te geven aan de url
            today = datetime.today().strftime('%Y-%m-%d')

            # beginDate mag niet te vroeg zijn 2017-01-01 werkt, 2008 niet
            dataBBdict = {"registrationPeriod": {"beginDate": "2017-01-01", "endDate": today}, "area": {"boundingBox": {"lowerCorner": {"lat": miny, "lon": minx}, "upperCorner": {"lat": maxy, "lon": maxx}}}}
            dataBB = json.dumps(dataBBdict)

            # doe de request
            broResp = requests.post(url, headers=headers, data=dataBB)
            broResp_dec = broResp.content.decode("utf-8")
           
            root = ET.fromstring(broResp_dec)

            # lees xy en id in uit de xml
            broIds = []
            broGeoms = []

            for element in root.iter():
                if 'dispatchDocument' in element.tag:
                    broId = False
                    broGeom = False

                    metadata = ({re.sub(r'{.*}', '', p.tag) : re.sub(r'\s*', '', p.text) for p in element.iter() if p.text is not None})

                    broId = metadata['broId']
                    
                    for child in element.iter():
                        if 'standardizedLocation' in child.tag:
                            locationData = ({re.sub(r'{.*}', '', p.tag) : re.sub(r'\s*', '', p.text) for p in element.iter() if p.text is not None})
                            coords = locationData['pos']
                            
                            broGeom = Point(float(coords[:int(len(coords)/2)]), float(coords[int(len(coords)/2):]))

                    if type(broId) == str and type(broGeom) == Point:
                        broIds.append(broId)
                        broGeoms.append(broGeom)

            for broId in broIds:
                if test_type == 'cpt':
                    test = Cpt()
                    url = f"https://publiek.broservices.nl/sr/cpt/v1/objects/{broId}"
                    resp = requests.get(url).content.decode("utf-8")
                    test.load_xml(resp, checkAddFrictionRatio=True, checkAddDepth=True, fromFile=False)
                    multicpt.cpts.append(test)
                elif test_type == 'bhrgt':
                    test = Bore()
                    url = f"https://publiek.broservices.nl/sr/bhrgt/v2/objects/{broId}"
                    resp = requests.get(url).content.decode("utf-8")
                    test.load_xml(resp, fromFile=False)
                    multibore.bores.append(test)
        
        QMessageBox.information(self.dockwidget, "aantal", f"boringen {multibore.bores} \n cpt {multicpt.cpts}")
        gtl = GeotechnischLengteProfiel()
        gtl.set_line(geometry)
        gtl.set_cpts(multicpt)
        gtl.set_bores(multibore)
        gtl.project_on_line()
        gtl.set_groundlevel()
        fig = gtl.plot(boundaries={}, profilename="", saveFig=False)
        fig.show()

    def haal_en_plot(self, minx, maxx, miny, maxy, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder):
        test_types = []
        if do_cpt:
            test_types.append('cpt')
        if do_boring:
            test_types.append('bhrgt')
            
        for test_type in test_types:
            if test_type == 'cpt':
                test = Cpt()
                url = "https://publiek.broservices.nl/sr/cpt/v1/characteristics/searches"

            elif test_type == 'bhrgt':
                test = Bore()
                url = "https://publiek.broservices.nl/sr/bhrgt/v2/characteristics/searches"
                 
            headers = CaseInsensitiveDict()
            headers["Accept"] = "application/json"
            headers["Content-Type"] = "application/json"

            # maak een request om mee te geven aan de url
            today = datetime.today().strftime('%Y-%m-%d')

            # beginDate mag niet te vroeg zijn 2017-01-01 werkt, 2008 niet
            dataBBdict = {"registrationPeriod": {"beginDate": "2017-01-01", "endDate": today}, "area": {"boundingBox": {"lowerCorner": {"lat": miny, "lon": minx}, "upperCorner": {"lat": maxy, "lon": maxx}}}}
            dataBB = json.dumps(dataBBdict)

            # doe de request
            broResp = requests.post(url, headers=headers, data=dataBB)
            broResp_dec = broResp.content.decode("utf-8")
            
            root = ET.fromstring(broResp_dec)

            # lees xy en id in uit de xml
            broIds = []
            broGeoms = []

            for element in root.iter():
                if 'dispatchDocument' in element.tag:
                    broId = False
                    broGeom = False

                    metadata = ({re.sub(r'{.*}', '', p.tag) : re.sub(r'\s*', '', p.text) for p in element.iter() if p.text is not None})
                    broId = metadata['broId']

                    for child in element.iter():
                        if 'standardizedLocation' in child.tag:
                            locationData = ({re.sub(r'{.*}', '', p.tag) : re.sub(r'\s*', '', p.text) for p in element.iter() if p.text is not None})
                            coords = locationData['pos']

                            broGeom = Point(float(coords[:int(len(coords)/2)]), float(coords[int(len(coords)/2):]))

                    if type(broId) == str and type(broGeom) == Point:
                        broIds.append(broId)
                        broGeoms.append(broGeom)

            # QMessageBox.information(self.dlg, "aantal", f"aantal {len(broIds)}")

            for broId in broIds:
                if test_type == 'cpt':
                    url = f"https://publiek.broservices.nl/sr/cpt/v1/objects/{broId}"
                    resp = requests.get(url).content.decode("utf-8")
                    test.load_xml(resp, checkAddFrictionRatio=True, checkAddDepth=True, fromFile=False)
                elif test_type == 'bhrgt':
                    url = f"https://publiek.broservices.nl/sr/bhrgt/v2/objects/{broId}"
                    resp = requests.get(url).content.decode("utf-8")
                    test.load_xml(resp, fromFile=False)


                # plot met de method uit de gefxml_reader
                figure = test.plot(saveFig=False)
                if save_png:
                    figure.savefig(f'{folder}/{broId}.png')
                if save_pdf:
                    figure.savefig(f'{folder}/{broId}.pdf')
                if show_plot:
                    figure.show()
                if save_xml:
                    with open(f'{folder}/{broId}.xml', 'a') as f:
                        f.write(resp)

    def mouseClicked(self, point: QgsPointXY):
        self.update(point)
        
    def update(self, point: QgsPointXY):
        QMessageBox.information(self.dockwidget, "aantal", f"boringen {point}")        
        # TODO: dit omschrijven, zodat het runt dat er BRO data wordt gehaald, maar dat is helemaal anders geworden

    def startCapturing(self):
        self.iface.mapCanvas().setMapTool(self.mapTool)
