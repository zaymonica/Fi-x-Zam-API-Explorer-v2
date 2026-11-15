"""RapidTV provider — short-drama MP4 (host video rapid.timeappmarketing.com).

Temuan RE (verified live via proxy nonton.sonzaix.codes):
- API path `/rapidtv/api/v1/...` (base = proxy Sonzai).
- Butuh `Authorization: Bearer *** (env fallback MELOLO_TOKEN).
- Endpoint:
    GET /rapidtv/api/v1/dramas              -> list drama (array: id, title, description, poster, totalEpisodes)
    GET /rapidtv/api/v1/dramas/{id}         -> detail + SEMUA episode (embed)
       episodes[].episode      -> nomor episode (1-based)
       episodes[].episodeId    -> id episode
       episodes[].videos[]     -> {quality (540P/720P/..), url (MP4 signed), duration, size}
- Video = MP4 langsung (bukan HLS), per kualitas. URL signed (auth_key) expired ~24-30 hari.
- Cover/poster full URL -> gak perlu /img proxy.

Struktur class sama seperti DramaboxProvider (lihat dramabox.py).
"""
import os

import httpx

BASE = os.environ.get("RAPIDTV_BASE", "https://nonton.sonzaix.codes")
TOKEN = os.environ.get("RAPIDTV_TOKEN") or os.environ.get("MELOLO_TOKEN", "")
PREFIX = "/rapidtv/api/v1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "application/json",
    "X-Device": "sonzai-aggregator",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


class RapidtvProvider:
    name = "rapidtv"

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
            "chapters": self.detail,
            "chapter_list": self.detail,
            "play": self.play,
            "stream": self.stream,
        }.get(resource)

    # ---------- helpers ----------
    async def _get(self, path: str):
        r = await self.client.get(PREFIX + path)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _slim(x: dict) -> dict:
        return {
            "id": str(x.get("id", "")),
            "title": x.get("title"),
            "cover": x.get("poster") or x.get("cover"),
            "summary": x.get("description"),
            "episode_count": x.get("totalEpisodes") or x.get("episodes"),
        }

    @staticmethod
    def _pick_video(videos: list, quality: str = None):
        """Pilih URL video dari list videos[] — prioritas kualitas tertinggi."""
        if not videos:
            return None, None
        if quality:
            for v in videos:
                if str(v.get("quality")) == quality:
                    return v.get("url"), v.get("quality")
        # default: ambil terakhir (biasanya kualitas tertinggi) / pertama
        v = videos[-1] if len(videos) > 1 else videos[0]
        return v.get("url"), v.get("quality")

    # ---------- home ----------
    async def home(self, params: dict):
        lang = params.get("lang", "id")  # id = Indonesia (default)
        j = await self._get(f"/dramas?lang={lang}")
        data = j if isinstance(j, list) else j.get("data", []) if isinstance(j, dict) else []
        items = [self._slim(x) for x in data if isinstance(x, dict) and x.get("id")]
        return {"source": "home", "lang": lang, "count": len(items), "items": items}

    # ---------- search ----------
    async def search(self, params: dict):
        q = (params.get("q") or params.get("query") or params.get("keyword") or "").lower()
        if not q:
            raise ValueError("q required")
        lang = params.get("lang", "id")
        # fallback: filter dari home by judul (upstream gak punya endpoint search)
        j = await self._get(f"/dramas?lang={lang}")
        data = j if isinstance(j, list) else j.get("data", []) if isinstance(j, dict) else []
        items = [self._slim(x) for x in data
                 if isinstance(x, dict) and q in (x.get("title") or "").lower()]
        return {"q": q, "lang": lang, "count": len(items), "items": items,
                "note": "filtered from home (no dedicated search endpoint)"}

    # ---------- detail (embed semua episode) ----------
    async def detail(self, params: dict):
        drama_id = params.get("id") or params.get("drama_id") or params.get("book_id")
        if not drama_id:
            raise ValueError("id required")
        lang = params.get("lang", "id")
        j = await self._get(f"/dramas/{drama_id}?lang={lang}")
        eps_raw = j.get("episodes", []) or []
        episodes = []
        for e in eps_raw:
            if not isinstance(e, dict):
                continue
            url, quality = self._pick_video(e.get("videos", []))
            episodes.append({
                "episode": e.get("episode"),
                "episode_id": e.get("episodeId"),
                "quality": quality,
                "url": url,
                "duration": next((v.get("duration") for v in e.get("videos", []) if v.get("duration")), None),
            })
        return {
            "id": str(j.get("id", "")),
            "title": j.get("title"),
            "cover": j.get("poster") or j.get("cover"),
            "summary": j.get("description"),
            "episode_count": len(episodes) or j.get("totalEpisodes"),
            "episodes": episodes,
        }

    # ---------- play / stream ----------
    async def stream(self, params: dict):
        drama_id = params.get("id") or params.get("drama_id") or params.get("book_id")
        if not drama_id:
            raise ValueError("id required")
        ep = params.get("ep") or params.get("episode") or 1
        quality = params.get("quality")
        j = await self._get(f"/dramas/{drama_id}")
        eps = j.get("episodes", []) or []
        target = None
        for e in eps:
            if str(e.get("episode")) == str(ep):
                target = e
                break
        if target is None and eps:
            target = eps[0]
        if not target:
            raise ValueError("episode not found")
        url, q = self._pick_video(target.get("videos", []), quality)
        if not url:
            raise ValueError("no video url")
        return {"type": "mp4", "url": url, "id": str(drama_id), "ep": ep, "quality": q}

    async def play(self, params: dict):
        return await self.stream(params)

    # ---------- download ----------
    async def resolve_download(self, params: dict):
        drama_id = params.get("id") or params.get("drama_id") or params.get("book_id")
        if not drama_id:
            raise ValueError("id required")
        ep = params.get("ep") or params.get("episode") or 1
        quality = params.get("quality")
        j = await self._get(f"/dramas/{drama_id}")
        eps = j.get("episodes", []) or []
        target = None
        for e in eps:
            if str(e.get("episode")) == str(ep):
                target = e
                break
        if target is None and eps:
            target = eps[0]
        if not target:
            raise ValueError("episode not found")
        url, q = self._pick_video(target.get("videos", []), quality)
        if not url:
            raise ValueError("no video url")
        return {
            "type": "mp4", "url": url, "drm_token": None,
            "title": j.get("title"), "episode": ep, "quality": q,
            "note": "MP4 signed (auth_key). Ambil URL fresh tiap request; expired ~24-30 hari.",
        }
