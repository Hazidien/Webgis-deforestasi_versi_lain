// ================================================================
// GeoAI Deforestation WebGIS reference script
// ================================================================
// Keep this file as the original GEE workflow for reproducibility.
// Add your own ROI geometry before running it in the GEE Code Editor.
var roi = /* color: #0b4a8b */ ee.Geometry.Polygon([[[112.60,-7.05],[112.60,-7.35],[112.95,-7.35],[112.95,-7.05],[112.60,-7.05]]]);
var l4 = ee.ImageCollection('LANDSAT/LT04/C02/T1_L2');
var l5 = ee.ImageCollection('LANDSAT/LT05/C02/T1_L2');
var l8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2');
var l9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2');

// ===========================
// YEAR LIST
// ===========================
var yearList = [1990, 1995, 2000, 2005, 2010, 2015, 2020];

// ===========================
// FUNCTION FILTER
// ===========================
function filterCol(col, roi, date) {
  return col.filterDate(date[0], date[1]).filterBounds(roi);
}

// ===========================
// CLOUD MASK + COLLECTIONS
// ===========================
function cloudMaskTm(image) {
  var qa = image.select('QA_PIXEL');
  var dilated = 1 << 1;
  var cloud = 1 << 3;
  var shadow = 1 << 4;
  var mask = qa.bitwiseAnd(dilated).eq(0)
    .and(qa.bitwiseAnd(cloud).eq(0))
    .and(qa.bitwiseAnd(shadow).eq(0));
  return image.select(['SR_B1','SR_B2','SR_B3','SR_B4','SR_B5','SR_B7'],['B2','B3','B4','B5','B6','B7'])
    .updateMask(mask).multiply(0.0000275).add(-0.2);
}
function cloudMaskOli(image) {
  var qa = image.select('QA_PIXEL');
  var dilated = 1 << 1;
  var cirrus = 1 << 2;
  var cloud = 1 << 3;
  var shadow = 1 << 4;
  var mask = qa.bitwiseAnd(dilated).eq(0)
    .and(qa.bitwiseAnd(cirrus).eq(0))
    .and(qa.bitwiseAnd(cloud).eq(0))
    .and(qa.bitwiseAnd(shadow).eq(0));
  return image.select(['SR_B2','SR_B3','SR_B4','SR_B5','SR_B6','SR_B7'],['B2','B3','B4','B5','B6','B7'])
    .updateMask(mask).multiply(0.0000275).add(-0.2);
}
function landsat457(roi, date) {
  return filterCol(l4, roi, date).merge(filterCol(l5, roi, date)).map(cloudMaskTm).median().clip(roi);
}
function landsat89(roi, date) {
  return filterCol(l8, roi, date).merge(filterCol(l9, roi, date)).map(cloudMaskOli).median().clip(roi);
}

// ===========================
// GENERATE IMAGE PER YEAR
// ===========================
var forestCol = ee.ImageCollection(yearList.map(function(year) {
  var start = ee.Date.fromYMD(year - 1, 1, 1);
  var end = ee.Date.fromYMD(year + 1, 12, 31);
  var date = [start, end];
  var landsat = year < 2014 ? landsat457 : landsat89;
  var image = landsat(roi, date);
  var bandMap = { NIR: image.select('B5'), SWIR: image.select('B7') };
  var vi = image.expression('(NIR - SWIR) / (NIR + SWIR)', bandMap).rename('VI');
  var forest = vi.gt(0.7).selfMask().rename('forest').toUint16();
  var forestArea = forest.multiply(ee.Image.pixelArea().divide(10000)).rename('area');
  return forest.multiply(year).toUint16().addBands(forestArea).set('year', year).set('system:time_start', start);
}));

var vis = {forest_class_values: yearList, forest_class_palette: ['4B0082','B22222','FF4500','FFD700','FFFF00','ADFF2F','228B22']};
var forestYear = forestCol.select('forest').max().set(vis).clip(roi);
Map.addLayer(forestYear, {}, 'Forest Year');

var forestAreaChart = ui.Chart.image.series({imageCollection: forestCol.select('area'),region: roi,reducer: ee.Reducer.sum(),scale: 90,xProperty: 'year'})
  .setChartType('AreaChart').setOptions({title:'Forest Area 1990 - 2020',vAxis:{title:'Area (Ha)'},hAxis:{title:'Year'}});
print(forestAreaChart);

var labelList = ['1990 - 1995','1995 - 2000','2000 - 2005','2005 - 2010','2010 - 2015','2015 - 2020','Current forest'];
var legendPanel = ui.Panel([ui.Label('Deforestation',{fontWeight:'bold'})],ui.Panel.Layout.flow('vertical'),{position:'bottom-left'});
Map.add(legendPanel);
labelList.map(function(label,idx){legendPanel.add(ui.Panel([ui.Label('',{backgroundColor:vis.forest_class_palette[idx],width:'30px',height:'20px'}),ui.Label(label,{height:'20px'})],ui.Panel.Layout.flow('horizontal')));});

Export.image.toDrive({image:forestYear,description:'Forest_Year_1990_2020',scale:30,region:roi,fileFormat:'GeoTIFF',maxPixels:1e13});
