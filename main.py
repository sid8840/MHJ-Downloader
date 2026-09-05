import csv
import json
import logging
import os
import re
import sys
import shutil
import subprocess
import threading
import time
import traceback
import uuid
import importlib.metadata as importlib_metadata
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtUiTools import loadUiType
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QSizePolicy, QVBoxLayout, QWidget
)
from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget

APP_NAME = "महाराष्ट्राची हास्य जत्रा"
APP_INTERNAL_NAME = "MHJ Downloader"
APP_VERSION = "1.0"
SHOW_ID = "1700000221"
DEFAULT_MANUAL_URL = "https://www.sonyliv.com/shows/maharashtrachi-hasya-jatra-hasnya-cha-common-reason-1700000221/episodes/801-900"

# Resource location: PyInstaller bundle or normal source directory.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
FFMPEG_DIR = RESOURCE_DIR
FFMPEG_EXE = FFMPEG_DIR / "ffmpeg.exe"
FFPROBE_EXE = FFMPEG_DIR / "ffprobe.exe"
MAIN_UI_FILE = RESOURCE_DIR / "main_gui.ui"
SETTINGS_UI_FILE = RESOURCE_DIR / "settings_gui.ui"
BUNDLED_CATALOGUE_FILE = RESOURCE_DIR / "mhj_catalogue.json"

MainUiForm, _MainUiBase = loadUiType(str(MAIN_UI_FILE))
SettingsUiForm, _SettingsUiBase = loadUiType(str(SETTINGS_UI_FILE))

# Writable runtime state. No dependency on D:\\Desktop\\project\\mhj.
PROGRAM_DATA_ROOT = Path(os.environ.get("PROGRAMDATA", Path.home() / "AppData" / "Local"))
PROJECT_DIR = PROGRAM_DATA_ROOT / APP_INTERNAL_NAME
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "mhj_history.csv"
CATALOGUE_FILE = DATA_DIR / "mhj_catalogue.json"
TEMP_ROOT = DATA_DIR / "temp"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
YTDLP_VERSION_STATE_FILE = DATA_DIR / "ytdlp_version_check.json"

# yt-dlp update tracking is deliberately independent of SonyLIV catalogue work.
def installed_ytdlp_version():
    try:
        return importlib_metadata.version("yt-dlp")
    except Exception:
        return "unknown"

def check_ytdlp_version(force=False):
    local = installed_ytdlp_version()
    now = time.time()
    state = {}
    try:
        state = json.loads(YTDLP_VERSION_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    last = float(state.get("last_check", 0) or 0)
    if not force and now - last < 7 * 24 * 3600:
        logger.info("yt-dlp version check not due; local=%s; next check after weekly interval", local)
        return local, state.get("latest")

    try:
        r = requests.get("https://pypi.org/pypi/yt-dlp/json", timeout=5,
                         headers={"Accept":"application/json"})
        r.raise_for_status()
        latest = str((r.json().get("info") or {}).get("version") or "unknown")
        state = {"last_check": now, "latest": latest}
        YTDLP_VERSION_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        if local != "unknown" and latest != "unknown" and local != latest:
            logger.warning("yt-dlp update available: local=%s latest=%s", local, latest)
        else:
            logger.info("yt-dlp version is current: %s", local)
        return local, latest
    except Exception as exc:
        logger.warning("Could not check latest yt-dlp version: local=%s error=%s", local, exc)
        return local, state.get("latest")

def start_ytdlp_version_check(force=False):
    threading.Thread(target=check_ytdlp_version, args=(force,),
                     name="yt-dlp-Version-Check", daemon=True).start()

# Seed the working catalogue only on first run.
if not CATALOGUE_FILE.exists() and BUNDLED_CATALOGUE_FILE.exists():
    try:
        shutil.copy2(BUNDLED_CATALOGUE_FILE, CATALOGUE_FILE)
    except Exception:
        pass

FIELDS = ["episode_number","episode_id","title","air_date","url","filename",
          "final_path","file_size","status","completed_at"]

def setup_logger():
    log = logging.getLogger("mhj")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()

    # One activity log per application session.
    # Example:
    # log_05-09-2026 (09.27.00).log
    session_name = datetime.now().strftime("log_%d-%m-%Y (%H.%M.%S).log")
    session_log = LOG_DIR / session_name

    h = logging.FileHandler(
        session_log,
        mode="a",
        encoding="utf-8"
    )

    h.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s"
        )
    )

    log.addHandler(h)

    log.info("=" * 72)
    log.info("%s v%s started", APP_NAME, APP_VERSION)
    log.info("Project directory: %s", PROJECT_DIR)
    log.info("Session log: %s", session_log)

    return log


logger = setup_logger()

def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]+', "_", str(s or "")).strip().rstrip(". ")

def show_id_from_url(url):
    m = re.search(r"sonyliv\.com/shows/[^/?#]+-(\d{10})(?:/|$|\?|#)", url or "", re.I)
    return m.group(1) if m else None

YTDLP_IMPERSONATE_LABEL = "Chrome-116 / Windows-10"
YTDLP_IMPERSONATE = ImpersonateTarget(client="chrome", version="116", os="windows", os_version="10")

