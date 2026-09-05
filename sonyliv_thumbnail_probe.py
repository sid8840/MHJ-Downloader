#!/usr/bin/env python3
"""
Standalone MHJ SonyLIV metadata/thumbnail probe.

Uses the exact SonyLiv API implementation copied from the user's working
MHJ Downloader source. It does not import or modify main.py.

Usage:
    python sonyliv_thumbnail_probe_exact.py 820
"""

import sys
import json
import re
import time
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL

PROJECT_DIR = Path(__file__).resolve().parent
SHOW_ID = "1700000221"
DEFAULT_MANUAL_URL = "https://www.sonyliv.com/shows/maharashtrachi-hasya-jatra-hasnya-cha-common-reason-1700000221/episodes/801-900"
CATALOGUE_FILE = PROJECT_DIR / "mhj_catalogue.json"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("thumbnail-probe")

@dataclass
class Episode:
    number: int
    eid: str
    url: str
    title: str = ""
    date: str = ""
    thumbnail: str = ""

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



IMAGE_HINTS = (
    "image", "img", "thumbnail", "thumb", "poster", "landscape",
    "portrait", "banner", "cover", "still", "picture", "photo", "sprite"
)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")


def walk(obj, path="$"):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def find_episode_in_json(payload, wanted):
    """Find the smallest useful dict whose metadata says episodeNumber=wanted."""
    matches = []
    for path, d in walk(payload):
        md = d.get("metadata") if isinstance(d, dict) else None
        if not isinstance(md, dict):
            continue
        n = md.get("episodeNumber") or md.get("episode")
        try:
            n = int(n)
        except Exception:
            continue
        if n == wanted:
            matches.append((len(json.dumps(d, ensure_ascii=False)), path, d))
    if not matches:
        return None, None
    matches.sort(key=lambda x: x[0])
    _, path, obj = matches[0]
    return path, obj


def collect_image_urls(obj):
    """Collect every image-looking absolute URL anywhere in the episode object."""
    found, seen = [], set()

    def rec(x, path="$"):
        if isinstance(x, dict):
            for k, v in x.items():
                p = f"{path}.{k}"
                if isinstance(v, str):
                    value = v.strip().replace("\\/", "/")
                    if value.startswith("//"):
                        value = "https:" + value
                    lk = str(k).lower()
                    if value.startswith(("http://", "https://")):
                        if any(h in lk for h in IMAGE_HINTS) or any(e in value.lower() for e in IMAGE_EXTS):
                            if value not in seen:
                                seen.add(value)
                                found.append((p, value))
                else:
                    rec(v, p)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                rec(v, f"{path}[{i}]")

    rec(obj)
    return found


def ext_from_response(r, url):
    ctype = r.headers.get("content-type", "").split(";", 1)[0].lower().strip()
    known = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
        "image/webp": ".webp", "image/avif": ".avif", "image/gif": ".gif",
    }
    if ctype in known:
        return known[ctype]
    ext = Path(urlparse(url).path).suffix.lower()
    if ext == ".jpeg":
        return ".jpg"
    return ext if ext in IMAGE_EXTS else ".img"


