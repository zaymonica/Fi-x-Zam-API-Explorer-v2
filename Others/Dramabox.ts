// Supabase Edge Function: DramaBox API (Native Port)
// Native Deno implementation to bypass Cloudflare Worker WAF blocks
// Uses static hardcoded token by default to skip register process.

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
};

function jsonResponse(data: any, status = 200) {
    return new Response(JSON.stringify(data, null, 2), {
        status,
        headers: { ...CORS, "Content-Type": "application/json; charset=utf-8" },
    });
}

// ─── Constants Settings ───────────────────────────────────────────────
const BASE_URL = "https://sapi.dramaboxdb.com/drama-box";

const CATEGORIES: Record<string, string> = { cina: "中国", korea: "韩国", amerika: "美国" };

const LANG_MAP: Record<string, any> = {
  "en": { lang: "en", locale: "en_US", code: "US" },
  "ja": { lang: "ja", locale: "ja_JP", code: "JP" },
  "ko": { lang: "ko", locale: "ko_KR", code: "KR" },
  "es": { lang: "es", locale: "es_ES", code: "ES" },
  "in": { lang: "in", locale: "in_ID", code: "ID" },
  "fr": { lang: "fr", locale: "fr_FR", code: "FR" },
  "pt": { lang: "pt", locale: "pt_BR", code: "BR" },
  "th": { lang: "th", locale: "th_TH", code: "TH" },
  "ar": { lang: "ar", locale: "ar_SA", code: "SA" },
  "de": { lang: "de", locale: "de_DE", code: "DE" },
  "pl": { lang: "pl", locale: "pl_PL", code: "PL" },
  "vi": { lang: "vi", locale: "vi_VN", code: "VN" },
  "it": { lang: "it", locale: "it_IT", code: "IT" },
  "tr": { lang: "tr", locale: "tr_TR", code: "TR" },
  "zh": { lang: "zh", locale: "zh_TW", code: "TW" },
  "zhHans": { lang: "zh", currentLang: "zhHans", locale: "zh_CN", code: "CN" }
};

// ─── Crypto Implementation (EdDSA / RSA PKCS8 PEM) ─────────────────────────
const KEY_PART1 = "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC9Q4Y5QX5j08HrnbY3irfKdkEllAU2OORnAjlXDyCzcm2Z6ZRrGvtTZUAMelfU5PWS6XGEm3d4kJEKbXi4Crl8o2E/E3YJPk1lQD1d0JTdrvZleETN1ViHZFSQwS3L94Woh0E3TPebaEYq88eExvKu1tDdjSoFjBbgMezySnas5Nc2xF28";
const KEY_PART2_OBFUSCATED = 'l|d,WL$EI,?xyw+*)^#?U`[whXlG`-GZif,.jCxbKkaY"{w*y]_jax^/1iVDdyg(Wbz+z/$xVjCiH0lZf/d|%gZglW)"~J,^~}w"}m(E\'eEunz)eyEy`XGaVF|_(Kw)|awUG"\'{{e#%$0E.ffHVU++$giHzdvC0ZLXG|U{aVUUYW{{YVU^x),J\'If`nG|C[`ZF),xLv(-H\'}ZIEyCfke0dZ%aU[V)"V0}mhKvZ]Gw%-^a|m\'`\\f}{(~kzi&zjG+|fXX0$IH#j`+hfnME"|fa/{.j.xf,"LZ.K^bZy%c.W^/v{x#(J},Ua,ew#.##K(ki)$LX{a-1\\MG/zL&JlEKEw\'Hg|D&{EfuKYM[nGKx1V#lFu^V_LjVzw+n%+,Xd';
const KEY_PART3 = "x52e71nafqfbjXxZuEtpu92oJd6A9mWbd0BZTk72ZHUmDcKcqjfcEH19SWOphMJFYkxU5FRoIEr3/zisyTO4Mt33ZmwELOrY9PdlyAAyed7ZoH+hlTr7c025QROvb2LmqgRiUT56tMECgYEA+jH5m6iMRK6XjiBhSUnlr3DzRybwlQrtIj5sZprWe2my5uYHG3jbViYIO7GtQvMTnDrBCxNhuM6dPrL0cRnbsp/iBMXe3pyjT/aWveBkn4R+UpBsnbtDn28r1MZpCDtr5UNc0TPj4KFJvjnV/e8oGoyYEroECqcw1LqNOGDiLhkCgYEAwaemNePYrXW+MVX/hatfLQ96tpxwf7yuHdENZ2q5AFw73GJWYvC8VY+TcoKPAmeoCUMltI3TrS6K5Q/GoLd5K2BsoJrSxQNQFd3ehWAtdOuPDvQ5rn/2fsvgvc3rOvJh7uNnwEZCI/45WQg+UFWref4PPc+ArNtp9Xj2y7LndwkCgYARojIQeXmhYZjG6JtSugWZLuHGkwUDzChYcIPdW25gdluokG/RzNvQn4+W/XfTryQjr7RpXm1VxCIrCBvYWNU2KrSYV4XUtL+B5ERNj6In6AOrOAifuVITy5cQQQeoD+AT4YKKMBkQfO2gnZzqb8+ox130e+3K/mufoqJPZeyrCQKBgC2fobjwhQvYwYY+DIUharri+rYrBRYTDbJYnh/PNOaw1CmHwXJt5PEDcml3+NlIMn58I1X2U/hpDrAIl3MlxpZBkVYFI8LmlOeR7ereTddN59ZOE4jY/OnCfqA480Jf+FKfoMHby5lPO5OOLaAfjtae1FhrmpUe3EfIx9wVuhKBAoGBAPFzHKQZbGhkqmyPW2ctTEIWLdUHyO37fm8dj1WjN4wjRAI4ohNiKQJRh3QE11E1PzBTl9lZVWT8QtEsSjnrA/tpGr378fcUT7WGBgTmBRaAnv1P1n/Tp0TSvh5XpIhhMuxcitIgrhYMIG3GbP9JNAarxO/qPW6Gi0xWaF7il7Or";

