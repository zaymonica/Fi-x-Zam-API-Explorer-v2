/**
 * Cloudflare Worker - Unified Proxy (TeraBox + FlickReels HLS)
 *
 * Routes:
 *   /dl?url=<URL>&cookie=<BASE64>  - TeraBox download proxy (CORS & Resume/Pause)
 *   /tb?url=<URL>&cookie=<BASE64>  - TeraBox API proxy (JSON passthrough, for /share/list, /api/shorturlinfo etc)
 *   /proxy?url=<URL>               - FlickReels HLS proxy (.m3u8 rewriting + .ts streaming)
 *
 * Deploy:
 *   npx wrangler deploy hls-proxy-worker.js --name proxy-sonzaixlab
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Handle CORS Preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    // Route: /dl?url=... → TeraBox Download Proxy
    if (url.pathname === "/dl") {
      return handleTeraboxProxy(request, url);
    }

    // Route: /tb?url=... → TeraBox API Proxy (JSON passthrough)
    if (url.pathname === "/tb") {
      return handleTeraboxApiProxy(request, url);
    }

    // Route: /proxy?url=... → FlickReels HLS Proxy
    if (url.pathname === "/proxy") {
      return handleHlsProxy(request, url);
    }

    // Route: /stream?id=..&auth_key=.. → Melolo decrypted-MP4 CDN proxy (range-aware)
    if (url.pathname === "/stream") {
      return handleMeloloProxy(request, url);
    }

    // Default: show usage
    return new Response(JSON.stringify({
      service: "Unified Proxy Worker",
      routes: {
        "/dl?url=<URL>&cookie=<BASE64>": "TeraBox download proxy (CORS, resume/pause)",
        "/tb?url=<URL>&cookie=<BASE64>": "TeraBox API proxy (JSON passthrough)",
        "/proxy?url=<URL>": "FlickReels HLS proxy (.m3u8 rewriting + .ts streaming)",
        "/stream?id=<ID>&auth_key=<KEY>": "Melolo decrypted-MP4 CDN proxy (range-aware)",
      },
    }, null, 2), {
      headers: { "Content-Type": "application/json", ...corsHeaders() },
    });
  }
};

// ==================== SHARED ====================

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type, Authorization",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
    "Access-Control-Max-Age": "86400",
  };
}

function errorResponse(message, status = 400) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders() },
  });
}

function parseTargetUrl(rawUrl) {
  if (!rawUrl) return null;
  try {
    let targetUrl;
    if (rawUrl.startsWith("http")) {
      targetUrl = rawUrl;
    } else {
      targetUrl = atob(rawUrl); // base64 decode
    }
    new URL(targetUrl); // validate
    return targetUrl;
  } catch (e) {
    return null;
  }
}

function decodeBase64(raw) {
  if (!raw) return null;
  try { return atob(raw); } catch (e) { return null; }
}

// ==================== TERABOX PROXY (/dl) ====================

async function handleTeraboxProxy(request, url) {
  const encodedUrl = url.searchParams.get("url");
  const encodedCookie = url.searchParams.get("cookie");
  const targetUrl = parseTargetUrl(encodedUrl);

  if (!targetUrl) {
    return errorResponse("Missing or invalid 'url' parameter");
  }

  const upstreamHeaders = new Headers();
  upstreamHeaders.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36");
  upstreamHeaders.set("Accept", "*/*");
  upstreamHeaders.set("Connection", "keep-alive");

  if (encodedCookie) {
    const cookie = decodeBase64(encodedCookie);
    if (cookie) upstreamHeaders.set("Cookie", cookie);
  }

  const clientRange = request.headers.get("Range");
  if (clientRange) {
    upstreamHeaders.set("Range", clientRange);
  }

  try {
    const response = await fetch(targetUrl, {
      method: request.method,
      headers: upstreamHeaders,
      redirect: "follow",
    });

    const newHeaders = new Headers(response.headers);
    newHeaders.set("Access-Control-Allow-Origin", "*");
    newHeaders.set("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges");

    if (!newHeaders.has("Accept-Ranges")) {
      newHeaders.set("Accept-Ranges", "bytes");
    }

    newHeaders.delete("Content-Security-Policy");
    newHeaders.delete("X-Frame-Options");
    newHeaders.delete("Set-Cookie");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders,
    });
  } catch (err) {
    return errorResponse("TeraBox proxy error: " + err.message, 500);
  }
}


// ==================== TERABOX API PROXY (/tb) ====================

/**
 * Proxy TeraBox API calls (share/list, shorturlinfo, etc)
 * Forwards request with proper headers from Cloudflare edge IP.
 *
 * Query params:
 *   url=<FULL_API_URL>          - The full TeraBox API URL (e.g. https://dm.terabox.app/share/list?...)
 *   cookie=<BASE64_COOKIE>      - Base64-encoded cookie string
 *   referer=<ORIGIN_URL>        - Optional referer origin (default: extracted from url param)
 *   host=<HOST>                 - Optional Host header override
 */