def main():
    wanted = int(sys.argv[1]) if len(sys.argv) > 1 else 820
    print(f"SonyLIV direct thumbnail probe — Episode {wanted}")
    print(f"Project directory: {PROJECT_DIR}")

    client = SonyLiv(5)

    # Use the exact working token/retry/session implementation.
    client.token()
    print("GETTOKEN: OK")

    detail = client.get(
        f"{client.BASE}/1.9/R/ENG/WEB/IN/DL/DETAIL/{SHOW_ID}",
        {"kids_safe": "false", "from": "0", "to": "49"},
    )
    print("SHOW DETAIL: OK")

    detail_file = PROJECT_DIR / "thumbnail_probe_show_detail.json"
    detail_file.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")

    # First try to find the episode directly in the large show-detail response.
    raw_path, episode_obj = find_episode_in_json(detail, wanted)

    # If the detail response only contains season/range descriptors, fetch ONLY
    # the target 100-episode bundle and search that response.
    source = "show detail"
    if episode_obj is None:
        low = ((wanted - 1) // 100) * 100 + 1
        high = low + 99
        range_text = f"{low}-{high}"
        print(f"Episode not embedded directly; locating bundle for range {range_text}...")

        seasons = []
        try:
            seasons = detail["resultObj"]["containers"][0]["containers"]
        except Exception:
            pass

        target = None
        for season in seasons:
            if not isinstance(season, dict):
                continue
            title = str((season.get("metadata") or {}).get("title") or "")
            if title.replace(" ", "") == range_text or range_text in title.replace(" ", ""):
                target = season
                break

        if target is None:
            raise RuntimeError(f"Could not identify SonyLIV bundle for episode range {range_text}")

        bundle_id = str(target.get("id") or "")
        if not bundle_id.isdigit():
            raise RuntimeError(f"Invalid bundle ID for range {range_text}: {bundle_id!r}")

        print(f"Target bundle: {bundle_id} ({range_text})")
        for start in (0, 100):
            payload = client.get(
                f"{client.BASE}/1.4/R/ENG/WEB/IN/CONTENT/DETAIL/BUNDLE/{bundle_id}",
                {"from": str(start), "to": str(start + 99),
                 "orderBy": "episodeNumber", "sortOrder": "desc"},
            )
            raw_path, episode_obj = find_episode_in_json(payload, wanted)
            if episode_obj is not None:
                source = f"bundle {bundle_id}"
                break

    if episode_obj is None:
        raise RuntimeError(f"Episode {wanted} was not found in SonyLIV JSON")

    print(f"EPISODE FOUND in {source}: {raw_path}")

    raw_file = PROJECT_DIR / f"episode_{wanted}_raw_metadata.json"
    raw_file.write_text(json.dumps(episode_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Raw metadata saved: {raw_file.name}")

    # Print emfAttributes keys because this is the area SonyLIV appears to use
    # for episode artwork.
    md = episode_obj.get("metadata") or {}
    emf = md.get("emfAttributes") or episode_obj.get("emfAttributes") or {}
    if isinstance(emf, dict):
        print("\nemfAttributes image-related fields:")
        any_printed = False
        for k, v in emf.items():
            lk = str(k).lower()
            if any(h in lk for h in IMAGE_HINTS):
                print(f"  {k} = {v}")
                any_printed = True
        if not any_printed:
            print("  (none with image-like key names)")

    images = collect_image_urls(episode_obj)
    candidates_file = PROJECT_DIR / f"episode_{wanted}_image_candidates.json"
    candidates_file.write_text(
        json.dumps([{"json_path": p, "url": u} for p, u in images],
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nImage candidates found: {len(images)}")
    print(f"Candidate list saved: {candidates_file.name}")

    if not images:
        print("\nNo image URL was present in the episode object.")
        print(f"Please upload {raw_file.name}")
        return 2

    # Prefer normal episode art over sprite sheets when possible.
    def rank(item):
        path, url = item
        s = (path + " " + url).lower()
        score = 0
        if "thumbnail" in s: score += 100
        if "landscape" in s: score += 90
        if "poster" in s: score += 80
        if "image" in s: score += 50
        if "sprite" in s: score -= 100
        return score

    images.sort(key=rank, reverse=True)

    for i, (path, url) in enumerate(images, 1):
        print(f"\n[{i}/{len(images)}] {path}")
        print(f"  {url}")
        try:
            # Do not send SonyLIV API security headers to the CDN.
            r = requests.get(
                url,
                headers={
                    "User-Agent": client.s.headers.get("User-Agent", "Mozilla/5.0"),
                    "Referer": "https://www.sonyliv.com/",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
                timeout=20,
            )
            ctype = r.headers.get("content-type", "")
            print(f"  HTTP {r.status_code}, {ctype}, {len(r.content)} bytes")
            if r.ok and r.content and ctype.lower().startswith("image/"):
                ext = ext_from_response(r, url)
                outfile = PROJECT_DIR / f"episode_{wanted}_thumbnail{ext}"
                outfile.write_bytes(r.content)
                print("\nSUCCESS")
                print(f"Thumbnail saved: {outfile}")
                return 0
        except Exception as exc:
            print(f"  Failed: {exc}")

    print("\nEpisode metadata contained image URL(s), but none downloaded successfully.")
    print(f"Please upload {raw_file.name} and {candidates_file.name}")
    return 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logger.exception("Probe failed")
        raise SystemExit(1)