function caesarDecode(s: string) {
  let result = "";
  for (const ch of s) {
    const code = ch.charCodeAt(0);
    if (code < 0x21 || code > 0x7e) { result += ch; continue; }
    const shifted = code - 20;
    result += shifted < 0x21 ? String.fromCharCode(shifted + 0x5d) : String.fromCharCode(shifted);
  }
  return result;
}

const FULL_KEY_B64 = KEY_PART1 + caesarDecode(KEY_PART2_OBFUSCATED) + KEY_PART3;

let _privateKey: CryptoKey | null = null;
async function getPrivateKey() {
  if (_privateKey) return _privateKey;
  const bin = atob(FULL_KEY_B64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  _privateKey = await crypto.subtle.importKey(
    "pkcs8", buf.buffer,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false, ["sign"]
  );
  return _privateKey;
}

async function signData(dataStr: string) {
  const key = await getPrivateKey();
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(dataStr));
  const bytes = new Uint8Array(sig);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

// ─── Token Cache & Identifiers ─────────────────────────────────────────────
// WAJIB menggunakan Hardcoded Token secara default. 
// Token baru (bootstrap) biasanya akan ter-sandbox oleh DramaBox, menyebabkan Search kosong dan Bahasa reset ke default (ngaco).
let _tokenCache: any = {
  token: "Bearer ZXlKMGVYQWlPaUpLVjFRaUxDSmhiR2NpT2lKSVV6STFOaUo5LmV5SnlaV2RwYzNSbGNsUjVjR1VpT2lKUVJWSk5RVTVGVGxRaUxDSjFjMlZ5U1dRaU9qUXlNVFEyTVRBd09IMC5HTWVmdzh3YzRCb18zdlBoa2t4ZXVvcVp1cXhiQ0lfbFVuX0dBM1BXcjhB",
  deviceId: "df04c9f1-daac-439d-9a77-502c55391714",
  androidId: "ffffffff8a124e658a124e6500000000",
  expiry: 0  // Force bootstrap — hardcoded token sudah expired/ditolak
};

function generateUUID() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function randomAndroidId() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function bootstrapToken() {
  const deviceId = generateUUID();
  const androidId = randomAndroidId();
  const timestamp = String(Date.now());
  const body = JSON.stringify({ distinctId: null });

  const dataToSign = `timestamp=${timestamp}${body}${deviceId}${androidId}`;
  const sn = await signData(dataToSign);

  const headers = {
    "content-type": "application/json; charset=UTF-8",
    "user-agent": "okhttp/4.12.0",
    "tn": "",
    "version": "561",
    "vn": "5.6.1",
    "cid": "DRA1000042",
    "package-name": "com.storymatrix.drama",
    "apn": "2",
    "p": "55",
    "pline": "ANDROID",
    "device-id": deviceId,
    "android-id": androidId,
    "language": "in",
    "current-language": "in",
    "sn": sn,
  };

  const url = `${BASE_URL}/ap001/bootstrap?timestamp=${timestamp}`;
  const resp = await fetch(url, { method: "POST", headers, body });
  const textResponse = await resp.text();
  
  let data;
  try {
    data = JSON.parse(textResponse);
  } catch (err) {
    console.error("Gagal parse JSON bootstrap (mungkin WAF blokir IP AWS):", textResponse.substring(0, 50));
    throw new Error(`Bootstrap failed: WAF Block terdeteksi`);
  }

  if (!data?.data?.user?.token) {
    throw new Error(`Bootstrap failed: ${JSON.stringify(data)}`);
  }

  const tokenData = {
    token: `Bearer ${data.data.user.token}`,
    deviceId,
    androidId,
    expiry: Date.now() + 12 * 60 * 60 * 1000, 
  };
  _tokenCache = tokenData;
  return tokenData;
}

async function getActiveToken() {
  if (_tokenCache && _tokenCache.expiry > Date.now()) {
    return _tokenCache;
  }
  try {
    return await bootstrapToken();
  } catch (e) {
    console.error("Gagal generate token dinamis, fallback ke _tokenCache lama:", e);
    return _tokenCache;
  }
}

async function refreshToken() {
  const oldCache = _tokenCache;
  _tokenCache = null;
  try {
    return await bootstrapToken();
  } catch (e) {
    console.error("Refresh gagal, restore token lama:", e);
    _tokenCache = oldCache;
    return oldCache;
  }
}

// ─── Request Builder ───────────────────────────────────────────
async function makeRequest(endpoint: string, body: any, langCode = "in", _retry = false) {
  const tokenData = await getActiveToken();
  if (!tokenData || !tokenData.deviceId) {
    throw new Error("No valid token available — bootstrap may have failed.");
  }
  const timestamp = String(Date.now());
  const requestBody = JSON.stringify(body);

  const dataToSign = `timestamp=${timestamp}${requestBody}${tokenData.deviceId}${tokenData.androidId}${tokenData.token}`;
  const sn = await signData(dataToSign);

  const url = `${BASE_URL}/${endpoint}?timestamp=${timestamp}`;

  const now = new Date();
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  const localTime = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.000 +0700`;

  const lMap = LANG_MAP[langCode] || LANG_MAP[langCode.toLowerCase()] || LANG_MAP["in"];

  const headers = {
    "content-type": "application/json; charset=UTF-8",
    "user-agent": "okhttp/4.12.0",
    "version": "561",
    "vn": "5.6.1",
    "pline": "ANDROID",
    "package-name": "com.storymatrix.drama",
    "p": "55",
    "cid": "DRA1000042",
    "apn": "2",
    "device-id": tokenData.deviceId,
    "android-id": tokenData.androidId,
    "tn": tokenData.token,
    "language": lMap.lang,
    "current-language": lMap.currentLang || lMap.lang,
    "country-code": lMap.code,
    "locale": lMap.locale,
    "local-time": localTime,
    "sn": sn,
    "active-time": String(Date.now() - 1771784575869),
  };

  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: requestBody,
  });

  const textResponse = await resp.text();
  let result;
  try {
    result = JSON.parse(textResponse);
  } catch (err) {
    // Return HTML error payload politely if Supabase IP gets WAF'd
    return {
      success: false,
      status: 403,
      message: "AWS (Supabase) IP is currently blocked by DramaBox WAF.",
      error_html_snippet: textResponse.substring(0, 150)
    };
  }

  // Auto-refresh if access denied (status 12 = 拒绝访问)
  if (!_retry && result.success === false && (result.status === 12 || result.message === "拒绝访问")) {
    await refreshToken();
    return makeRequest(endpoint, body, langCode, true);
  }

  return result;
}

// ─── Routing Core ────────────────────────────────────────────────────────
function getPage(url: URL) {
  const p = parseInt(url.searchParams.get("page") || "1", 10);
  return p >= 1 ? p : 1;
}

async function handleDramaboxList(url: URL) {
  const page = getPage(url);
  const lang = url.searchParams.get("lang") || "in";

  if (url.searchParams.has("new")) {
    return jsonResponse(await makeRequest("he001/theater", {
      newChannelStyle: 1, isNeedRank: 1, pageNo: page, index: 1, channelId: 43,
    }, lang));
  }

  if (url.searchParams.has("home")) {
    if (page === 1) {
      return jsonResponse(await makeRequest("he001/theater", {
        homePageStyle: 0, isNeedRank: 1, index: 0, type: 0, channelId: 175,
      }, lang));
    }
    return jsonResponse(await makeRequest("he001/recommendBook", {
      isNeedRank: 1, specialColumnId: 0, pageNo: page,
    }, lang));
  }

  if (url.searchParams.has("category")) {
    const cat = (url.searchParams.get("category") || "").toLowerCase();
    if (!CATEGORIES[cat]) {
      return jsonResponse({ error: `Unknown category '${cat}'`, available: Object.keys(CATEGORIES) }, 400);
    }
    return jsonResponse(await makeRequest("he001/classify", {
      typeList: [
        { type: 1, value: CATEGORIES[cat] },
        { type: 2, value: "" }, { type: 3, value: "" },
        { type: 4, value: "" }, { type: 4, value: "" },
        { type: 5, value: "1" },
      ],
      showLabels: false, pageNo: page, pageSize: 15,
    }, lang));
  }

  if (url.searchParams.has("rank")) {
    const [r1, r2, r3] = await Promise.all([
      makeRequest("he001/rank", { rankType: 1 }, lang),
      makeRequest("he001/rank", { rankType: 2 }, lang),
      makeRequest("he001/rank", { rankType: 3 }, lang),
    ]);
    return jsonResponse({
      success: true,
      trending: (r1.data || {}).rankList || [],
      popular: (r2.data || {}).rankList || [],
      newest: (r3.data || {}).rankList || [],
    });
  }

  if (url.searchParams.has("populer")) {
    return jsonResponse(await makeRequest("he001/classify", {
      typeList: [
        { type: 1, value: "" }, { type: 2, value: "" },
        { type: 3, value: "" }, { type: 4, value: "" },
        { type: 4, value: "" }, { type: 5, value: "1" },
      ],
      showLabels: false, pageNo: page, pageSize: 15,
    }, lang));
  }

  if (url.searchParams.has("search")) {
    const keyword = url.searchParams.get("search") || "";
    if (!keyword) return jsonResponse({ error: "Provide search query, e.g. ?search=cinta&page=1" }, 400);
    return jsonResponse(await makeRequest("search/search", {
      searchSource: "搜索按钮", pageNo: page, pageSize: 20,
      from: "search_sug", keyword,
    }, lang));
  }

  return jsonResponse({ error: "Use ?home, ?new, ?populer, ?category=, ?rank, or ?search=" }, 400);
}

async function handleDetail(url: URL) {
  const bookId = url.searchParams.get("bookId") || url.searchParams.get("id") || url.searchParams.get("dramaId") || "";
  const lang = url.searchParams.get("lang") || "in";
  if (!bookId) return jsonResponse({ error: "Provide bookId, e.g. /detail?bookId=42000004908" }, 400);

  const [streamReq, detailReq] = await Promise.all([
    makeRequest("chapterv2/batch/load", {
      boundaryIndex: 0, index: 0, comingPlaySectionId: -1,
      currencyPlaySource: "discover_175_rec", needEndRecommend: 0,
      currencyPlaySourceName: "首页发现_Untukmu_推荐列表", preLoad: false,
      rid: "", pullCid: "", enterReaderChapterIndex: 0, loadDirection: 2,
      startUpKey: "22f8e732-51fc-4e0f-b2ba-07043dfbf5f2", bookId,
    }, lang),
    makeRequest("chapterv2/detail", {
      needRecommend: false, from: "book_ablum", bookId,
    }, lang)
  ]);

  if (streamReq.success && streamReq.data && detailReq.success && detailReq.data) {
    const sData = streamReq.data;
    const mergeKeys = [
      "bookId", "bookName", "bookCover", "introduction", "playCount",
      "tags", "tagV3s", "markNamesConnectKey", "firstPlaySourceVo",
      "chapterCount", "inLibraryCount", "playChapterIndex",
      "bookCategory", "bookType", "inLibrary", "vip"
    ];
    const newData: any = {};
    for (const k of mergeKeys) {
      if (sData[k] !== undefined) newData[k] = sData[k];
    }
    for (const k in detailReq.data) {
      newData[k] = detailReq.data[k];
    }
    detailReq.data = newData;
  }

  return jsonResponse(detailReq);
}

async function handleStream(url: URL) {
  const bookId = url.searchParams.get("bookId") || url.searchParams.get("id") || url.searchParams.get("dramaId") || "";
  const lang = url.searchParams.get("lang") || "in";
  if (!bookId) return jsonResponse({ error: "Provide bookId, e.g. /stream?bookId=42000004908&chapterIndex=0" }, 400);

  const epParam = url.searchParams.get("chapterIndex") || url.searchParams.get("episodeIndex") || url.searchParams.get("episode");
  const chapterIndex = parseInt(epParam || "0", 10) || 0;

  const result = await makeRequest("chapterv2/batch/load", {
    boundaryIndex: 0, comingPlaySectionId: -1,
    index: chapterIndex,
    currencyPlaySource: "discover_175_rec",
    needEndRecommend: 0,
    currencyPlaySourceName: "首页发现_Untukmu_推荐列表",
    preLoad: false, rid: "", pullCid: "",
    enterReaderChapterIndex: 0,
    loadDirection: 2,
    startUpKey: "22f8e732-51fc-4e0f-b2ba-07043dfbf5f2",
    bookId,
  }, lang);

  // Filter to only the requested chapter
  if (result.success && result.data) {
    const chapters = result.data.chapterList || [];
    const matched = chapters.filter((ch: any) => ch.chapterIndex === chapterIndex);
    result.data = { chapterList: matched };
  }

  return jsonResponse(result);
}

// ─── Edge Function Entry ──────────────────────────────────────────────────
serve(async (req) => {
    if (req.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: CORS });
    }

    const url = new URL(req.url);
    const path = url.pathname;

    try {
        // Debug endpoint — test bootstrap dari Supabase
        if (path.endsWith("/test")) {
            try {
                const token = await bootstrapToken();
                return jsonResponse({
                  success: true,
                  message: "Bootstrap OK",
                  deviceId: token.deviceId,
                  tokenPreview: token.token.substring(0, 30) + "...",
                });
            } catch (e) {
                return jsonResponse({
                  success: false,
                  message: "Bootstrap FAILED",
                  error: (e as Error).message,
                }, 500);
            }
        }

        if (path.endsWith("/detail")) return await handleDetail(url);
        if (path.endsWith("/stream")) return await handleStream(url);
        
        // Handle root/home routing natively
        if (
            url.searchParams.has("home") || 
            url.searchParams.has("new") || 
            url.searchParams.has("category") || 
            url.searchParams.has("rank") || 
            url.searchParams.has("populer") || 
            url.searchParams.has("search")
        ) {
            return await handleDramaboxList(url);
        }

        // Info Route Provide Documentation
        return jsonResponse({
          author: "Sonzai X シ",
          message: "DramaBox API Native Supabase",
          routes: [
            "/?home&page=1",
            "/?new&page=1",
            "/?populer&page=1",
            "/?category=cina&page=1",
            "/?rank",
            "/?search=cinta&page=1",
            "/detail?bookId=42000004908",
            "/stream?bookId=42000004908&chapterIndex=0",
          ],
        });
    } catch (err) {
        return jsonResponse({ error: "Server Error", message: (err as Error).message }, 500);
    }
});
