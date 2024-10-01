"""
Script om geotechnische lengteprofielen te tekenen
Geschreven door Thomas van der Linden, Ingenieursbureau Amsterdam

Input:
- sonderingen, als XML of GEF in een map met de naam cpts in dezelfde directory als de code
- profiellijn, als geojson bestand
- lagen, als excel tabel met de naam layers.xlsx in dezelfde directory als de code
    de tabel heeft kolommen laag (nummer in dezelfde volgorde als je getekend hebt), materiaal, kleur (kleurnamen in het Engels)

Output:
- output.geo dat ingelezen kan worden in de D-Serie # TODO: materialen toevoegen
- gtl.png en gtl.svg figuren met het geotechnisch lengteprofiel

Het programma opent een venster waarin geklikt kan worden om lijnen op te geven
Een klik met de linker muisknop voegt een punt toe aan de lijn (grens)
Een klik met de rechter muisknop creëert een nieuwe lijn (grens)
Sluit het venster af met de knop Quit, anders blijft het programma lopen en wordt er geen output gemaakt

Afhankelijkheden
- cpt_reader geschreven door Thomas van der Linden 
- standaard Python packages
"""

__author__ = "Thomas van der Linden"
__credits__ = ""
__license__ = "EUPL-2.0"
__version__ = ""
__maintainer__ = "Thomas van der Linden"
__email__ = "t.van.der.linden@amsterdam.nl"
__status__ = "Dev"

import numpy as np
import pandas as pd
import sys
from datetime import datetime
import matplotlib.pyplot as plt
from shapely.geometry import Point, box
import shapely.affinity as sa
import geopandas as gpd

# TODO: gefxml_reader importeren uit geotexxx
sys.path.insert(0, '../gefxml_viewer')
from gefxml_reader import Cpt, Bore

class Cptverzameling():
    def __init__(self):
        self.cpts = []

    def load_multi_cpt(self, fileList):
        for f in fileList:
            print(f)
            cpt = Cpt()
            if f.lower().endswith("xml"):
                cpt.load_xml(f, checkAddFrictionRatio=True, checkAddDepth=True)
                self.cpts.append(cpt)
            elif f.lower().endswith("gef"):
                cpt.load_gef(f, checkAddFrictionRatio=True, checkAddDepth=True)
                self.cpts.append(cpt)    

class Boreverzameling():
    def __init__(self):
        self.bores = []
    
    def load_multi_bore(self, fileList):
        for f in fileList:
            print(f)
            bore = Bore()
            if f.lower().endswith("xml"):
                bore.load_xml(f)
                self.bores.append(bore)
            elif f.lower().endswith("gef"):
                bore.load_gef(f)
                self.bores.append(bore)

    def load_sikb(self, locationFiles, line, buffer):
        # sikb bestanden zijn zelf al verzamelingen
        # het zijn oorspronkelijk xml, die met de gefxml_viewer omgezet worden in
        # een csv met locaties en een bijbehorende map met boringen in csv
        for locationFile in locationFiles:
            locations = pd.read_csv(locationFile, sep=';')

            if len(locations) > 1:
                # filter alleen de locaties met een boorbeschrijving
                locations = locations[locations['boorbeschrijving']]

                # zet de boringid om in een string om te voorkomen dat 0 aan het begin wordt afgeknipt
                locations['boring'] = locations['boring'].astype(str)

                # doe een geografische filtering
                objectBuffer = line.buffer(buffer)

                # elke regel in het bestand met locaties is een boring
                for row in locations.itertuples():
                    geometry = Point(getattr(row, 'x'), getattr(row, 'y'))
                    if geometry.within(objectBuffer):
                        try:
                            bore = Bore()
                            testid = getattr(row, 'boring')
                            # de boring staat in een mapje met dezelfde naam als het bestand met de locaties
                            boreFile = f'{locationFile.replace(".csv", "")}/{testid}.csv'
                            # lees de boring in
                            bore.from_sikb_csv(testid, boreFile, locationFile)
                            self.bores.append(bore)
                        except Exception as e:
                            print(locationFile, row, e)

