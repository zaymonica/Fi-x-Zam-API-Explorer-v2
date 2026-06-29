import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import crypto from "node:crypto";
import { Buffer } from "node:buffer";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, x-client-info, apikey",
};

function jsonResponse(data: any, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8" },
  });
}

function errorResponse(status: number, message: string) {
  return jsonResponse({ code: status, message, error: message }, status);
}

// ─── MovieBox Config ────────────────────────────────────────────────────────
const MB_HOST = "https://api4sg.aoneroom.com";
const MB_BFF = "/wefeed-mobile-bff";
const MB_SIGN_SECRET = "76iRl07s0xSN9jqmEWAt79EBJZulIQIsV64FZr2O";
const MB_KEY_VERSION = "1";
const MB_VERSION_NAME = "3.0.15.0513.03";
const MB_VERSION_CODE = 30015013;
const MB_PACKAGE = "com.community.oneroom";
const MB_UA = `${MB_PACKAGE}/${MB_VERSION_CODE}`;

const MB_REGION = "ID";
const MB_LANGUAGE = "in";
const MB_TIMEZONE = "Asia/Jakarta";
const MB_TIMEOUT = 20000;

const MB_RANKING_LIST_ID = "9047558218997816672";
const MB_RANKING_CATEGORIES: Record<string, any> = {
  indonesia: { name: "Indonesia", type: "6528093688173053896" },
  global: { name: "Seluruh dunia", type: "8821254238245470240" },
  hollywood: { name: "Hollywood", type: "997144265920760504" },
  asia: { name: "Asia lainnya", type: "4230655749032234008" },
  horror: { name: "Horror", type: "5848753831881965888" },
  animasi: { name: "Animasi", type: "7132534597631837112" },
};

const MB_DRAMA_LIST_ID = "7311490931390663312";
const MB_DRAMA_CATEGORIES: Record<string, any> = {
  kdrama: { name: "K-Drama", type: "4380734070238626200" },
  indo: { name: "Indo Drama", type: "5283462032510044280" },
  anime: { name: "Anime", type: "8617025562613270856" },
  barat: { name: "Barat", type: "5307082080063488480" },
  cdrama: { name: "C-Drama", type: "8624142774394406504" },
  thai: { name: "Thai-Drama", type: "1164329479448281992" },
  reality: { name: "Reality", type: "5720220657917522824" },
};

// ─── Token Cache ────────────────────────────────────────────────────────────
let _tokenCache = { token: "", deviceId: "", exp: 0 };

// ─── Helpers ────────────────────────────────────────────────────────────────
function md5Hex(str: string): string {
  return crypto.createHash("md5").update(str).digest("hex");
}

function clientToken(): string {
  const ts = String(Date.now());
  return `${ts},${md5Hex(md5Hex(ts))}`;
}

function clientInfo(deviceId: string): string {
  return JSON.stringify({
    package_name: MB_PACKAGE,
    version_name: MB_VERSION_NAME,
    version_code: MB_VERSION_CODE,
    os: "android",
    os_version: "13",
    device_id: deviceId,
    install_store: "1",
    brand: "samsung",
    model: "SM-G991B",
    system_language: MB_LANGUAGE,
    net: "WIFI",
    region: MB_REGION,
    timezone: MB_TIMEZONE,
    sp_code: "",
  });
}

function sortedQueryString(params: URLSearchParams): string {
  if (!params || [...params.keys()].length === 0) return "";
  const pairs = [...params.entries()];
  pairs.sort((a, b) => a[0].localeCompare(b[0]));
  return pairs.map(([k, v]) => `${k}=${v}`).join("&");
}

