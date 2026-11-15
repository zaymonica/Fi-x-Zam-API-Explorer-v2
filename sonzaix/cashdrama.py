"""CashDrama provider — short-drama (host video cashdrama-vod.jowo.tv).

Temuan RE (verified live via proxy):
- API path `/cashdrama/api/v1/...` (origin di balik CDN jowo.tv, tak resolve publik).
  Base point ke proxy reachable (`CASHDRAMA_BASE`, default proxy Sonzai).
- Butuh `Authorization: Bearer <token>` (env `CASHDRAMA_TOKEN`; fallback MELOLO_TOKEN).
- Endpoint:
    GET /cashdrama/api/v1/home?lang={l}              -> feed katalog
    GET /cashdrama/api/v1/search?q={kw}              -> pencarian
    GET /cashdrama/api/v1/drama/{bookId}?lang={l}    -> detail + daftar episode
    GET /cashdrama/api/v1/play/{vid}/{ep}?lang={l}   -> data stream (drmToken + m3u8)
- Response pakai envelope `{"success":true,"data":{...}}`.

Struktur class sama seperti MeloloProvider.
"""
import os

import httpx

BASE = os.environ.get("CASHDRAMA_BASE", "https://nonton.sonzaix.codes")
TOKEN = os.environ.get("CASHDRAMA_TOKEN") or os.environ.get("MELOLO_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "application/json",
    "X-Device": "sonzai-aggregator",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


class CashDramaProvider:
    name = "cashdrama"

    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=BASE, headers=HEADERS, timeout=15.0, follow_redirects=True
        )
        self.auth_token = TOKEN  # token utk m3u8/segmen/drmkey proxy (dipakai downloader)

    def route(self, resource: str):
        return {
            "home": self.home,
            "search": self.search,
            "detail": self.detail,
            "play": self.play,
            "tags": self.tags,
        }.get(resource)

    # ---------- tags: cari berdasarkan tag ----------
    async def tags(self, params: dict):
        tag_id = params.get("tag_id") or params.get("tagId")
        if not tag_id:
            raise ValueError("tag_id required")
        lang = params.get("lang", "id")
        r = await self.client.get("/cashdrama/api/v1/tags/search",
                                  params={"tagId": tag_id, "lang": lang})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        lst = data.get("list", []) if isinstance(data, dict) else []
        return {"tag_id": tag_id, "count": data.get("count", len(lst)),
                "items": [self._slim(x) for x in lst]}

    async def resolve_download(self, params: dict):
        """Return dict utk downloader: HLS m3u8 + drm_token (untuk AES key)."""
        play = await self.play(params)
        streams = play.get("streams", [])
        if not streams:
            raise ValueError("no stream")
        return {"type": "hls", "url": streams[0]["url"], "drm_token": play.get("drm_token"),
                "vid": play.get("vid"), "ep": play.get("ep")}

    # ---------- home ----------
    async def home(self, params: dict):
        lang = params.get("lang", "id")
        page = params.get("page", 1)
        r = await self.client.get("/cashdrama/api/v1/home", params={"lang": lang, "page": page})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        items = [self._slim(x) for x in data.get("list", [])]
        return {"source": "home", "lang": lang, "count": len(items), "items": items}

    # ---------- search ----------
    async def search(self, params: dict):
        q = params.get("q") or params.get("query")
        if not q:
            raise ValueError("q required")
        lang = params.get("lang", "id")
        r = await self.client.get("/cashdrama/api/v1/search", params={"q": q, "lang": lang})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        lst = data.get("list") or data.get("records") or []
        out = [self._slim(x) for x in lst]
        return {"q": q, "count": len(out), "items": out}

    # ---------- detail + episodes ----------
    async def detail(self, params: dict):
        book_id = params.get("book_id") or params.get("id")
        if not book_id:
            raise ValueError("book_id required")
        lang = params.get("lang", "id")
        r = await self.client.get("/cashdrama/api/v1/drama/" + str(book_id), params={"lang": lang})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        info = data.get("info", {}) if isinstance(data.get("info"), dict) else data
        eps = data.get("episodes") or info.get("episodes") or []
        return {
            "book_id": book_id,
            "detail": info,
            "episode_count": len(eps),
            "episodes": [
                {
                    "id": e.get("id") or e.get("vid"),
                    "name": e.get("name") or e.get("title"),
                    "cover": e.get("cover"),
                    "duration": e.get("duration"),
                }
                for e in eps
            ],
        }

    # ---------- play / stream ----------
    async def play(self, params: dict):
        vid = params.get("vid") or params.get("book_id")
        ep = params.get("ep") or params.get("episode") or 1
        if not vid:
            raise ValueError("vid required")
        lang = params.get("lang", "id")
        r = await self.client.get(f"/cashdrama/api/v1/play/{vid}/{ep}", params={"lang": lang})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        adaptive = data.get("adaptive", [])
        return {
            "vid": vid,
            "ep": ep,
            "drm_token": data.get("drmToken"),
            "streams": [
                {"quality": a.get("quality"), "url": a.get("url"), "type": a.get("type")}
                for a in adaptive
            ],
        }

    # ---------- helper ----------
    @staticmethod
    def _slim(x: dict) -> dict:
        return {
            "book_id": x.get("id"),
            "title": x.get("name") or x.get("title"),
            "cover": x.get("cover"),
            "abstract": x.get("introduction") or x.get("abstract") or x.get("description"),
            "read_count": x.get("readCount") or x.get("read_count"),
        }