class GeotechnischLengteProfiel():
    def __init__(self):
        self.line = None
        self.cpts = None
        self.materials = None
        self.boundaries = {}
        self.groundlevelRel = []
        self.groundlevelAbs = []
        self.profilename = ''

    def set_line(self, line):
        self.line = line

    def set_cpts(self, cptVerzameling):
        self.cpts = cptVerzameling.cpts

    def set_bores(self, boreVerzameling):
        self.bores = boreVerzameling.bores

    def set_profilename(self, profilename):
        self.profilename = profilename

    def set_layers(self, materialsTable):
        materials = pd.read_excel(materialsTable, index_col="laag")
        self.materials = materials
     
    def project_on_line(self):
        for cpt in self.cpts:
            cptLocation = Point(cpt.easting, cpt.northing)
            cpt.projectedLocation = self.line.project(cptLocation, normalized=True)
        for bore in self.bores:
            boreLocation = Point(bore.easting, bore.northing)
            bore.projectedLocation = self.line.project(boreLocation, normalized=True)

    def set_groundlevel(self):
        # TODO: dit is niet zo mooi, twee keer hetzelfde
        for bore in self.bores:
            self.groundlevelRel.append([bore.projectedLocation, bore.groundlevel])
            self.groundlevelAbs.append([bore.projectedLocation * self.line.length, bore.groundlevel])
        for cpt in self.cpts:
            self.groundlevelRel.append([cpt.projectedLocation, cpt.groundlevel])
            self.groundlevelAbs.append([cpt.projectedLocation * self.line.length, cpt.groundlevel])

        self.groundlevelAbs.sort()
        self.groundlevelAbs.insert(0, [0, self.groundlevelAbs[0][1]])
        self.groundlevelAbs.append([self.line.length, self.groundlevelAbs[-1][1]])
        self.groundlevelAbs = np.asarray(self.groundlevelAbs)

        self.groundlevelRel.sort()
        self.groundlevelRel.insert(0, [0, self.groundlevelRel[0][1]])
        self.groundlevelRel.append([self.line.length, self.groundlevelRel[-1][1]])
        self.groundlevelRel = np.asarray(self.groundlevelRel)



    def plot(self, boundaries, profilename, saveFig=True, moten=None, plotTop=None, scaleXAxis=20, scaleData=2): #TODO: pas op bij opschonen, de boundaries veranderen nog weleens
        fig = plt.figure(figsize=(self.line.length / scaleXAxis, 7)) 
        ax1 = fig.add_subplot(211)

        # maak een grid
        plt.grid()
        plt.minorticks_on()
        plt.grid(which="minor", lw=0.1)
        
        # plot de cpts
        for cpt in self.cpts:
            qcX = cpt.data["coneResistance"] / scaleData + cpt.projectedLocation * self.line.length # TODO: ipv een vaste waarde een factor afhankelijk van aantal cpts en tussenafstand?
            rfX = cpt.data["frictionRatio"] / scaleData + cpt.projectedLocation * self.line.length # TODO: ipv vaste waarde een factor afhankelijk van aantal cpts en tussenafstand?
            y = -1 * cpt.data["depth"] + cpt.groundlevel
            plt.plot(qcX, y, c="blue", linewidth=0.5)
            plt.plot(rfX, y, c="green", linewidth=0.5)
            # labels in de figuur kunnen storend zijn, daarom een optie om ze uit te zetten
            # TODO: dit moet ergens anders ingesteld.
            includeLabels = True
            if includeLabels:
                plt.text(qcX.min(), y.max(), cpt.testid, rotation="vertical", fontsize='x-small')

        # plot de boringen
        materials = {0: 'grind', 1: 'zand', 2: 'klei', 3: 'leem', 4: 'veen', 5: 'silt', 6: 'overig'}
        colorsDict = {0: "orange", 1: "yellow", 2: "green", 3: "yellowgreen", 4: "brown", 5: "grey", 6: "black"} # BRO style # TODO: import from gefxml_viewer?

        # voeg een legenda toe
        import matplotlib.patches as mpatches
        handles = []
        for i in materials.keys():
            handles.append(mpatches.Patch(color=colorsDict[i], label=materials[i]))
        ax1.legend(handles=handles, fontsize='xx-small')

        plotAllMaterial = True
        if plotAllMaterial:
            for bore in self.bores:
                boreX = bore.projectedLocation * self.line.length
                for descriptionLocation, soillayers in bore.soillayers.items():
                    if "upper_NAP" in soillayers.columns:
                        uppers = list(soillayers["upper_NAP"])
                        lowers = list(soillayers["lower_NAP"])
                        components = list(soillayers["components"])

                        for upper, lower, component in reversed(list(zip(uppers, lowers, components))):
                            left = 0
                            # TODO: kan dit beter. Gemaakt vanwege een geval met component = nan (lab boring van Anthony Moddermanstraat)
                            if type(component) is dict:
                                for comp, nr in component.items():
                                    barPlot = plt.barh(lower, width=2*comp, left=left+boreX, height=upper-lower, color=colorsDict[nr], align="edge")
                                    left += 2*comp
                        # labels in de figuur kunnen storend zijn, daarom een optie om ze uit te zetten
                        # TODO: dit moet ergens anders ingesteld.
                        includeLabels = True
                        if includeLabels:
                            plt.text(boreX, bore.groundlevel, bore.testid, rotation="vertical", fontsize='x-small')
        else:
            # maak een eenvoudige plot van een boring
            for bore in self.bores:
                boreX = bore.projectedLocation * self.line.length
                for i, layer in bore.soillayers['veld'].iterrows(): # plot alleen de veldbeschrijving, deze is als optie toegevoegd rond 19 mei 2022 aan de gefxml_viewer
                    mainMaterial = layer.components[max(layer.components.keys())]
                    plotColor = colorsDict[mainMaterial]
                    plt.plot([boreX, boreX], [layer.upper_NAP, layer.lower_NAP], plotColor, lw=4, alpha=0.7) # TODO: xml boringen hebben een attribute plotColor, dat is niet meer nodig
                # labels in de figuur kunnen storend zijn, daarom een optie om ze uit te zetten
                # TODO: dit moet ergens anders ingesteld.
                includeLabels = True
                if includeLabels:
                    plt.text(boreX, bore.groundlevel, bore.testid, rotation="vertical", fontsize='x-small')

        # plot maaiveld
        x = [xy[0] for xy in self.groundlevelAbs.tolist()]
        y = [xy[1] for xy in self.groundlevelAbs.tolist()]
        plt.plot(x, y, "k--", lw=0.5)

        # plot de laaggrenzen als lijnen
        for boundary, points in boundaries.items():
            points = np.array(points)
            plt.plot(points[:,0], points[:,1], c="black")

        # kleur de lagen
        for boundary in boundaries.keys():
            if boundary < max(boundaries.keys()):
                pointsTop = np.array(boundaries[boundary + 1])
                pointsBottom = np.array(boundaries[boundary])

                xTop = pointsTop[:,0]
                yTop = pointsTop[:,1]
                xBottom = pointsBottom[:,0]
                yBottom = pointsBottom[:,1]

                # zorgen dat beide lijnen dezelfde x-coördinaten hebben
                allX = np.concatenate((xTop, xBottom))
                allX = np.unique(allX)
                allX = np.sort(allX)
                
                # y waarden interpoleren
                allYTop = np.interp(allX, xTop, yTop)
                allYBottom = np.interp(allX, xBottom, yBottom)            

                plt.fill_between(allX, allYBottom, allYTop, color=self.materials.loc[boundary]["kleur"])

        # voeg de moten toe
        if moten is not None:
            metreringen = 10125 - moten['metrering'].to_numpy()
            mootnamen = moten['Moot-nummer'].to_numpy()
            for i, metrering in enumerate(metreringen):
                plt.axvline(metrering, c='black')
                if i < len(metreringen) - 1:
                    if plotTop is not None:
                        yText = plotTop+0.5
                    else:
                        yText = plt.gca().get_ylim()[0]+0.5
                    plt.text(x=(metrering + metreringen[i+1])/2, y=yText, s=mootnamen[i])

            plt.xticks(ticks=metreringen, labels=moten['metrering'].to_numpy())


        # optie om alleen de bovenste meters te plotten
        if plotTop is not None:
            ax1.set_ylim(bottom=plotTop)

        # Tweede as aan de rechterkant van de plot
        ax2 = ax1.twinx().set_ylim(ax1.get_ylim())
        
        # stel de assen in
        ax1.set_xlabel("afstand [m]")
        ax1.set_ylabel("niveau [m t.o.v. NAP]")

        # beperk de plot tot lengte van de profiellijn
        ax1.set_xlim(left=0) # TODO: dit werkt niet handig als je de coördinaten uit grondonderzoek haalt. right=self.line.length

        plt.suptitle(profilename)
        fig.text(0.05, 0.15, 'Ingenieursbureau Gemeente Amsterdam - Team WGM - Vakgroep Geotechniek', fontsize='x-small')

        addMap = True
        if addMap:
            fig = self.add_map_to_plot(fig)

        if saveFig:
            plt.savefig(f"./output/gtl_{profilename}.svg", bbox_inches="tight")
            plt.savefig(f"./output/gtl_{profilename}.png", bbox_inches="tight")   
        else:
            return(fig)
        
    def add_map_to_plot(self, fig):
        # Voeg een kaart toe
        ax3 = fig.add_subplot(212)
        
        pointdict = {}
        for cpt in self.cpts:
            pointdict[cpt.testid] = {'geometry': Point(cpt.easting, cpt.northing)}
        for bore in self.bores:
            pointdict[bore.testid] = {'geometry': Point(bore.easting, bore.northing)}
        
        linedf = pd.DataFrame().from_dict({'line': {'geometry': self.line}}).T
        linegdf = gpd.GeoDataFrame(linedf, geometry='geometry').set_crs('epsg:28992')
        pointdf = pd.DataFrame().from_dict(pointdict).T
        pointgdf = gpd.GeoDataFrame(pointdf, geometry='geometry').set_crs('epsg:28992')

        # draai het profiel op de kaart naar oost-west oriëntatie
        from matplotlib import transforms
        base = ax3.transData
        # punt midden op de lijn als centrum voor de rotaties
        x = self.line.interpolate(0.5).x
        y = self.line.interpolate(0.5).y
        
        north = [0, 1]

        # bepaal de generale trend van de lijn
        # omdat er regelmatig een haakje zit aan een einde, gebruiken we het middenstuk van de lijn
        # TODO: de lijn plot soms toch niet horizontaal
        p1 = self.line.interpolate(0.3).x - self.line.interpolate(0.7).x
        p2 = self.line.interpolate(0.3).y - self.line.interpolate(0.7).y
        gen_line = [p1, p2] / np.linalg.norm([p1, p2])

        # arccos gebruikt maar de helft van de cirkel, daarom een check in welk kwadrant de vector zit
        # 0.5 * pi om te zorgen dat de lijn links-rechts geörienteerd wordt
        # TODO: De rotatie is niet altijd correct
        xtest = self.line.interpolate(0.).x < self.line.interpolate(1.).x
        ytest = self.line.interpolate(0.).y < self.line.interpolate(1.).y

        if xtest and ytest:
            angle = 0.5 * np.pi - np.arccos(np.dot(gen_line, north)) 
        elif xtest and not ytest:
            angle = 0.5 * np.pi - np.arccos(np.dot(gen_line, north)) 
        elif not xtest and not ytest:
            angle = 0.5 * np.pi + np.arccos(np.dot(gen_line, north)) 
        elif not xtest and ytest:
            angle = 0.5 * np.pi + np.arccos(np.dot(gen_line, north))
        rot = transforms.Affine2D().rotate_around(x, y, angle)
        
        # plot de lijn en de punten
        linegdf.plot(ax=ax3, transform=rot+base)
        pointgdf.plot(ax=ax3, transform=rot+base)

        # nog een bbox om achtergrondkaart te laden, anders krijg je een deel zonder kaart
        bbox = self.line.bounds
        bboxdict = {'bbox': {'geometry': box(bbox[0] - 50, bbox[1] - 25, bbox[2] + 50, bbox[3] + 25)}}
        bboxdf = pd.DataFrame().from_dict(bboxdict).T
        bboxgdf = gpd.GeoDataFrame(bboxdf, geometry='geometry').set_crs('epsg:28992')
        bboxgdf.plot(ax=ax3, facecolor='none', edgecolor='none') # deze lijkt niet nodig, maar moet blijven staan

        # voeg een achtergrondkaart toe
        # omdat deze nog weleens een foutmelding geeft, een try-except
        try:
            _ = ctx.bounds2raster(*bboxgdf.to_crs('epsg:3857').total_bounds, path='./temp.tiff', zoom=17)
            ctx.add_basemap(ax3, crs=bboxgdf.crs.to_string(), transform=rot+base, source='./temp.tiff')
        except:
            pass

        # assen afsnijden
        plotbox = linegdf.rotate(angle, [x,y], use_radians=True).total_bounds
        ax3.set_xlim(plotbox[0] - 50, plotbox[2] + 50)
        ax3.set_ylim(plotbox[1] - 25, plotbox[3] + 25)

        # voeg tekst toe aan de meetpunten
        for test, point in pointgdf.rotate(angle, [x,y], use_radians=True).items(): 
            textx = point.x
            texty = point.y
            ax3.annotate(test, [textx, texty], rotation='vertical', fontsize='xx-small')

        ax3.axis('off')

        return fig



    def add_line(self, eventorigin):
        # deze functie maakt het mogelijk om een lijn (grens) toe te voegen 
        global i
        i += 1 # TODO: dit zou toch via gtl.boundaries moeten kunnen?

    tklines = []
    def draw_line(self, eventorigin):
        # deze functie maakt het mogelijk om een lijn (grens) te tekenen
        global tkline
        global x,y
        x = eventorigin.x
        y = eventorigin.y
        
        # check of er een nieuwe lijn is begonnen
        # dan deze toevoegen aan de verzameling
        if i not in self.boundaries.keys():
            # voeg het geklikte punt toe aan de lijn
            self.boundaries[i] = [[x,y]]
        else:
            # voeg het geklikte punt toe aan de lijn
            self.boundaries[i].append([x,y])
        # teken de lijn (als er meer dan 1 punt is)
        if len(self.boundaries[i]) > 1:
            tkline = C.create_line(self.boundaries[i])
            self.tklines.append(tkline)

    def remove_last_point(self, eventorigin):
        # deze functie verwijdert het laatste punt van de laatste boundary (kan meerdere punten verwijderen)
        # en verwijdert het laatst getekende lijnstuk
        last_boundary = max(self.boundaries.keys())
        if len(self.boundaries[last_boundary]) > 0:
            del self.boundaries[last_boundary][-1]
            C.delete(self.tklines[-1])
            del self.tklines[-1]

    def finish(self):
        # deze functie zorgt voor het afsluiten van het tekenvenster 
        # en het verder verwerken van de ingevoerde punten / grenzen
        root.quit()

        # verwijder het laatste punt van boundaries, dat ontstaat bij het sluiten
        self.boundaries[max(self.boundaries.keys())] = self.boundaries[max(self.boundaries.keys())][:-1]
        
        yScale, top = self.get_yscale_for_canvas()
        realLength = self.line.length
        scaledBoundaries = self.scale_points_to_real_world(self.boundaries, realLength, self.canvasWidth, yScale, top)
        boundariesModifiedLimits = self.modify_geometry_limits(scaledBoundaries, 0, realLength)
        
        # voeg het maaiveld toe
        boundariesModifiedLimits[1] = self.groundlevelAbs.tolist() # voor de DSerie input
        
        self.write_to_DSerie_input(boundariesModifiedLimits)
        self.plot(boundariesModifiedLimits, self.profilename)

    def write_to_DSerie_input(self, boundaries):
        # deze functie maakt een geometriebestand dat ingelezen kan worden in de D-Serie
        pointsi = 1
        pointstxt = ""

        for points in boundaries.values():
            for point in points:
                pointstxt += f'\t\t{pointsi}\t{round(point[0], 3)}\t\t{round(point[1], 3)}\t\t0.000\n'
                pointsi += 1
        pointstxt = f"[POINTS]\n\t{pointsi - 1} - Number of geometry points -\n" + pointstxt
        pointstxt += "[END OF POINTS]\n"
            
        pointsi = 2
        curvesi = 1
        curvestxt = ""
        boundstxt = ""

        maxBoundary = max(boundaries.keys())
        for boundary, points in boundaries.items():
            startcurve = curvesi
            for point in range(len(points)-1):
                curvestxt += f"\t{curvesi} - Curve number\n"
                curvestxt += f"\t\t2 - number of points on curve, next line(s) are pointnumbers\n"
                curvestxt += f"\t\t\t{pointsi-1}\t{pointsi}\n"
                pointsi += 1
                curvesi += 1
            endcurve = curvesi
            pointsi += 1

            boundtxt = f"\t{maxBoundary - boundary} - Boundary number\n"
            boundtxt += f"\t\t{endcurve - startcurve} - number of curves on boundary, next line(s) are curvenumbers\n\t\t\t"
            for curve in range(startcurve, endcurve):
                boundtxt += f"{curve}\t"
            boundtxt += "\n"

            boundstxt = boundtxt + boundstxt

        curvestxt = f"[CURVES]\n\t{curvesi - 1}\t- Number of curves -\n" + curvestxt
        curvestxt += "[END OF CURVES]\n"
        
        boundstxt = f"[BOUNDARIES]\n\t{len(boundaries.keys())}\t- Number of boundaries -\n" + boundstxt
        boundstxt += "[END OF BOUNDARIES]\n"
        
        layerstxt = f"[LAYERS]\n" 
        layerstxt += f"{len(boundaries.keys()) - 1} - Number of Layers -\n"
        for boundaryi in range(len(boundaries.keys())-1):
            layerstxt += f"\t{boundaryi + 1} - Layer number, next line is material of layer\n"
            layerstxt += f"\t\tmaterial\n"
            layerstxt += f"\t\t0 - Piezometric level line at top of layer\n"
            layerstxt += f"\t\t0 - Piezometric level line at bottom of layer\n"
            layerstxt += f"\t\t{boundaryi + 1} - Boundarynumber at top of layer\n"
            layerstxt += f"\t\t{boundaryi} - Boundarynumber at bottom of layer\n"
        layerstxt += "[END OF LAYERS]\n"

        headertxt = "GEOMETRY FILE FOR THE M-SERIES\n"
        headertxt += "==============================================================================\n"
        headertxt += "COMPANY    : Gemeente Amsterdam Ingenieursbureau  \n"
        headertxt += f"DATE       : {datetime.today().strftime('%m/%d/%Y')}\n"
        headertxt += f"TIME       : {datetime.now().strftime('%I:%M:%S %p')}\n"
        headertxt += "FILENAME   : H:/test.geo\n"
        headertxt += "CREATED BY : D-Settlement version 20.1.1.29740\n"
        headertxt += "==========================    BEGINNING OF DATA     ==========================\n"
        headertxt += "[TITLES]\n"
        headertxt += "Geometry created with a tool written by Thomas van der Linden\n"
        headertxt += "\n"
        headertxt += "[END OF TITLES]\n"
        headertxt += "[EXTRA TITLE]\n"
        headertxt += "\n"
        headertxt += "[END OF EXTRA TITLE]\n"
        headertxt += "[ACCURACY]\n"
        headertxt += "\t0.0010\n"
        headertxt += "[END OF ACCURACY]\n"
        headertxt += "\n"

        with open("./output.geo", "w") as output:
            output.write(headertxt)
            output.write(pointstxt)
            output.write(curvestxt)
            output.write(boundstxt)
            output.write(layerstxt)
            output.write("END OF GEOMETRY FILE")

    def modify_geometry_limits(self, boundaries, leftLimit, rightLimit):
        # deze functie zorgt ervoor dat alle eerste punten op een grens x=0 hebben
        # en alle laatste punten op een grens x=lengte van de lijn
        
        for boundary, points in boundaries.items():
            points.insert(0, [leftLimit, points[0][1]])
            points.append([rightLimit, points[-1][1]])
        return boundaries

    def scale_points_to_real_world(self, boundaries, realLength, canvasWidth, yScale, top):
        # deze functie schaalt de coördinaten van het canvas naar de fysieke wereld
        scaledBoundaries = {}
        for boundary, points in boundaries.items():
            points = np.array(points)
            scaledX = points[:,0] * realLength / canvasWidth
            scaledY = top - 1 * points[:,1] / yScale
            scaledBoundaries[boundary] = [[scaledX, scaledY] for scaledX, scaledY in list(zip(scaledX, scaledY))]
        return scaledBoundaries

    def get_yscale_for_canvas(self):
        # volgende blok bepaalt de yscale
        groundlevels = []
        finaldepths = []
        for cpt in self.cpts:
            groundlevels.append(cpt.groundlevel)
            finaldepths.append(cpt.finaldepth)
        for bore in self.bores:
            groundlevels.append(bore.groundlevel)
            finaldepths.append(bore.finaldepth) 
        top = max(groundlevels)
        length = max(finaldepths)
        yscale = self.canvasHeight / length

        return yscale, top

    def scale_cpt_to_canvas(self, cpt, xScaleCPT, yscale, groundlevel, top, width):
        qcX = cpt.data["coneResistance"] * xScaleCPT + cpt.projectedLocation * width # uses relative projectedLocation (0-1)
        rfX = cpt.data["frictionRatio"]  * xScaleCPT + cpt.projectedLocation * width # uses relative projectedLocation (0-1)
        y = (top - groundlevel + cpt.data["depth"]) * yscale 
        return qcX, rfX, y

    def scale_bore_to_canvas(self, bore, yscale, groundlevel, top, width):
        xs = np.full(len(bore.soillayers['veld'].index), bore.projectedLocation * width)
        uppers = (top - groundlevel + bore.soillayers['veld']["upper"]) * yscale 
        lowers = (top - groundlevel + bore.soillayers['veld']["lower"]) * yscale 
        return xs, uppers, lowers

    def scale_groundlevel_to_canvas(self, yscale, top, width):
        xs = self.groundlevelRel[:,0] * width
        ys = (self.groundlevelRel[:,1] * -1 + top) * yscale
        return xs, ys

    def create_canvas_with_cpts(self):
        # deze functie maakt een canvas met daarop plots van cpts

        # maak het canvas
        global C, i, root
        root = tk.Tk()
        C = tk.Canvas(root, height=self.canvasHeight, width=self.canvasWidth)

        # bepaal de schaal voor de verticale as
        yscale, top = self.get_yscale_for_canvas()

        # voeg de cpts toe aan het canvas
        for i, cpt in enumerate(self.cpts):

            qcX, rfX, y = self.scale_cpt_to_canvas(cpt, self.xScaleCPT, yscale, cpt.groundlevel, top, self.canvasWidth)
            # tkinter moet een lijst van x,y punten hebben
            qcPoints = list(zip(qcX, y))
            rfPoints = list(zip(rfX, y))
            qcLine = C.create_line(qcPoints, fill="blue")
            rfLine = C.create_line(rfPoints, fill="green")
            cptText = C.create_text(qcPoints[0], text=cpt.testid)

        # voeg de boringen toe aan het canvas
        for i, bore in enumerate(self.bores):

            xs, uppers, lowers = self.scale_bore_to_canvas(bore, yscale, bore.groundlevel, top, self.canvasWidth)
            colors = bore.soillayers['veld']["plotColor"]

            for x, upper, lower, color in list(zip(xs, uppers, lowers, colors)):
                point_from = (x, upper)
                point_to = (x, lower)
                print(point_from, point_to)
                layer_line = C.create_line(x, upper, x, lower, fill=color, width=5)

        # voeg het maaiveld toe aan het canvas
        xs, ys = self.scale_groundlevel_to_canvas(yscale, top, self.canvasWidth)
        groundlevelPoints = list(zip(xs, ys))
        groundlevel_line = C.create_line(groundlevelPoints)

        i = 2
        quitbutton = tk.Button(root, text="Quit", command=self.finish).pack()

        C.pack()

        # de linker muisknop is Button 1, een klik voegt een punt toe aan een lijn (grens)
        root.bind("<Button 1>", self.draw_line)

        # de rechter muisknop is button 2 of button 3, een klik maakt een nieuwe lijn (grens)
        line = root.bind("<Button 2>", self.add_line)
        line = root.bind("<Button 3>", self.add_line)

        # klik x om het laatste punt te verwijderen
        root.bind("x", self.remove_last_point)

        root.mainloop()

