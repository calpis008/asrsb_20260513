import os
import glob
import json
import subprocess
import math
import shutil

# 設定路徑
SRC_DIR = "/Users/miaoch/Documents/馬太鞍溪S2衛星時序監控/ASRSB_Disaster_Monitor_2026"
PROJECT_DIR = "/Users/miaoch/Documents/claude code/Mataian_S2_Viewer"
IMG_OUT_DIR = os.path.join(PROJECT_DIR, "images")

# QGIS GDAL 與環境變數設定
GDAL_INFO = "/Applications/QGIS.app/Contents/MacOS/gdalinfo"
GDAL_TRANS = "/Applications/QGIS.app/Contents/MacOS/gdal_translate"
GDAL_DEM = "/Applications/QGIS.app/Contents/MacOS/gdaldem"
GDAL_TILES = "/Applications/QGIS.app/Contents/MacOS/gdal2tiles.py"

# 設定 PROJ 資源路徑以解決 proj.db 缺失問題
os.environ["PROJ_LIB"] = "/Applications/QGIS.app/Contents/Resources/qgis/proj"
os.environ["GDAL_DATA"] = "/Applications/QGIS.app/Contents/Resources/qgis/gdal"

os.makedirs(IMG_OUT_DIR, exist_ok=True)

def create_ndwi_color_txt():
    """建立修正後的 NDWI 彩色色階"""
    color_path = os.path.join(PROJECT_DIR, "ndwi_colors.txt")
    content = """
-1.0  139  69  19
-0.5  160  82  45
-0.1  244 164  96
 0.05 245 222 179
 0.11 230 230 230
 0.115 100 149 237
 0.4   30 144 255
 0.6    0   0 139
 1.0    0   0  50
"""
    with open(color_path, "w") as f:
        f.write(content.strip())
    return color_path

def twd97_to_wgs84(x, y):
    a, b = 6378137.0, 6356752.314245
    long0, k0, dx = math.radians(121), 0.9999, 250000
    e = math.sqrt(1 - (b**2) / (a**2))
    e2 = (e**2) / (1 - e**2)
    x -= dx
    M = y / k0
    mu = M / (a * (1 - (e**2)/4 - 3*(e**4)/64 - 5*(e**6)/256))
    e1 = (1 - math.sqrt(1 - e**2)) / (1 + math.sqrt(1 - e**2))
    j1, j2, j3, j4 = (3*e1/2 - 27*e1**3/32), (21*e1**2/16 - 55*e1**4/32), (151*e1**3/96), (1097*e1**4/512)
    fp = mu + j1*math.sin(2*mu) + j2*math.sin(4*mu) + j3*math.sin(6*mu) + j4*math.sin(8*mu)
    c1, t1 = e2 * math.cos(fp)**2, math.tan(fp)**2
    r1 = a * (1 - e**2) / (1 - e**2 * math.sin(fp)**2)**1.5
    n1 = a / math.sqrt(1 - e**2 * math.sin(fp)**2)
    d = x / (n1 * k0)
    q1 = d - (1 + 2*t1 + c1) * d**3 / 6 + (5 - 2*c1 + 28*t1 - 3*c1**2 + 8*e2 + 24*t1**2) * d**5 / 120
    lat = fp - (n1 * math.tan(fp) / r1) * (d**2 / 2 - (5 + 3*t1 + 10*c1 - 4*c1**2 - 9*e2) * d**4 / 24 + (61 + 90*t1 + 298*c1 + 45*t1**2 - 252*e2 - 3*c1**2) * d**6 / 720)
    lon = long0 + q1 / math.cos(fp)
    return [math.degrees(lat), math.degrees(lon)]

