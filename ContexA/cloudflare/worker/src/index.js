const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Cross-Origin-Opener-Policy": "same-origin",
  "X-Permitted-Cross-Domain-Policies": "none",
};

function allowedOrigins(env) {
  return new Set((env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim().replace(/\/$/, ""))
    .filter(Boolean));
}

function withEdgeHeaders(response, origin, requestId) {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(SECURITY_HEADERS)) headers.set(key, value);
  headers.set("X-Request-ID", requestId);
  headers.set("X-ContexA-Edge", "Cloudflare Workers");
  headers.set("Cache-Control", "no-store");
  headers.append("Vary", "Origin");
  if (origin) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-ID");
    headers.set("Access-Control-Expose-Headers", "Content-Disposition, X-Request-ID, CF-Ray");
    headers.set("Access-Control-Max-Age", "86400");
  }
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...extraHeaders },
  });
}

async function enforceLimit(binding, key) {
  if (!binding) return true;
  try {
    const decision = await binding.limit({ key });
    return decision.success;
  } catch {
    // Backend database throttles remain authoritative; do not take down the API
    // if Cloudflare's approximate edge limiter has a transient control-plane issue.
    return true;
  }
}

export default {
  async scheduled(event, env, ctx) {
    if (!env.API_ORIGIN || !env.TRUTH_DRIFT_CRON_TOKEN) {
      console.error("ContexA scheduled truth monitoring is not configured.");
      return;
    }
    const headers = new Headers({
      "Authorization": `Bearer ${env.TRUTH_DRIFT_CRON_TOKEN}`,
      "Content-Type": "application/json",
      "X-Request-ID": crypto.randomUUID(),
    });
    if (env.ORIGIN_SHARED_SECRET) headers.set("X-ContexA-Origin-Secret", env.ORIGIN_SHARED_SECRET);
    const url = new URL("/api/internal/truth-drift/scan-due", env.API_ORIGIN);
    ctx.waitUntil(fetch(url.toString(), { method: "POST", headers, body: "{}" }).then(async (response) => {
      if (!response.ok) throw new Error(`Scheduled truth scan failed (${response.status}): ${(await response.text()).slice(0, 300)}`);
      const result = await response.json();
      console.log("ContexA scheduled truth scan completed", result);
    }).catch((error) => console.error("ContexA scheduled truth scan error", String(error))));
  },
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const requestId = request.headers.get("x-request-id") || crypto.randomUUID();
    const origin = request.headers.get("Origin");
    const originAllowed = !origin || allowedOrigins(env).has(origin.replace(/\/$/, ""));

    if (!originAllowed) return json({ detail: "Origin is not allowed by the ContexA edge policy." }, 403, SECURITY_HEADERS);

    if (url.pathname === "/edge-health") {
      if (request.method !== "GET") return json({ detail: "Method not allowed." }, 405, SECURITY_HEADERS);
      const ready = Boolean(env.API_ORIGIN);
      return withEdgeHeaders(json({
        status: ready ? "ok" : "needs_configuration",
        edge: "cloudflare-workers",
        version: env.EDGE_VERSION || "unknown",
        colo: request.cf?.colo || null,
        origin_configured: ready,
      }, ready ? 200 : 503), origin, requestId);
    }

    // This Worker is an API gateway, not a general-purpose open proxy.
    if (!(url.pathname === "/api" || url.pathname.startsWith("/api/"))) {
      return withEdgeHeaders(json({ detail: "Not found." }, 404), origin, requestId);
    }
    if (!env.API_ORIGIN) {
      return withEdgeHeaders(json({ detail: "API origin is not configured on the Cloudflare Worker." }, 503), origin, requestId);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const isAuth = /^\/api\/auth\/(login|register|password\/forgot)$/.test(url.pathname);
    const isUpload = url.pathname === "/api/documents/upload"
      || url.pathname === "/api/assets/upload"
      || url.pathname === "/api/multimodal/inspect";
    if (isAuth && !(await enforceLimit(env.AUTH_LIMITER, `auth:${ip}`))) {
      return withEdgeHeaders(json({ detail: "Too many authentication requests. Please retry in a minute." }, 429, { "Retry-After": "60" }), origin, requestId);
    }
    if (isUpload && !(await enforceLimit(env.UPLOAD_LIMITER, `upload:${ip}`))) {
      return withEdgeHeaders(json({ detail: "Upload request rate exceeded. Please retry in a minute." }, 429, { "Retry-After": "60" }), origin, requestId);
    }

    let upstreamUrl;
    try {
      const apiOrigin = new URL(env.API_ORIGIN);
      if (!/^https?:$/.test(apiOrigin.protocol)) throw new Error("Unsupported origin protocol");
      upstreamUrl = new URL(`${url.pathname}${url.search}`, apiOrigin.origin);
    } catch {
      return withEdgeHeaders(json({ detail: "API origin configuration is invalid." }, 503), origin, requestId);
    }

    const outgoingHeaders = new Headers(request.headers);
    outgoingHeaders.set("CF-Connecting-IP", ip);
    outgoingHeaders.set("X-Forwarded-For", ip);
    outgoingHeaders.set("X-Forwarded-Proto", "https");
    outgoingHeaders.set("X-Forwarded-Host", url.host);
    outgoingHeaders.set("X-Request-ID", requestId);
    // Never trust a browser-supplied origin secret; only inject the Worker secret.
    outgoingHeaders.delete("X-ContexA-Origin-Secret");
    if (env.ORIGIN_SHARED_SECRET) outgoingHeaders.set("X-ContexA-Origin-Secret", env.ORIGIN_SHARED_SECRET);
    outgoingHeaders.delete("Host");

    try {
      const upstreamRequest = new Request(upstreamUrl.toString(), {
        method: request.method,
        headers: outgoingHeaders,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        redirect: "manual",
      });
      const upstreamResponse = await fetch(upstreamRequest);
      return withEdgeHeaders(upstreamResponse, origin, requestId);
    } catch (error) {
      console.error("ContexA API origin request failed", { requestId, error: String(error) });
      return withEdgeHeaders(json({ detail: "ContexA API is temporarily unavailable.", request_id: requestId }, 502), origin, requestId);
    }
  },
};
