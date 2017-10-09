import re
import os
import codecs
from urlparse import parse_qs

from PyQt4.QtCore import QCoreApplication
from qgis.core import (QgsRenderContext,
                       QgsSingleSymbolRendererV2,
                       QgsCategorizedSymbolRendererV2,
                       QgsGraduatedSymbolRendererV2,
                       QgsHeatmapRenderer,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform)
from utils import safeName, is25d, BLEND_MODES
from basemaps import basemapOL
qms = False
try:
    from quick_map_services.py_tiled_layer.tilelayer import TileLayer
    qms = True
except:
    pass


def writeLayersAndGroups(layers, groups, visible, folder, popup,
                         settings, json, matchCRS, clustered, iface,
                         restrictToExtent, extent):

    canvas = iface.mapCanvas()
    basemapList = settings["Appearance"]["Base layer"]
    baseLayer = getBasemaps(basemapList)
    layerVars = ""
    layer_names_id = {}
    for count, (layer, encode2json, cluster) in enumerate(zip(layers, json,
                                                              clustered)):
        layer_names_id[layer.id()] = str(count)
        if is25d(layer, canvas, restrictToExtent, extent):
            pass
        else:
            layerVars += "\n".join([layerToJavascript(iface, layer,
                                                      encode2json,
                                                      matchCRS, cluster,
                                                      restrictToExtent,
                                                      extent, count)])
    (groupVars, groupedLayers) = buildGroups(groups, qms, layer_names_id)
    (mapLayers, osmb) = layersAnd25d(layers, canvas, restrictToExtent, extent,
                                     qms)
    visibility = getVisibility(mapLayers, visible)

    usedGroups = []
    (group_list, no_group_list,
     usedGroups) = getGroups(canvas, layers, basemapList, restrictToExtent,
                             extent, groupedLayers)
    layersList = []
    for layer in (group_list + no_group_list):
        layersList.append(layer)
    layersListString = "var layersList = [" + ",".join(layersList) + "];"

    fieldAliases = ""
    fieldImages = ""
    fieldLabels = ""
    blend_mode = ""
    labelgun = ""
    for count, (layer, labels) in enumerate(zip(layers, popup)):
        sln = safeName(layer.name()) + "_" + unicode(count)
        if layer.type() == layer.VectorLayer and not is25d(layer, canvas,
                                                           restrictToExtent,
                                                           extent):
            (fieldLabels, fieldAliases, fieldImages,
             blend_mode, labelgun) = getPopups(layer, labels, sln, fieldLabels,
                                               fieldAliases, fieldImages)
    path = os.path.join(folder, "layers", "layers.js")
    with codecs.open(path, "w", "utf-8") as f:
        if basemapList:
            f.write(baseLayer + "\n")
        f.write(layerVars + "\n")
        f.write(groupVars + "\n")
        f.write(visibility + "\n")
        f.write(layersListString + "\n")
        f.write(fieldAliases)
        f.write(fieldImages)
        f.write(fieldLabels)
        f.write(blend_mode)
        f.write(labelgun)
    return osmb


