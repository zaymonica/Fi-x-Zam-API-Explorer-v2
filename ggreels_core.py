#!/usr/bin/env python3
"""GGReels core — scraper katalog/episode + video via @GGReelsBot.
Tanpa proxy sonzaix. Drama Sub Indo."""
import asyncio, os, re, time
import requests
from bs4 import BeautifulSoup

BASE = "https://ggreels.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36"
VIDEO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos")
os.makedirs(VIDEO_DIR, exist_ok=True)

# Telegram (untuk download video)
API_ID = 11511839
API_HASH = "0e917a8ab7aa6e9886c03913ca4341d1"
TG_SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ggreels_session.txt")
BOT = "GGReelsBot"


def _get(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    return r.text


def catalog():
    """Scrape katalog drama dari ggreels.com. Return list {id, title, url}."""
    html = _get(BASE)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=re.compile(r"/f/([0-9A-F]+)")):
        href = a.get("href", "")
        m = re.search(r"/f/([0-9A-F]+)", href)
        if not m:
            continue
        fid = m.group(1)
        if fid in seen:
            continue
        seen.add(fid)
        # judul dari alt img atau text
        img = a.find("img")
        title = ""
        if img and img.get("alt"):
            title = img.get("alt")
        if not title:
            title = re.sub(r"<[^>]+>", " ", str(a)).strip()
        title = re.sub(r"\s*Sub Indo\s*$", "", title).strip()
        out.append({"id": fid, "title": title, "url": f"{BASE}/f/{fid}"})
    return out


def episodes(drama_id):
    """Scrape episode list dari ggreels.com/f/{id}. Return {title, poster, episodes:[{ep, url}]}."""
    html = _get(f"{BASE}/f/{drama_id}")
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title:
        title = soup.title.get_text().replace(" Sub Indo · GGReels", "").strip()
    poster = ""
    og = soup.find("meta", property="og:image")
    if og:
        poster = og.get("content", "")
    # episode links: /f/{id}/ep/{n}
    eps = []
    seen = set()
    for a in soup.find_all("a", href=re.compile(rf"/f/{drama_id}/ep/(\d+)")):
        m = re.search(rf"/f/{drama_id}/ep/(\d+)", a.get("href", ""))
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            eps.append({"ep": int(m.group(1)), "url": f"{BASE}/f/{drama_id}/ep/{m.group(1)}"})
    eps.sort(key=lambda x: x["ep"])
    # part info dari meta description
    desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md:
        desc = md.get("content", "")
    return {"id": drama_id, "title": title, "poster": poster, "description": desc,
            "episode_count": len(eps), "episodes": eps}


# ---- Video via @GGReelsBot (Telegram) ----

def get_video(drama_id, timeout=90):
    """Interaksi ke @GGReelsBot, download video. Return path file lokal."""
    # cek cache
    cached = os.path.join(VIDEO_DIR, f"ggreels_{drama_id}_part1.mp4")
    if os.path.exists(cached) and os.path.getsize(cached) > 0:
        return cached

    from telethon import TelegramClient, events
    from telethon.sessions import StringSession

    sess = ""
    if os.path.exists(TG_SESSION_FILE):
        sess = open(TG_SESSION_FILE).read().strip()
    if not sess:
        raise RuntimeError("TG session belum ada — login dulu (tg_login2.py)")

    async def _dl():
        client = TelegramClient(StringSession(sess), API_ID, API_HASH)
        await client.connect()
        bot = await client.get_entity(BOT)
        await client.send_message(bot, f"/start {drama_id}")
        videos = []

        @client.on(events.NewMessage(from_users=BOT))
        async def handler(ev):
            if ev.video or ev.document:
                videos.append(ev)

        await asyncio.sleep(25)
        if not videos:
            await client.disconnect()
            raise RuntimeError("NO_VIDEO dari bot")

        v = videos[0]
        fname = f"ggreels_{drama_id}_part1.mp4"
        fpath = os.path.join(VIDEO_DIR, fname)
        path = await client.download_media(v.message, file=fpath)
        await client.disconnect()
        if path and os.path.exists(path):
            return path
        raise RuntimeError("DOWNLOAD_FAIL")

    return asyncio.run(_dl())