function xTrSignature(method: string, pathWithQuery: string, bodyText: string): string {
  const ts = Date.now();
  const accept = "*/*";
  const contentType = "application/json";
  const bodyLen = bodyText ? String(bodyText.length) : "";
  const bodyHash = bodyText ? md5Hex(bodyText) : "";

  // The logic to extract path and search params
  const [pathPart, queryPart] = pathWithQuery.split("?");
  let normPath = pathPart;
  if (queryPart) {
    const params = new URLSearchParams(queryPart);
    const sq = sortedQueryString(params);
    if (sq) normPath = `${normPath}?${sq}`;
  }

  const signString = [
    method.toUpperCase(), accept, contentType, bodyLen,
    String(ts), bodyHash, normPath
  ].join("\n");

  const key = Buffer.from(MB_SIGN_SECRET, "base64");
  const mac = crypto.createHmac("md5", key).update(signString, "utf8").digest("base64");
  return `${ts}|${MB_KEY_VERSION}|${mac}`;
}

function uuidv4(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

async function getToken(force = false): Promise<{ token: string; deviceId: string }> {
  const now = Math.floor(Date.now() / 1000);
  if (!force && _tokenCache.token && _tokenCache.exp - 60 > now) {
    return { token: _tokenCache.token, deviceId: _tokenCache.deviceId };
  }

  const deviceId = _tokenCache.deviceId || uuidv4();
  const path = `${MB_BFF}/user-api/visitor-login`;
  const body = JSON.stringify({ deviceId });
  const headers = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "x-tr-signature": xTrSignature("POST", path, body),
    "X-Client-Token": clientToken(),
    "X-Client-Info": clientInfo(deviceId),
    "X-Client-Status": "1",
    "User-Agent": MB_UA,
  };

  const resp = await fetch(MB_HOST + path, { method: "POST", headers, body });
  const data = await resp.json();
  if (data.code !== 0 || !data.data?.token) {
    throw new Error(`visitor-login failed: ${data.message || JSON.stringify(data)}`);
  }

  const token = data.data.token;
  let exp = now + 3600 * 24;
  try {
    const payloadB64 = token.split(".")[1];
    const padded = payloadB64.padEnd(payloadB64.length + (4 - (payloadB64.length % 4)) % 4, "=");
    const claims = JSON.parse(atob(padded));
    if (claims.exp) exp = parseInt(claims.exp, 10);
  } catch (e) {}

  _tokenCache = { token, deviceId, exp };
  return { token, deviceId };
}

async function mbRequest(method: string, path: string, query: Record<string, any> = {}, payload: any = null, retry = true): Promise<any> {
  const { token, deviceId } = await getToken();
  const searchParams = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) searchParams.append(k, String(v));
  }
  const queryStr = searchParams.toString();
  const fullPath = path + (queryStr ? `?${queryStr}` : "");
  const bodyText = payload ? JSON.stringify(payload) : "";

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "x-tr-signature": xTrSignature(method, fullPath, bodyText),
    "X-Client-Token": clientToken(),
    "X-Client-Info": clientInfo(deviceId),
    "X-Client-Status": "1",
    "Authorization": `Bearer ${token}`,
    "User-Agent": MB_UA,
  };

  const url = MB_HOST + fullPath;
  const reqInit: RequestInit = { method, headers };
  if (method.toUpperCase() !== "GET" && method.toUpperCase() !== "HEAD") {
    reqInit.body = bodyText;
  }

  const resp = await fetch(url, reqInit);
  let data;
  try {
    data = await resp.json();
  } catch (e) {
    return { code: -1, message: "invalid json", raw: await resp.text() };
  }

  if (retry && (resp.status === 401 || resp.status === 403 || data?.code === 401 || data?.code === 403)) {
    await getToken(true);
    return mbRequest(method, path, query, payload, false);
  }
  return data;
}

// ─── API Methods ────────────────────────────────────────────────────────────

async function ranking(catKey: string, categories = MB_RANKING_CATEGORIES, defaultListId = MB_RANKING_LIST_ID, reqUrl: URL) {
  const cat = categories[catKey];
  if (!cat) throw new Error("Category not found");
  const page = reqUrl.searchParams.get("page") || "1";
  const perPage = reqUrl.searchParams.get("perPage") || "10";
  const tabId = reqUrl.searchParams.get("tabId") || "0";
  const rankingListId = reqUrl.searchParams.get("rankingListId") || defaultListId;

  const data = await mbRequest("GET", `${MB_BFF}/tab/ranking-list`, {
    tabId, categoryType: cat.type, page, perPage, rankingListId,
  });
  if (data && typeof data === "object" && !Array.isArray(data)) {
    data.category = { key: catKey, name: cat.name, type: cat.type };
  }
  return data;
}

