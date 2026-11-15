"""DramaNova provider — short-drama MP4 (host video cdn.playsverse.com).

Temuan RE (verified live via proxy nonton.sonzaix.codes):
- API path `/dramanova/...` (base = proxy Sonzai).
- Butuh `Authorization: Bearer *** (env fallback MELOLO_TOKEN).
- Endpoint:
    GET /dramanova/discover?lang={l}&page={n}&size={s}  -> list drama (dramaId, title, synopsis, totalEpisodes, score)
    GET /dramanova/search?q={kw}&lang={l}               -> pencarian (total, rows)
    GET /dramanova/episodes?dramaId={id}&lang={l}        -> daftar episode (episodeId, episodeNo, locked)
    GET /dramanova/play?dramaId={id}&ep={n}&lang={l}     -> URL MP4 signed (data[].url)
- `ep` = nomor episode (1-based).
- Bahasa: in(id Indonesia), en, pt, th, vi, es. Default `in`.
- URL dari /play = proxy wrapper `https://proxy/web/mp4/play.mp4?url=<encodeURIComponent(cdn.mp4?auth_key=..)>`.
  Wrapper itu 403 ("Tiket video tidak valid") saat diakses langsung, jadi kita DECODE param `url=`
  dan pakai URL CDN asli (cdn.playsverse.com). auth_key expired ~24-30 hari -> ambil fresh tiap request.

Struktur class sama seperti DramaboxProvider (lihat dramabox.py).
"""
import os
from urllib.parse import unquote

import httpx

BASE = os.environ.get("DRAMANOVA_BASE", "https://nonton.sonzaix.codes")
TOKEN = os.environ.get("DRAMANOVA_TOKEN") or os.environ.get("MELOLO_TOKEN", "")
DEFAULT_LANG = "in"  # in = Indonesia
PREFIX = "/dramanova"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "application/json",
    "X-Device": "sonzai-aggregator",
    "Content-Type": "application/json",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"
    HEADERS["token"] = TOKEN


class DramaNovaProvider:
    name = "dramanova"

    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=BASE, headers=HEADERS, timeout=15.0, follow_redirects=True
        )
        self.auth_token = TOKEN

    def route(self, resource: str):
        return {
            "home": self.home,
            "discover": self.home,
            "search": self.search,
            "detail": self.detail,
            "episodes": self.detail,
            "chapters": self.detail,
            "chapter_list": self.detail,
            "play": self.play,
            "stream": self.stream,
        }.get(resource)

    # ---------- helpers ----------
    async def _get(self, path: str, params: dict):
        r = await self.client.get(PREFIX + path, params=params)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _slim(x: dict) -> dict:
        return {
            "id": str(x.get("dramaId", "")),
            "drama_id": str(x.get("dramaId", "")),
            "title": x.get("title"),
            "cover": None,  # posterUri relatif (base CDN image belum diketahui)
            "synopsis": x.get("synopsis"),
            "total_episodes": x.get("totalEpisodes"),
            "score": x.get("score"),
        }

    async def _episode_mp4(self, drama_id, ep, lang):
        j = await self._get("/play", {"dramaId": str(drama_id), "ep": ep, "lang": lang})
        data = j.get("data", []) if isinstance(j, dict) else []
        if not data:
            raise ValueError("no play data")
        url = (data[0] or {}).get("url") or ""
        if "url=" in url:
            return unquote(url.split("url=", 1)[1])
        if url:
            return url
        raise ValueError("no mp4 url")

    # ---------- home / discover ----------
    async def home(self, params: dict):
        lang = params.get("lang", DEFAULT_LANG)
        page = int(params.get("page", 1) or 1)
        size = min(int(params.get("size", 20) or 20), 20)  # upstream cap 20/hal
        j = await self._get("/discover", {"lang": lang, "page": page, "size": size})
        data = j.get("data", {}) if isinstance(j, dict) else {}
        rows = data.get("items", []) or []
        items = [self._slim(x) for x in rows if isinstance(x, dict) and x.get("dramaId")]
        return {"source": "discover", "lang": lang, "page": page,
                "size": size, "count": len(items), "items": items}

    # ---------- search ----------
    async def search(self, params: dict):
        q = params.get("q") or params.get("query") or params.get("keyword")
        if not q:
            raise ValueError("q required")
        lang = params.get("lang", DEFAULT_LANG)
        j = await self._get("/search", {"q": q, "lang": lang})
        data = j.get("data", {}) if isinstance(j, dict) else {}
        rows = data.get("rows", []) or []
        items = [self._slim(x) for x in rows if isinstance(x, dict) and x.get("dramaId")]
        return {"q": q, "lang": lang, "count": len(items),
                "total": data.get("total", len(items)), "items": items}

    # ---------- detail + episodes ----------
    async def detail(self, params: dict):
        drama_id = params.get("drama_id") or params.get("dramaId") or params.get("id")
        if not drama_id:
            raise ValueError("drama_id required")
        lang = params.get("lang", DEFAULT_LANG)
        try:
            meta_j = await self._get("/detail", {"dramaId": str(drama_id), "lang": lang})
            meta = meta_j.get("data", {}) if isinstance(meta_j, dict) else {}
        except Exception:
            meta = {}
        try:
            ep_j = await self._get("/episodes", {"dramaId": str(drama_id), "lang": lang})
            eps = (ep_j.get("data", {}) or {}).get("episodes", []) or []
        except Exception:
            eps = []
        episodes = []
        for i, e in enumerate(eps):
            if not isinstance(e, dict):
                continue
            episodes.append({
                "episode": e.get("episodeNo", i + 1),
                "episode_id": str(e.get("episodeId", "")),
                "locked": bool(e.get("locked")),
                "can_preview": bool(e.get("canPreview")),
            })
        return {
            "drama_id": str(drama_id),
            "title": meta.get("title"),
            "cover": None,
            "synopsis": meta.get("description") or meta.get("synopsis"),
            "score": meta.get("score"),
            "episode_count": len(episodes),
            "episodes": episodes,
        }

    # ---------- play / stream ----------
    async def stream(self, params: dict):
        drama_id = params.get("drama_id") or params.get("dramaId") or params.get("id")
        if not drama_id:
            raise ValueError("drama_id required")
        ep = params.get("ep") or params.get("episode") or 1
        lang = params.get("lang", DEFAULT_LANG)
        url = await self._episode_mp4(drama_id, ep, lang)
        return {"type": "mp4", "url": url, "drama_id": str(drama_id), "ep": ep}

    async def play(self, params: dict):
        return await self.stream(params)

    # ---------- download ----------
    async def resolve_download(self, params: dict):
        drama_id = params.get("drama_id") or params.get("dramaId") or params.get("id")
        if not drama_id:
            raise ValueError("drama_id required")
        ep = params.get("ep") or params.get("episode") or 1
        lang = params.get("lang", DEFAULT_LANG)
        quality = params.get("quality", "default")
        url = await self._episode_mp4(drama_id, ep, lang)
        return {
            "type": "mp4", "url": url, "drm_token": None,
            "ext": "mp4", "quality": quality,
            "title": None, "episode": ep,
            "note": "MP4 signed (auth_key). Ambil URL fresh tiap request; expired ~24-30 hari.",
        }
