"""ShortMax provider — short-drama HLS (host video akamai-static.shorttv.live).

Temuan RE (verified live via proxy nonton.sonzaix.codes):
- API path `/shortmax/api/v1/...` (base = proxy Sonzai).
- Butuh `Authorization: Bearer *** (env fallback MELOLO_TOKEN).
- Endpoint:
    GET /shortmax/api/v1/home                     -> list drama (id, code, name, cover, episodes, summary)
    GET /shortmax/api/v1/detail/{id}              -> detail 1 drama (sama field dgn home)
    GET /shortmax/api/v1/play/{id}                -> daftar episode (id, episode, locked)
    GET /shortmax/api/v1/play/{id}?ep={n}         -> URL video episode (data.video.video_480/720/1080)
- `ep` = nomor episode (1-based).
- Video = HLS m3u8 (bukan AES), 3 kualitas (480/720/1080). Default 720.
- m3u8 & segment lewat proxy wrapper `/web/m3u8/...` (butuh Bearer -> downloader tempel token).
- Cover full URL (akamai-static.shorttv.live) -> gak perlu /img proxy.

Struktur class sama seperti DramaboxProvider (lihat dramabox.py).
"""
import os

import httpx

BASE = os.environ.get("SHORTMAX_BASE", "https://nonton.sonzaix.codes")
TOKEN = os.environ.get("SHORTMAX_TOKEN") or os.environ.get("MELOLO_TOKEN", "")
PREFIX = "/shortmax/api/v1"
DEFAULT_QUALITY = "video_720"  # video_480 / video_720 / video_1080

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "application/json",
    "X-Device": "sonzai-aggregator",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


class ShortMaxProvider:
    name = "shortmax"

    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=BASE, headers=HEADERS, timeout=15.0, follow_redirects=True
        )
        self.auth_token = TOKEN  # dipakai downloader utk m3u8/segment proxy

    def route(self, resource: str):
        return {
            "home": self.home,
            "search": self.search,
            "detail": self.detail,
            "chapters": self.detail,
            "play": self.play,
            "stream": self.stream,
        }.get(resource)

    # ---------- helpers ----------
    async def _get(self, path: str, params: dict = None):
        r = await self.client.get(PREFIX + path, params=params)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _slim(x: dict) -> dict:
        return {
            "id": x.get("id"),
            "code": x.get("code"),
            "title": x.get("name"),
            "cover": x.get("cover"),
            "episode_count": x.get("episodes"),
            "summary": x.get("summary"),
        }

    async def _episodes(self, drama_id, lang="id"):
        j = await self._get(f"/play/{drama_id}", {"lang": lang})
        eps = j.get("data", []) if isinstance(j, dict) else []
        out = []
        for e in eps:
            if not isinstance(e, dict):
                continue
            out.append({
                "episode": e.get("episode"),
                "episode_id": e.get("id"),
                "locked": bool(e.get("locked")),
            })
        return out

    async def _m3u8(self, drama_id, ep, quality, lang="id"):
        j = await self._get(f"/play/{drama_id}", {"ep": ep, "lang": lang})
        data = j.get("data", {}) if isinstance(j, dict) else {}
        video = data.get("video", {}) if isinstance(data, dict) else {}
        url = video.get(quality) or video.get(DEFAULT_QUALITY) or video.get("video_480")
        if not url:
            # fallback: ambil kualitas pertama yg ada
            for v in (video.values() if isinstance(video, dict) else []):
                if isinstance(v, str) and v:
                    url = v
                    break
        if not url:
            raise ValueError("no video url")
        return url

    # ---------- home ----------
    async def home(self, params: dict):
        lang = params.get("lang", "id")  # id = Indonesia (default)
        j = await self._get("/home", {"lang": lang})
        data = j.get("data", [])
        items = [self._slim(x) for x in data if isinstance(x, dict) and x.get("id")]
        return {"source": "home", "lang": lang, "count": len(items), "items": items}

    # ---------- search ----------
    async def search(self, params: dict):
        q = params.get("q") or params.get("query") or params.get("keyword")
        if not q:
            raise ValueError("q required")
        lang = params.get("lang", "id")
        # probe: home-based filter / endpoint search (kalau upstream sediakan)
        try:
            j = await self._get("/search", {"q": q, "lang": lang})
            data = j.get("data", [])
            if isinstance(data, dict):
                data = data.get("records") or data.get("items") or []
            items = [self._slim(x) for x in data if isinstance(x, dict) and x.get("id")]
            return {"q": q, "lang": lang, "count": len(items), "items": items}
        except Exception:
            # fallback: filter dari home by judul
            j = await self._get("/home", {"lang": lang})
            data = j.get("data", [])
            ql = q.lower()
            items = [self._slim(x) for x in data
                     if isinstance(x, dict) and ql in (x.get("name") or "").lower()]
            return {"q": q, "lang": lang, "count": len(items), "items": items,
                    "note": "filtered from home (no dedicated search endpoint)"}

    # ---------- detail + episodes ----------
    async def detail(self, params: dict):
        drama_id = params.get("id") or params.get("drama_id") or params.get("book_id")
        if not drama_id:
            raise ValueError("id required")
        lang = params.get("lang", "id")
        j = await self._get(f"/detail/{drama_id}", {"lang": lang})
        d = j.get("data", {}) if isinstance(j, dict) else {}
        try:
            eps = await self._episodes(drama_id, lang)
        except Exception:
            eps = []
        return {
            "id": d.get("id"),
            "code": d.get("code"),
            "title": d.get("name"),
            "cover": d.get("cover"),
            "summary": d.get("summary"),
            "episode_count": len(eps) or d.get("episodes"),
            "episodes": eps,
        }

    # ---------- play / stream ----------
    async def stream(self, params: dict):
        drama_id = params.get("id") or params.get("drama_id") or params.get("book_id")
        if not drama_id:
            raise ValueError("id required")
        ep = params.get("ep") or params.get("episode") or 1
        quality = params.get("quality", DEFAULT_QUALITY)
        lang = params.get("lang", "id")
        url = await self._m3u8(drama_id, ep, quality, lang)
        return {"type": "hls", "url": url, "id": drama_id, "ep": ep,
                "requires_auth": True}

    async def play(self, params: dict):
        return await self.stream(params)

    # ---------- download ----------
    async def resolve_download(self, params: dict):
        drama_id = params.get("id") or params.get("drama_id") or params.get("book_id")
        if not drama_id:
            raise ValueError("id required")
        ep = params.get("ep") or params.get("episode") or 1
        quality = params.get("quality", DEFAULT_QUALITY)
        lang = params.get("lang", "id")
        url = await self._m3u8(drama_id, ep, quality, lang)
        return {
            "type": "hls", "url": url, "drm_token": None,
            "title": None, "episode": ep,
            "requires_auth": True,
            "note": "HLS m3u8 (bukan AES). m3u8+segment butuh Bearer token.",
        }