def layerToJavascript(iface, layer, encode2json, matchCRS, cluster,
                      restrictToExtent, extent, count):
    (minResolution, maxResolution) = getScaleRes(layer)
    layerName = safeName(layer.name()) + "_" + unicode(count)
    layerAttr = getAttribution(layer)
    if layer.type() == layer.VectorLayer and not is25d(layer,
                                                       iface.mapCanvas(),
                                                       restrictToExtent,
                                                       extent):
        renderer = layer.rendererV2()
        cluster = isCluster(cluster, renderer)
        hmRadius = 0
        hmRamp = ""
        hmWeight = 0
        hmWeightMax = 0
        if isinstance(renderer, QgsHeatmapRenderer):
            (pointLayerType, hmRadius,
             hmRamp, hmWeight, hmWeightMax) = getHeatmap(layer, renderer)
        else:
            pointLayerType = "Vector"
        crsConvert = getCRS(iface, matchCRS)
        if layer.providerType() == "WFS" and not encode2json:
            return getWFS(layer, layerName, layerAttr, cluster,
                          minResolution, maxResolution)
        else:
            return getJSON(layerName, crsConvert, layerAttr, cluster,
                           pointLayerType, minResolution, maxResolution,
                           hmRadius, hmRamp, hmWeight, hmWeightMax, renderer,
                           layer)
    elif layer.type() == layer.RasterLayer:
        if layer.providerType().lower() == "wms":
            source = layer.source()
            opacity = layer.renderer().opacity()
            d = parse_qs(source)
            if "type" in d and d["type"][0] == "xyz":
                return getXYZ(layerName, opacity, minResolution,
                              maxResolution, layerAttr, d["url"][0])
            elif "tileMatrixSet" in d:
                return getWMTS(layer, d, layerAttr, layerName, opacity,
                               minResolution, maxResolution)
            else:
                return getWMS(source, layer, layerAttr, layerName, opacity,
                              minResolution, maxResolution)
        elif layer.providerType().lower() == "gdal":
            return getRaster(iface, layer, layerName, layerAttr, minResolution,
                             maxResolution, matchCRS)


def getScaleRes(layer):
    minResolution = ""
    maxResolution = ""
    if layer.hasScaleBasedVisibility():
        if layer.minimumScale() != 0:
            minRes = 1 / ((1 / layer.minimumScale()) * 39.37 * 90.7)
            minResolution = "\nminResolution:%s,\n" % unicode(minRes)
        if layer.maximumScale() != 0:
            maxRes = 1 / ((1 / layer.maximumScale()) * 39.37 * 90.7)
            maxResolution = "maxResolution:%s,\n" % unicode(maxRes)
    return (minResolution, maxResolution)


def getAttribution(layer):
    attrText = layer.attribution()
    attrUrl = layer.attributionUrl()
    layerAttr = '<a href="%s">%s</a>' % (attrUrl, attrText)
    return layerAttr


def getBasemaps(basemapList):
    basemaps = [basemapOL()[item] for _, item in enumerate(basemapList)]
    if len(basemapList) > 1:
        baseGroup = "Base maps"
    else:
        baseGroup = ""
    baseLayer = """var baseLayer = new ol.layer.Group({
    'title': '%s',
    layers: [%s\n]
});""" % (baseGroup, ','.join(basemaps))
    return baseLayer


def build25d(canvas, layer, count):
    shadows = ""
    renderer = layer.rendererV2()
    renderContext = QgsRenderContext.fromMapSettings(canvas.mapSettings())
    fields = layer.pendingFields()
    renderer.startRender(renderContext, fields)
    for feat in layer.getFeatures():
        if isinstance(renderer, QgsCategorizedSymbolRendererV2):
            classAttribute = renderer.classAttribute()
            attrValue = feat.attribute(classAttribute)
            catIndex = renderer.categoryIndexForValue(attrValue)
            categories = renderer.categories()
            symbol = categories[catIndex].symbol()
        elif isinstance(renderer, QgsGraduatedSymbolRendererV2):
            classAttribute = renderer.classAttribute()
            attrValue = feat.attribute(classAttribute)
            ranges = renderer.ranges()
            for range in ranges:
                if (attrValue >= range.lowerValue() and
                        attrValue <= range.upperValue()):
                    symbol = range.symbol().clone()
        else:
            symbol = renderer.symbolForFeature2(feat, renderContext)
        symbolLayer = symbol.symbolLayer(0)
        if not symbolLayer.paintEffect().effectList()[0].enabled():
            shadows = "'2015-07-15 10:00:00'"
    renderer.stopRender(renderContext)
    osmb = """
var osmb = new OSMBuildings(map).date(new Date({shadows}));
osmb.set(json_{sln}_{count});""".format(shadows=shadows,
                                        sln=safeName(layer.name()),
                                        count=unicode(count))
    return osmb


