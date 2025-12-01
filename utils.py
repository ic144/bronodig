from datetime import datetime
import json
import re
import xml.etree.ElementTree as ET
from shapely.geometry import Point, Polygon

from qgis.PyQt.QtCore import pyqtSignal, QSettings, QTranslator, QCoreApplication, Qt, QUrl, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QVBoxLayout, QWidget
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsPointXY, QgsGeometry, QgsVectorLayer, QgsProject, QgsFeature, QgsNetworkAccessManager, QgsFields, QgsField

from .gefxml_reader import Cpt, Bore
from .geotechnisch_lengteprofiel import Cptverzameling, Boreverzameling, GeotechnischLengteProfiel

def haal_bro_overzicht(test_type: str, minx: float, miny: float, maxx: float, maxy: float) -> str:
    """Functie om ids uit BRO op te halen voor een bounding box.

    Args:
        test_type (str): type test, sondering of boring
        minx (float): links
        miny (float): onder
        maxx (float): rechts
        maxy (float): boven

    Returns:
        str: xml uit de BRO
    """
    if test_type == 'cpt':
        url = "https://publiek.broservices.nl/sr/cpt/v1/characteristics/searches"

    elif test_type == 'bhrgt':
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
    
    return broResp_dec


def haal_cpt_bro(broId: str) -> Cpt:
    """Functie om een sondering uit BRO in te lezen.

    Args:
        broId (str): id zoals BRO die gebruikt CPT000xxxxx

    Returns:
        Cpt: een sondering volgens het format van gefxml_reader
    """
    test = Cpt()
    url = f"https://publiek.broservices.nl/sr/cpt/v1/objects/{broId}"
    request = QNetworkRequest()
    request.setUrl(QUrl(url))
    resp = QgsNetworkAccessManager.blockingGet(request).content()
    test.load_xml(resp, checkAddFrictionRatio=True, checkAddDepth=True, fromFile=False)

    return test


def haal_bore_bro(broId: str) -> Bore:
    """Functie om een boring uit BRO in te lezen.

    Args:
        broId (str): id zoals BRO die gebruikt BHR000xxxxx

    Returns:
        Bore: een boring volgens het format van gefxml_reader
    """
    test = Bore()
    url = f"https://publiek.broservices.nl/sr/bhrgt/v2/objects/{broId}"
    request = QNetworkRequest()
    request.setUrl(QUrl(url))
    resp = QgsNetworkAccessManager.blockingGet(request).content()
    test.load_xml(resp, fromFile=False)

    return test

def process_bro_overzicht(root: str, geometry: Polygon):
    """Functie om ids en locaties uit een BRO overzicht XML te halen.

    Args:
        root (str): de XML
        geometry (Polygon): een polygoon waarbinnen de onderzoekslocaties moeten liggen

    Returns:
        _type_: lijsten met ids en locaties
    """
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
    return broIds, broGeoms
