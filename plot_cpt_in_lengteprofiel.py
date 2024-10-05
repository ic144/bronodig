import os
import geopandas as gpd

from .geotechnisch_lengteprofiel import Cptverzameling, Boreverzameling, GeotechnischLengteProfiel
from .gefxml_reader import Cpt, Bore, Test

def readCptBores(path):

    files = os.listdir(path)
    files = [path + f for f in files]
    cptList = []
    boreList = []

    for f in files:
        if f.lower().endswith('gef'):
            testType = Test().type_from_gef(f)
            if testType == 'cpt':
                cptList.append(f)
            elif testType == 'bore':
                boreList.append(f)
        elif f.lower().endswith('xml'):
            testType = Test().type_from_xml(f)
            if testType == 'cpt':
                cptList.append(f)
            elif testType == 'bore':
                boreList.append(f)

    return boreList, cptList

def read_sikb_files(path):

    sikbFileList = [f'{path}{f}' for f in os.listdir(path) if f.lower().endswith('csv')]
    return sikbFileList


def make_multibore_multicpt(boreList, cptList):
    multicpt = Cptverzameling()
    multicpt.load_multi_cpt(cptList)
    multibore = Boreverzameling()
    multibore.load_multi_bore(boreList)
    return multicpt, multibore

def plotBoreCptInProfile(multicpt, multibore, line, profileName):
    gtl = GeotechnischLengteProfiel()
    gtl.set_line(line)
    gtl.set_cpts(multicpt)
    gtl.set_bores(multibore)
    gtl.project_on_line()
    gtl.set_groundlevel()
    gtl.plot(boundaries={}, profilename=profileName)

def plotBoreCptInProfileWithBoundaries(multicpt, multibore, line, profileName, boundaries, moten, plotTop, scaleXAxis=20, scaleData=2):
    gtl = GeotechnischLengteProfiel()
    gtl.set_line(line)
    gtl.set_cpts(multicpt)
    gtl.set_bores(multibore)
    gtl.project_on_line()
    gtl.set_groundlevel() # er zijn sonderingen die op diepte beginnen, die geven storende lijnen
    gtl.set_layers('./input/gaasper.xlsx')
    gtl.plot(boundaries=boundaries, profilename=profileName, moten=moten, plotTop=plotTop, scaleXAxis=scaleXAxis, scaleData=scaleData)


if __name__ == "__main__":
    objectGDF = gpd.read_file(f"./input/profiel.geojson")
    line = objectGDF['geometry'].iloc[0]

    boreList, cptList = readCptBores(f'./input/')
    multicpt, multibore = make_multibore_multicpt(boreList, cptList)
    plotBoreCptInProfile(multicpt, multibore, line, profileName="")