def getVisibility(mapLayers, visible):
    visibility = ""
    for layer, v in zip(mapLayers[1:], visible):
        visibility += "\n".join(["%s.setVisible(%s);" % (layer,
                                                         unicode(v).lower())])
    return visibility


def buildGroups(groups, qms, layer_names_id):
    groupVars = ""
    groupedLayers = {}
    for group, groupLayers in groups.iteritems():
        groupLayerObjs = ""
        for layer in groupLayers:
            if qms:
                if isinstance(layer, TileLayer):
                    continue
            groupLayerObjs += ("lyr_" + safeName(layer.name()) + "_" +
                               layer_names_id[layer.id()] + ",")
        groupVars += ('''var %s = new ol.layer.Group({
                                layers: [%s],
                                title: "%s"});\n''' %
                      ("group_" + safeName(group), groupLayerObjs, group))
        for layer in groupLayers:
            groupedLayers[layer.id()] = safeName(group)
    return (groupVars, groupedLayers)


def layersAnd25d(layers, canvas, restrictToExtent, extent, qms):
    mapLayers = ["baseLayer"]
    osmb = ""
    for count, layer in enumerate(layers):
        if is25d(layer, canvas, restrictToExtent, extent):
            osmb = build25d(canvas, layer, count)
        else:
            if (qms and not isinstance(layer, TileLayer)) or not qms:
                mapLayers.append("lyr_" + safeName(layer.name()) + "_" +
                                 unicode(count))
    return (mapLayers, osmb)


def getGroups(canvas, layers, basemapList, restrictToExtent, extent,
              groupedLayers):
    group_list = ["baseLayer"] if len(basemapList) else []
    no_group_list = []
    usedGroups = []
    for count, layer in enumerate(layers):
        try:
            if is25d(layer, canvas, restrictToExtent, extent):
                pass
            else:
                if layer.id() in groupedLayers:
                    groupName = groupedLayers[layer.id()]
                    if groupName not in usedGroups:
                        group_list.append("group_" + safeName(groupName))
                        usedGroups.append(groupName)
                else:
                    no_group_list.append("lyr_" + safeName(layer.name()) +
                                         "_" + unicode(count))
        except:
            if layer.id() in groupedLayers:
                groupName = groupedLayers[layer.id()]
                if groupName not in usedGroups:
                    group_list.append("group_" + safeName(groupName))
                    usedGroups.append(groupName)
            else:
                no_group_list.append("lyr_" + safeName(layer.name()) +
                                     "_" + unicode(count))
    return (group_list, no_group_list, usedGroups)


def getPopups(layer, labels, sln, fieldLabels, fieldAliases, fieldImages):
    fieldList = layer.pendingFields()
    aliasFields = ""
    imageFields = ""
    labelFields = ""
    for field, label in zip(labels.keys(), labels.values()):
        labelFields += "'%(field)s': '%(label)s', " % (
            {"field": field, "label": label})
    labelFields = "{%(labelFields)s});\n" % (
        {"labelFields": labelFields})
    labelFields = "lyr_%(name)s.set('fieldLabels', " % (
        {"name": sln}) + labelFields
    fieldLabels += labelFields
    for f in fieldList:
        fieldIndex = fieldList.indexFromName(unicode(f.name()))
        aliasFields += "'%(field)s': '%(alias)s', " % (
            {"field": f.name(),
             "alias": layer.attributeDisplayName(fieldIndex)})
        widget = layer.editFormConfig().widgetType(fieldIndex)
        imageFields += "'%(field)s': '%(image)s', " % (
            {"field": f.name(),
             "image": widget})
    aliasFields = "{%(aliasFields)s});\n" % (
        {"aliasFields": aliasFields})
    aliasFields = "lyr_%(name)s.set('fieldAliases', " % (
        {"name": sln}) + aliasFields
    fieldAliases += aliasFields
    imageFields = "{%(imageFields)s});\n" % (
        {"imageFields": imageFields})
    imageFields = "lyr_%(name)s.set('fieldImages', " % (
        {"name": sln}) + imageFields
    fieldImages += imageFields
    blend_mode = """lyr_%(name)s.on('precompose', function(evt) {
    evt.context.globalCompositeOperation = '%(blend)s';
});""" % (
                {"name": sln, "blend": BLEND_MODES[layer.blendMode()]})
    labelgun = """
    lyr_%s.on("postcompose", update);

    var listenerKey = lyr_%s.on('change', function(e) {
        update();
        ol.Observable.unByKey(listenerKey);
    });""" % (sln, sln)
    return (fieldLabels, fieldAliases, fieldImages, blend_mode, labelgun)