def get_bounds(file_path):
    try:
        cmd = [GDAL_INFO, "-json", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        corner = info.get("cornerCoordinates")
        if corner:
            sw_twd, ne_twd = corner.get("lowerLeft"), corner.get("upperRight")
            return [twd97_to_wgs84(sw_twd[0], sw_twd[1]), twd97_to_wgs84(ne_twd[0], ne_twd[1])]
    except: pass
    return [[23.645, 121.365], [23.705, 121.435]]

def build_viewer():
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*.tif")))
    if not files: return
    
    color_txt = create_ndwi_color_txt()
    data_list = []
    global_bounds = get_bounds(files[0])

    for f in files:
        name = os.path.basename(f)
        png_name = name.replace(".tif", ".png")
        png_path = os.path.join(IMG_OUT_DIR, png_name)
        img_type = "NDWI" if "NDWI" in name else "SWIR"
        date_str = name.split('_')[-1].replace(".tif", "")
        
        # 1. 產生 PNG
        print(f"處理: {png_name}")
        if img_type == "NDWI":
            cmd = [GDAL_DEM, "color-relief", f, color_txt, png_path, "-of", "PNG"]
        else:
            cmd = [GDAL_TRANS, "-of", "PNG", "-ot", "Byte", "-scale", "-exponent", "0.6", f, png_path]
        subprocess.run(cmd, check=True)
        
        # 2. 核心優化：產生 TMS 圖磚
        tiles_subdir = f"tiles_{img_type}_{date_str}"
        tiles_abs_path = os.path.join(IMG_OUT_DIR, tiles_subdir)
        
        if not os.path.exists(tiles_abs_path):
            print(f"[{date_str}] 切圖中...")
            cmd_tiles = [GDAL_TILES, "-z", "12-17", "-w", "none", "-p", "mercator", png_path, tiles_abs_path]
            subprocess.run(cmd_tiles, check=True)
            
        data_list.append({
            "type": img_type, 
            "date": date_str, 
            "tiles": f"images/{tiles_subdir}/{{z}}/{{x}}/{{y}}.png"
        })

    html_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>馬太鞍溪衛星監控 (TMS 高速版)</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        body, html { margin: 0; padding: 0; height: 100%; overflow: hidden; background: #000; color: #fff; font-family: sans-serif; }
        .container { display: flex; flex-direction: column; height: 100vh; }
        .view-pane { position: relative; flex: 1; overflow: hidden; background: #111; }
        #pane-top { border-bottom: 4px solid #444; }
        #map-top, #map-bottom { width: 100%; height: 100%; }
        .resizer { height: 14px; background: #333; cursor: row-resize; z-index: 5000; display: flex; align-items: center; justify-content: center; border-top: 1px solid #555; }
        .resizer-handle { width: 60px; height: 5px; background: #777; border-radius: 3px; }
        .overlay-label { position: absolute; top: 20px; left: 20px; background: rgba(0,0,0,0.9); padding: 10px 20px; border-radius: 8px; z-index: 2000; font-weight: bold; border-left: 6px solid #00ff96; }
        .timeline-box { position: absolute; bottom: 40px; left: 50%; transform: translateX(-50%); background: rgba(0, 255, 150, 1); color: #000; padding: 15px 60px; border-radius: 80px; z-index: 6000; font-size: 42px; font-weight: 900; box-shadow: 0 20px 60px rgba(0,0,0,1); }
        .playback-controls { position: absolute; bottom: 45px; right: 45px; z-index: 6000; display: flex; gap: 20px; }
        .btn { background: #222; color: #fff; border: 2px solid #444; padding: 16px 32px; border-radius: 15px; cursor: pointer; font-size: 18px; font-weight: bold; }
        .btn.active { color: #00ff96; border-color: #00ff96; box-shadow: 0 0 30px rgba(0,255,150,0.5); }
        .legend { position: absolute; bottom: 20px; left: 20px; background: rgba(0,0,0,0.9); padding: 15px; border-radius: 10px; font-size: 14px; z-index: 2000; display: flex; flex-direction: column; gap: 8px; border: 1px solid #444; }
        .legend-item { display: flex; align-items: center; gap: 12px; }
        .color-box { width: 20px; height: 20px; border-radius: 4px; border: 1px solid #fff; }
    </style>
</head>
<body>
    <div class="container">
        <div id="pane-top" class="view-pane"><div id="map-top"></div><div class="overlay-label">NDWI (彩色偵測)</div>
            <div class="legend">
                <div class="legend-item"><div class="color-box" style="background:#00008b"></div> 水體 (NDWI > 0.115)</div>
                <div class="legend-item"><div class="color-box" style="background:#f5deb3"></div> 裸露地/河床 (-0.1 ~ 0.115)</div>
                <div class="legend-item"><div class="color-box" style="background:#8b4513"></div> 乾燥陸地/植被</div>
            </div>
        </div>
        <div class="resizer" id="drag-handle"><div class="resizer-handle"></div></div>
        <div id="pane-bottom" class="view-pane"><div id="map-bottom"></div><div class="overlay-label">SWIR (短波紅外)</div></div>
    </div>
    <div class="timeline-box" id="current-date">載入中...</div>
    <div class="playback-controls">
        <button class="btn" onclick="prevStep()">◀</button>
        <button class="btn active" id="playBtn" onclick="togglePlay()">暫停</button>
        <button class="btn" onclick="nextStep()">▶</button>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const imageData = """ + json.dumps(data_list) + """;
        const mapBounds = """ + json.dumps(global_bounds) + """;
        const dates = [...new Set(imageData.map(d => d.date))].sort();
        
        const mapTop = L.map('map-top', { zoomControl: false }).fitBounds(mapBounds);
        const mapBottom = L.map('map-bottom', { zoomControl: false }).fitBounds(mapBounds);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { opacity: 0.5 }).addTo(mapTop);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { opacity: 0.5 }).addTo(mapBottom);

        function syncMaps(source, target) { target.setView(source.getCenter(), source.getZoom(), { animate: false }); }
        mapTop.on('drag zoom', () => syncMaps(mapTop, mapBottom));
        mapBottom.on('drag zoom', () => syncMaps(mapBottom, mapTop));

        const resizer = document.getElementById('drag-handle'), topPane = document.getElementById('pane-top');
        let isDragging = false;
        resizer.addEventListener('mousedown', () => isDragging = true);
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const percentage = (e.clientY / window.innerHeight) * 100;
            if (percentage > 10 && percentage < 90) {
                topPane.style.flex = `0 0 ${percentage}%`;
                mapTop.invalidateSize(); mapBottom.invalidateSize();
            }
        });
        document.addEventListener('mouseup', () => isDragging = false);

        let layers = { NDWI: {}, SWIR: {} };
        imageData.forEach(item => {
            // 切換為 TileLayer 以優化效能
            const layer = L.tileLayer(item.tiles, { opacity: 0, zIndex: 1000, tms: true });
            layers[item.type][item.date] = layer;
            layer.addTo(item.type === 'NDWI' ? mapTop : mapBottom);
        });

        let currentIndex = 0, isPlaying = true, timer = null;
        function updateFrame() {
            const date = dates[currentIndex];
            document.getElementById('current-date').innerText = date;
            for (let type in layers) {
                for (let d in layers[type]) layers[type][d].setOpacity(0);
                if (layers[type][date]) layers[type][date].setOpacity(1);
            }
        }
        function nextStep() { currentIndex = (currentIndex + 1) % dates.length; updateFrame(); }
        function prevStep() { currentIndex = (currentIndex - 1 + dates.length) % dates.length; updateFrame(); }
        function togglePlay() {
            isPlaying = !isPlaying;
            document.getElementById('playBtn').innerText = isPlaying ? '暫停' : '播放';
            document.getElementById('playBtn').classList.toggle('active', isPlaying);
            isPlaying ? startTimer() : stopTimer();
        }
        function startTimer() { if (timer) clearInterval(timer); timer = setInterval(nextStep, 1000); }
        function stopTimer() { clearInterval(timer); timer = null; }
        updateFrame(); startTimer();
    </script>
</body>
</html>
    """
    with open(os.path.join(PROJECT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"完成! 圖磚系統已就緒，請重新執行並推送到 GitHub。")

if __name__ == "__main__":
    build_viewer()