async function indoCaption(sid: string, streamId: string) {
  try {
    const caps = await mbRequest("GET", `${MB_BFF}/subject-api/get-stream-captions`, { subjectId: sid, streamId });
    const ext = caps?.data?.extCaptions || [];
    for (const c of ext) {
      if (["in_id", "id", "in"].includes(c.lan) || c.lanName === "Indonesian") {
        return c;
      }
    }
  } catch (e) {}
  return null;
}

async function originalDubSid(subjectId: string) {
  try {
    const di = await mbRequest("GET", `${MB_BFF}/subject-api/dub-info`, { subjectId });
    const dubs = di?.data?.dubs || [];
    for (const d of dubs) {
      if (d.original && d.subjectId) return d.subjectId;
    }
    if (dubs.length > 0 && dubs[0].subjectId) return dubs[0].subjectId;
  } catch (e) {}
  return subjectId;
}

async function fetchResource(sid: string, se: number, epFrom: number, epTo: number, resolution: number, perPage: number, pagerMode = 0) {
  const res = await mbRequest("GET", `${MB_BFF}/subject-api/resource`, {
    subjectId: sid, page: 1, perPage,
    all: 0, startPosition: epFrom, endPosition: epTo, pagerMode,
    resolution, se, epFrom, epTo,
  });
  const data = res?.data || {};
  return { files: data.list || [], meta: data };
}