def getWFS(layer, layerName, layerAttr, cluster, minResolution, maxResolution):
    layerCode = '''var format_%(n)s = new ol.format.GeoJSON();
var jsonSource_%(n)s = new ol.source.Vector({
    attributions: [new ol.Attribution({html: '%(layerAttr)s'})],
    format: format_%(n)s
});''' % {"n": layerName, "layerAttr": layerAttr}
    if cluster:
        layerCode += '''cluster_%(n)s = new ol.source.Cluster({
  distance: 10,
  source: jsonSource_%(n)s
});''' % {"n": layerName}
    layerCode += '''var lyr_%(n)s = new ol.layer.Vector({
    source: ''' % {"n": layerName}
    if cluster:
        layerCode += 'cluster_%(n)s,' % {"n": layerName}
    else:
        layerCode += 'jsonSource_%(n)s,' % {"n": layerName}
    layerCode += '''%(min)s %(max)s
    style: style_%(n)s,
    title: "%(name)s"
});

function get%(n)sJson(geojson) {
    var features_%(n)s = format_%(n)s.readFeatures(geojson);
    jsonSource_%(n)s.addFeatures(features_%(n)s);
}''' % {"name": layer.name(), "n": layerName,
        "min": minResolution, "max": maxResolution}


def getJSON(layerName, crsConvert, layerAttr, cluster, pointLayerType,
            minResolution, maxResolution, hmRadius, hmRamp, hmWeight,
            hmWeightMax, renderer, layer):
    layerCode = '''var format_%(n)s = new ol.format.GeoJSON();
var features_%(n)s = format_%(n)s.readFeatures(json_%(n)s, %(crs)s);
var jsonSource_%(n)s = new ol.source.Vector({
    attributions: [new ol.Attribution({html: '%(layerAttr)s'})],
});
jsonSource_%(n)s.addFeatures(features_%(n)s);''' % {"n": layerName,
                                                    "crs": crsConvert,
                                                    "layerAttr": layerAttr}
    if cluster:
        layerCode += '''cluster_%(n)s = new ol.source.Cluster({
  distance: 10,
  source: jsonSource_%(n)s
});''' % {"n": layerName}
    layerCode += '''var lyr_%(n)s = new ol.layer.%(t)s({
                source:''' % {"n": layerName, "t": pointLayerType}
    if cluster:
        layerCode += 'cluster_%(n)s,' % {"n": layerName}
    else:
        layerCode += 'jsonSource_%(n)s,' % {"n": layerName}
    layerCode += '''%(min)s %(max)s''' % {"min": minResolution,
                                          "max": maxResolution}
    if pointLayerType == "Vector":
        layerCode += '''
                style: style_%(n)s,''' % {"n": layerName}
    else:
        layerCode += writeHeatmap(hmRadius, hmRamp, hmWeight, hmWeightMax)
    if isinstance(renderer, QgsSingleSymbolRendererV2):
        layerCode += '''
                title: '<img src="styles/legend/%(icon)s.png" /> %(name)s'
            });''' % {"icon": layerName, "name": layer.name()}
    elif isinstance(renderer, QgsCategorizedSymbolRendererV2):
        layerCode += getLegend(renderer.categories(), layer, layerName)
    elif isinstance(renderer, QgsGraduatedSymbolRendererV2):
        layerCode += getLegend(renderer.ranges(), layer, layerName)
    else:
        layerCode += '''
                title: '%(name)s'
            });''' % {"name": layer.name()}
    return layerCode