def ytdlp_base_options():
    """Common yt-dlp networking options for SonyLIV.

    curl_cffi provides a browser-like TLS/HTTP fingerprint without Selenium,
    ChromeDriver, or launching a browser.
    """
    return {
        "impersonate": YTDLP_IMPERSONATE,
        "http_headers": {
            "Referer": "https://www.sonyliv.com/",
            "Origin": "https://www.sonyliv.com",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

def date_text(v):
    """Return episode dates in the user-facing DD-MM-YYYY format."""
    if not v:
        return ""
    try:
        if isinstance(v,(int,float)) or str(v).isdigit():
            n=int(v)
            if n>10_000_000_000:
                n//=1000
            return datetime.fromtimestamp(n).strftime("%d-%m-%Y")

        s=str(v).strip()

        # SonyLIV/cache values are normally ISO dates (YYYY-MM-DD). Convert
        # them before they reach Episode.stem(), so the GUI and final filename
        # always use exactly the same representation.
        m=re.match(r"^(\d{4})-(\d{2})-(\d{2})",s)
        if m:
            yyyy,mm,dd=m.groups()
            return f"{dd}-{mm}-{yyyy}"

        # Already converted / legacy DD-MM-YYYY values.
        m=re.match(r"^(\d{2})-(\d{2})-(\d{4})",s)
        if m:
            return m.group(0)

        return s[:30]
    except Exception:
        return str(v)[:30]

@dataclass
class Episode:
    number:int
    eid:str
    title:str
    air_date:str
    url:str
    thumbnail:str=""
    def stem(self):
        title=safe_name(self.title) or f"Episode {self.number}"
        return f"{self.number} - {title}" + (f" ({safe_name(self.air_date)})" if self.air_date else "")

class History:
    # One lock for the entire application, shared by every History instance.
    _file_lock = threading.Lock()

    def __init__(self, path):
        self.path = Path(path)

        if not self.path.exists():
            with self._file_lock:
                if not self.path.exists():
                    with self.path.open("w", newline="", encoding="utf-8-sig") as f:
                        csv.DictWriter(f, fieldnames=FIELDS).writeheader()

    def rows(self):
        with self._file_lock:
            try:
                with self.path.open("r", newline="", encoding="utf-8-sig") as f:
                    return list(csv.DictReader(f))
            except Exception:
                logger.exception("History read failed")
                return []

    def find(self, ep):
        for r in self.rows():
            if (
                r.get("episode_id") == ep.eid
                or (ep.number and r.get("episode_number") == str(ep.number))
            ):
                return r
        return None

    def upsert(self, ep, path):
        p = Path(path)

        row = {
            "episode_number": ep.number,
            "episode_id": ep.eid,
            "title": ep.title,
            "air_date": ep.air_date,
            "url": ep.url,
            "filename": p.name,
            "final_path": str(p),
            "file_size": p.stat().st_size if p.exists() else 0,
            "status": "completed",
            "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Serialize ALL History instances and use a unique temporary file.
        with History._file_lock:
            rows = []

            if self.path.exists():
                try:
                    with self.path.open(
                        "r", newline="", encoding="utf-8-sig"
                    ) as f:
                        rows = list(csv.DictReader(f))
                except Exception:
                    logger.exception("History read failed during upsert")
                    rows = []

            done = False

            for i, r in enumerate(rows):
                if (
                    r.get("episode_id") == ep.eid
                    or (
                        ep.number
                        and r.get("episode_number") == str(ep.number)
                    )
                ):
                    rows[i] = row
                    done = True
                    break

            if not done:
                rows.append(row)

            # Unique temporary filename prevents different History instances
            # from ever fighting over the same .tmp file.
            tmp = self.path.with_name(
                f"{self.path.stem}.{uuid.uuid4().hex}.tmp"
            )

            try:
                with tmp.open(
                    "w", newline="", encoding="utf-8-sig"
                ) as f:
                    writer = csv.DictWriter(f, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp, self.path)

            except Exception:
                logger.exception(
                    "History CSV update failed for episode %s",
                    ep.number
                )

                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass

                raise

        logger.info(
            "History CSV updated for episode %s -> %s",
            ep.number,
            p
        )


class CatalogueCache:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"version": 1, "episodes": {}}
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("episodes"), dict):
                    self.data = raw
        except Exception:
            logger.exception("Catalogue cache load failed; using empty cache")
        logger.info("Catalogue cache loaded: %d entries", len(self.data["episodes"]))

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def seed_history(self, history):
        changed = 0
        for r in history.rows():
            eid = str(r.get("episode_id") or "").strip()
            try:
                number = int(r.get("episode_number") or 0)
            except Exception:
                number = 0
            if eid and number and eid not in self.data["episodes"]:
                self.data["episodes"][eid] = {
                    "episode_number": number,
                    "title": r.get("title") or f"Episode {number}",
                    "air_date": date_text(r.get("air_date") or ""),
                    "url": r.get("url") or f"sonyliv:{eid}",
                    "thumbnail": "",
                    "last_verified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "history",
                }
                changed += 1
        if changed:
            self.save()
            logger.info("Seeded catalogue cache with %d entries from history CSV", changed)

    def get_status(self, eid):
        c = self.data["episodes"].get(str(eid))
        return (c or {}).get("status", "usable" if c else "")

    def apply(self, ep):
        c = self.data["episodes"].get(ep.eid)
        if not c or c.get("status") == "unavailable":
            return False
        try:
            ep.number = int(c.get("episode_number") or 0)
        except Exception:
            ep.number = 0
        ep.title = c.get("title") or ep.title
        ep.air_date = date_text(c.get("air_date") or ep.air_date)
        ep.url = c.get("url") or ep.url
        ep.thumbnail = c.get("thumbnail") or ep.thumbnail
        return bool(ep.number)

    def mark_unavailable(self, ep, reason):
        self.data["episodes"][ep.eid] = {
            "episode_number": 0,
            "title": ep.title,
            "air_date": ep.air_date,
            "url": ep.url,
            "thumbnail": ep.thumbnail,
            "status": "unavailable",
            "reason": str(reason)[:500],
            "last_verified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "metadata",
        }

    def put(self, ep, source="metadata"):
        if ep.eid and ep.number:
            self.data["episodes"][ep.eid] = {
                "episode_number": int(ep.number),
                "title": ep.title,
                "air_date": ep.air_date,
                "url": ep.url,
                "thumbnail": ep.thumbnail,
                "last_verified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": source,
                "status": "usable",
            }

class PremiumContentError(RuntimeError):
    """SonyLIV has the episode, but the account is not currently entitled to play it."""


class SonyLiv:
    BASE="https://apiv2.sonyliv.com/AGL"
    def __init__(self,retries=5):
        self.retries=retries
        self.new_session()
    def new_session(self):
        self.s=requests.Session()
        self.s.headers.update({
            "Accept":"application/json, text/plain, */*",
            "Accept-Language":"en-US,en;q=0.9",
            "Origin":"https://www.sonyliv.com",
            "Referer":"https://www.sonyliv.com/",
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
            "sec-ch-ua":'"Chromium";v="150", "Google Chrome";v="150", "Not_A Brand";v="99"',
            "sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"Windows"',
        })
    def get(self,url,params=None):
        last=None
        for attempt in range(1,self.retries+1):
            try:
                r=self.s.get(url,params=params,timeout=30)
                logger.debug("GET %s -> %s attempt %d/%d",r.url,r.status_code,attempt,self.retries)
                # 406 is SonyLIV's entitlement response for premium-only content.
                # Do not waste the retry budget on it; video_content() classifies it.
                if r.status_code == 406:
                    r.raise_for_status()
                if r.status_code in (403,429,500,502,503,504):
                    last=RuntimeError(f"HTTP {r.status_code}")
                    if attempt<self.retries:
                        delay=min(2**(attempt-1),12)
                        logger.warning("SonyLIV returned %s; retrying in %ss",r.status_code,delay)
                        time.sleep(delay); self.new_session(); continue
                r.raise_for_status(); return r.json()
            except Exception as e:
                last=e
                if attempt<self.retries:
                    time.sleep(min(2**(attempt-1),12)); self.new_session()
        raise last
    def token(self):
        d=self.get(f"{self.BASE}/1.4/A/ENG/WEB/ALL/GETTOKEN")
        t=d.get("resultObj")
        if not t: raise RuntimeError("SonyLIV security token missing")
        self.s.headers["security_token"]=t

    def video_content(self, episode_id):
        """Resolve SonyLIV entitlement and return the media descriptor.

        This deliberately uses the same direct API path that already works for
        discovery in this application.  It prevents yt-dlp's SonyLIV extractor
        from re-running GETTOKEN through its curl_cffi transport.

        A 406 with SonyLIV's subscription message is a normal, temporary
        entitlement state, not a technical download failure.
        """
        self.token()
        url=f"{self.BASE}/1.5/A/ENG/WEB/IN/CONTENT/VIDEOURL/VOD/{episode_id}"
        try:
            d=self.get(url)
        except requests.HTTPError as exc:
            response=getattr(exc, "response", None)
            if response is not None and response.status_code == 406:
                try:
                    body=response.json()
                except Exception:
                    body={}
                message=str(body.get("message") or body.get("resultObj",{}).get("message") or "").strip()
                if message.lower() == "please subscribe to watch this content":
                    raise PremiumContentError(message) from exc
            raise
        result=d.get("resultObj") or {}
        if not result:
            raise RuntimeError(f"SonyLIV returned no video information for episode {episode_id}")
        return result
    def discover_api(self,sid):
        self.token()
        d=self.get(f"{self.BASE}/1.9/R/ENG/WEB/IN/DL/DETAIL/{sid}",
                   {"kids_safe":"false","from":"0","to":"49"})
        seasons=d["resultObj"]["containers"][0]["containers"]
        seasons=[x for x in seasons if str(x.get("id","")).isdigit()][::-1]
        out=[]; seen=set()
        for season in seasons:
            season_id=str(season["id"])
            meta=season.get("metadata") or {}
            logger.info("Scanning SonyLIV season/range: %s",meta.get("title",season_id))
            start=0
            while True:
                b=self.get(f"{self.BASE}/1.4/R/ENG/WEB/IN/CONTENT/DETAIL/BUNDLE/{season_id}",
                           {"from":str(start),"to":str(start+99),"orderBy":"episodeNumber","sortOrder":"desc"})
                try: items=b["resultObj"]["containers"][0]["containers"]
                except Exception: items=[]
                if not items: break
                for x in items:
                    eid=str(x.get("id",""))
                    if not eid.isdigit() or eid in seen: continue
                    seen.add(eid); md=x.get("metadata") or {}
                    n=md.get("episodeNumber") or md.get("episode") or 0
                    try:n=int(n)
                    except:n=0
                    title=md.get("episodeTitle") or md.get("title") or md.get("name") or f"Episode {n or eid}"
                    thumb=md.get("thumbnail") or md.get("posterURL") or md.get("landscapeImage") or md.get("image") or ""
                    if isinstance(thumb,dict): thumb=thumb.get("url","")
                    out.append(Episode(n,eid,str(title).strip(),date_text(md.get("creationDate") or md.get("airDate") or md.get("releaseDate")),
                                       f"sonyliv:{eid}",str(thumb or "")))
                start+=100
        out.sort(key=lambda e:(e.number,int(e.eid)),reverse=True)
        return out
    def discover_latest(self,sid,limit=10):
        """Fetch only the newest episode window for New Episodes mode.

        This intentionally avoids full-series discovery and catalogue ID
        resolution. One show-detail request identifies the newest season, then
        one bundle request retrieves its newest numbered episodes.
        """
        self.token()
        d=self.get(f"{self.BASE}/1.9/R/ENG/WEB/IN/DL/DETAIL/{sid}",
                   {"kids_safe":"false","from":"0","to":"49"})
        seasons=d["resultObj"]["containers"][0]["containers"]
        seasons=[x for x in seasons if str(x.get("id","")).isdigit()][::-1]
        if not seasons:
            raise RuntimeError("SonyLIV returned no usable season information")
        season=seasons[0]
        season_id=str(season["id"])
        b=self.get(f"{self.BASE}/1.4/R/ENG/WEB/IN/CONTENT/DETAIL/BUNDLE/{season_id}",
                   {"from":"0","to":"99","orderBy":"episodeNumber","sortOrder":"desc"})
        try:
            items=b["resultObj"]["containers"][0]["containers"]
        except Exception:
            items=[]
        out=[]
        for x in items:
            eid=str(x.get("id",""))
            if not eid.isdigit():
                continue
            md=x.get("metadata") or {}
            n=md.get("episodeNumber") or md.get("episode") or 0
            try:n=int(n)
            except:n=0
            if not n:
                continue
            title=md.get("episodeTitle") or md.get("title") or md.get("name") or f"Episode {n}"
            thumb=md.get("thumbnail") or md.get("posterURL") or md.get("landscapeImage") or md.get("image") or ""
            if isinstance(thumb,dict): thumb=thumb.get("url","")
            out.append(Episode(n,eid,str(title).strip(),
                               date_text(md.get("creationDate") or md.get("airDate") or md.get("releaseDate")),
                               f"sonyliv:{eid}",str(thumb or "")))
        out.sort(key=lambda e:e.number, reverse=True)
        if not out:
            raise RuntimeError("SonyLIV returned no numbered latest episodes")
        logger.info("SonyLIV latest-window discovery complete: %d episodes; latest=%s",
                    min(limit,len(out)), out[0].number)
        return out[:limit]
        
        
        

    def discover_new_episode_list(self, sid):
        """Fetch the complete numbered episode list for the newest SonyLIV season.

        Used only by New Episodes mode when the destination already contains
        media. This bypasses yt-dlp playlist discovery and catalogue ID
        resolution because the direct SonyLIV bundle API provides episode numbers.
        """
        self.token()

        d = self.get(
            f"{self.BASE}/1.9/R/ENG/WEB/IN/DL/DETAIL/{sid}",
            {"kids_safe": "false", "from": "0", "to": "49"}
        )

        seasons = d["resultObj"]["containers"][0]["containers"]
        seasons = [x for x in seasons if str(x.get("id", "")).isdigit()][::-1]

        if not seasons:
            raise RuntimeError("SonyLIV returned no usable season information")

        season_id = str(seasons[0]["id"])

        logger.info(
            "SonyLIV complete-new-episode discovery: scanning newest season %s",
            season_id
        )

        out = []
        seen = set()
        start = 0

        while True:
            b = self.get(
                f"{self.BASE}/1.4/R/ENG/WEB/IN/CONTENT/DETAIL/BUNDLE/{season_id}",
                {
                    "from": str(start),
                    "to": str(start + 99),
                    "orderBy": "episodeNumber",
                    "sortOrder": "desc"
                }
            )

            try:
                items = b["resultObj"]["containers"][0]["containers"]
            except Exception:
                items = []

            if not items:
                break

            added = 0

            for x in items:
                eid = str(x.get("id", ""))

                if not eid.isdigit() or eid in seen:
                    continue

                md = x.get("metadata") or {}

                n = md.get("episodeNumber") or md.get("episode") or 0
                try:
                    n = int(n)
                except Exception:
                    n = 0

                if not n:
                    continue

                title = (
                    md.get("episodeTitle")
                    or md.get("title")
                    or md.get("name")
                    or f"Episode {n}"
                )

                thumb = (
                    md.get("thumbnail")
                    or md.get("posterURL")
                    or md.get("landscapeImage")
                    or md.get("image")
                    or ""
                )

                if isinstance(thumb, dict):
                    thumb = thumb.get("url", "")

                out.append(
                    Episode(
                        n,
                        eid,
                        str(title).strip(),
                        date_text(
                            md.get("originalAirDate")                              
                            or md.get("airDate")
                            or md.get("releaseDate")
                            or md.get("creationDate")
                        ),
                        f"sonyliv:{eid}",
                        str(thumb or "")
                    )
                )

                seen.add(eid)
                added += 1

            logger.info(
                "SonyLIV complete-new-episode discovery: page %d-%d -> %d new episodes",
                start,
                start + 99,
                added
            )

            if len(items) < 100:
                break

            start += 100

        out.sort(key=lambda e: (e.number, int(e.eid)), reverse=True)

        if not out:
            raise RuntimeError(
                "SonyLIV returned no numbered episodes for the newest season"
            )

        logger.info(
            "SonyLIV complete-new-episode discovery complete: %d episodes; latest=%s",
            len(out),
            out[0].number
        )

        return out

    
    def discover_ytdlp(self,sid):
        # Fallback maintained by yt-dlp itself.
        logger.warning("Using yt-dlp SonyLIVSeries fallback discovery")
        url=f"https://www.sonyliv.com/shows/mhj-{sid}"
        opts=ytdlp_base_options()
        opts.update({"quiet":True,"no_warnings":True,"extract_flat":"in_playlist",
                     "skip_download":True,
                     "extractor_args":{"sonylivseries":{"sort_order":["desc"]}}})
        logger.info("yt-dlp SonyLIV discovery using impersonation target: %s", YTDLP_IMPERSONATE_LABEL)
        with YoutubeDL(opts) as y:
            info=y.extract_info(url,download=False)
        entries=list(info.get("entries") or [])
        out=[]
        for x in entries:
            if not x: continue
            eid=str(x.get("id") or "")
            if not eid: continue
            n=x.get("episode_number") or x.get("episode") or 0
            try:n=int(n)
            except:n=0
            title=x.get("title") or f"Episode {n or eid}"
            thumb=x.get("thumbnail") or ""
            out.append(Episode(n,eid,title,date_text(x.get("timestamp") or x.get("release_timestamp")),
                               x.get("url") if str(x.get("url","")).startswith("sonyliv:") else f"sonyliv:{eid}",thumb))
        # Flat playlist extraction often omits episode_number. Keep the entries,
        # then resolve their authoritative episode numbers before any selection,
        # CSV reconciliation, or disk reconciliation is attempted.
        if not out:
            raise RuntimeError("yt-dlp fallback returned no episodes")
        return out

    def discover(self, sid):
        # Primary path: yt-dlp + curl_cffi browser impersonation.
        try:
            out = self.discover_ytdlp(sid)
            if not out:
                raise RuntimeError("Impersonated yt-dlp discovery returned no episodes")
            logger.info("Impersonated yt-dlp discovery complete: %d episodes", len(out))
            return out
        except Exception:
            logger.exception("Impersonated yt-dlp discovery failed; trying direct API fallback")
            out = self.discover_api(sid)
            if not out:
                raise RuntimeError("Direct API fallback returned no episodes")
            logger.info("Direct API fallback discovery complete: %d episodes", len(out))
            return out

    def resolve_catalogue_numbers(self, episodes, cache):
        cached, unavailable, unresolved = 0, 0, []
        for ep in episodes:
            if ep.number:
                cache.put(ep, "series")
            elif cache.get_status(ep.eid) == "unavailable":
                unavailable += 1
            elif cache.apply(ep):
                cached += 1
            else:
                unresolved.append(ep)

        logger.info("Catalogue cache matched %d/%d usable entries; %d unavailable; %d new/unresolved IDs",
                    cached, len(episodes), unavailable, len(unresolved))

        if unresolved:
            opts = ytdlp_base_options()
            opts.update({"quiet":True, "no_warnings":True, "skip_download":True, "noplaylist":True})
            resolved = failed = 0
            for i, ep in enumerate(unresolved, 1):
                try:
                    with YoutubeDL(opts) as y:
                        info = y.extract_info(ep.url, download=False)
                    try:
                        n = int(info.get("episode_number") or info.get("episode") or 0)
                    except Exception:
                        n = 0
                    if n:
                        ep.number = n
                        ep.title = info.get("title") or ep.title
                        ep.thumbnail = info.get("thumbnail") or ep.thumbnail
                        ts = info.get("timestamp") or info.get("release_timestamp")
                        if ts:
                            ep.air_date = date_text(ts)
                        cache.put(ep, "metadata")
                        resolved += 1
                    else:
                        failed += 1
                        logger.warning("New SonyLIV ID %s has no episode number", ep.eid)
                except Exception as exc:
                    failed += 1
                    cache.mark_unavailable(ep, exc)
                    logger.warning("Catalogue ID %s marked unavailable and will not be retried automatically: %s",
                                   ep.eid, str(exc).splitlines()[-1] if str(exc) else type(exc).__name__)

                if i == 1 or i % 10 == 0 or i == len(unresolved):
                    logger.info("New-ID resolution: %d/%d checked, %d resolved, %d unresolved",
                                i, len(unresolved), resolved, failed)
            cache.save()

        usable = [e for e in episodes if e.number]
        usable.sort(key=lambda e:(e.number, int(e.eid) if e.eid.isdigit() else 0), reverse=True)
        logger.info("Catalogue indexing complete: %d usable numbered episodes", len(usable))
        return usable



def local_episode_numbers(folder):
    """Episode numbers represented by actual media files in the download folder."""
    found=set()
    folder=Path(folder)
    if not folder.exists(): return found
    for f in folder.iterdir():
        if not f.is_file() or f.suffix.lower() not in {".mp4",".mkv",".webm",".m4v",".avi"}:
            continue
        m=re.match(r"^\s*(\d+)\s*(?:[-_. ]|$)",f.stem)
        if m: found.add(int(m.group(1)))
    return found


def episode_temp_dir(ep):
    """Private working directory for one episode."""
    n = int(ep.number or 0)
    return TEMP_ROOT / (f"episode_{n}" if n else f"id_{safe_name(ep.eid)}")


def interrupted_download_files(folder, ep):
    """Return yt-dlp resumable files from the private temp directory."""
    work = episode_temp_dir(ep)
    if not work.exists():
        return []
    partials = []
    for f in work.rglob("*"):
        if not f.is_file():
            continue
        low = f.name.lower()
        if low.endswith(".part") or low.endswith(".ytdl") or ".part-" in low:
            partials.append(f)
    return partials


def scan_managed_temp():
    """Map episode numbers that have resumable state in DATA_DIR/temp."""
    partials = {}
    if not TEMP_ROOT.exists():
        return partials
    for d in TEMP_ROOT.glob("episode_*"):
        if not d.is_dir():
            continue
        m = re.fullmatch(r"episode_(\d+)", d.name)
        if not m:
            continue
        n = int(m.group(1))
        files = []
        for f in d.rglob("*"):
            if f.is_file():
                low = f.name.lower()
                if low.endswith(".part") or low.endswith(".ytdl") or ".part-" in low:
                    files.append(str(f))
        if files:
            partials[n] = files
    return partials


def cleanup_episode_temp(ep):
    work = episode_temp_dir(ep)
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)