async function handleTeraboxApiProxy(request, url) {
  const rawUrl = url.searchParams.get("url");
  const encodedCookie = url.searchParams.get("cookie");
  const refererOrigin = url.searchParams.get("referer");
  const hostOverride = url.searchParams.get("host");
  const methodOverride = url.searchParams.get("method") || "GET";
  const encodedBody = url.searchParams.get("body");

  if (!rawUrl) {
    return errorResponse("Missing 'url' parameter");
  }

  let targetUrl;
  try {
    targetUrl = new URL(rawUrl);
  } catch (e) {
    return errorResponse("Invalid URL: " + rawUrl);
  }

  const upstreamHeaders = new Headers();
  upstreamHeaders.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36");
  upstreamHeaders.set("Accept", "application/json, text/plain, */*");
  upstreamHeaders.set("Accept-Language", "en-US,en;q=0.5");
  upstreamHeaders.set("X-Requested-With", "XMLHttpRequest");
  upstreamHeaders.set("Connection", "keep-alive");
  upstreamHeaders.set("Content-Type", "application/x-www-form-urlencoded");

  // Host header
  if (hostOverride) {
    upstreamHeaders.set("Host", hostOverride);
  } else {
    upstreamHeaders.set("Host", targetUrl.host);
  }

  // Referer — use surl param for verify calls, shorturl for list calls
  const origin = refererOrigin || `${targetUrl.protocol}//${targetUrl.host}`;
  const surl = targetUrl.searchParams.get("shorturl") || targetUrl.searchParams.get("surl") || "";
  upstreamHeaders.set("Referer", `${origin}/sharing/link?surl=${surl}&clearCache=1`);

  // Cookie
  if (encodedCookie) {
    const cookie = decodeBase64(encodedCookie);
    if (cookie) upstreamHeaders.set("Cookie", cookie);
  }

  // Decode POST body if provided
  let requestBody = null;
  if (methodOverride.toUpperCase() === "POST" && encodedBody) {
    requestBody = decodeBase64(encodedBody);
  }

  try {
    const fetchOptions = {
      method: methodOverride.toUpperCase(),
      headers: upstreamHeaders,
      redirect: "follow",
    };
    if (requestBody) {
      fetchOptions.body = requestBody;
    }

    const response = await fetch(targetUrl.toString(), fetchOptions);

    // Return JSON response with CORS
    const body = await response.text();
    const newHeaders = new Headers();
    newHeaders.set("Content-Type", "application/json; charset=UTF-8");
    newHeaders.set("Access-Control-Allow-Origin", "*");
    newHeaders.set("Access-Control-Expose-Headers", "Content-Length");

    return new Response(body, {
      status: response.status,
      headers: newHeaders,
    });
  } catch (err) {
    return errorResponse("TeraBox API proxy error: " + err.message, 500);
  }
}


// ==================== HLS PROXY (/proxy) ====================

/**
 * Headers to send to FlickReels CDN
 */
function hlsCdnHeaders(rangeHeader) {
  const headers = {
    "Referer": "https://www.flickreels.net/",
    "Origin": "https://www.flickreels.net",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "*/*",
    "Connection": "keep-alive",
  };
  if (rangeHeader) {
    headers["Range"] = rangeHeader;
  }
  return headers;
}

/**
 * Get the base URL (everything before last /)
 */
function getBaseUrl(fullUrl) {
  return fullUrl.substring(0, fullUrl.lastIndexOf("/") + 1);
}

/**
 * Resolve relative URL against base
 */
function resolveUrl(path, baseUrl) {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (path.startsWith("/")) return new URL(baseUrl).origin + path;
  return baseUrl + path;
}

/**
 * Rewrite .m3u8: convert relative paths to proxy-wrapped absolute URLs
 */
function rewriteM3u8(content, originalUrl, proxyBase) {
  const baseUrl = getBaseUrl(originalUrl);

  return content.split("\n").map(line => {
    const trimmed = line.trim();

    if (trimmed === "" || (trimmed.startsWith("#") && !trimmed.includes("URI="))) {
      return line;
    }

    // Rewrite URI="..." in #EXT-X-MAP, #EXT-X-KEY, etc.
    if (trimmed.includes("URI=")) {
      return line.replace(/URI="([^"]+)"/g, (_, uri) => {
        const abs = resolveUrl(uri, baseUrl);
        return `URI="${proxyBase}/proxy?url=${encodeURIComponent(abs)}"`;
      });
    }

    // Non-comment = segment/playlist reference
    if (!trimmed.startsWith("#")) {
      const abs = resolveUrl(trimmed, baseUrl);
      return `${proxyBase}/proxy?url=${encodeURIComponent(abs)}`;
    }

    return line;
  }).join("\n");
}

