"""GoodShort provider — short-drama HLS (host video v3.goodshort.com / goodreels.com).

Temuan RE (verified live via proxy):
- API path `/goodshort/api/v1/...` (origin di balik CDN goodreels, tak resolve di DNS publik).
  Base point ke proxy reachable (`GOODSHORT_BASE`, default proxy Sonzai).
- Butuh `Authorization: Bearer <token>` (set via env `GOODSHORT_TOKEN`; fallback ke MELOLO_TOKEN).
- Endpoint:
    GET /goodshort/api/v1/home?page={n}          -> feed katalog (channel/section)
    GET /goodshort/api/v1/search?q={kw}          -> pencarian
    GET /goodshort/api/v1/chapters/{bookId}      -> daftar chapter + cdnList (HLS m3u8)
- Tiap chapter punya `cdnList[].videoPath` = m3u8 (via proxy play.m3u8) + `__token__` expiry.
  Stream HLS, butuh player yang support m3u8 (atau di-download & digabung segmennya).

Struktur class sama seperti MeloloProvider (lihat melolo.py).
"""
import os

import httpx

BASE = os.environ.get("GOODSHORT_BASE", "https://nonton.sonzaix.codes")
TOKEN = os.environ.get("GOODSHORT_TOKEN") or os.environ.get("MELOLO_TOKEN", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "application/json",
    "X-Device": "sonzai-aggregator",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


class GoodShortProvider:
    name = "goodshort"

    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=BASE, headers=HEADERS, timeout=15.0, follow_redirects=True
        )
        self.auth_token = TOKEN  # token utk m3u8/segmen proxy (dipakai downloader)

    def route(self, resource: str):
        return {
            "home": self.home,
            "search": self.search,
            "chapters": self.chapters,
            "unlock": self.unlock,
        }.get(resource)

    # ---------- unlock: status unlock/beli episode ----------
    async def unlock(self, params: dict):
        book_id = params.get("book_id") or params.get("id")
        if not book_id:
            raise ValueError("book_id required")
        r = await self.client.get("/goodshort/api/v1/unlock/" + str(book_id))
        r.raise_for_status()
        j = r.json()
        # respons: book/total/episodes di level atas (bukan di dalam "data")
        eps = j.get("episodes", []) or j.get("data", {}).get("episodes", [])
        return {
            "book_id": book_id,
            "book": j.get("book") or j.get("data", {}).get("book"),
            "total": j.get("total") if j.get("total") is not None else len(eps),
            "count": len(eps),
            "episodes": [
                {"id": e.get("id"), "episode": e.get("episode"),
                 "price": e.get("price"), "url": e.get("url")}
                for e in eps
            ],
        }

    async def resolve_download(self, params: dict):
        """Return dict utk downloader: HLS m3u8 chapter terpilih."""
        chs = await self.chapters(params)
        ch_list = chs.get("chapters", [])
        idx = int(params.get("chapter_index", 0) or 0)
        target = ch_list[idx] if idx < len(ch_list) else (ch_list[0] if ch_list else None)
        if not target:
            raise ValueError("chapter not found")
        streams = target.get("streams", [])
        if not streams:
            raise ValueError("no stream for chapter")
        # prioritas stream pertama (proxy) — downloader follow nested + auth
        return {"type": "hls", "url": streams[0], "drm_token": None,
                "title": chs.get("title") or chs.get("book_id"),
                "chapter": target.get("name"), "alt_streams": streams[1:]}

    # ---------- home ----------
    async def home(self, params: dict):
        page = params.get("page", 1)
        r = await self.client.get("/goodshort/api/v1/home", params={"page": page})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        items = []
        for section in data.get("records", []):
            for it in section.get("items", []):
                items.append(self._slim(it))
        # dedupe by bookId, keep order
        seen = set()
        uniq = []
        for it in items:
            bid = it.get("book_id")
            if bid and bid not in seen:
                seen.add(bid)
                uniq.append(it)
        return {"source": "home", "page": page, "count": len(uniq), "items": uniq}

    # ---------- search ----------
    async def search(self, params: dict):
        q = params.get("q") or params.get("query")
        if not q:
            raise ValueError("q required")
        r = await self.client.get("/goodshort/api/v1/search", params={"q": q})
        r.raise_for_status()
        j = r.json()
        sr = j.get("data", {}).get("searchResult", {})
        out = [self._slim(rec) for rec in sr.get("records", [])]
        return {"q": q, "total": sr.get("total"), "count": len(out), "items": out}

    # ---------- chapters + HLS ----------
    async def chapters(self, params: dict):
        book_id = params.get("book_id") or params.get("id")
        if not book_id:
            raise ValueError("book_id required")
        r = await self.client.get("/goodshort/api/v1/chapters/" + str(book_id))
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        out = []
        for ch in data.get("list", []):
            # ambil stream m3u8 dari cdnList (prioritaskan yg bukan proxy jika ada)
            streams = []
            for cdn in ch.get("cdnList", []):
                vp = cdn.get("videoPath")
                if vp:
                    streams.append(vp)
            multi = []
            for mv in ch.get("multiVideos", []):
                fp = mv.get("filePath")
                if fp:
                    multi.append({"quality": mv.get("type"), "url": fp})
            out.append({
                "chapter_id": ch.get("id"),
                "name": ch.get("chapterName"),
                "play_time": ch.get("playTime"),
                "index": ch.get("index"),
                "price": ch.get("price"),
                "cover": ch.get("image"),
                "streams": streams,
                "qualities": multi,
            })
        return {"book_id": book_id, "count": len(out), "chapters": out}

    # ---------- helper ----------
    @staticmethod
    def _slim(it: dict) -> dict:
        return {
            "book_id": it.get("bookId") or it.get("action"),
            "title": it.get("bookName"),
            "author": it.get("pseudonym"),
            "abstract": it.get("introduction"),
            "cover": it.get("cover"),
            "view_count": it.get("viewCount"),
        }