// ─── Request Handler ────────────────────────────────────────────────────────
serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/moviebox\/?/, "/");

  try {
    if (path === "/" || path === "") {
      return jsonResponse({
        author: "Sonzai X シ",
        contact: "https://t.me/November2k",
        status: "online",
        service: "MovieBox Ranking API",
        source: "aoneroom / wefeed",
        region: MB_REGION,
        version: "2.0.0",
      });
    }

    if (path === "/homepage") {
      const tabId = url.searchParams.get("tabId") || "0";
      const version = url.searchParams.get("version") || "";
      const data = await mbRequest("GET", `${MB_BFF}/tab-operating`, { tabId, version });
      return jsonResponse(data);
    }

    if (path === "/search") {
      const keyword = url.searchParams.get("q") || url.searchParams.get("keyword");
      if (!keyword) return errorResponse(400, "missing 'q' (keyword)");
      const page = url.searchParams.get("page") || "1";
      const perPage = url.searchParams.get("perPage") || "10";
      const data = await mbRequest("POST", `${MB_BFF}/subject-api/search/v2`, {}, { page: parseInt(page, 10), perPage: parseInt(perPage, 10), keyword });
      return jsonResponse(data);
    }

    if (path === "/detail") {
      const subjectId = url.searchParams.get("subjectId") || url.searchParams.get("id");
      if (!subjectId) return errorResponse(400, "missing 'subjectId'");
      const query: any = { subjectId };
      if (url.searchParams.has("se")) query.se = url.searchParams.get("se");
      const data = await mbRequest("GET", `${MB_BFF}/subject-api/get`, query);
      return jsonResponse(data);
    }

    if (path === "/download-movie") {
      const subjectId = url.searchParams.get("subjectId") || url.searchParams.get("id");
      if (!subjectId) return errorResponse(400, "missing 'subjectId'");
      const se = parseInt(url.searchParams.get("se") || "1", 10);
      const ep = parseInt(url.searchParams.get("ep") || "1", 10);
      const perPage = parseInt(url.searchParams.get("perPage") || "20", 10);
      const resolution = parseInt(url.searchParams.get("resolution") || "0", 10);

      const sid = await originalDubSid(subjectId);
      const { files, meta } = await fetchResource(sid, se, ep, ep, resolution, perPage);

      let subtitle = null;
      try {
        for (const q of [{ subjectId: sid, se, ep }, { subjectId: sid, se: 0, ep: 0 }]) {
          const play = await mbRequest("GET", `${MB_BFF}/subject-api/play-info`, q);
          const streams = play?.data?.streams || [];
          if (streams.length > 0 && streams[0].id) {
            subtitle = await indoCaption(sid, streams[0].id);
            if (subtitle) break;
          }
        }
      } catch (e) {}

      if (!subtitle) {
        for (const f of files) {
          if (f.resourceId) {
            subtitle = await indoCaption(sid, f.resourceId);
            if (subtitle) break;
          }
        }
      }

      return jsonResponse({
        code: 0, message: "ok",
        data: {
          subjectId: sid,
          title: meta.subjectTitle,
          totalSize: meta.totalSize,
          subtitle,
          files: files.map((f: any) => ({
            resolution: f.resolution,
            size: f.size,
            codecName: f.codecName,
            duration: f.duration,
            resourceLink: f.resourceLink,
            resourceId: f.resourceId,
          })),
        },
      });
    }

    if (path === "/download-series") {
      const subjectId = url.searchParams.get("subjectId") || url.searchParams.get("id");
      if (!subjectId) return errorResponse(400, "missing 'subjectId'");
      const se = parseInt(url.searchParams.get("se") || "1", 10);
      const perPage = parseInt(url.searchParams.get("perPage") || "20", 10);
      const resolution = parseInt(url.searchParams.get("resolution") || "0", 10);
      const epTo = parseInt(url.searchParams.get("epTo") || "10", 10);

      const sid = await originalDubSid(subjectId);
      let { files, meta } = await fetchResource(sid, se, 1, epTo, resolution, perPage, 1);
      if (!files || files.length === 0) {
        ({ files, meta } = await fetchResource(sid, se, 1, 1, resolution, perPage, 0));
      }

      const episodes = [];
      let idx = 1;
      for (const f of files) {
        const epNo = f.ep || idx;
        const rid = f.resourceId;
        let subtitle = null;
        try {
          const play = await mbRequest("GET", `${MB_BFF}/subject-api/play-info`, { subjectId: sid, se, ep: epNo });
          const streams = play?.data?.streams || [];
          if (streams.length > 0 && streams[0].id) {
            subtitle = await indoCaption(sid, streams[0].id);
          }
        } catch (e) {}
        if (!subtitle && rid) subtitle = await indoCaption(sid, rid);
        episodes.push({
          se: f.se,
          ep: epNo,
          title: f.title,
          resolution: f.resolution,
          size: f.size,
          codecName: f.codecName,
          duration: f.duration,
          resourceLink: f.resourceLink,
          resourceId: rid,
          subtitle,
        });
        idx++;
      }

      return jsonResponse({
        code: 0, message: "ok",
        data: {
          subjectId: sid,
          title: meta.subjectTitle,
          totalEpisode: meta.totalEpisode || episodes.length,
          totalSize: meta.totalSize,
          episodes,
        },
      });
    }

    // Static Ranking Routes
    for (const cat of ["indonesia", "global", "hollywood", "asia", "horror", "animasi"]) {
      if (path === `/${cat}`) return jsonResponse(await ranking(cat, MB_RANKING_CATEGORIES, MB_RANKING_LIST_ID, url));
    }

    if (path === "/series" || path === "/series/") {
      return jsonResponse({
        code: 0,
        rankingListId: MB_DRAMA_LIST_ID,
        categories: Object.entries(MB_DRAMA_CATEGORIES).map(([k, v]) => ({
          key: k, name: v.name, type: v.type, path: `/moviebox/series/${k}`
        })),
      });
    }

    if (path.startsWith("/series/")) {
      const cat = path.split("/")[2].toLowerCase();
      if (!MB_DRAMA_CATEGORIES[cat]) {
        return errorResponse(404, `unknown series category '${cat}'. Available: ${Object.keys(MB_DRAMA_CATEGORIES).join(", ")}`);
      }
      return jsonResponse(await ranking(cat, MB_DRAMA_CATEGORIES, MB_DRAMA_LIST_ID, url));
    }

    return errorResponse(404, "Endpoint not found");

  } catch (e: any) {
    return errorResponse(500, e.message || String(e));
  }
});