def getLegend(subitems, layer, layerName):
    icons = ""
    for count, subitem in enumerate(subitems):
        text = subitem.label().replace("'", "\\'")
        icons += ("""\\
    <img src="styles/legend/%(icon)s_%(count)s.png" /> %(text)s<br />""" %
                  {"icon": layerName, "count": count, "text": text})
    legend = '''
    title: '%(name)s<br />%(icons)s'
        });''' % {"icons": icons, "name": layer.name()}
    return legend


def isCluster(cluster, renderer):
    if (cluster and isinstance(renderer, QgsSingleSymbolRendererV2)):
        cluster = True
    else:
        cluster = False
    return cluster


def getHeatmap(layer, renderer):
    pointLayerType = "Heatmap"
    hmRadius = renderer.radius()
    colorRamp = renderer.colorRamp()
    hmStart = colorRamp.color1().name()
    hmEnd = colorRamp.color2().name()
    hmRamp = "['" + hmStart + "', "
    hmStops = colorRamp.stops()
    for stop in hmStops:
        hmRamp += "'" + stop.color.name() + "', "
    hmRamp += "'" + hmEnd + "']"
    hmWeight = renderer.weightExpression()
    hmWeightId = layer.fieldNameIndex(hmWeight)
    hmWeightMax = layer.maximumValue(hmWeightId)
    return (pointLayerType, hmRadius, hmRamp, hmWeight, hmWeightMax)


def getCRS(iface, matchCRS):
    if matchCRS:
        mapCRS = iface.mapCanvas().mapSettings().destinationCrs().authid()
        crsConvert = """
            {dataProjection: 'EPSG:4326', featureProjection: '%(d)s'}""" % {
                "d": mapCRS}
    else:
        crsConvert = """
            {dataProjection: 'EPSG:4326', featureProjection: 'EPSG:3857'}"""
    return crsConvert


def writeHeatmap(hmRadius, hmRamp, hmWeight, hmWeightMax):
    layerCode = '''
                radius: %(hmRadius)d * 2,
                gradient: %(hmRamp)s,
                blur: 15,
                shadow: 250,''' % {"hmRadius": hmRadius, "hmRamp": hmRamp}
    if hmWeight != "":
        layerCode += '''
    weight: function(feature){
        var weightField = '%(hmWeight)s';
        var featureWeight = feature.get(weightField);
        var maxWeight = %(hmWeightMax)d;
        var calibratedWeight = featureWeight/maxWeight;
        return calibratedWeight;
    },''' % {"hmWeight": hmWeight, "hmWeightMax": hmWeightMax}
    return layerCode


def getXYZ(layerName, opacity, minResolution, maxResolution,
           layerAttr, url):
    return """
        var lyr_%s = new ol.layer.Tile({
            'title': '%s',
            'type': 'base',
            'opacity': %f,
            %s
            %s
            source: new ol.source.XYZ({
    attributions: [new ol.Attribution({html: '%s'})],
                url: '%s'
            })
        });""" % (layerName, layerName, opacity, minResolution, maxResolution,
                  layerAttr, url)


