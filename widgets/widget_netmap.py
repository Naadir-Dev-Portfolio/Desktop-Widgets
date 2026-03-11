# netmap_widget.py
# Desktop map widget: precise SVG pins, green pin for your WAN IP.
# Features: CSV Logging, Privacy Toggles, Overlay Controls.
# Default State: SILENT (No scanning, no API, no logging).
from __future__ import annotations
import os, sys, time, json, ipaddress, sqlite3, queue, threading, requests, psutil, subprocess, platform, socket, csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QPoint, QTimer, Qt, QEvent
from PyQt6.QtGui import QMoveEvent, QMouseEvent
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# ---------------- Configuration ----------------
# SET THESE TO TRUE TO ENABLE FEATURES ON STARTUP
DEFAULT_SCANNER_ON = False
DEFAULT_API_ON     = False
DEFAULT_LOG_ON     = False

# ---------------- UI Constants ----------------
START_WIDTH  = 740
START_HEIGHT = 300
START_TOP_PX = 435
START_RIGHT_MARGIN_PX = 390
WINDOW_OPACITY = 140   # out of 255, matching suite

# Overlay button positioning (% of widget width from left edge)
# Increase to move buttons toward center, decrease to move toward left edge
OVERLAY_LEFT_PCT = 0.18

REFRESH_SEC = 0.5
CACHE_TTL_SEC = 30*24*3600

DB_FILE = "geo_cache.sqlite3"
MMDB_PATH = os.getenv("GEOLITE2_MMDB") or os.path.join(os.path.dirname(__file__), "GeoLite2-City.mmdb")
LAND_OPACITY_DEFAULT = 0.45
BLOCKLIST_FILE = "blocklist.txt"
ENABLE_AUTO_BLOCK = True

# Geo resolver threading
RESOLVER_WORKERS = 4
IP_API_MIN_INTERVAL = 1.4

# Pins
PIN_BASE_RADIUS = 9.5
PIN_MIN_RADIUS  = 8.5
PIN_MAX_RADIUS  = 14.0
ANIMATE_RECENT_SEC = 6.0

# WAN IP refresh
MYIP_REFRESH_SEC = 30

# CSV Logging
CSV_FOLDER = "connections"
CSV_MAX_ROWS = 1_000_000

def ts(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def is_public_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast)
    except ValueError:
        return False

def proc_name(pid: int|None) -> str:
    if not pid: return "-"
    try: return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied): return f"pid:{pid}"

# ---------------- Position persistence ----------------
class PositionStore:
    def __init__(self, app_id: str):
        p = Path(__file__).resolve()
        self.path = p.parent / "widget_positions" / f"{p.stem}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.app_id = app_id

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            v = data.get(self.app_id)
            if isinstance(v, dict) and "x" in v and "y" in v:
                return int(v["x"]), int(v["y"])
        except Exception:
            pass
        return None

    def save(self, x: int, y: int):
        try:
            data = {}
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            data[self.app_id] = {"x": int(x), "y": int(y)}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

