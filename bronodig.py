# -*- coding: utf-8 -*-
"""
/***************************************************************************
 BROnodig
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
 *   it under the terms of the EUPL v1.2                                   *
 *                                                                         *
 ***************************************************************************/
"""
from qgis.PyQt.QtCore import pyqtSignal, QSettings, QTranslator, QCoreApplication, Qt, QUrl
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QVBoxLayout, QWidget
from qgis.PyQt.QtNetwork import QNetworkRequest

# Initialize Qt resources from file resources.py
from .resources import *
# Import the code for the dialog
from .bronodig_dockwidget import BroDownloadPlotDockWidget
import os.path

from .coordinate_capture_map_tool import CoordinateCaptureMapTool

from qgis.core import QgsPointXY, QgsGeometry, QgsVectorLayer, QgsProject, QgsFeature, QgsNetworkAccessManager

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

import xml.etree.ElementTree as ET

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

            self.dockwidget.pushButtonVerkennen.clicked.connect(self.verkennen_tab)
            self.dockwidget.pushButtonBulk.clicked.connect(self.bulk_tab)
            self.dockwidget.pushButtonProfiel.clicked.connect(self.profiel_tab)
    
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


    def verkennen_tab(self):

        self.do_cpt = self.dockwidget.radioButtonCpt.isChecked()
        self.do_boring = self.dockwidget.radioButtonBoring.isChecked()

        self.show_plot = True

        # dit was startCapturing
        self.iface.mapCanvas().setMapTool(self.mapTool)

    def bulk_tab(self):

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

        maak_laag = self.dockwidget.checkBox_laag_bulk.isChecked()

        selected_layer = self.dockwidget.mMapLayerComboBox.currentLayer()

        self.plotDataBro_bulk(do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder, maak_laag, selected_layer)

    def profiel_tab(self):
        do_cpt = self.dockwidget.checkBoxCpt_profiel.isChecked()
        do_boring = self.dockwidget.checkBoxBoring_profiel.isChecked()

        save_svg = self.dockwidget.checkBoxSvg_profiel.isChecked()
        save_png = self.dockwidget.checkBoxPng_profiel.isChecked()
        save_pdf = self.dockwidget.checkBoxPdf_profiel.isChecked()
        if any([save_pdf, save_png, save_svg]):
            folder = self.dockwidget.mQgsFileWidget_profiel.filePath()
        else:
            folder = ""

        buffer = float(self.dockwidget.spinBox_buffer.value())

        show_plot = self.dockwidget.checkBoxShow_profiel.isChecked()

        maak_laag = self.dockwidget.checkBox_laag_profiel.isChecked()

        selected_layer = self.dockwidget.mMapLayerComboBox_profiel.currentLayer()

        self.plotDataBro_profiel(do_cpt, do_boring, save_svg, save_png, save_pdf, show_plot, folder, maak_laag, selected_layer, buffer)


    def plotDataBro_verkennen(self, point, do_cpt, do_boring, show_plot):
        # maak een bounding box in lat, lon -> gebruiken we niet
        # maak een center met radius in lat, lon -> gebruiken we wel
        latlon = CRS.from_epsg(4326)  # TODO: volgens BRO API 4258
        rd = CRS.from_epsg(28992)
        transformer = Transformer.from_crs(rd, latlon)

        save_xml, save_png, save_pdf = False, False, False
        folder = ''
        
        geometry = QgsGeometry.fromPointXY(point).buffer(1, 5)

        bbox = geometry.boundingBox()
        miny, minx = transformer.transform(bbox.xMinimum(), bbox.yMinimum())
        maxy, maxx = transformer.transform(bbox.xMaximum(), bbox.yMaximum())
        self.haal_en_plot(geometry, minx, maxx, miny, maxy, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder, maak_laag=False)

    def maak_laag(self):
        uri = "point?crs=epsg:28992&field=id:integer"
        scratchLayer = QgsVectorLayer(uri, "Scratch point layer",  "memory")
        vpr = scratchLayer.dataProvider()
        QgsProject.instance().addMapLayer(scratchLayer)
        return vpr
                
    def voeg_toe_aan_laag(self, dataprovider, punt):
        pnt = QgsGeometry.fromWkt(str(punt)) 
        f = QgsFeature()
        f.setGeometry(pnt)
        f.setAttributes([1]) #added line
        dataprovider.addFeatures([f])

        return

    def plotDataBro_bulk(self, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder, maak_laag, selected_layer):
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
                miny, minx = transformer.transform(bbox.xMinimum(), bbox.yMinimum())
                maxy, maxx = transformer.transform(bbox.xMaximum(), bbox.yMaximum())
                self.haal_en_plot(geometry, minx, maxx, miny, maxy, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder, maak_laag)

    def plotDataBro_profiel(self, do_cpt, do_boring, save_svg, save_png, save_pdf, show_plot, folder, maak_laag, selected_layer, buffer):
        # maak een bounding box in lat, lon
        latlon = CRS.from_epsg(4326)  # TODO: volgens BRO API 4258
        rd = CRS.from_epsg(28992)
        transformer = Transformer.from_crs(rd, latlon)

        # maak een profiel als er een lijn is opgegeven
        for feature in selected_layer.getFeatures():
            geometry = feature.geometry()        
            if geometry.asWkt().lower().startswith('linestring'):
                # maak een bounding box voor het ophalen van data
                bbox = geometry.buffer(buffer, segments=5).boundingBox()
                miny, minx = transformer.transform(bbox.xMinimum(), bbox.yMinimum())
                maxy, maxx = transformer.transform(bbox.xMaximum(), bbox.yMaximum())
                geometry = geometry.asWkt()
                geometry = loads(geometry)
                
                self.maak_profiel(geometry, buffer, minx, miny, maxx, maxy, do_cpt, do_boring, save_svg, save_png, save_pdf, show_plot, folder, maak_laag)
        
    def maak_profiel(self, geometry, buffer, minx, miny, maxx, maxy, do_cpt, do_boring, save_svg, save_png, save_pdf, show_plot, folder, maak_laag):
        test_types = ['cpt', 'bhrgt']
        
        if maak_laag:
            dataprovider = self.maak_laag()
        
        for test_type in test_types:
            if test_type == 'cpt':
                url = "https://publiek.broservices.nl/sr/cpt/v1/characteristics/searches"
                multicpt = Cptverzameling()

            elif test_type == 'bhrgt':
                url = "https://publiek.broservices.nl/sr/bhrgt/v2/characteristics/searches"
                multibore = Boreverzameling()

            # maak een request om mee te geven aan de url
            today = datetime.today().strftime('%Y-%m-%d')

            # beginDate mag niet te vroeg zijn 2017-01-01 werkt, 2008 niet
            dataBBdict = {"registrationPeriod": {"beginDate": "2017-01-01", "endDate": today}, "area": {"boundingBox": {"lowerCorner": {"lat": miny, "lon": minx}, "upperCorner": {"lat": maxy, "lon": maxx}}}}
            dataBB = json.dumps(dataBBdict)

            # doe de request
            request = QNetworkRequest()
            request.setUrl(QUrl(url))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            broResp = QgsNetworkAccessManager.blockingPost(request, data=str.encode(dataBB))
            broResp_dec = broResp.content()
           
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

                    if type(broId) == str and type(broGeom) == Point and QgsGeometry.fromWkt(str(geometry.buffer(buffer, 5))).contains(QgsGeometry.fromWkt(str(broGeom))):
                            broIds.append(broId)
                            broGeoms.append(broGeom)
                            if maak_laag:
                                self.voeg_toe_aan_laag(dataprovider, broGeom)

            for broId in broIds:  # TODO: check ook of locatie binnen polygoon valt
                if test_type == 'cpt' and do_cpt:
                    test = Cpt()
                    url = f"https://publiek.broservices.nl/sr/cpt/v1/objects/{broId}"
                    request = QNetworkRequest()
                    request.setUrl(QUrl(url))
                    resp = QgsNetworkAccessManager.blockingGet(request).content()
                    test.load_xml(resp, checkAddFrictionRatio=True, checkAddDepth=True, fromFile=False)
                    multicpt.cpts.append(test)
                elif test_type == 'bhrgt' and do_boring:
                    test = Bore()
                    url = f"https://publiek.broservices.nl/sr/bhrgt/v2/objects/{broId}"
                    request = QNetworkRequest()
                    request.setUrl(QUrl(url))
                    resp = QgsNetworkAccessManager.blockingGet(request).content()
                    test.load_xml(resp, fromFile=False)
                    multibore.bores.append(test)
        
        # QMessageBox.information(self.dockwidget, "aantal", f"boringen {multibore.bores} \n cpt {multicpt.cpts}")
        gtl = GeotechnischLengteProfiel()
        gtl.set_line(geometry)
        gtl.set_cpts(multicpt)
        gtl.set_bores(multibore)
        gtl.project_on_line()
        gtl.set_groundlevel()
        fig = gtl.plot(boundaries={}, profilename="", saveFig=False)
        if show_plot:
            fig.show()
        if save_svg:
            fig.savefig(f'{folder}/lengteprofiel.svg')  # TODO: naam moet overgenomen uit laag in QGis
        if save_png:
            fig.savefig(f'{folder}/lengteprofiel.png')
        if save_pdf:
            fig.savefig(f'{folder}/lengteprofiel.pdf')

    def haal_en_plot(self, geometry, minx, maxx, miny, maxy, do_cpt, do_boring, save_xml, save_png, save_pdf, show_plot, folder, maak_laag):
        
        if maak_laag:
            dataprovider = self.maak_laag()
        
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

            # maak een request om mee te geven aan de url
            today = datetime.today().strftime('%Y-%m-%d')

            # beginDate mag niet te vroeg zijn 2017-01-01 werkt, 2008 niet
            dataBBdict = {"registrationPeriod": {"beginDate": "2017-01-01", "endDate": today}, "area": {"boundingBox": {"lowerCorner": {"lat": miny, "lon": minx}, "upperCorner": {"lat": maxy, "lon": maxx}}}}
            dataBB = json.dumps(dataBBdict)

            # doe de request
            request = QNetworkRequest()
            request.setUrl(QUrl(url))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            broResp = QgsNetworkAccessManager.blockingPost(request, data=str.encode(dataBB))
            broResp_dec = broResp.content()
            
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

                    if type(broId) == str and type(broGeom) == Point and geometry.contains(QgsGeometry.fromWkt(str(broGeom))):
                        broIds.append(broId)
                        broGeoms.append(broGeom)
                        if maak_laag:
                            self.voeg_toe_aan_laag(dataprovider, broGeom)


            for broId in broIds:
                if test_type == 'cpt':
                    url = f"https://publiek.broservices.nl/sr/cpt/v1/objects/{broId}"
                    request = QNetworkRequest()
                    request.setUrl(QUrl(url))
                    resp = QgsNetworkAccessManager.blockingGet(request).content()
                    test.load_xml(resp, checkAddFrictionRatio=True, checkAddDepth=True, fromFile=False)
                elif test_type == 'bhrgt':
                    url = f"https://publiek.broservices.nl/sr/bhrgt/v2/objects/{broId}"
                    request = QNetworkRequest()
                    request.setUrl(QUrl(url))
                    resp = QgsNetworkAccessManager.blockingGet(request).content()
                    test.load_xml(resp, fromFile=False)

                # QMessageBox.information(self.dockwidget, "aantal", f"{resp} {test_type}")
                
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
                        f.write(str(resp.data(), encoding='utf-8'))

    def mouseClicked(self, point: QgsPointXY):
        self.update(point)
        
    def update(self, point: QgsPointXY):   
        self.plotDataBro_verkennen(point, self.do_cpt, self.do_boring, self.show_plot)