def cleanup_finished_temp():
    """Remove empty/stale work directories that contain no resumable state."""
    if not TEMP_ROOT.exists():
        return
    for d in TEMP_ROOT.iterdir():
        if not d.is_dir():
            continue
        has_resume = False
        for f in d.rglob("*"):
            if f.is_file():
                low = f.name.lower()
                if low.endswith(".part") or low.endswith(".ytdl") or ".part-" in low:
                    has_resume = True
                    break
        if not has_resume:
            shutil.rmtree(d, ignore_errors=True)


def kill_descendant_processes():
    """Immediately terminate descendant processes without killing the GUI process."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_TERMINATE = 0x0001
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE:
            return
        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(pe)
            parent = {}
            if k32.Process32FirstW(snap, ctypes.byref(pe)):
                while True:
                    parent[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
                    if not k32.Process32NextW(snap, ctypes.byref(pe)):
                        break
        finally:
            k32.CloseHandle(snap)

        root = os.getpid()
        descendants = set()
        changed = True
        while changed:
            changed = False
            for child, par in parent.items():
                if child != root and (par == root or par in descendants) and child not in descendants:
                    descendants.add(child)
                    changed = True

        # Kill deepest/newest descendants first. In practice this catches ffmpeg
        # before yt-dlp can finish the merge and move the result.
        for pid in sorted(descendants, reverse=True):
            h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if h:
                try:
                    k32.TerminateProcess(h, 1)
                finally:
                    k32.CloseHandle(h)
        if descendants:
            logger.info("MASTER STOP terminated descendant PID(s): %s",
                        ", ".join(map(str, sorted(descendants))))
    except Exception:
        logger.exception("Could not terminate descendant processes")


def scan_local_collection(folder):
    folder=Path(folder)
    media={}; partials={}
    if folder.exists():
        for f in folder.iterdir():
            if not f.is_file(): continue
            m=re.match(r"^\s*(\d+)\s*(?:[-_. ]|$)",f.stem)
            if not m: continue
            n=int(m.group(1)); low=f.name.lower()
            if f.suffix.lower() in {".mp4",".mkv",".webm",".m4v",".avi"} and not low.endswith(".part"):
                media.setdefault(n,[]).append(str(f))
            if low.endswith(".part") or low.endswith(".ytdl") or ".part-" in low:
                partials.setdefault(n,[]).append(str(f))
    # Resumable yt-dlp state is intentionally kept outside the user's
    # download folder. Merge it into the local facts used by the cascade.
    for n, files in scan_managed_temp().items():
        partials.setdefault(n, []).extend(files)
    nums=sorted(media)
    return {"media":media,"partials":partials,
            "lowest":nums[0] if nums else 0,"highest":nums[-1] if nums else 0}

def _find_episode_node(obj, episode_number, episode_id=""):
    """Recursively find the episode object in SonyLIV show-detail JSON."""
    if isinstance(obj, dict):
        md = obj.get("metadata") or {}
        try:
            n = int(md.get("episodeNumber") or md.get("episode") or 0)
        except Exception:
            n = 0
        eid = str(obj.get("id") or "")
        if (episode_id and eid == str(episode_id)) or (episode_number and n == int(episode_number)):
            return obj
        for value in obj.values():
            found = _find_episode_node(value, episode_number, episode_id)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_episode_node(value, episode_number, episode_id)
            if found is not None:
                return found
    return None


def _thumbnail_candidates(node):
    """Return image URLs in preference order from a SonyLIV episode node."""
    if not isinstance(node, dict):
        return []
    md = node.get("metadata") or {}
    emf = md.get("emfAttributes") or {}
    preferred = (
        "thumbnail", "landscape_thumb", "landscapeImage", "posterURL", "image",
        "tv_sprite_image_url", "sprite_image_url", "tv_background_image",
    )
    out = []
    for source in (emf, md, node):
        if not isinstance(source, dict):
            continue
        for key in preferred:
            value = source.get(key)
            if isinstance(value, dict):
                value = value.get("url")
            if isinstance(value, str) and value.startswith("http") and value not in out:
                out.append(value)
    return out


def fetch_episode_thumbnail(ep, retries=5):
    """Best-effort direct thumbnail probe; completely independent of yt-dlp download."""
    client = SonyLiv(retries)
    client.token()
    detail = client.get(
        f"{client.BASE}/1.9/R/ENG/WEB/IN/DL/DETAIL/{SHOW_ID}",
        {"kids_safe": "false", "from": "0", "to": "49"},
    )
    node = _find_episode_node(detail, ep.number, ep.eid)
    if node is None:
        raise RuntimeError(f"Episode {ep.number} was not found in SonyLIV show detail")
    candidates = _thumbnail_candidates(node)
    if not candidates:
        raise RuntimeError(f"Episode {ep.number} has no thumbnail candidates")
    headers = {
        "User-Agent": client.s.headers.get("User-Agent", "Mozilla/5.0"),
        "Referer": "https://www.sonyliv.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    last = None
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            if not r.content or (ctype and "image" not in ctype):
                raise RuntimeError(f"Unexpected thumbnail response: {ctype or 'unknown'}")
            logger.info("Episode %s thumbnail probe succeeded: %s (%d bytes)", ep.number, url, len(r.content))
            return bytes(r.content)
        except Exception as exc:
            last = exc
            logger.debug("Episode %s thumbnail candidate failed: %s", ep.number, exc)
    raise last or RuntimeError("No usable thumbnail image")


class ThumbnailService(QObject):
    ready = Signal(int, bytes)
    failed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self._generation = 0
        self._lock = threading.Lock()

    def request(self, ep, retries):
        """Start one disposable low-impact daemon thread for the current episode."""
        with self._lock:
            self._generation += 1
            generation = self._generation
        snapshot = Episode(ep.number, ep.eid, ep.title, ep.air_date, ep.url, ep.thumbnail)
        threading.Thread(
            target=self._run,
            args=(generation, snapshot, retries),
            name=f"MHJ-Thumbnail-{ep.number}",
            daemon=True,
        ).start()

    def invalidate(self):
        with self._lock:
            self._generation += 1

    def _run(self, generation, ep, retries):
        # Thumbnail work is intentionally best-effort and never gates video work.
        time.sleep(0.10)
        try:
            data = fetch_episode_thumbnail(ep, retries)
            with self._lock:
                current = generation == self._generation
            if current:
                self.ready.emit(int(ep.number), data)
        except Exception as exc:
            logger.warning("Episode %s thumbnail probe failed: %s", ep.number, exc)
            with self._lock:
                current = generation == self._generation
            if current:
                self.failed.emit(int(ep.number), str(exc))


class LocalDiskWorker(QObject):
    ready=Signal(object); error=Signal(str)
    def __init__(self,folder): super().__init__(); self.folder=folder
    def run(self):
        try:
            logger.info("Local disk worker started")
            f=scan_local_collection(self.folder)
            logger.info("Local disk worker complete: completed=%d interrupted=%d lowest=%s highest=%s",
                        len(f["media"]),len(f["partials"]),f["lowest"] or "none",f["highest"] or "none")
            self.ready.emit(f)
        except Exception:
            logger.exception("Local disk worker failed"); self.error.emit(traceback.format_exc())

class CascadeEngine:
    def __init__(self,st,hist,catalogue,disk):
        self.st=st; self.hist=hist
        self.catalogue=sorted(catalogue,key=lambda e:e.number,reverse=True)
        self.disk=disk; self.by_num={e.number:e for e in self.catalogue if e.number}
    def decide(self):
        media=set(self.disk["media"]); parts=set(self.disk["partials"])
        latest=max(self.by_num,default=0); lowest=self.disk["lowest"]
        repaired=0
        for n in media:
            ep=self.by_num.get(n)
            if ep and not self.hist.find(ep):
                self.hist.upsert(ep,Path(self.disk["media"][n][0])); repaired+=1
        interrupted=[self.by_num[n] for n in sorted(parts,reverse=True)
                     if n in self.by_num and n not in media]
        historical=[]
        if self.st.get("check_missing_older",True) and lowest:
            historical=[self.by_num[n] for n in sorted(self.by_num,reverse=True)
                        if lowest<=n<=latest and n not in media and n not in parts]
        mode=self.st["mode"]
        if mode=="single":
            scoped=[self.by_num[self.st["single"]]] if self.st["single"] in self.by_num else []
        elif mode=="range":
            lo,hi=sorted((self.st["from_ep"],self.st["to_ep"]))
            scoped=[self.by_num[n] for n in sorted(self.by_num,reverse=True) if lo<=n<=hi]
        elif mode=="all": scoped=list(self.catalogue)
        else:
            highest = max(media, default=0)
            lowest = min(media, default=0)

            if media:
                # Existing collection:
                # The LOCAL DISK is authoritative.
                #
                # Compare every SonyLIV episode against the physical files on disk.
                # This catches BOTH:
                #   1. new episodes above the local highest
                #   2. gaps inside the existing local collection
                scoped = [
                    e for e in self.catalogue
                    if e.number not in media
                ]

                logger.info(
                    "New Episodes cascade: local scan reconciliation; "
                    "local lowest=%s highest=%s physical=%d SonyLIV latest=%s "
                    "missing=%s",
                    lowest,
                    highest,
                    len(media),
                    latest or "unknown",
                    ",".join(str(e.number) for e in scoped) or "none"
                )

                if not scoped:
                    logger.info(
                        "No missing/new episodes: local physical collection "
                        "matches SonyLIV episode list"
                    )

            else:
                # Empty collection:
                # discover_latest() already supplied exactly the latest 10.
                scoped = list(self.catalogue[:10])

                logger.info(
                    "New Episodes cascade: destination is empty; "
                    "selected latest %s episode(s): %s",
                    len(scoped),
                    ",".join(str(e.number) for e in scoped)
                )
        queue = []
        csv_missing = []
        intnums = {e.number for e in interrupted}

        for ep in scoped:
            # Physical disk is authoritative in New Episodes mode.
            if ep.number in media:
                continue

            if ep.number in intnums:
                continue

            if mode == "new":
                queue.append(ep)
                continue

            # Existing behaviour for Single / Range / Entire Library modes.
            row = self.hist.find(ep)
            if row and row.get("status") == "completed":
                csv_missing.append(ep)
            else:
                queue.append(ep)

        if mode == "new":
            csv_missing = []
            historical = []
            reserved={e.number for e in queue+csv_missing+interrupted}
            historical=[e for e in historical if e.number not in reserved]
            logger.info("Cascade result: queue=%s interrupted=%s csv-missing=%s historical=%s repaired=%d",
                        ",".join(str(e.number) for e in queue) or "none",
                        ",".join(str(e.number) for e in interrupted) or "none",
                        ",".join(str(e.number) for e in csv_missing) or "none",
                        ",".join(str(e.number) for e in historical) or "none",repaired)
            return queue,csv_missing,historical,interrupted

def disk_file(folder,ep,row=None):
    folder=Path(folder)
    if row:
        fp=row.get("final_path","")
        if fp:
            p=Path(fp)
            if p.exists() and p.is_file() and p.stat().st_size>0:return p
        fn=row.get("filename","")
        if fn:
            p=folder/fn
            if p.exists() and p.stat().st_size>0:return p
    if ep.number:
        pats=[f"{ep.number} - *.mp4",f"{ep.number} - *.mkv",f"{ep.number} - *.webm"]
        for pat in pats:
            for p in folder.glob(pat):
                if p.is_file() and p.stat().st_size>0:return p
    return None

class ScanWorker(QObject):
    log=Signal(str); ready=Signal(object,object,object,object); error=Signal(str)
    def __init__(self,settings,sid):
        super().__init__(); self.st=settings; self.sid=sid
    def say(self,s): self.log.emit(s); logger.info(s)
    @Slot()
    def run(self):
        try:
            self.say("Checking SonyLIV for latest episodes...")
            hist=History(HISTORY_FILE); cache=CatalogueCache(CATALOGUE_FILE); cache.seed_history(hist)
            sony=SonyLiv(self.st["retries"])
            if self.st.get("mode") == "new":
                folder=Path(self.st["folder"])
                has_local_files=any(
                    p.is_file() and p.suffix.lower() in (".mp4",".mkv",".webm")
                    for p in folder.glob("*")
                )

                if has_local_files:
                    logger.info(
                        "New Episodes mode: local collection exists; "
                        "fetching complete SonyLIV episode list for comparison"
                    )
                    episodes = sony.discover_new_episode_list(self.sid)
                else:
                    logger.info(
                        "New Episodes mode: destination is empty; "
                        "fetching only latest 10 SonyLIV episodes"
                    )
                    episodes=sony.discover_latest(self.sid,10)
            else:
                episodes=sony.discover(self.sid)
                episodes=sony.resolve_catalogue_numbers(episodes,cache)
            if not episodes: raise RuntimeError("No usable episodes were found.")
            logger.info("SonyLIV worker complete: %d usable episodes; latest=%s",len(episodes),episodes[0].number)
            self.ready.emit(episodes,[],[],[])
        except Exception:
            logger.exception("SonyLIV scan failed"); self.error.emit(traceback.format_exc())

class DownloadWorker(QObject):
    log=Signal(str); started=Signal(str,str); thumbnail_request=Signal(object)
    current_progress=Signal(int,str); overall=Signal(int,int); status=Signal(str)
    phase=Signal(str); finished=Signal(dict); error=Signal(str)

    def __init__(self,episodes,settings):
        super().__init__(); self.eps=episodes; self.st=normalize_settings(settings)
        self.stop_event=threading.Event(); self.hist=History(HISTORY_FILE)
        self.lock=threading.Lock(); self.done=0

    @Slot()
    def stop(self):
        self.stop_event.set()
        logger.info("MASTER STOP requested")
        self.status.emit("Stopping immediately...")
        # If yt-dlp is currently inside FFmpeg merging/post-processing, progress
        # hooks cannot run. Kill only descendants of this Python process.
        # Kill ffmpeg/ffprobe helpers synchronously before returning from STOP.
        # This gives STOP precedence over a merge that is close to completion.
        kill_descendant_processes()

    def say(self,s):
        self.log.emit(s); logger.info(s)

    @Slot()
    def run(self):
        summary={"downloaded":0,"premium":0,"failed":0,"stopped":False}
        try:
            pending=iter(self.eps); active={}
            with ThreadPoolExecutor(max_workers=self.st["parallel"],
                                    thread_name_prefix="MHJ-Episode") as pool:
                def fill():
                    while len(active)<self.st["parallel"] and not self.stop_event.is_set():
                        try:e=next(pending)
                        except StopIteration:return
                        active[pool.submit(self.one,e)]=e
                fill()
                while active:
                    done,_=wait(list(active),return_when=FIRST_COMPLETED)
                    for fut in done:
                        ep=active.pop(fut)
                        try:r=fut.result()
                        except Exception as ex:
                            if self.stop_event.is_set():
                                r="stop"
                            else:
                                logger.exception("Episode %s failed",ep.number)
                                r="failed"; self.say(f"Episode {ep.number} failed: {ex}")
                        if r=="ok":summary["downloaded"]+=1
                        elif r=="premium":summary["premium"]+=1
                        elif r=="failed":summary["failed"]+=1
                        with self.lock:
                            self.done+=1; self.overall.emit(self.done,len(self.eps))
                    fill()
                if self.stop_event.is_set():
                    summary["stopped"]=True
            self.finished.emit(summary)
        except Exception as e:
            if self.stop_event.is_set():
                summary["stopped"]=True
                self.finished.emit(summary)
            else:
                logger.exception("Download session failed"); self.error.emit(str(e))

    def one(self,ep):
        if self.stop_event.is_set(): return "stop"

        final_folder=Path(self.st["folder"])
        final_folder.mkdir(parents=True, exist_ok=True)
        work=episode_temp_dir(ep)
        work.mkdir(parents=True, exist_ok=True)

        initial_expected=final_folder/(ep.stem()+".mp4")
        self.started.emit(f"Episode {ep.number} - {ep.title}",initial_expected.name)
        self.thumbnail_request.emit(ep)

        row=self.hist.find(ep)
        local=disk_file(final_folder,ep,row)
        if local:
            if not row:self.hist.upsert(ep,local)
            cleanup_episode_temp(ep)
            return "ok"

        if self.stop_event.is_set(): return "stop"
        # Resolve entitlement and media URL through the direct SonyLIV API.
        # This is intentionally separate from yt-dlp's SonyLIV extractor: the
        # application's direct requests transport already reaches GETTOKEN
        # reliably, while the current curl_cffi path can fail with HTTP 0: OK.
        logger.info("Episode %s resolving SonyLIV media entitlement via direct API", ep.number)
        sony=SonyLiv(self.st["retries"])
        try:
            content=sony.video_content(ep.eid)
        except PremiumContentError as exc:
            logger.info("Episode %s is currently premium; skipping until SonyLIV makes it available: %s",
                        ep.number, exc)
            self.status.emit(f"Episode {ep.number} is currently premium — skipped")
            return "premium"

        if self.stop_event.is_set(): return "stop"
        if content.get("isEncrypted"):
            raise RuntimeError(f"Episode {ep.number} is DRM protected and cannot be downloaded by this downloader")
        stream_url=str(content.get("videoURL") or "").strip()
        if not stream_url.startswith(("https://","http://")):
            raise RuntimeError(f"SonyLIV returned no usable media URL for Episode {ep.number}")

        # Re-evaluate work directory after the authoritative episode object.
        work=episode_temp_dir(ep)
        work.mkdir(parents=True, exist_ok=True)
        stem=ep.stem()
        expected_work=work/(stem+".mp4")
        expected_final=final_folder/(stem+".mp4")

        def hook(d):
            if self.stop_event.is_set():
                raise RuntimeError("__STOP__")
            if d.get("status")=="downloading":
                total=d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got=d.get("downloaded_bytes") or 0
                pct=int(got*100/total) if total else 0
                speed=(d.get("_speed_str") or "").strip()
                eta=(d.get("_eta_str") or "").strip()
                self.current_progress.emit(
                    pct,"  ".join(x for x in (speed,("ETA "+eta if eta else "")) if x)
                )
                self.phase.emit("download")
                self.status.emit(f"Downloading Episode {ep.number}...")
            elif d.get("status")=="finished":
                self.current_progress.emit(100,"")
                self.phase.emit("finalizing")
                self.status.emit(f"Joining video and audio for Episode {ep.number}...")

        def pp_hook(d):
            if self.stop_event.is_set():
                raise RuntimeError("__STOP__")
            status=d.get("status")
            if status=="started":
                self.phase.emit("finalizing")
                self.status.emit(f"Finalizing Episode {ep.number} — please wait...")
            elif status=="finished":
                self.phase.emit("moving")
                self.status.emit(f"Saving Episode {ep.number}...")

        existing_parts=interrupted_download_files(final_folder,ep)
        if existing_parts:
            logger.info("Resuming Episode %s with %d existing managed temp file(s)",
                        ep.number,len(existing_parts))
            self.status.emit(f"Resuming Episode {ep.number}...")

        playback_headers={
            "x-playback-session-id": f"{uuid.uuid4().hex}-{int(time.time()*1000)}",
            "Referer":"https://www.sonyliv.com/",
            "Origin":"https://www.sonyliv.com",
        }
        opts=ytdlp_base_options()
        opts["http_headers"].update(playback_headers)
        opts.update({
            "format":"bestvideo+bestaudio/best",
            "merge_output_format":"mp4",
            "ffmpeg_location":str(FFMPEG_DIR),
            "outtmpl":str(work/(stem+".%(ext)s")),
            "quiet":True,"no_warnings":True,"noprogress":True,
            "progress_hooks":[hook],
            "postprocessor_hooks":[pp_hook],
            "concurrent_fragment_downloads":self.st["fragments"],
            "retries":self.st["retries"],
            "fragment_retries":self.st["retries"],
            "continuedl":True,"overwrites":False,
        })
        logger.info("Episode %s download using private temp directory: %s",ep.number,work)

        try:
            with YoutubeDL(opts) as y:
                result=y.extract_info(stream_url,download=True)
                prepared=Path(y.prepare_filename(result))
        except Exception as e:
            if isinstance(e, PremiumContentError):
                logger.info("Episode %s is currently premium; skipped", ep.number)
                self.status.emit(f"Episode {ep.number} is currently premium — skipped")
                return "premium"
            if "__STOP__" in str(e) or self.stop_event.is_set():
                logger.info("Episode %s stopped; resumable temp data preserved",ep.number)
                return "stop"
            msg=str(e)
            if "Use \"--username <mobile_number>\"" in msg or "--username token --password" in msg:
                logger.info("Episode %s requires SonyLIV authentication; treating as premium and skipping", ep.number)
                self.status.emit(f"Episode {ep.number} requires authentication — skipped")
                return "premium"
            logger.warning("yt-dlp behaved unexpectedly for Episode %s; forcing an immediate version check", ep.number)
            check_ytdlp_version(True)
            raise

        if self.stop_event.is_set():
            return "stop"

        candidates=[expected_work,prepared.with_suffix(".mp4"),prepared]
        final_work=next((p for p in candidates
                         if p.exists() and p.is_file() and p.stat().st_size>0),None)
        if not final_work:
            final_work=next((p for p in work.glob(f"{ep.number} - *")
                             if p.is_file()
                             and p.suffix.lower() not in (".part",".ytdl")
                             and p.stat().st_size>0),None)
        if not final_work:
            raise RuntimeError("Final media file could not be verified in temp directory")

        self.phase.emit("moving")
        self.status.emit(f"Moving Episode {ep.number} to your download folder...")
        if expected_final.exists():
            expected_final.unlink()
        shutil.move(str(final_work),str(expected_final))

        if not expected_final.exists() or expected_final.stat().st_size<=0:
            raise RuntimeError("Final media file could not be verified after move")

        self.hist.upsert(ep,expected_final)
        cleanup_episode_temp(ep)
        self.current_progress.emit(100,"")
        self.say(f"Completed Episode {ep.number}: {expected_final.name}")
        return "ok"

class UrlWorker(QObject):
    result=Signal(bool,str)
    def __init__(self,url,retries):super().__init__();self.url=url;self.retries=retries
    @Slot()
    def run(self):
        try:
            sid=show_id_from_url(self.url)
            if sid!=SHOW_ID:raise ValueError()
            eps=SonyLiv(self.retries).discover(sid)
            if not eps:raise ValueError()
            self.result.emit(True,f"Latest episodes are found.\n\nLatest detected episode: {eps[0].number}")
        except Exception:
            logger.exception("Manual URL check failed")
            self.result.emit(False,"Wrong URL is provided, check again")

DEFAULTS={"folder":str(PROJECT_DIR),"auto_source":True,"manual_url":DEFAULT_MANUAL_URL,
          "mode":"new","single":825,"from_ep":801,"to_ep":825,
          "parallel":2,"fragments":4,"retries":5,"check_missing_older":True}

def load_settings():
    s=DEFAULTS.copy()
    try:
        if SETTINGS_FILE.exists():s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:logger.exception("Settings load failed")
    return s
def normalize_settings(st):
    """Backwards-compatible settings schema used by background/on-demand workers."""
    merged=dict(DEFAULTS)
    if isinstance(st,dict):
        merged.update(st)
    # Old/new schema compatibility.
    if "auto" not in merged:
        merged["auto"] = merged.get("source","auto") != "manual"
    merged.setdefault("manual_url","")
    merged.setdefault("folder",str(PROJECT_DIR))
    merged.setdefault("mode","new")
    merged.setdefault("single",1)
    merged.setdefault("from_ep",1)
    merged.setdefault("to_ep",1)
    merged.setdefault("check_missing_older",True)
    return merged


def save_settings(s):
    SETTINGS_FILE.write_text(json.dumps(s,indent=2),encoding="utf-8")

class SettingsDialog(QDialog, SettingsUiForm):
    def __init__(self,parent,settings):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle(APP_NAME)
        self.s=settings.copy()
        self.setWindowTitle("MHJ Downloader Settings")
        self.setFixedSize(self.size())

        # Bind the Designer UI to the frozen v2.0.13 settings schema.
        self.auto = self.autoSourceRadioButton
        self.manual = self.manualSourceRadioButton
        self.url = self.manualUrlLineEdit
        self.check = self.checkUrlButton
        self.r_new = self.newEpisodesRadioButton
        self.r_single = self.specificEpisodeRadioButton
        self.r_range = self.episodeRangeRadioButton
        self.r_all = self.entireLibraryRadioButton
        self.single = self.specificEpisodeSpinBox
        self.fr = self.rangeFromSpinBox
        self.to = self.rangeToSpinBox
        self.folder = self.downloadFolderLineEdit
        self.browse = self.browseFolderButton
        self.parallel = self.simultaneousEpisodesSpinBox
        self.fragments = self.fragmentsSpinBox
        self.retries = self.retryAttemptsSpinBox
        self.check_missing = self.collectionMaintenanceCheckBox

        self.auto.setChecked(bool(self.s.get("auto_source",True)))
        self.manual.setChecked(not bool(self.s.get("auto_source",True)))
        self.url.setText(self.s.get("manual_url",DEFAULT_MANUAL_URL))
        # Restore the saved download folder. `folder` is canonical;
        # `download_folder` remains a legacy compatibility fallback.
        saved_folder = self.s.get("folder") or self.s.get("download_folder") or str(PROJECT_DIR)
        self.folder.setText(str(saved_folder))
        mode=self.s.get("mode","new")
        {"new":self.r_new,"single":self.r_single,"range":self.r_range,"all":self.r_all}.get(mode,self.r_new).setChecked(True)
        self.single.setRange(1,9999); self.single.setValue(int(self.s.get("single",825)))
        self.fr.setRange(1,9999); self.fr.setValue(int(self.s.get("from_ep",801)))
        self.to.setRange(1,9999); self.to.setValue(int(self.s.get("to_ep",825)))
        self.parallel.setRange(1,5); self.parallel.setValue(int(self.s.get("parallel",2)))
        self.fragments.setRange(1,16); self.fragments.setValue(int(self.s.get("fragments",4)))
        self.retries.setRange(1,20); self.retries.setValue(int(self.s.get("retries",5)))
        self.check_missing.setChecked(bool(self.s.get("check_missing_older",True)))

        self.cancelButton.clicked.connect(self.reject)
        self.saveButton.clicked.connect(self.accept_save)
        self.browse.clicked.connect(self.pick)
        self.check.clicked.connect(self.check_url)
        self.auto.toggled.connect(self.update_source)
        self.manual.toggled.connect(self.update_source)
        for r in (self.r_new,self.r_single,self.r_range,self.r_all):
            r.toggled.connect(self.update_selection_controls)
        self.update_source()
        self.update_selection_controls()

    def update_source(self):
        enabled=self.manual.isChecked()
        self.url.setEnabled(enabled)
        self.check.setEnabled(enabled)

    def update_selection_controls(self):
        self.single.setEnabled(self.r_single.isChecked())
        range_on=self.r_range.isChecked()
        self.fr.setEnabled(range_on)
        self.to.setEnabled(range_on)

    def pick(self):
        p=QFileDialog.getExistingDirectory(self,"Select Download Folder",self.folder.text())
        if p:self.folder.setText(p)

    def check_url(self):
        self.check.setEnabled(False)
        self.t=QThread()
        self.w=UrlWorker(self.url.text().strip(),self.retries.value())
        self.w.moveToThread(self.t)
        self.t.started.connect(self.w.run)
        self.w.result.connect(self.checked)
        self.w.result.connect(self.t.quit)
        self.t.finished.connect(self.w.deleteLater)
        self.t.finished.connect(self.t.deleteLater)
        self.t.start()

    def checked(self,ok,msg):
        self.check.setEnabled(True)
        (QMessageBox.information if ok else QMessageBox.warning)(self,APP_NAME,msg)

    def accept_save(self):
        folder=Path(self.folder.text().strip())
        if not folder.exists():
            QMessageBox.warning(self,APP_NAME,"Please select a valid download folder.")
            return
        mode="new" if self.r_new.isChecked() else "single" if self.r_single.isChecked() else "range" if self.r_range.isChecked() else "all"
        if mode=="all":
            if QMessageBox.question(self,APP_NAME,"Entire Library can download hundreds of episodes.\n\nSave this option?",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:
                return
        self.s.update({
            "folder":str(folder),"download_folder":str(folder),"auto_source":self.auto.isChecked(),
            "manual_url":self.url.text().strip(),"mode":mode,
            "single":self.single.value(),"from_ep":self.fr.value(),"to_ep":self.to.value(),
            "parallel":self.parallel.value(),"fragments":self.fragments.value(),
            "retries":self.retries.value(),"check_missing_older":self.check_missing.isChecked()
        })
        save_settings(self.s)
        self.accept()


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
def clean_console_text(value):
    s="" if value is None else str(value)
    s=ANSI_RE.sub("",s)
    s=re.sub(r"(?:\ufffd|\u001b)?\[[0-9;?]*[A-Za-z]","",s)
    return " ".join(s.replace("\r"," ").replace("\n"," ").split())

def friendly_download_info(value):
    s=clean_console_text(value)
    speed=re.search(r"(?i)(\d+(?:\.\d+)?)\s*([KMGTP]?i?B/s)",s)
    eta=re.search(r"(?i)\bETA\s+([0-9:]+)",s)
    parts=[]
    if speed: parts.append(f"{speed.group(1)} {speed.group(2)}")
    if eta: parts.append(f"ETA {eta.group(1)}")
    return "  •  ".join(parts) if parts else s

def compact_question(parent, title, message):
    """Compact, parent-friendly confirmation dialog without stretched orientation."""
    box=QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Question)
    box.setText(message)
    box.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
    box.setDefaultButton(QMessageBox.Yes)
    box.setStyleSheet("""
        QMessageBox { background:#f5f6f8; }
        QMessageBox QLabel { color:#202124; min-width:0px; max-width:360px; }
        QMessageBox QPushButton { min-width:82px; min-height:28px; padding:3px 10px; }
    """)
    box.setMinimumWidth(430)
    return box.exec()==QMessageBox.Yes


class MainWindow(QMainWindow, MainUiForm):
    def __init__(self):
        self._close_after_stop=False
        self._preflight_sony=None
        self._preflight_disk=None
        self._preflight_settings=None
        self._preflight_running=False
        self._download_requested=False
        self._is_busy=False
        self._queue_total=0
        self._queue_completed=0
        self._current_episode_pct=0
        super().__init__()
        self.s=load_settings()
        self.scan_t=self.scan_w=self.dl_t=self.dl_w=None
        self.setupUi(self)
        self.thumbnail_service=ThumbnailService()
        self.thumbnail_service.ready.connect(self.set_thumb)
        self.thumbnail_service.failed.connect(self.thumbnail_failed)
        self._thumbnail_episode=0
        self.setWindowTitle("MHJ Downloader • Maharashtrachi Hasya Jatra")
        self.setFixedSize(self.size())
        self.build()
        self._active_settings = None
        self._sony_facts = None
        self._disk_facts = None
        self._preflight_sony = None
        self._preflight_disk = None
        start_ytdlp_version_check(False)
        QTimer.singleShot(300,self.start_preflight)

    def build(self):
        # Compatibility aliases let the frozen v2.0.13 engine continue to use
        # its established widget references while presentation comes from Designer.
        self.settings=self.settingsButton
        self.download=self.downloadButton
        self.stop=self.stopButton
        self.status=self.statusLabel
        self.thumb=self.thumbnailLabel
        self.ep=self.episodeTitleLabel
        self.fn=self.filenameLabel
        self.current=self.currentProgressBar
        self.overall=self.overallProgressBar
        self.detail=self.otherInfoLabel
        self.detail.setText("")
        self.status.setWordWrap(False)
        self.download.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.stop.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.download.setMinimumHeight(48)
        self.stop.setMinimumHeight(38)
        self.download.setStyleSheet("""
            QPushButton { background:#198754; color:white; border:1px solid #146c43; border-radius:4px; font-weight:600; padding:8px 18px; }
            QPushButton:hover { background:#157347; }
            QPushButton:pressed { background:#146c43; }
            QPushButton:disabled { background:#39453d; color:#89918b; border-color:#465049; }
        """)
        self.stop.setStyleSheet("""
            QPushButton { background:#dc3545; color:white; border:1px solid #b02a37; border-radius:4px; font-weight:600; padding:8px 18px; }
            QPushButton:hover { background:#bb2d3b; }
            QPushButton:pressed { background:#b02a37; }
            QPushButton:disabled { background:#493638; color:#97898a; border-color:#574144; }
        """)
        info_box=self.thumb.parentWidget()
        while info_box is not None and not isinstance(info_box,QGroupBox):
            info_box=info_box.parentWidget()
        if isinstance(info_box,QGroupBox):
            for lbl in info_box.findChildren(QLabel):
                if lbl not in (self.thumb,self.ep,self.fn,self.detail) and lbl.text().strip()=="TextLabel":
                    lbl.clear()
        # Hide the Designer placeholder caption on the controls group.
        box=self.download.parentWidget()
        while box is not None and not isinstance(box,QGroupBox):
            box=box.parentWidget()
        if isinstance(box,QGroupBox):
            box.setTitle("")

        # Runtime-enforced properties that Qt Designer preview did not reliably retain.
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFrameShape(QFrame.Box)
        self.thumb.setFrameShadow(QFrame.Plain)
        self.thumb.setLineWidth(1)
        self.thumb.setScaledContents(False)
        self.ep.setWordWrap(True)
        self.fn.setWordWrap(True)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignCenter)

        self.current.setRange(0,100)
        self.overall.setRange(0,100)
        self.current.setValue(0)
        self.overall.setValue(0)
        self.current.setFormat("%p%")
        self.overall.setFormat("%p%")
        self.current.setTextVisible(True)
        self.overall.setTextVisible(True)

        self.download.setText("DOWNLOAD")
        self.stop.setText("STOP")
        self.status.setText("Preparing collection in background...")
        self.ep.setText("No episode is being downloaded.")
        self.fn.setText("")
        self.detail.setText("Ready")

        self.settings.clicked.connect(self.open_settings)
        self.download.clicked.connect(self.start_scan)
        self.stop.clicked.connect(self.stop_now)
        self.stop.setEnabled(False)
    def reset_download_display(self, checking=False):
        """
        Clear information belonging to the previous download session.

        This is presentation-only. It does NOT delete or modify any
        yt-dlp fragment/part/state files.
        """
        self.thumbnail_service.invalidate()
        self._thumbnail_episode = 0

        self._queue_total = 0
        self._queue_completed = 0
        self._current_episode_pct = 0

        self.thumb.clear()
        self.thumb.setAlignment(Qt.AlignCenter)

        self.ep.setText("No episode selected yet.")
        self.fn.setText("")

        self.current.setValue(0)
        self.overall.setValue(0)

        self.detail.setText("")

        if checking:
            self.status.setText("Checking SonyLIV and local collection...")
        else:
            self.status.setText("Ready")
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    def busy(self,b):
        self._is_busy=bool(b)
        self.download.setEnabled(not b);self.settings.setEnabled(not b);self.stop.setEnabled(b)
    def open_settings(self):
        d=SettingsDialog(self,self.s)
        if d.exec()==QDialog.Accepted:
            self.s=d.s
            self._preflight_sony=None;self._preflight_disk=None;self._preflight_settings=None
            self.status.setText("Settings saved. Refreshing in background...")
            QTimer.singleShot(100,self.start_preflight)
    def start_preflight(self):
        logger.info("Background preflight trigger fired")
        if self._is_busy or self._preflight_running:
            return
        try:
            st=normalize_settings(load_settings())
            sid=show_id_from(st.get("manual_url","")) if not st.get("auto",True) else SHOW_ID
            self._preflight_settings=st
            self._preflight_sony=None
            self._preflight_disk=None
            self._preflight_running=True
            self.status.setText("Preparing collection in background...")

            logger.info("Creating background SonyLIV worker for show ID %s",sid)
            self.scan_thread=QThread();self.scan=ScanWorker(st,sid);self.scan.moveToThread(self.scan_thread)
            self.scan_thread.started.connect(self.scan.run)
            self.scan.ready.connect(self._preflight_sony_ready)
            self.scan.error.connect(self._preflight_error)
            self.scan.ready.connect(self.scan_thread.quit);self.scan.error.connect(self.scan_thread.quit)

            self.disk_thread=QThread();self.disk_worker=LocalDiskWorker(st["folder"]);self.disk_worker.moveToThread(self.disk_thread)
            self.disk_thread.started.connect(self.disk_worker.run)
            self.disk_worker.ready.connect(self._preflight_disk_ready)
            self.disk_worker.error.connect(self._preflight_error)
            self.disk_worker.ready.connect(self.disk_thread.quit);self.disk_worker.error.connect(self.disk_thread.quit)

            logger.info("Background cascade preflight started: SonyLIV + local disk")
            self.scan_thread.start();self.disk_thread.start()
        except Exception:
            self._preflight_running=False
            self._preflight_sony=None;self._preflight_disk=None
            logger.exception("Could not start background preflight")
            self.status.setText("Ready - press Download to retry")

    def _preflight_sony_ready(self,episodes,_m,_h,_i):
        self._preflight_sony=episodes
        logger.info("Background preflight received SonyLIV facts")
        self._preflight_maybe_ready()

    def _preflight_disk_ready(self,facts):
        self._preflight_disk=facts
        logger.info("Background preflight received local disk facts")
        self._preflight_maybe_ready()

    def _preflight_error(self,msg):
        self._preflight_running=False
        self._preflight_sony=None;self._preflight_disk=None
        logger.error("Background preflight failed: %s",msg)
        self.status.setText("Ready - press Download to retry")
        # If Download was already pressed while preparation was running, retry
        # through the normal on-demand path instead of silently stalling.
        if self._download_requested:
            self._download_requested=False
            QTimer.singleShot(100,self.start_scan)

    def _preflight_maybe_ready(self):
        if self._preflight_sony is None or self._preflight_disk is None:
            return
        self._preflight_running=False
        self.status.setText("Ready")
        logger.info("Background cascade preflight ready")
        if self._download_requested:
            self._download_requested=False
            self.start_scan()

    def start_scan(self):
        logger.info("GUI Download button pressed")

        if self._is_busy:
            return

        # If a background preflight is already running, don't create another
        # SonyLIV/local-disk scan. Remember the click and automatically
        # continue when the existing preflight finishes.
        if self._preflight_running:
            self._download_requested = True
            self.reset_download_display(checking=False)
            self.status.setText("Preparing... download will start automatically")
            logger.info("Download requested while background preflight is running")
            return

        current = normalize_settings(load_settings())
        self._active_settings = current

        # Reuse a completed background snapshot only when it belongs to the
        # exact same settings currently in use.
        if (
            self._preflight_sony is not None
            and self._preflight_disk is not None
            and self._preflight_settings == current
        ):
            logger.info("Download using prepared background cascade facts")

            self.reset_download_display(checking=True)
            self.busy(True)

            hist = History(HISTORY_FILE)
            self._active_settings = current
            self._sony_facts = self._preflight_sony
            self._disk_facts = self._preflight_disk
            q, m, h, i = CascadeEngine(
                current,
                hist,
                self._preflight_sony,
                self._preflight_disk,
            ).decide()

            # Snapshot has now been consumed. Never reuse it after a download
            # because the local collection may change while downloading.
            self._preflight_sony = None
            self._preflight_disk = None
            self._preflight_settings = None

            self.scan_ready(q, m, h, i)
            return

        # No usable snapshot exists.
        #
        # Perform a fresh SonyLIV + local filesystem reconciliation.
        # This is especially important after STOP because .part/.ytdl/
        # fragment files may have changed since the previous session.
        logger.info(
            "No valid prepared snapshot; starting fresh on-demand cascade workers"
        )

        self.reset_download_display(checking=True)
        self.busy(True)

        self._sony_facts = None
        self._disk_facts = None
        self._active_settings = current

        sid = (
            show_id_from(current.get("manual_url", ""))
            if not current.get("auto", True)
            else SHOW_ID
        )

        try:
            logger.info(
                "Creating on-demand SonyLIV worker for show ID %s",
                sid,
            )

            self.scan_thread = QThread()
            self.scan = ScanWorker(current, sid)
            self.scan.moveToThread(self.scan_thread)

            self.scan_thread.started.connect(self.scan.run)
            self.scan.log.connect(self.status.setText)

            self.scan.ready.connect(self._sony_ready)
            self.scan.error.connect(self.scan_error)

            self.scan.ready.connect(self.scan_thread.quit)
            self.scan.error.connect(self.scan_thread.quit)

            self.disk_thread = QThread()
            self.disk_worker = LocalDiskWorker(current["folder"])
            self.disk_worker.moveToThread(self.disk_thread)

            self.disk_thread.started.connect(self.disk_worker.run)
            self.disk_worker.ready.connect(self._disk_ready)
            self.disk_worker.error.connect(self.scan_error)

            self.disk_worker.ready.connect(self.disk_thread.quit)
            self.disk_worker.error.connect(self.disk_thread.quit)

            logger.info(
                "Starting on-demand parallel fact workers: SonyLIV + local disk"
            )

            self.scan_thread.start()
            self.disk_thread.start()

        except Exception as exc:
            logger.exception("Could not start on-demand cascade workers")

            self._sony_facts = None
            self._disk_facts = None

            self.busy(False)

            self.status.setText(
                "Could not check SonyLIV and local collection."
            )

            QMessageBox.critical(
                self,
                APP_NAME,
                "The episode check could not be started.\n\n"
                "Technical details were saved in the activity log.",
            )

    def _sony_ready(self,episodes,_m,_h,_i):
        self._sony_facts=episodes;logger.info("GUI received SonyLIV facts");self._try_cascade()

    def _disk_ready(self,facts):
        self._disk_facts=facts;logger.info("GUI received local disk facts");self._try_cascade()

    def _try_cascade(self):
        if self._sony_facts is None or self._disk_facts is None:return
        self.status.setText("Reconciling collection...")
        hist=History(HISTORY_FILE)
        q,m,h,i=CascadeEngine(self._active_settings,hist,self._sony_facts,self._disk_facts).decide()
        self.scan_ready(q,m,h,i)

    def scan_ready(self,queue,missing,historical_missing,interrupted):
        selected=list(queue)
        if interrupted:
            nums=", ".join(str(e.number) for e in interrupted)
            if len(interrupted)==1:
                msg=(f"Episode {nums} was interrupted before the download finished.\n\n"
                     "Do you want to resume it?")
            else:
                msg=(f"{len(interrupted)} interrupted downloads were found.\n\n"
                     f"Episodes: {nums}\n\nDo you want to resume them?")
            if compact_question(self,"Resume Download",msg):
                selected.extend(interrupted)
                logger.info("User accepted interrupted download resume: %s",nums)
            else:
                logger.info("User declined interrupted download resume: %s",nums)
        if missing:
            nums=", ".join(str(e.number) for e in missing[:20])+("..." if len(missing)>20 else "")
            if len(missing) == 1:
                msg=f"Episode {nums} was downloaded before, but its video file is missing.\n\nDo you want to download it again?"
            else:
                msg=f"These episodes were downloaded before, but their video files are missing:\n\n{nums}\n\nDo you want to download them again?"
            if compact_question(self,APP_NAME,msg): selected.extend(missing)
        if historical_missing:
            nums=", ".join(str(e.number) for e in historical_missing)
            if len(historical_missing) == 1:
                msg=(f"1 older episode is missing from the collection.\n\n"
                     f"Episode {nums} is missing.\n\nDo you want to download it?")
            else:
                msg=(f"{len(historical_missing)} older episodes are missing from the collection.\n\n"
                     f"Episodes {nums} are missing.\n\nDo you want to download them?")
            if compact_question(self,"Missing Episodes",msg):
                selected.extend(historical_missing)
                logger.info("User accepted historical missing episodes: %s",nums)
            else:
                logger.info("User declined historical missing episodes: %s",nums)
        # Deduplicate by authoritative episode number.
        selected=list({e.number:e for e in selected}.values())
        selected.sort(key=lambda e:e.number,reverse=True)
        
        if self._active_settings.get("mode") == "new":
            media_count=len((self._disk_facts or {}).get("media", {}))
            if media_count == 0 and selected:
                logger.info("New Episodes mode: destination is empty; latest 10 episode limit warning shown to user")
                if not compact_question(
                    self,
                    "Download Latest Episodes",
                    "Only the latest 10 episodes will be downloaded.\n\n"
                    "To download more, select Range of Episodes in the Settings window.\n\n"
                    "Do you want to continue?"
                ):
                    logger.info("User declined latest-10 download warning")
                    self.busy(False)
                    self.status.setText("Download cancelled.")
                    self.download.setText("DOWNLOAD")
                    return
                logger.info("User accepted latest-10 download warning")
        if not selected:
            self.busy(False)
            logger.info("No new episodes found.")
            self.status.setText("✓ You're up to date!  There are no new episodes to download.")
            self.detail.setText("No new episodes found.")
            self.download.setText("DOWNLOAD")
            return
        self.status.setText(f"{len(selected)} episode(s) ready. Starting download...")
        self.detail.setText(f"0 of {len(selected)} episodes completed")
        self._queue_total=len(selected);self._queue_completed=0;self._current_episode_pct=0
        self.dl_t=QThread();self.dl_w=DownloadWorker(selected,self.s);self.dl_w.moveToThread(self.dl_t);self.dl_t.started.connect(self.dl_w.run)
        self.dl_w.log.connect(lambda s: logger.info("GUI: %s",s));self.dl_w.started.connect(self.started);self.dl_w.thumbnail_request.connect(self.start_thumbnail_probe)
        self.dl_w.current_progress.connect(self.progress);self.dl_w.overall.connect(self.overall_progress);self.dl_w.status.connect(self.status.setText);self.dl_w.phase.connect(self.download_phase)
        self.dl_w.finished.connect(self.finished);self.dl_w.error.connect(self.fail);self.dl_w.finished.connect(self.dl_t.quit);self.dl_w.error.connect(self.dl_t.quit)
        self.dl_t.finished.connect(self.dl_w.deleteLater);self.dl_t.finished.connect(self.dl_t.deleteLater);self.dl_t.start()
    def started(self,name,fn):
        self._current_episode_pct=0;self.current.setRange(0,100);self.current.setFormat("%p%");self.current.setValue(0)
        self.ep.setText(name);self.fn.setText(fn);self.detail.setText("Starting download...")
        self.thumb.clear();self.thumb.setAlignment(Qt.AlignCenter);self.thumb.setText("Loading thumbnail...")
    def start_thumbnail_probe(self,ep):
        self._thumbnail_episode=int(ep.number or 0)
        self.thumbnail_service.invalidate()
        self.thumb.clear();self.thumb.setAlignment(Qt.AlignCenter);self.thumb.setText("Loading thumbnail...")
        logger.info("Episode %s asynchronous thumbnail probe started",ep.number)
        self.thumbnail_service.request(ep,int(self.s.get("retries",5)))

    def set_thumb(self,episode_number,data):
        if int(episode_number)!=int(self._thumbnail_episode):
            return
        p=QPixmap()
        if p.loadFromData(data) and not p.isNull():
            logger.info("GUI thumbnail decoded successfully for episode %s: %dx%d",episode_number,p.width(),p.height())
            self.thumb.setAlignment(Qt.AlignCenter)
            self.thumb.setPixmap(p.scaled(self.thumb.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:
            logger.warning("GUI could not decode episode %s thumbnail (%d bytes)",episode_number,len(data) if data else 0)
            self.thumb.setAlignment(Qt.AlignCenter);self.thumb.setText("Thumbnail unavailable")

    def thumbnail_failed(self,episode_number,message):
        if int(episode_number)!=int(self._thumbnail_episode):
            return
        self.thumb.clear();self.thumb.setAlignment(Qt.AlignCenter);self.thumb.setText("No thumbnail")
        logger.info("GUI kept running after episode %s thumbnail failure: %s",episode_number,message)
    def progress(self,pct,detail):
        self._current_episode_pct=max(0,min(100,int(pct)))
        if self.current.minimum()!=0 or self.current.maximum()!=100:
            self.current.setRange(0,100);self.current.setFormat("%p%")
        self.current.setValue(self._current_episode_pct)
        self.detail.setText(friendly_download_info(detail))
        if self._queue_total:
            overall=int(((self._queue_completed+self._current_episode_pct/100.0)/self._queue_total)*100)
            self.overall.setValue(max(0,min(100,overall)))
    def download_phase(self,phase):
        if phase=="finalizing":
            # FFmpeg/yt-dlp does not expose a trustworthy merge percentage.
            # An indeterminate bar makes it obvious that work is still active.
            self.current.setRange(0,0)
            self.detail.setText("Joining video and audio — please wait...")
        elif phase=="moving":
            self.current.setRange(0,0)
            self.detail.setText("Saving completed episode...")
        else:
            if self.current.minimum()!=0 or self.current.maximum()!=100:
                self.current.setRange(0,100)
                self.current.setFormat("%p%")

    def overall_progress(self,n,total):
        self._queue_completed=n;self._queue_total=total;self._current_episode_pct=0
        self.overall.setValue(int(n*100/total) if total else 0)
        self.detail.setText(f"{n} of {total} episodes completed")
    def finished(self, s):
        self.busy(False)
        self.thumbnail_service.invalidate()
        self._preflight_sony=None
        self._preflight_disk=None
        self._preflight_settings=None
        self.current.setRange(0,100)
        self.current.setFormat("%p%")

        if s["stopped"]:
            self.status.setText("Download stopped.")
            self.detail.setText("Press DOWNLOAD when you want to continue.")
            logger.info("Download session stopped; resumable temp data preserved")

        elif s["failed"]:
            self.status.setText(
                f"Finished with {s['failed']} problem(s). Please check the activity log."
            )
            if s.get("premium"):
                self.detail.setText(
                    f"{s.get('premium',0)} premium episode(s) skipped"
                )
            logger.info(
                "Download session finished with errors; premium_skipped=%d",
                s.get("premium",0)
            )

        else:
            # Successful terminal state:
            # Clear all information belonging to the completed download session.
            # Premium episodes are intentionally treated as skipped, not failed.
            cleanup_finished_temp()

            self.thumb.clear()
            self.thumb.setAlignment(Qt.AlignCenter)
            self._thumbnail_episode=0

            self.ep.setText("")
            self.fn.setText("")

            self.current.setValue(0)
            self.overall.setValue(100)

            self.detail.setText("")
            self.status.setText("Ready")

            logger.info(
                "Download queue completed; downloaded=%d premium_skipped=%d; "
                "managed temp clutter cleaned",
                s.get("downloaded",0),
                s.get("premium",0)
            )

            # If premium episodes were encountered but there were no actual
            # download failures, the collection is otherwise complete.
            if s.get("premium"):
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "All Episodes are downloaded"
                )

        if self._close_after_stop:
            QTimer.singleShot(0,self._force_close)
            return

        QTimer.singleShot(500,self.start_preflight)

    def scan_error(self,msg):
        """Handle failure of an on-demand SonyLIV/local-disk fact worker."""
        logger.error("On-demand cascade worker failed: %s", msg)
        self._sony_facts=None
        self._disk_facts=None
        self._active_settings=None
        self.busy(False)
        self.status.setText("Could not check SonyLIV and local collection.")
        QMessageBox.critical(
            self,
            APP_NAME,
            "Could not check SonyLIV and local collection.\n\n"
            "Please check the activity log for details."
        )

    def fail(self,msg):
        self.busy(False);self.status.setText("Something went wrong. Please ask Siddhesh to check the activity log.")
        QMessageBox.critical(self,APP_NAME,f"Download could not continue.\n\n{msg}\n\nTechnical details were saved in the activity log.")
    def stop_now(self):
        logger.info("GUI MASTER STOP pressed")
        self.thumbnail_service.invalidate()
        self._download_requested=False

        # Cancel an active download immediately. The worker also kills any
        # descendant FFmpeg process so STOP remains effective during merging.
        if self.dl_w:
            self.dl_w.stop()
            self.status.setText("Stopping immediately...")
            return

        # Preflight/scan workers do not own media files. We cannot safely
        # terminate a QThread that is inside requests/yt-dlp, so invalidate
        # the pending action and return control to the user immediately.
        if self._preflight_running or getattr(self,"_sony_facts",None) is not None:
            self._preflight_sony=None;self._preflight_disk=None;self._preflight_settings=None
            self._sony_facts=None;self._disk_facts=None
            self._preflight_running=False
            self.busy(False)
            self.status.setText("Stopped.")
            logger.info("Preflight result invalidated by MASTER STOP")
            return

        self.status.setText("Stopped.")

    def closeEvent(self,e):
        if getattr(self,"_super_closing",False):
            e.accept()
            return
        if self._is_busy or self._preflight_running:
            self._close_after_stop=True
            e.ignore()
            self.status.setText("Closing — terminating active work...")
            logger.info("SUPER MASTER close requested")
            self.thumbnail_service.invalidate()
            if self.dl_w:
                self.dl_w.stop()
            # Give the worker a very short chance to preserve its normal
            # resumable state, then force-close if anything is still alive.
            QTimer.singleShot(700,self._force_close)
        else:
            e.accept()

    def _force_close(self):
        if getattr(self,"_super_closing",False):
            return
        self._super_closing=True
        logger.info("SUPER MASTER close executing")
        kill_descendant_processes()
        QApplication.quit()
        # If a non-cooperative network/QThread call still prevents Qt from
        # exiting, terminate this process. Temp .part/.ytdl files remain
        # resumable because completed media is moved only after verification.
        QTimer.singleShot(300,lambda: os._exit(0))


def main():
    if FFMPEG_EXE.exists() and FFPROBE_EXE.exists():
        logger.info("FFmpeg available: %s", FFMPEG_EXE)
        logger.info("FFprobe available: %s", FFPROBE_EXE)
    else:
        logger.error("FFmpeg not found. Expected: %s", FFMPEG_EXE)
        logger.error("FFprobe not found. Expected: %s", FFPROBE_EXE)
    app=QApplication(sys.argv);app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMessageBox { background: #f5f6f8; }
        QMessageBox QLabel { color: #202124; }
        QMessageBox QPushButton { min-width: 76px; padding: 5px 12px; }
        QPushButton:disabled { color: #8a8f98; }
    """)
    w=MainWindow();w.show();return app.exec()
if __name__=="__main__":sys.exit(main())