async function handleHlsProxy(request, url) {
  const targetUrl = url.searchParams.get("url");

  if (!targetUrl) {
    return errorResponse("Missing 'url' parameter");
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(targetUrl);
  } catch (e) {
    return errorResponse("Invalid URL format");
  }

  try {
    const rangeHeader = request.headers.get("Range");
    const response = await fetch(targetUrl, {
      method: request.method,
      headers: hlsCdnHeaders(rangeHeader),
      redirect: "follow",
    });

    if (!response.ok && response.status !== 206) {
      return new Response(JSON.stringify({
        error: "Upstream failed",
        status: response.status,
        statusText: response.statusText,
      }), {
        status: response.status,
        headers: { "Content-Type": "application/json", ...corsHeaders() },
      });
    }

    const pathLower = parsedUrl.pathname.toLowerCase();

    // .m3u8 → rewrite content
    if (pathLower.endsWith(".m3u8")) {
      const text = await response.text();
      const proxyBase = `${url.protocol}//${url.host}`;
      const rewritten = rewriteM3u8(text, targetUrl, proxyBase);

      return new Response(rewritten, {
        status: 200,
        headers: {
          "Content-Type": "application/vnd.apple.mpegurl",
          "Cache-Control": "no-cache",
          ...corsHeaders(),
        },
      });
    }

    // .ts / .mp4 / binary → stream through
    const newHeaders = new Headers();
    newHeaders.set("Access-Control-Allow-Origin", "*");
    newHeaders.set("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges");

    let isStego = false;

    if (pathLower.endsWith(".ts")) {
      newHeaders.set("Content-Type", "video/mp2t");
    } else if (pathLower.endsWith(".mp4")) {
      newHeaders.set("Content-Type", "video/mp4");
    } else {
      const ct = response.headers.get("Content-Type");

      // DECRYPT LK21 PNG STEGANOGRAPHY
      if ((ct && ct.includes("image/png")) || parsedUrl.host.includes("googleusercontent")) {
         isStego = true;
         newHeaders.set("Content-Type", "video/mp2t");

         const buf = await response.arrayBuffer();
         const bytes = new Uint8Array(buf);

         // Dynamically find exact TS Sync Byte (0x47)
         let offset = 0;
         for (let i = 0; i < Math.min(2000, bytes.length); i++) {
             if (bytes[i] === 0x47 && bytes[i + 188] === 0x47 && bytes[i + 376] === 0x47) {
                 offset = i;
                 break;
             }
         }

         const slicedBuffer = buf.slice(offset);
         newHeaders.set("Content-Length", slicedBuffer.byteLength.toString());
         newHeaders.set("Accept-Ranges", "bytes");

         return new Response(slicedBuffer, {
             status: response.status,
             statusText: response.statusText,
             headers: newHeaders,
         });

      } else if (ct) {
         newHeaders.set("Content-Type", ct);
      }
    }

    // Normal non-stego processing
    for (const h of ["Content-Length", "Content-Range", "Accept-Ranges"]) {
      const val = response.headers.get(h);
      if (val) newHeaders.set(h, val);
    }

    if (!newHeaders.has("Accept-Ranges")) {
      newHeaders.set("Accept-Ranges", "bytes");
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders,
    });

  } catch (err) {
    return errorResponse("HLS proxy error: " + err.message, 500);
  }
}


// ==================== MELOLO PROXY (/stream) ====================

/**
 * Range-aware proxy for resolved (decrypted) Melolo MP4 URLs.
 * Rebuilds the tobrutmelolo CDN URL from id + auth_key, so the public
 * URL stays clean: /stream?id=<ID>&auth_key=<KEY>.
 */
const MELOLO_CDN = "https://tobrutmelolo.inicdn.net/api/v1/video/stream";

async function handleMeloloProxy(request, url) {
  const id = url.searchParams.get("id");
  const authKey = url.searchParams.get("auth_key");
  if (!id || !authKey) {
    return errorResponse("Missing 'id' or 'auth_key' parameter");
  }

  const targetUrl = `${MELOLO_CDN}?id=${encodeURIComponent(id)}&auth_key=${encodeURIComponent(authKey)}`;

  const upstreamHeaders = new Headers();
  upstreamHeaders.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36");
  upstreamHeaders.set("Accept", "*/*");
  upstreamHeaders.set("Origin", "https://dramakuy.com");
  upstreamHeaders.set("Referer", "https://dramakuy.com/");
  upstreamHeaders.set("Connection", "keep-alive");

  const clientRange = request.headers.get("Range");
  if (clientRange) {
    upstreamHeaders.set("Range", clientRange);
  }

  try {
    const response = await fetch(targetUrl, {
      method: request.method,
      headers: upstreamHeaders,
      redirect: "follow",
    });

    const newHeaders = new Headers();
    newHeaders.set("Access-Control-Allow-Origin", "*");
    newHeaders.set("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges");
    for (const h of ["Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"]) {
      const val = response.headers.get(h);
      if (val) newHeaders.set(h, val);
    }
    if (!newHeaders.has("Content-Type")) {
      newHeaders.set("Content-Type", "video/mp4");
    }
    if (!newHeaders.has("Accept-Ranges")) {
      newHeaders.set("Accept-Ranges", "bytes");
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders,
    });
  } catch (err) {
    return errorResponse("Melolo proxy error: " + err.message, 500);
  }
}
