"""ReelShort provider — API publik (getBookInfo/getChapterList/getChapterInfo).

Temuan RE (verified live):
- URL episode SSR: /episodes/episode-1-{slug}-{BOOK_ID}-{CHAPTER_ID}?play_time=1
  * BOOK_ID    = segmen kedua-terakhir (24-hex, contoh 6aafa7fc530d47585a054f74)
  * CHAPTER_ID = segmen terakhir (contoh aqthox3d16)
- `getBookInfo`            -> publik, detail buku.
- `getChapterList`         -> publik, butuh page & page_size. Balikin chapter_list.
- `getChapterInfo`         -> publik, balikin `video_url` (HLS m3u8) per chapter!
- `getFreeChapter`         -> publik, tapi sering "该章节未上架" (belum tayang).
- Endpoint webInfo/webSearch/getTagList butuh session -> SPA HTML (skip).
- Video stream = HLS m3u8 dari CDN crazymaplestudios, **tanpa auth**, segmen .ts valid.

Semua akses publik tanpa token. Struktur class mengikuti provider lain.
"""
import os
import re

import httpx

BASE = "https://www.reelshort.com"
# Proxy (nonton.sonzaix.codes) utk endpoint session-gated: tabfeed/search.
# Path `/reelshort/api/v1/...` adalah PATH PROXY, bukan path di reelshort.com.
PROXY_BASE = os.environ.get("REELSHORT_PROXY_BASE", "https://nonton.sonzaix.codes")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/125.0.0.0 Mobile",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/",
}