# ---------------- CSV Logger ----------------
class CsvLogger(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.queue: queue.Queue[dict | None] = queue.Queue()
        self.running = True
        self.logging_enabled = DEFAULT_LOG_ON
        self.folder = Path(__file__).parent / CSV_FOLDER
        self.folder.mkdir(exist_ok=True)
        
        self.current_file = None
        self.f_handle = None
        self.writer = None
        self.current_rows = 0
        
        self.headers = [
            "Time_Initiated", "Process", "PID", "Local_IP", "Local_Port", 
            "Remote_IP", "Remote_Port", "City", "Country", "Latitude", "Longitude",
            "ISP_Org", "ASN", "RDNS", "Timezone", "Malicious"
        ]

    def set_active(self, active: bool):
        self.logging_enabled = active

    def log_connection(self, data: dict):
        """Always enqueue — the writer thread respects logging_enabled."""
        self.queue.put(data)

    def stop(self):
        self.running = False
        self.queue.put(None)
        self.join()

    def _get_active_file(self):
        files = sorted(list(self.folder.glob("*.csv")))
        if files:
            latest = files[-1]
            try:
                with open(latest, 'r', encoding='utf-8') as f:
                    count = sum(1 for _ in f)
                if count < CSV_MAX_ROWS:
                    return latest, count
            except Exception:
                pass 
        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S.csv")
        return self.folder / name, 0

    def run(self):
        while self.running:
            try:
                # Wait for an item before opening a file
                if not self.f_handle:
                    try:
                        item = self.queue.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if item is None: break

                    # Drop the item if logging is off (checked at write time)
                    if not self.logging_enabled:
                        continue

                    # Open the CSV file, then fall through to write this item
                    path, rows = self._get_active_file()
                    try:
                        self.f_handle = open(path, 'a', newline='', encoding='utf-8')
                        self.writer = csv.writer(self.f_handle)
                        self.current_rows = rows
                        self.current_file = path
                        if self.f_handle.tell() == 0:
                            self.writer.writerow(self.headers)
                            self.f_handle.flush()
                            self.current_rows = 1
                    except Exception:
                        self.f_handle = None
                        time.sleep(1); continue
                else:
                    # File already open — get next item
                    try:
                        item = self.queue.get(timeout=0.5)
                    except queue.Empty:
                        if self.f_handle: self.f_handle.flush()
                        # If logging was turned off, close the handle so we
                        # re-check logging_enabled on next iteration
                        if not self.logging_enabled:
                            try: self.f_handle.close()
                            except: pass
                            self.f_handle = None
                        continue

                    if item is None: break

                    # Respect the toggle: if logging just got turned off, drop item
                    if not self.logging_enabled:
                        continue

                # ── Write the row ──
                if self.current_rows >= CSV_MAX_ROWS:
                    try: self.f_handle.close()
                    except: pass
                    self.f_handle = None
                    self.queue.put(item) 
                    continue

                try:
                    row = [
                        item.get("started_str"), item.get("proc"), item.get("pid"),
                        item.get("l_ip"), item.get("l_port"), item.get("ip"), item.get("r_port"),
                        item.get("city"), item.get("cc"), item.get("lat"), item.get("lon"),
                        item.get("org"), item.get("asn"), item.get("rev"), item.get("tz"),
                        "Yes" if item.get("alert") else "No"
                    ]
                    self.writer.writerow(row)
                    self.f_handle.flush()
                    self.current_rows += 1
                except Exception:
                    try: self.f_handle.close() 
                    except: pass
                    self.f_handle = None
                    self.queue.put(item)

            except Exception:
                time.sleep(1)
        
        if self.f_handle:
            try: self.f_handle.close()
            except: pass

# ---------------- Geo Resolver ----------------
@dataclass
class Geo:
    ip: str; lat: float; lon: float
    city: str|None; cc: str|None; org: str|None; asn: str|None
    tz: str|None; rev: str|None; source: str

class GeoResolver(QtCore.QObject):
    resolved = QtCore.pyqtSignal(str, object)

    def __init__(self, db_path=DB_FILE, mmdb_path=MMDB_PATH, parent=None):
        super().__init__(parent)
        self.allow_external = DEFAULT_API_ON
        self.mmdb = None
        if mmdb_path and os.path.exists(mmdb_path):
            try:
                import geoip2.database
                self.mmdb = geoip2.database.Reader(mmdb_path)
            except Exception:
                self.mmdb = None
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._ensure_schema()
        self.mem_cache: dict[str, tuple[float, Geo]] = {}

        self.q: "queue.Queue[str]" = queue.Queue()
        self.pending: set[str] = set()
        self.stop_event = threading.Event()
        self.workers: list[threading.Thread] = []
        for i in range(RESOLVER_WORKERS):
            t = threading.Thread(target=self.worker, args=(i,), daemon=True)
            t.start()
            self.workers.append(t)

        self._last_http_lock = threading.Lock()
        self._last_http_time = 0.0

    def set_external_allowed(self, allowed: bool):
        self.allow_external = allowed

    def _ensure_schema(self):
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS geo_cache(
            ip TEXT PRIMARY KEY, lat REAL, lon REAL, city TEXT, cc TEXT, org TEXT, ts INTEGER,
            asn TEXT, tz TEXT, rev TEXT)""")
        self.conn.commit()

    def stop(self):
        self.stop_event.set()
        try:
            for _ in self.workers: self.q.put_nowait("__STOP__")
        except Exception: pass
        for t in self.workers:
            try: t.join(timeout=1.0)
            except Exception: pass
        try: self.conn.close()
        except Exception: pass
        if self.mmdb:
            try: self.mmdb.close()
            except Exception: pass

    @QtCore.pyqtSlot(str)
    def resolve(self, ip: str):
        if not is_public_ip(ip):
            self.resolved.emit(ip, None); return
        now = time.time()
        hit = self.mem_cache.get(ip)
        if hit and hit[0] > now:
            self.resolved.emit(ip, hit[1]); return
        row = self.conn.execute("SELECT lat,lon,city,cc,org,asn,tz,rev,ts FROM geo_cache WHERE ip=?", (ip,)).fetchone()
        if row:
            lat, lon, city, cc, org, asn, tz, rev, ts_cached = row
            if (ts_cached or 0)+CACHE_TTL_SEC > now and lat is not None and lon is not None:
                g = Geo(ip, lat, lon, city, cc, org, asn, tz, rev, "cache")
                self.mem_cache[ip] = (now+CACHE_TTL_SEC, g)
                self.resolved.emit(ip, g); return
        if ip not in self.pending:
            self.pending.add(ip); self.q.put(ip)

    def worker(self, worker_id: int):
        sess = requests.Session()
        while not self.stop_event.is_set():
            try:
                ip = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if ip == "__STOP__": break
            g = None

            # 1) MaxMind / Local
            if self.mmdb and g is None:
                try:
                    r = self.mmdb.city(ip)
                    if r and r.location and r.location.latitude is not None:
                        rev = None
                        try: rev = socket.gethostbyaddr(ip)[0]
                        except Exception: pass
                        asn = None
                        try:
                            asn_db = os.path.join(os.path.dirname(MMDB_PATH), "GeoLite2-ASN.mmdb")
                            if os.path.exists(asn_db):
                                import geoip2.database
                                with geoip2.database.Reader(asn_db) as rd:
                                    ar = rd.asn(ip)
                                    if ar and ar.autonomous_system_number:
                                        asn = f"AS{ar.autonomous_system_number} {ar.autonomous_system_organization or ''}".strip()
                        except Exception: pass
                        g = Geo(ip, r.location.latitude, r.location.longitude,
                                r.city.name or None, r.country.iso_code or None,
                                getattr(r.traits, "isp", None) or getattr(r.traits, "organization", None),
                                asn, r.location.time_zone or None, rev, "mmdb")
                except Exception:
                    g = None

            # 2) External APIs (Only if allowed)
            if self.allow_external and g is None:
                try:
                    j = sess.get(f"https://ipwho.is/{ip}", timeout=4).json()
                    if j.get("success"):
                        conn = j.get("connection") or {}
                        tz = (j.get("timezone") or {}).get("id") or j.get("timezone")
                        g = Geo(ip, float(j["latitude"]), float(j["longitude"]),
                                j.get("city"), j.get("country_code"),
                                conn.get("isp") or conn.get("org") or j.get("org"),
                                f"AS{conn.get('asn')}" if conn.get('asn') else None,
                                tz, j.get("reverse"), "ipwho.is")
                except Exception:
                    g = None

                if g is None:
                    wait = 0.0
                    with self._last_http_lock:
                        now = time.time()
                        wait = max(0.0, self._last_http_time + IP_API_MIN_INTERVAL - now)
                        if wait == 0.0:
                            self._last_http_time = now
                    if wait: time.sleep(wait)
                    try:
                        j = sess.get(
                            f"http://ip-api.com/json/{ip}?fields=status,lat,lon,city,countryCode,org,as,timezone,reverse",
                            timeout=5).json()
                        with self._last_http_lock:
                            self._last_http_time = time.time()
                        if j.get("status")=="success":
                            g = Geo(ip, j["lat"], j["lon"], j.get("city"),
                                    j.get("countryCode"), j.get("org"), j.get("as"),
                                    j.get("timezone"), j.get("reverse"), "ip-api")
                    except Exception:
                        g=None

            self.pending.discard(ip)
            if g:
                now = time.time()
                self.mem_cache[ip] = (now+CACHE_TTL_SEC, g)
                try:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO geo_cache (ip,lat,lon,city,cc,org,ts,asn,tz,rev) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (g.ip, g.lat, g.lon, g.city, g.cc, g.org, int(now), g.asn, g.tz, g.rev))
                    self.conn.commit()
                except Exception:
                    pass
            
            QtCore.QMetaObject.invokeMethod(self, "emitResolved",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, ip), QtCore.Q_ARG(object, g))

    @QtCore.pyqtSlot(str, object)
    def emitResolved(self, ip, g):
        self.resolved.emit(ip, g)

# ---------------- Connection monitor ----------------
class ConnWorker(QtCore.QThread):
    new_conn = QtCore.pyqtSignal(dict)
    closed_conn = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._seen: set[tuple] = set()
        self._first_seen: dict[tuple, float] = {}
        self._running = True
        self._paused = not DEFAULT_SCANNER_ON

    def set_paused(self, paused: bool):
        self._paused = paused

    def run(self):
        while self._running:
            if self._paused:
                self.msleep(500)
                continue

            current = set()
            try:
                for c in psutil.net_connections(kind="tcp"):
                    if not c.raddr or c.status != psutil.CONN_ESTABLISHED:
                        continue
                    l_ip = getattr(c.laddr, "ip", None); l_port = getattr(c.laddr, "port", None)
                    r_ip = getattr(c.raddr, "ip", None); r_port = getattr(c.raddr, "port", None)
                    key = (c.pid, l_ip, l_port, r_ip, r_port)
                    current.add(key)
                    if key not in self._seen:
                        self._first_seen[key] = time.time()
                        cid = f"{c.pid}|{l_ip}:{l_port}->{r_ip}:{r_port}"
                        self.new_conn.emit({
                            "id": cid, "pid": c.pid, "proc": proc_name(c.pid),
                            "l_ip": l_ip, "l_port": l_port, "r_ip": r_ip, "r_port": r_port,
                            "started": self._first_seen[key]
                        })
                for key in list(self._seen):
                    if key not in current:
                        pid, l_ip, l_port, r_ip, r_port = key
                        cid = f"{pid}|{l_ip}:{l_port}->{r_ip}:{r_port}"
                        self.closed_conn.emit(cid)
                        self._first_seen.pop(key, None)
                self._seen = current
            except Exception:
                pass
            self.msleep(int(REFRESH_SEC*1000))

    def stop(self):
        self._running = False

# ---------------- Blocker ----------------
class Blocker:
    def __init__(self):
        self.os = platform.system().lower()

    def block_ip(self, ip: str) -> bool:
        try:
            if self.os.startswith("win"):
                cmd = ["netsh","advfirewall","firewall","add","rule","name=NetMapBlock_"+ip,"dir=out","action=block","remoteip="+ip]
            elif self.os == "darwin":
                cmd = ["bash","-lc", f'echo "block drop out quick to {ip}" | sudo pfctl -f - && sudo pfctl -e']
            else:
                if shutil_which("nft"):
                    cmd = ["bash","-lc", f"sudo nft add rule inet filter output ip daddr {ip} drop || true"]
                else:
                    cmd = ["bash","-lc", f"sudo iptables -A OUTPUT -d {ip} -j DROP || true"]
            res = subprocess.run(cmd, capture_output=True)
            return res.returncode == 0
        except Exception:
            return False

def shutil_which(name):
    for p in os.getenv("PATH","").split(os.pathsep):
        fp = os.path.join(p, name)
        if os.path.isfile(fp) and os.access(fp, os.X_OK): return fp
        if os.name == "nt" and os.path.isfile(fp+".exe") and os.access(fp+".exe", os.X_OK): return fp+".exe"
        return None

# ---------------- HTML ----------------
HTML_TMPL = r"""
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script src="https://unpkg.com/d3@7"></script>
<script src="https://unpkg.com/topojson-client@3"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
  :root{
    --land:#b9c4d2;
    --land-stroke:#b9c4d233;
    --land-opacity:%(land_opacity)f;
  }
  html,body{height:100%%;margin:0;background:transparent}
  #wrap{position:relative;width:100%%;height:100%%;overflow:visible;background:transparent}
  svg{width:100%%;height:100%%;display:block;background:transparent}
  .land{fill:var(--land);fill-opacity:var(--land-opacity);stroke:var(--land-stroke);stroke-width:0.8}
  .pin{stroke:#00000088;stroke-width:1.0;pointer-events:auto}
  .pin.recent{animation:pulse 1.5s ease-out infinite}
  .pin.alert{filter:url(#glowYellow)}
  .pin.me{filter:url(#glowGreen)}
  .pin.default{filter:url(#glowRed)}
  @keyframes pulse{0%%{opacity:1} 60%%{opacity:0.65} 100%%{opacity:1}}
  .fade{transition:opacity .8s ease;opacity:0}
</style></head>
<body oncontextmenu="return false">
<div id="wrap">
  <svg id="map" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid meet">
    <defs>
      <filter id="glowRed" x="-50%%" y="-50%%" width="200%%" height="200%%">
        <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
        <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <filter id="glowGreen" x="-50%%" y="-50%%" width="200%%" height="200%%">
        <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
        <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <filter id="glowYellow" x="-50%%" y="-50%%" width="200%%" height="200%%">
        <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
        <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <g id="world"></g>
    <g id="pins"></g>
  </svg>
</div>
<script>
let svg=d3.select("#map"), g=svg.select("#world"), pinsLayer=svg.select("#pins");
let pins=new Map();
let meta=new Map();
let projection, path;

function pinRadius(){
  const bb = svg.node().getBoundingClientRect();
  const r = (bb.width/1200.0) * %(pin_base)f;
  return Math.max(%(pin_min)f, Math.min(%(pin_max)f, r));
}

function placePin(id, info){
  if(!projection) return;
  const xy = projection([info.lon, info.lat]); if(!xy) return;
  const r = pinRadius();

  let el = pins.get(id);
  if(!el){
    el = pinsLayer.append("circle")
      .attr("class", "pin")
      .on("mouseenter", (e)=>{ bridgeEnter(id, e.clientX, e.clientY); })
      .on("mousemove",  (e)=>{ bridgeMove(id, e.clientX, e.clientY); })
      .on("mouseleave", ()=>{ bridgeLeave(id); });
    pins.set(id, el);
  }else{
    el.classed("fade", false);
  }

  el.attr("cx", xy[0]).attr("cy", xy[1]).attr("r", r);

  if(info.me){ el.attr("fill", "#2ecc71").classed("me", true).classed("alert", false).classed("default", false); }
  else if(info.alert){ el.attr("fill", "#ffd400").classed("alert", true).classed("me", false).classed("default", false); }
  else { el.attr("fill", "#ff4545").classed("default", true).classed("alert", false).classed("me", false); }

  const now = Date.now()/1000;
  const recent = (now - (info.started||now)) <= %(animate_recent)s;
  el.classed("recent", recent);
}

function removePin(id){
  const el=pins.get(id); if(!el) return;
  el.classed("fade", true);
  setTimeout(()=>{ try{ el.remove(); }catch(e){} pins.delete(id); }, 850);
}

function reprojectAll(){
  if(!projection) return;
  for(const [id,info] of meta.entries()) placePin(id, info);
}

fetch("https://unpkg.com/world-atlas@2/land-110m.json").then(r=>r.json()).then(world=>{
  const land=topojson.feature(world, world.objects.land);
  projection=d3.geoEqualEarth().fitSize([1200,600], land);
  path=d3.geoPath(projection);
  g.append("path").datum(land).attr("class","land").attr("d",path);
  window.addEventListener('resize', reprojectAll);
  reprojectAll();
});

// Qt bridge
function bridgeEnter(id,cx,cy){ if(window.qtBridge) qtBridge.onHoverEnter(id, cx, cy); }
function bridgeMove(id,cx,cy){ if(window.qtBridge) qtBridge.onHoverMove(id, cx, cy); }
function bridgeLeave(id){ if(window.qtBridge) qtBridge.onHoverLeave(id); }

let qtBridge=null;
new QWebChannel(qt.webChannelTransport, (ch)=>{
  qtBridge = ch.objects.bridge; window.qtBridge = qtBridge;
  qtBridge.addHit.connect((payload)=>{
    const d=JSON.parse(payload);
    meta.set(d.id, d); placePin(d.id, d);
  });
  qtBridge.closeHit.connect((id)=>{ meta.delete(id); removePin(id); });
  qtBridge.setLandOpacity.connect((op)=>{ document.documentElement.style.setProperty('--land-opacity', op); });
});

  // ---- drag + context menu forwarding (works even when WebEngine swallows Qt mouse events) ----
  let __dragging = false;

  document.addEventListener('mousedown', (e)=>{
    if(!qtBridge) return;
    if(e.button === 0){
      __dragging = true;
      qtBridge.onDragStart(Math.floor(e.screenX), Math.floor(e.screenY));
      e.preventDefault();
    }
  }, {passive:false});

  document.addEventListener('mousemove', (e)=>{
    if(!qtBridge || !__dragging) return;
    qtBridge.onDragMove(Math.floor(e.screenX), Math.floor(e.screenY));
    e.preventDefault();
  }, {passive:false});

  document.addEventListener('mouseup', (e)=>{
    if(!qtBridge) return;
    if(__dragging && e.button === 0){
      __dragging = false;
      qtBridge.onDragEnd();
      e.preventDefault();
    }
  }, {passive:false});

  document.addEventListener('contextmenu', (e)=>{
    if(!qtBridge) return;
    qtBridge.onContextMenu(Math.floor(e.screenX), Math.floor(e.screenY));
    e.preventDefault();
    return false;
  }, {passive:false});

</script>
</body></html>
"""

# ---------------- Suite button style ----------------
SUITE_BUTTON_STYLE = """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #343434, stop:1 #1A1A1A);
        color: rgba(255,255,255,220);
        font: 10px 'Segoe UI';
        border: 1px solid #3d3d3d;
        border-radius: 6px;
        padding: 4px 12px;
        min-width: 36px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3e3e3e, stop:1 #252525);
        border: 1px solid #555555;
    }
    QPushButton:checked {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2e7d32, stop:1 #1b5e20);
        color: white;
        border: 1px solid #4caf50;
    }
    QPushButton:checked:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #388e3c, stop:1 #256427);
        border: 1px solid #66bb6a;
    }
    QPushButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1A1A1A, stop:1 #111111);
    }
"""

# ---------------- Tooltip ----------------
class TipWindow(QtWidgets.QFrame):
    def __init__(self, owner: QtWidgets.QWidget):
        super().__init__(
            owner,
            flags=QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Window
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        self.setObjectName("TipWindow")
        self.setStyleSheet("""
#TipWindow { background: rgba(54,69,79,0.92); border:1px solid #2a3240; border-radius:10px; }
QLabel { color:#E8EEF3; font:12px 'Segoe UI', sans-serif; background: transparent; }
""")
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(10,10,10,10)
        self.label = QtWidgets.QLabel(); self.label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.label.setWordWrap(True); lay.addWidget(self.label)
        self.hide()

        hide_from_taskbar_later(self)

    def show_info(self, html: str, global_pos: QtCore.QPoint):
        self.label.setText(html); self.adjustSize()
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        x = min(max(global_pos.x()+14, screen.left()), screen.right()-self.width()-4)
        y = min(max(global_pos.y()+14, screen.top()), screen.bottom()-self.height()-4)
        self.move(x,y); self.show()

# ---------------- Qt bridge ----------------
class Bridge(QtCore.QObject):
    addHit = QtCore.pyqtSignal(str)
    closeHit = QtCore.pyqtSignal(str)
    setLandOpacity = QtCore.pyqtSignal(float)

    @QtCore.pyqtSlot(str, int, int)
    def onHoverEnter(self, cid, client_x, client_y):
        self.parent().on_hover(cid, client_x, client_y)

    @QtCore.pyqtSlot(str, int, int)
    def onHoverMove(self, cid, client_x, client_y):
        self.parent().on_hover(cid, client_x, client_y)

    @QtCore.pyqtSlot(str)
    def onHoverLeave(self, cid):
        self.parent().on_hover_leave(cid)

    @QtCore.pyqtSlot(int, int)
    def onDragStart(self, screen_x: int, screen_y: int):
        self.parent().on_drag_start(screen_x, screen_y)

    @QtCore.pyqtSlot(int, int)
    def onDragMove(self, screen_x: int, screen_y: int):
        self.parent().on_drag_move(screen_x, screen_y)

    @QtCore.pyqtSlot()
    def onDragEnd(self):
        self.parent().on_drag_end()

    @QtCore.pyqtSlot(int, int)
    def onContextMenu(self, screen_x: int, screen_y: int):
        self.parent().on_context_menu(screen_x, screen_y)

# ---------------- My IP watcher ----------------
class MyIPWorker(QtCore.QThread):
    resolved_my_ip = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self.current_ip = None

    def run(self):
        while self._running:
            try:
                ip = None
                for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"):
                    try:
                        r = requests.get(url, timeout=3)
                        if r.ok:
                            ip = r.text.strip()
                            break
                    except Exception:
                        continue
                if ip and ip != self.current_ip and is_public_ip(ip):
                    self.current_ip = ip
                    self.resolved_my_ip.emit(ip)
            except Exception:
                pass
            for _ in range(int(MYIP_REFRESH_SEC*10)):
                if not self._running: break
                self.msleep(100)

    def stop(self):
        self._running = False

# ---------------- Hit-Test Root (painter-based translucency) ----------------
class _HitTestRoot(QtWidgets.QFrame):
    """
    A nearly-invisible QFrame painted via QPainter so that the rgba(0,0,0,10)
    tint composites correctly through WA_TranslucentBackground.
    Stylesheet-based background colours on child QFrames do NOT go through
    the translucent pipeline on Windows — they render as opaque black.
    Painting it ourselves fixes that.
    """
    _BG = QtGui.QColor(0, 0, 0, 2)          # rgba(0,0,0,10)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("")                 # clear any inherited style

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), self._BG)
        p.end()


# ---------------- Main Widget ----------------
class NetMap(QtWidgets.QWidget):
    APP_ID = "NetMap"

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, land_opacity=LAND_OPACITY_DEFAULT, stay_behind=True):
        super().__init__(parent)
        self.setObjectName("NetMap")
        self._embedded = parent is not None

        window_flags = QtCore.Qt.WindowType.FramelessWindowHint

        # Match the working widgets: real Window + bottom hint.
        # This keeps the widget on ONLY the virtual desktop where it was created.
        if not self._embedded:
            window_flags |= (
                QtCore.Qt.WindowType.WindowStaysOnBottomHint |
                QtCore.Qt.WindowType.Window
            )

        self.setWindowFlags(window_flags)

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Net Map")
        self.setWindowOpacity(WINDOW_OPACITY / 255.0)


        # persistence
        self.pos_store = PositionStore(self.APP_ID)

        # ── Position Locking System ──
        # Only user-initiated drags save position. OS glitches are rejected.
        self._locked_pos: QPoint | None = None    # last known-good position
        self._is_dragging: bool = False            # True while user is actively dragging
        self._drag_occurred: bool = False          # True if mouse actually moved during drag
        self._drag_offset: QPoint | None = None    # offset from window top-left to grab point

        if not self._embedded:
            self.resize(START_WIDTH, START_HEIGHT)
            self._restore_or_anchor()
            # Seed the locked position with wherever we just placed the window
            self._locked_pos = self.pos()

        # ── Hit-Test Root Architecture ──
        # A custom-painted QFrame with rgba(0,0,0,10) that catches ALL mouse
        # events in "empty" areas, preventing click-through to the desktop.
        # We paint it in paintEvent (not stylesheet) so it composites correctly
        # through the WA_TranslucentBackground pipeline.
        self.hit_root = _HitTestRoot(self)

        root_lay = QtWidgets.QVBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.addWidget(self.hit_root)

        # Container lives inside the hit-test root
        self.container = QtWidgets.QFrame(self.hit_root)
        self.container.setStyleSheet("background: transparent; border: none;")
        hit_lay = QtWidgets.QVBoxLayout(self.hit_root)
        hit_lay.setContentsMargins(0, 0, 0, 0)
        hit_lay.addWidget(self.container)

        self.web = QWebEngineView(self.container)
        self.web.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.web.setStyleSheet("background: transparent; border: none;")
        self.web.page().setBackgroundColor(QtGui.QColor(0, 0, 0, 0))
        self.web.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.NoContextMenu)
        self.web.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)

        cont_lay = QtWidgets.QVBoxLayout(self.container); cont_lay.setContentsMargins(0,0,0,0)
        cont_lay.addWidget(self.web)

        # ---------------- Floating Overlay Controls (3 buttons) ----------------
        self.overlay_frame = QtWidgets.QFrame(self.hit_root)
        self.overlay_frame.setStyleSheet(
            "QFrame { background: transparent; border: none; }"
        )
        olay = QtWidgets.QVBoxLayout(self.overlay_frame)
        olay.setContentsMargins(0, 0, 0, 0)
        olay.setSpacing(4)
        
        self.btn_scan = QtWidgets.QPushButton("Scan")
        self.btn_scan.setCheckable(True); self.btn_scan.setChecked(DEFAULT_SCANNER_ON)
        self.btn_scan.toggled.connect(self.toggle_scanner)
        self.btn_scan.setToolTip("Toggle scanning — shows pins on the map")
        self.btn_scan.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_scan.setStyleSheet(SUITE_BUTTON_STYLE)

        self.btn_log = QtWidgets.QPushButton("Log")
        self.btn_log.setCheckable(True); self.btn_log.setChecked(DEFAULT_LOG_ON)
        self.btn_log.toggled.connect(self.toggle_logging)
        self.btn_log.setToolTip("Toggle CSV logging of connections")
        self.btn_log.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_log.setStyleSheet(SUITE_BUTTON_STYLE)

        self.btn_openlog = QtWidgets.QPushButton("Open")
        self.btn_openlog.setToolTip("Open the latest CSV log file")
        self.btn_openlog.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_openlog.setStyleSheet(SUITE_BUTTON_STYLE)
        self.btn_openlog.clicked.connect(self.open_log_target)

        olay.addWidget(self.btn_scan)
        olay.addWidget(self.btn_log)
        olay.addWidget(self.btn_openlog)
        # -----------------------------------------------------------

        self.bridge = Bridge(self)
        self.channel = QWebChannel(self.web.page()); self.channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(self.channel)
        self.web.setHtml(HTML_TMPL % {
            "land_opacity": float(land_opacity),
            "pin_base": float(PIN_BASE_RADIUS),
            "pin_min": float(PIN_MIN_RADIUS),
            "pin_max": float(PIN_MAX_RADIUS),
            "animate_recent": float(ANIMATE_RECENT_SEC),
        })

        self.geo = GeoResolver(); self.geo.resolved.connect(self.on_geo)
        
        self.connw = ConnWorker()
        self.connw.new_conn.connect(self.on_new)
        self.connw.closed_conn.connect(self.on_closed)
        self.connw.start()
        
        self.blocker = Blocker()

        self.myipw = MyIPWorker(); self.myipw.resolved_my_ip.connect(self.on_my_ip); self.myipw.start()
        self.my_ip: str|None = None
        self._myip_geo: Geo|None = None

        self.conn_ip: dict[str, dict] = {}
        self.malicious: set[str] = set(); self.load_blocklist()
        
        # Start CSV Logger (Paused by default unless const is True)
        self.logger = CsvLogger()
        self.logger.start()

        self.tip = TipWindow(self)

        # Minimal event filter — only on web view for right-click menu
        self.web.installEventFilter(self)

        if not self._embedded:
            hide_from_taskbar_later(self)

    # --- Toggles ---
    def toggle_scanner(self, on: bool):
        """Scan button: enables/disables connection scanning AND external API geo resolution together."""
        self.connw.set_paused(not on)
        self.geo.set_external_allowed(on)
        # If turned ON, retry my IP geo if we don't have it yet
        if on and self.my_ip and not self._myip_geo:
            threading.Thread(target=self._resolve_myip_fast, args=(self.my_ip,), daemon=True).start()

    # ── showEvent: connect screenChanged once the native window handle exists ──
    def showEvent(self, event):
        super().showEvent(event)
        wh = self.windowHandle()
        if wh:
            try:
                wh.screenChanged.connect(
                    self._on_screen_changed,
                    Qt.ConnectionType.UniqueConnection
                )
            except Exception:
                pass
        # Ensure locked_pos is seeded (covers embedded + first-show)
        if self._locked_pos is None:
            self._locked_pos = self.pos()

    # ── Screen-change handler: DWM shuffles coordinates on topology change ──
    def _on_screen_changed(self, screen):
        """Force the window back to its locked position after a monitor change.
        Suppressed while the user is actively dragging — the drag-end will
        commit the final position instead."""
        if self._is_dragging:
            return
        if self._locked_pos is not None:
            locked = QPoint(self._locked_pos)          # copy
            QTimer.singleShot(100, lambda: self._snap_if_not_dragging(locked))

    def _snap_if_not_dragging(self, target: QPoint):
        """Secondary guard: if a drag started between the singleShot schedule
        and its execution, skip the snap."""
        if not self._is_dragging:
            self.move(target)
    
    def toggle_logging(self, on: bool):
        """Log button: toggles CSV writing. When turned ON, flushes all
        currently-tracked connections so nothing is missed."""
        self.logger.set_active(on)
        if on:
            self._flush_existing_connections_to_log()

    def _flush_existing_connections_to_log(self):
        """Write every currently-tracked connection (that has geo) to the CSV."""
        for cid, base in list(self.conn_ip.items()):
            g = base.get("_last_geo")
            if not g:
                continue
            ip = base["r_ip"]
            start_ts = base.get("started", time.time())
            start_str = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S")
            alert = base.get("_alert", False)
            log_data = {
                "started_str": start_str,
                "proc": base.get("proc", "-"),
                "pid": base.get("pid", ""),
                "l_ip": base.get("l_ip", ""),
                "l_port": base.get("l_port", ""),
                "ip": ip,
                "r_port": base.get("r_port", ""),
                "city": g.city or "",
                "cc": g.cc or "",
                "lat": f"{g.lat:.4f}",
                "lon": f"{g.lon:.4f}",
                "org": g.org or "",
                "asn": g.asn or "",
                "rev": g.rev or "",
                "tz": g.tz or "",
                "alert": alert
            }
            self.logger.log_connection(log_data)


    # Open log file
    def open_log_target(self):
        """Open the latest CSV log file, or the log folder if none exist yet."""
        try:
            folder = Path(__file__).parent / CSV_FOLDER
            folder.mkdir(exist_ok=True)

            # First try the logger's active file
            p = None
            if hasattr(self, "logger") and getattr(self.logger, "current_file", None):
                cf = Path(self.logger.current_file)
                if cf.exists():
                    p = cf

            # Fallback: find the most recently modified CSV in the folder
            if p is None:
                csvs = sorted(folder.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
                if csvs:
                    p = csvs[0]

            # Last resort: open the folder itself
            if p is None:
                p = folder

            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(p.resolve())))
        except Exception:
            pass

    # keep behind (Windows best-effort via Win32 — no sticky Qt flags)

    def load_blocklist(self):
        try:
            if os.path.exists(BLOCKLIST_FILE):
                with open(BLOCKLIST_FILE,"r", encoding="utf-8") as f:
                    for line in f:
                        ip = line.strip()
                        if ip and not ip.startswith("#"):
                            self.malicious.add(ip)
        except Exception: pass

    # --- Your IP ---
    @QtCore.pyqtSlot(str)
    def on_my_ip(self, ip: str):
        self.my_ip = ip
        self.geo.resolve(ip)
        threading.Thread(target=self._resolve_myip_fast, args=(ip,), daemon=True).start()

    def _resolve_myip_fast(self, ip: str):
        # We respect the external API toggle
        if not self.geo.allow_external: return

        g = None
        try:
            j = requests.get("https://ipinfo.io/json", timeout=4).json()
            if j.get("ip") and is_public_ip(j["ip"]):
                loc = j.get("loc")
                if loc:
                    lat_s, lon_s = loc.split(",")
                    g = Geo(ip=j["ip"], lat=float(lat_s), lon=float(lon_s),
                            city=j.get("city"), cc=j.get("country"),
                            org=j.get("org"), asn=None, tz=j.get("timezone"), rev=None, source="ipinfo")
        except Exception:
            g = None
        if g is None:
            try:
                k = requests.get(f"https://ipwho.is/{ip}", timeout=4).json()
                if k.get("success"):
                    conn = k.get("connection") or {}
                    tz = (k.get("timezone") or {}).get("id") or k.get("timezone")
                    g = Geo(ip=ip, lat=float(k["latitude"]), lon=float(k["longitude"]),
                            city=k.get("city"), cc=k.get("country_code"), org=conn.get("isp") or conn.get("org"),
                            asn=f"AS{conn.get('asn')}" if conn.get("asn") else None, tz=tz, rev=k.get("reverse"), source="ipwho.is-self")
            except Exception:
                g = None
        if g:
            QtCore.QMetaObject.invokeMethod(self, "_emit_myip_geo",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(object, g))

    @QtCore.pyqtSlot(object)
    def _emit_myip_geo(self, g: Geo):
        self._myip_geo = g
        payload = json.dumps({
            "id": "__myip__",
            "lat": g.lat, "lon": g.lon,
            "ip": g.ip, "city": g.city, "cc": g.cc, "org": g.org, "asn": g.asn, "tz": g.tz, "rev": g.rev,
            "proc": "Your IP", "l_ip": "-", "l_port": "-", "r_port": "-",
            "started": time.time(), "alert": False, "me": True
        })
        self.bridge.addHit.emit(payload)

    # --- Hover ---
    def on_hover(self, cid: str, client_x: int, client_y: int):
        if cid == "__myip__":
            info = self._myip_geo
            if not info: return
            parts = [
                "<div style='font-weight:600;margin-bottom:6px'>Your IP</div>",
                f"<div><b>IP</b> {info.ip}</div>",
                f"<div><b>Loc</b> {info.city or ''} {info.cc or ''}</div>",
                f"<div><b>Lat/Lon</b> {info.lat:.4f}, {info.lon:.4f}</div>",
                f"<div><b>ISP</b> {info.org or ''}</div>",
                f"<div><b>ASN</b> {info.asn or ''}</div>",
                f"<div><b>RDNS</b> {info.rev or ''}</div>",
                f"<div><b>TZ</b> {info.tz or ''}</div>",
            ]
            html = "".join(parts)
            gp = self.web.mapToGlobal(QtCore.QPoint(client_x, client_y))
            self.tip.show_info(html, gp)
            return

        base = self.conn_ip.get(cid)
        if not base: return
        info = base.get("_last_geo")
        if not info: return
        dur_s = max(0, int(time.time() - base.get("started", time.time())))
        dur = self.fmt_duration(dur_s)
        alert = base.get("_alert", False)
        parts = [
            f"<div style='font-weight:600;margin-bottom:6px'>{base.get('proc','-')}</div>",
            f"<div><b>IP</b> {info.ip}</div>",
            f"<div><b>Loc</b> {info.city or ''} {info.cc or ''}</div>",
            f"<div><b>Lat/Lon</b> {info.lat:.4f}, {info.lon:.4f}</div>",
            f"<div><b>ISP</b> {info.org or ''}</div>",
            f"<div><b>ASN</b> {info.asn or ''}</div>",
            f"<div><b>RDNS</b> {info.rev or ''}</div>",
            f"<div><b>TZ</b> {info.tz or ''}</div>",
            f"<div><b>Ports</b> {base.get('l_ip')}:{base.get('l_port')} → {info.ip}:{base.get('r_port')}</div>",
            f"<div><b>Duration</b> {dur}</div>",
        ]
        if alert: parts.append("<div style='margin-top:6px;color:#ffd400'><b>ALERT</b> Malicious destination</div>")
        html = "".join(parts)
        gp = self.web.mapToGlobal(QtCore.QPoint(client_x, client_y))
        self.tip.show_info(html, gp)

    def on_hover_leave(self, cid: str):
        self.tip.hide()

    # --- Connections ---
    @QtCore.pyqtSlot(dict)
    def on_new(self, info: dict):
        self.conn_ip[info["id"]] = info
        self.geo.resolve(info["r_ip"])

    @QtCore.pyqtSlot(str)
    def on_closed(self, cid: str):
        self.bridge.closeHit.emit(cid)
        self.conn_ip.pop(cid, None)

    @QtCore.pyqtSlot(str, object)
    def on_geo(self, ip: str, g: Geo|None):
        if not g: return

        if self.my_ip and ip == self.my_ip:
            self._emit_myip_geo(g)

        for cid, base in list(self.conn_ip.items()):
            if base["r_ip"] == ip:
                base["_last_geo"] = g
                alert = ip in self.malicious
                base["_alert"] = alert
                if alert and ENABLE_AUTO_BLOCK:
                    try: self.blocker.block_ip(ip)
                    except Exception: pass
                
                start_ts = base.get("started", time.time())
                start_str = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S")
                
                log_data = {
                    "started_str": start_str,
                    "proc": base.get("proc", "-"),
                    "pid": base.get("pid", ""),
                    "l_ip": base.get("l_ip", ""),
                    "l_port": base.get("l_port", ""),
                    "ip": ip,
                    "r_port": base.get("r_port", ""),
                    "city": g.city or "",
                    "cc": g.cc or "",
                    "lat": f"{g.lat:.4f}",
                    "lon": f"{g.lon:.4f}",
                    "org": g.org or "",
                    "asn": g.asn or "",
                    "rev": g.rev or "",
                    "tz": g.tz or "",
                    "alert": alert
                }
                self.logger.log_connection(log_data)

                payload = json.dumps({
                    "id": cid,
                    "lat": g.lat, "lon": g.lon,
                    "ip": ip, "city": g.city, "cc": g.cc, "org": g.org, "asn": g.asn, "tz": g.tz, "rev": g.rev,
                    "proc": base["proc"], "l_ip": base["l_ip"], "l_port": base["l_port"], "r_port": base["r_port"],
                    "started": start_ts,
                    "alert": alert, "me": False
                })
                self.bridge.addHit.emit(payload)

    def set_land_opacity(self, v: float):
        v = max(0.0, min(1.0, float(v)))
        self.bridge.setLandOpacity.emit(v)

    # ══════════════════════════════════════════════════════════════
    #  CENTRALIZED DRAG HELPERS  (only place that saves position)
    # ══════════════════════════════════════════════════════════════
    def _start_drag(self, global_pos: QPoint):
        """Begin a user-initiated drag. Records the grab offset."""
        self._is_dragging = True
        self._drag_occurred = False
        self._drag_offset = global_pos - self.frameGeometry().topLeft()

    def _do_drag(self, global_pos: QPoint):
        """Move the window while dragging. Does NOT save."""
        if self._drag_offset is None:
            return
        self._drag_occurred = True
        self.move(global_pos - self._drag_offset)

    def _end_drag(self):
        """Finish drag — save ONLY if the mouse actually moved the window."""
        was_dragging = self._is_dragging
        did_move = self._drag_occurred
        self._is_dragging = False
        self._drag_occurred = False
        self._drag_offset = None
        if was_dragging and did_move:
            pos = self.frameGeometry().topLeft()
            if self._is_position_visible(pos.x(), pos.y()):
                self._locked_pos = pos
                self.pos_store.save(pos.x(), pos.y())

    # ── Native mouse events for drag ──
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
            self._start_drag(gp)
        elif ev.button() == Qt.MouseButton.RightButton:
            gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
            self.show_context_menu(gp)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._is_dragging:
            gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
            self._do_drag(gp)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._end_drag()
        super().mouseReleaseEvent(ev)

    def eventFilter(self, obj, ev):
        """Minimal — only intercepts right-click on the web view."""
        if obj is self.web and ev.type() == QtCore.QEvent.Type.MouseButtonPress:
            btn = getattr(ev, "button", lambda: None)()
            if btn == QtCore.Qt.MouseButton.RightButton:
                gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
                self.show_context_menu(gp)
                return True
        return super().eventFilter(obj, ev)


    # ---- WebEngine JS-driven drag + context menu (Windows virtual-desktop safe, no nativeEvent) ----
    def on_drag_start(self, screen_x: int, screen_y: int):
        # Ignore drags started over overlay controls
        try:
            local = self.mapFromGlobal(QPoint(screen_x, screen_y))
            if self.overlay_frame.isVisible() and self.overlay_frame.geometry().contains(local):
                return
        except Exception:
            pass

        self._start_drag(QPoint(screen_x, screen_y))

    def on_drag_move(self, screen_x: int, screen_y: int):
        if not self._is_dragging:
            return
        self._do_drag(QPoint(screen_x, screen_y))

    def on_drag_end(self):
        if not self._is_dragging:
            return
        self._end_drag()

    def on_context_menu(self, screen_x: int, screen_y: int):
        # Right-click anywhere on the map
        self.show_context_menu(QtCore.QPoint(screen_x, screen_y))

    def show_context_menu(self, global_pos: QtCore.QPoint):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2b2b2b; color: #f0f0f0; border: 1px solid #3a3a3a; border-radius: 10px; padding: 6px; }
            QMenu::item { background-color: transparent; padding: 6px 12px; border-radius: 6px; }
            QMenu::item:selected { background-color: #3a3a3a; }
        """)
        act_close = menu.addAction("Close")
        act_close.triggered.connect(self.close)
        menu.exec(global_pos)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.web.resize(self.container.size())
        # Position overlay on map — left side, lower area
        self.overlay_frame.adjustSize()
        ow = self.overlay_frame.sizeHint().width()
        oh = self.overlay_frame.sizeHint().height()
        x = int(self.hit_root.width() * OVERLAY_LEFT_PCT)
        y = int(self.hit_root.height() * 0.58)
        y = min(y, self.hit_root.height() - oh - 6)
        self.overlay_frame.setGeometry(x, y, ow, oh)

    def _anchor_position(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        x = screen.right()-START_RIGHT_MARGIN_PX-START_WIDTH
        y = screen.top()+START_TOP_PX
        return x, y

    def _is_position_visible(self, x: int, y: int) -> bool:
        """True if at least 50x30 px of the widget is on any screen."""
        widget_rect = QtCore.QRect(x, y, self.width(), self.height())
        app = QtWidgets.QApplication.instance()
        if not app:
            return False
        for screen in app.screens():
            inter = widget_rect.intersected(screen.availableGeometry())
            if inter.width() >= 50 and inter.height() >= 30:
                return True
        return False

    def _restore_or_anchor(self):
        saved = self.pos_store.load()
        if saved and self._is_position_visible(*saved):
            self.move(*saved)
        else:
            self.move(*self._anchor_position())

    def moveEvent(self, event: QMoveEvent):
        """
        Position Locking — the core glitch protection.
        Only user-initiated drags are allowed through; OS-triggered moves
        (DWM ghost title bar, monitor re-index) are rejected or snapped back.
        """
        super().moveEvent(event)

        # During a user drag, just let the move happen (no save here).
        if self._is_dragging:
            return

        # No locked position yet (first show) — nothing to protect.
        if self._locked_pos is None:
            return

        current_pos = self.pos()

        # ── Massive coordinate jump (monitor re-index / negative coords) ──
        diff = current_pos - self._locked_pos
        manhattan = abs(diff.x()) + abs(diff.y())
        if manhattan > 100:
            # Completely ignore this garbage move — do NOT save.
            return

        # ── Ghost title-bar shift (DWM adds ~30-40 px upward) ──
        diff_y = self._locked_pos.y() - current_pos.y()
        if 15 <= diff_y <= 80:
            # Snap back on the next event-loop iteration (guarded)
            locked = QPoint(self._locked_pos)
            QTimer.singleShot(0, lambda: self._snap_if_not_dragging(locked))
            return

    @staticmethod
    def fmt_duration(s: int) -> str:
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        if d: return f"{d}d {h}h {m}m {s}s"
        if h: return f"{h}h {m}m {s}s"
        if m: return f"{m}m {s}s"
        return f"{s}s"

    def closeEvent(self, e):
        try: self.connw.stop()
        except Exception: pass
        try: self.geo.stop()
        except Exception: pass
        try: self.myipw.stop()
        except Exception: pass
        try: self.logger.stop()
        except Exception: pass
        # Save the last known-good position (not current pos, which may be glitched)
        if self._locked_pos is not None:
            self.pos_store.save(self._locked_pos.x(), self._locked_pos.y())
        super().closeEvent(e)

# ---------------- Public API ----------------
def create_netmap_widget(parent: QtWidgets.QWidget|None=None, *, land_opacity=LAND_OPACITY_DEFAULT, stay_behind=False) -> NetMap:
    return NetMap(parent, land_opacity=land_opacity, stay_behind=stay_behind)

# ---------------- Entry ----------------
def main():
    QtWidgets.QApplication.setStyle("Fusion")
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    w = NetMap(None, land_opacity=LAND_OPACITY_DEFAULT, stay_behind=True)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()