def getWMTS(layer, d, layerAttr, layerName, opacity, minResolution,
            maxResolution):
    layerId = d["layers"][0]
    url = d["url"][0]
    format = d["format"][0]
    style = d["styles"][0]
    return '''
    var projection_%(n)s = ol.proj.get('EPSG:3857');
    var projectionExtent_%(n)s = projection_%(n)s.getExtent();
    var size_%(n)s = ol.extent.getWidth(projectionExtent_%(n)s) / 256;
    var resolutions_%(n)s = new Array(14);
    var matrixIds_%(n)s = new Array(14);
    for (var z = 0; z < 14; ++z) {
        // generate resolutions and matrixIds arrays for this WMTS
        resolutions_%(n)s[z] = size_%(n)s / Math.pow(2, z);
        matrixIds_%(n)s[z] = z;
    }
    var lyr_%(n)s = new ol.layer.Tile({
                            source: new ol.source.WMTS(({
                              url: "%(url)s",
    attributions: [new ol.Attribution({html: '%(layerAttr)s'})],
                                "layer": "%(layerId)s",
                                "TILED": "true",
             matrixSet: 'EPSG:3857',
             format: '%(format)s',
              projection: projection_%(n)s,
              tileGrid: new ol.tilegrid.WMTS({
                origin: ol.extent.getTopLeft(projectionExtent_%(n)s),
                resolutions: resolutions_%(n)s,
                matrixIds: matrixIds_%(n)s
              }),
              style: '%(style)s',
              wrapX: true,
                                "VERSION": "1.0.0",
                            })),
                            title: "%(name)s",
                            opacity: %(opacity)s,
                            %(minRes)s
                            %(maxRes)s
                          });''' % {"layerId": layerId, "url": url,
                                    "layerAttr": layerAttr, "format": format,
                                    "n": layerName, "name": layer.name(),
                                    "opacity": opacity, "style": style,
                                    "minRes": minResolution,
                                    "maxRes": maxResolution}


def getWMS(source, layer, layerAttr, layerName, opacity, minResolution,
           maxResolution):
    layers = re.search(r"layers=(.*?)(?:&|$)", source).groups(0)[0]
    url = re.search(r"url=(.*?)(?:&|$)", source).groups(0)[0]
    metadata = layer.metadata()
    needle = "<tr><td>%s</td><td>(.+?)</td>" % (
        QCoreApplication.translate("QgsWmsProvider",
                                   "WMS Version"))
    result = re.search(needle, metadata)
    if result:
        version = result.group(1)
    else:
        version = ""
    return '''var lyr_%(n)s = new ol.layer.Tile({
                            source: new ol.source.TileWMS(({
                              url: "%(url)s",
    attributions: [new ol.Attribution({html: '%(layerAttr)s'})],
                              params: {
                                "LAYERS": "%(layers)s",
                                "TILED": "true",
                                "VERSION": "%(version)s"},
                            })),
                            title: "%(name)s",
                            opacity: %(opacity)f,
                            %(minRes)s
                            %(maxRes)s
                          });''' % {"layers": layers, "url": url,
                                    "layerAttr": layerAttr,
                                    "n": layerName, "name": layer.name(),
                                    "version": version, "opacity": opacity,
                                    "minRes": minResolution,
                                    "maxRes": maxResolution}


def getRaster(iface, layer, layerName, layerAttr, minResolution, maxResolution,
              matchCRS):
    crsSrc = layer.crs()
    projectCRS = iface.mapCanvas().mapSettings().destinationCrs()
    if not (matchCRS and crsSrc == projectCRS):
        print 1
        mapCRS = "EPSG:3857"
        crsDest = QgsCoordinateReferenceSystem(3857)

        xform = QgsCoordinateTransform(crsSrc, crsDest)
        extentRep = xform.transform(layer.extent())
    else:
        mapCRS = projectCRS.authid()
        extentRep = layer.extent()

    sExtent = "[%f, %f, %f, %f]" % (extentRep.xMinimum(), extentRep.yMinimum(),
                                    extentRep.xMaximum(), extentRep.yMaximum())

    return '''var lyr_%(n)s = new ol.layer.Image({
                            opacity: 1,
                            title: "%(name)s",
                            %(minRes)s
                            %(maxRes)s
                            source: new ol.source.ImageStatic({
                               url: "./layers/%(n)s.png",
    attributions: [new ol.Attribution({html: '%(layerAttr)s'})],
                                projection: '%(mapCRS)s',
                                alwaysInRange: true,
                                imageExtent: %(extent)s
                            })
                        });''' % {"n": layerName,
                                  "extent": sExtent,
                                  "name": layer.name(),
                                  "minRes": minResolution,
                                  "maxRes": maxResolution,
                                  "mapCRS": mapCRS,
                                  "layerAttr": layerAttr}
