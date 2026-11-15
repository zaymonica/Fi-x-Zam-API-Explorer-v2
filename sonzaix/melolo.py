"""Melolo provider — short-drama vertical (Fizzo/ByteDance infra).

Temuan RE (verified live):
- API diakses lewat path `/melolo/api/v1/...`. Origin asli berada di balik
  CDN Fizzo (`p16-novel-sign.fizzopic.org`) dan tidak ter-resolve di DNS publik,
  jadi base point ke proxy yang reliable (`MHOLOLO_BASE`, default proxy Sonzai).
- Butuh `Authorization: Bearer <token>` (token akun trial — set via env `MELOLO_TOKEN`).
- Endpoint publik-ish (via proxy):
    GET /melolo/api/v1/bookmall?lang=id          -> feed katalog
    GET /melolo/api/v1/search?q=<kw>&lang=id     -> pencarian
    GET /melolo/api/v1/book?id=<book_id>&lang=id -> detail drama
    GET /melolo/api/v1/multi-video?id=<book_id>  -> series + daftar episode
- Tiap episode punya `stream_url` (MP4, host `*.inicdn.net`) yang bisa di-fetch
  TANPA auth -> siap diputar/download langsung.

Struktur class sama seperti ReelShortProvider (lihat reelshort.py).
"""
import os

import httpx

BASE = os.environ.get("MELOLO_BASE", "https://nonton.sonzaix.codes")
TOKEN = os.environ.get("MELOLO_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "application/json",
    "X-Device": "sonzai-aggregator",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


class MeloloProvider:
    name = "melolo"

    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=BASE, headers=HEADERS, timeout=15.0, follow_redirects=True
        )

    def route(self, resource: str):
        return {
            "home": self.home,
            "search": self.search,
            "detail": self.detail,
            "episodes": self.episodes,
        }.get(resource)

    async def resolve_download(self, params: dict):
        """Return dict utk downloader: type mp4 + stream_url episode."""
        eps = await self.episodes(params)
        ep_list = eps.get("episodes", [])
        ep = int(params.get("ep", 1) or 1)
        target = None
        for e in ep_list:
            if e.get("index") == ep:
                target = e
                break
        if target is None and ep_list:
            target = ep_list[0]
        if not target or not target.get("stream_url"):
            raise ValueError("stream_url not found")
        return {"type": "mp4", "url": target["stream_url"], "drm_token": None,
                "title": eps.get("title"), "index": target.get("index")}

    # ---------- home / feed ----------
    async def home(self, params: dict):
        lang = params.get("lang", "id")
        r = await self.client.get("/melolo/api/v1/bookmall", params={"lang": lang})
        r.raise_for_status()
        j = r.json()
        books = []
        for cell in j.get("cell", {}).get("cell_data", []):
            books.extend(cell.get("books", []))
        out = [self._slim_book(b) for b in books]
        return {"source": "bookmall", "lang": lang, "count": len(out), "items": out}

    # ---------- search ----------
    async def search(self, params: dict):
        q = params.get("q") or params.get("query")
        if not q:
            raise ValueError("q required")
        lang = params.get("lang", "id")
        r = await self.client.get("/melolo/api/v1/search", params={"q": q, "lang": lang})
        r.raise_for_status()
        j = r.json()
        items = j.get("items", [])
        out = [self._slim_search(i) for i in items]
        return {"q": q, "total": j.get("total"), "count": len(out), "items": out}

    # ---------- detail drama ----------
    async def detail(self, params: dict):
        book_id = params.get("book_id") or params.get("id")
        if not book_id:
            raise ValueError("book_id required")
        lang = params.get("lang", "id")
        r = await self.client.get("/melolo/api/v1/book", params={"id": book_id, "lang": lang})
        r.raise_for_status()
        return r.json()

    # ---------- episode list + stream ----------
    async def episodes(self, params: dict):
        book_id = params.get("book_id") or params.get("id")
        if not book_id:
            raise ValueError("book_id required")
        r = await self.client.get("/melolo/api/v1/multi-video", params={"id": book_id})
        r.raise_for_status()
        j = r.json()
        series = j.get("series", {})
        eps = j.get("episodes", [])
        out = [
            {
                "index": e.get("index"),
                "vid": e.get("vid"),
                "duration": e.get("duration"),
                "stream_url": e.get("stream_url"),
                "cover": e.get("cover"),
            }
            for e in eps
        ]
        return {
            "book_id": book_id,
            "title": series.get("title"),
            "total": series.get("total", j.get("total")),
            "is_vip": series.get("is_vip"),
            "count": len(out),
            "episodes": out,
        }

    # ---------- helpers ----------
    @staticmethod
    def _slim_book(b: dict) -> dict:
        return {
            "book_id": b.get("book_id"),
            "title": b.get("book_name"),
            "author": b.get("author"),
            "abstract": b.get("abstract"),
            "cover": b.get("thumb_url") or b.get("first_chapter_cover"),
            "read_count": b.get("read_count"),
            "is_hot": b.get("is_hot"),
        }

    @staticmethod
    def _slim_search(i: dict) -> dict:
        return {
            "book_id": i.get("book_id"),
            "title": i.get("title"),
            "author": i.get("author"),
            "abstract": i.get("abstract"),
            "cover": i.get("cover"),
        }