class ReelShortProvider:
    name = "reelshort"

    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=15.0, follow_redirects=True)
        # client proxy (nonton.sonzaix.codes) utk endpoint session-gated: tabfeed/search
        self.auth_token = os.environ.get("REELSHORT_TOKEN") or os.environ.get("MELOLO_TOKEN", "")
        proxy_headers = dict(HEADERS)
        proxy_headers["Accept"] = "application/json"
        proxy_headers["X-Device"] = "sonzai-aggregator"
        if self.auth_token:
            proxy_headers["Authorization"] = f"Bearer {self.auth_token}"
        self.pclient = httpx.AsyncClient(base_url=PROXY_BASE, headers=proxy_headers,
                                         timeout=15.0, follow_redirects=True)

    def route(self, resource: str):
        return {
            "home": self.home,
            "book": self.book_info,
            "book_info": self.book_info,
            "chapters": self.chapters,
            "chapter_info": self.chapter_info,
            "stream": self.stream,
            "free_chapter": self.free_chapter,
            "tabfeed": self.tabfeed,
            "search": self.search,
        }.get(resource)

    # ---------- tabfeed: kategori (foryou/new/romance/drama/completed) ----------
    async def tabfeed(self, params: dict):
        tab = (params.get("tab") or "foryou").lower()
        lang = params.get("lang", "en")
        # path per kategori (dari smali tabFeed), lewat PROXY + token
        path = {
            "foryou": "/reelshort/api/v1/foryou",
            "new": "/reelshort/api/v1/new",
            "romance": "/reelshort/api/v1/romance",
            "drama": "/reelshort/api/v1/drama",
            "completed": "/reelshort/api/v1/completed",
        }.get(tab, "/reelshort/api/v1/foryou")
        r = await self.pclient.get(path, params={"lang": lang})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {}) if isinstance(j, dict) else {}
        # shape: data.lists[] -> masing2 punya .books[]
        items = []
        for section in data.get("lists", []):
            for b in section.get("books", []):
                items.append({
                    "book_id": b.get("book_id"),
                    "title": b.get("book_title"),
                    "cover": b.get("book_pic"),
                    "chapter_count": b.get("chapter_count"),
                    "read_count": b.get("read_count"),
                })
        # dedupe by book_id
        seen = set()
        uniq = []
        for it in items:
            bid = it.get("book_id")
            if bid and bid not in seen:
                seen.add(bid)
                uniq.append(it)
        return {"source": tab, "lang": lang, "count": len(uniq), "items": uniq}

    # ---------- search ----------
    async def search(self, params: dict):
        q = params.get("q") or params.get("query") or params.get("keyword")
        if not q:
            raise ValueError("q required")
        lang = params.get("lang", "en")
        r = await self.pclient.get("/reelshort/api/v1/search", params={"q": q, "lang": lang})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {}) if isinstance(j, dict) else {}
        # shape: data.lists[] langsung berisi book
        items = [{
            "book_id": b.get("book_id"),
            "title": b.get("book_title"),
            "cover": b.get("book_pic"),
            "chapter_count": b.get("chapter_count"),
            "read_count": b.get("read_count"),
        } for b in data.get("lists", [])]
        return {"q": q, "total": data.get("total"), "count": len(items), "items": items}

    async def resolve_download(self, params: dict):
        """Return dict utk downloader: type (hls/mp4) + url (+ drm_token)."""
        info = await self.stream(params)
        return {"type": "hls", "url": info.get("video_url"), "drm_token": None,
                "title": info.get("title")}

    # ---------- home: via API proxy (foryou) — item dgn cover ----------
    async def home(self, params: dict):
        # lang: en/pt/de/th/tr/ar/in (in = Indonesia). default en.
        lang = params.get("lang", "en")
        r = await self.pclient.get("/reelshort/api/v1/foryou", params={"lang": lang})
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {}) if isinstance(j, dict) else {}
        items = []
        seen = set()
        for section in data.get("lists", []):
            for b in section.get("books", []):
                bid = b.get("book_id")
                if not bid or bid in seen:
                    continue
                seen.add(bid)
                items.append({
                    "book_id": bid,
                    "title": b.get("book_title"),
                    "cover": b.get("book_pic"),
                    "chapter_count": b.get("chapter_count"),
                    "read_count": b.get("read_count"),
                })
        return {"source": "foryou", "lang": lang, "count": len(items), "items": items}

    def _parse_home(self, html: str):
        books = []
        seen = set()
        # blok <a href="/episodes/...">...<img src/data-src="COVER">...</a>
        block_pat = re.compile(
            r'<a[^>]+href="(/episodes/episode-1-[^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
        for m in block_pat.finditer(html):
            clean = m.group(1).split("?")[0].rstrip("/")
            inner = m.group(2)
            segs = clean.split("-")
            if len(segs) < 3:
                continue
            chapter_id = segs[-1]
            book_id = segs[-2]
            if book_id in seen:
                continue
            seen.add(book_id)
            # cover: img src / data-src di dalam blok
            cover = ""
            im = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', inner)
            if im:
                cover = im.group(1)
            books.append({"book_id": book_id, "chapter_id": chapter_id,
                          "url": BASE + clean, "cover": cover})
        # judul dari <img alt="..."> (berurutan dg link episode)
        titles = [t for t in re.findall(r'<img[^>]+alt="([^"]+)"', html)
                  if t.lower() not in ("logo", "reelshort")]
        for i, b in enumerate(books):
            if i < len(titles):
                b["title"] = re.sub(r"&#x27;", "'", titles[i]).strip()
        return books

    # ---------- book detail ----------
    async def book_info(self, params: dict):
        book_id = params.get("book_id")
        if not book_id:
            raise ValueError("book_id required")
        r = await self.client.get("/api/video/book/getBookInfo", params={"book_id": book_id})
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            raise ValueError(j.get("msg"))
        return j.get("data", {})

    # ---------- chapter list ----------
    async def chapters(self, params: dict):
        book_id = params.get("book_id")
        if not book_id:
            raise ValueError("book_id required")
        page = params.get("page", 1)
        page_size = params.get("page_size", 100)
        r = await self.client.get("/api/video/book/getChapterList",
                                  params={"book_id": book_id, "page": page, "page_size": page_size})
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            raise ValueError(j.get("msg"))
        data = j.get("data", {})
        out = [{
            "chapter_id": c.get("chapter_id"),
            "serial_number": c.get("serial_number"),
            "duration": c.get("duration"),
            "video_pic": c.get("video_pic"),
            "desc": c.get("desc"),
        } for c in data.get("chapter_list", [])]
        return {
            "book_id": book_id,
            "title": data.get("book_title"),
            "book_pic": data.get("book_pic"),
            "count": len(out),
            "chapters": out,
        }

    # ---------- chapter info (metadata + video_url) ----------
    async def chapter_info(self, params: dict):
        book_id = params.get("book_id")
        chapter_id = params.get("chapter_id")
        if not book_id or not chapter_id:
            raise ValueError("book_id and chapter_id required")
        r = await self.client.get("/api/video/book/getChapterInfo",
                                  params={"book_id": book_id, "chapter_id": chapter_id})
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            raise ValueError(j.get("msg"))
        return j.get("data", {})

    # ---------- stream: balikin video_url HLS ----------
    async def stream(self, params: dict):
        book_id = params.get("book_id")
        chapter_id = params.get("chapter_id")
        if not book_id or not chapter_id:
            raise ValueError("book_id and chapter_id required")
        info = await self.chapter_info({"book_id": book_id, "chapter_id": chapter_id})
        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "title": info.get("book_title"),
            "serial_number": info.get("serial_number"),
            "duration": info.get("duration"),
            "video_url": info.get("video_url"),
            "video_pic": info.get("video_pic"),
            "type": "hls" if info.get("video_url", "").endswith(".m3u8") else "unknown",
        }

    async def free_chapter(self, params: dict):
        book_id = params.get("book_id")
        chapter_id = params.get("chapter_id")
        if not book_id or not chapter_id:
            raise ValueError("book_id and chapter_id required")
        r = await self.client.get("/api/video/book/getFreeChapter",
                                  params={"book_id": book_id, "chapter_id": chapter_id})
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            raise ValueError(j.get("msg"))
        return j.get("data", {})
