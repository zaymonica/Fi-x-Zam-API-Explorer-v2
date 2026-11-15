"""Dramabox provider — short-drama MP4 (host video hwztvideo.dramaboxdb.com).

Temuan RE (verified live via proxy):
- API path `/dramabox/api/v1/...` (origin di balik CDN dramaboxdb.com).
  Base point ke proxy reachable (`DRAMABOX_BASE`, default proxy Sonzai).
- Butuh `Authorization: Bearer <token>` (env `DRAMABOX_TOKEN`; fallback MELOLO_TOKEN).
- Endpoint:
    GET /dramabox/api/v1/home?page={n}                    -> feed katalog
    GET /dramabox/api/v1/search?keyword={kw}              -> pencarian
    GET /dramabox/api/v1/book?bookId={id}                 -> detail + daftar episode
    GET /dramabox/api/v1/play?bookId={id}&episode={n}     -> data video (`video.mp4`)
- `episode` = nomor index (1-based), BUKAN chapterId.
- `video.mp4` via proxy `/web/mp4/play.mp4?url=...` (MP4 tunggal, quality 720).

Struktur class sama seperti MeloloProvider.
"""
import os

import httpx

BASE = os.environ.get("DRAMABOX_BASE", "https://nonton.sonzaix.codes")
TOKEN = os.environ.get("DRAMABOX_TOKEN") or os.environ.get("MELOLO_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "application/json",
    "X-Device": "sonzai-aggregator",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


class DramaboxProvider:
    name = "dramabox"

    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=BASE, headers=HEADERS, timeout=15.0, follow_redirects=True
        )
        self.auth_token = TOKEN

    def route(self, resource: str):
        return {
            "home": self.home,
            "search": self.search,
            "detail": self.detail,
            "play": self.play,
            "recommend": self.recommend,
            "vip": self.vip,
        }.get(resource)

    # ---------- recommend ----------
    async def recommend(self, params: dict):
        lang = params.get("lang", "id")
        r = await self.client.get("/dramabox/api/v1/recommend", params={"lang": lang})
        r.raise_for_status()
        j = r.json()
        items = [self._slim(x) for x in j.get("data", [])]
        return {"source": "recommend", "lang": lang, "count": len(items), "items": items}

    # ---------- vip ----------
    async def vip(self, params: dict):
        lang = params.get("lang", "id")
        r = await self.client.get("/dramabox/api/v1/vip", params={"lang": lang})
        r.raise_for_status()
        j = r.json()
        items = [self._slim(x) for x in j.get("data", [])]
        return {"source": "vip", "lang": lang, "count": len(items), "items": items}

    async def resolve_download(self, params: dict):
        """Return dict utk downloader: MP4 tunggal."""
        play = await self.play(params)
        v = play.get("video", {})
        url = v.get("mp4")
        if not url:
            raise ValueError("no mp4 url")
        return {"type": "mp4", "url": url, "drm_token": None,
                "title": play.get("name"), "episode": play.get("chapter", {}).get("index")}

    # ---------- home ----------
    async def home(self, params: dict):
        page = params.get("page", 1)
        r = await self.client.get("/dramabox/api/v1/home", params={"page": page})
        r.raise_for_status()
        j = r.json()
        items = [self._slim(x) for x in j.get("data", [])]
        return {"source": "home", "page": page, "count": len(items), "items": items}

    # ---------- search ----------
    async def search(self, params: dict):
        q = params.get("q") or params.get("query") or params.get("keyword")
        if not q:
            raise ValueError("q required")
        r = await self.client.get("/dramabox/api/v1/search", params={"keyword": q})
        r.raise_for_status()
        j = r.json()
        items = [self._slim(x) for x in j.get("data", [])]
        return {"q": q, "count": len(items), "items": items}

    # ---------- detail + episodes ----------
    async def detail(self, params: dict):
        book_id = params.get("book_id") or params.get("id")
        if not book_id:
            raise ValueError("book_id required")
        r = await self.client.get("/dramabox/api/v1/book", params={"bookId": book_id})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        eps = data.get("episodes", [])
        return {
            "book_id": data.get("id"),
            "title": data.get("name"),
            "cover": data.get("cover"),
            "abstract": data.get("description"),
            "chapter_count": data.get("chapterCount"),
            "episode_count": len(eps),
            "episodes": [
                {"chapter_id": e.get("chapterId"), "index": e.get("chapterIndex") + 1,
                 "name": e.get("chapterName")}
                for e in eps
            ],
        }

    # ---------- play / stream ----------
    async def play(self, params: dict):
        book_id = params.get("book_id") or params.get("vid") or params.get("id")
        ep = params.get("ep") or params.get("episode") or 1
        if not book_id:
            raise ValueError("book_id required")
        r = await self.client.get("/dramabox/api/v1/play",
                                  params={"bookId": book_id, "episode": ep})
        r.raise_for_status()
        j = r.json()
        if not j.get("success"):
            raise ValueError(j.get("error", {}).get("message", "play failed"))
        return j.get("data", {})

    # ---------- helper ----------
    @staticmethod
    def _slim(x: dict) -> dict:
        return {
            "book_id": x.get("id"),
            "title": x.get("name"),
            "cover": x.get("cover"),
            "chapter_count": x.get("chapterCount"),
        }
