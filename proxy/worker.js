// CORS proxy for the dashboard's "Observed" data when the page is hosted statically (e.g. GitHub Pages).
//
// The state water agencies' data services do not send CORS headers, so a web page cannot call them directly. This Cloudflare Worker
// forwards read-only requests to those services and adds the headers. It forwards nothing else:
//   - only GET, and only from the origins listed in ALLOWED_ORIGINS (comma separated; set in wrangler.toml);
//   - only the four agency hosts and the one data-service path each of them is queried on (UPSTREAMS below);
//   - no cookies or request headers are passed on, and redirects are followed only to another allowed host and path.
//
// Request format:  GET https://<this worker>/<agency host>/<path>?<query>    (what src/browser_backend.py sends for the getter's requests)

const UPSTREAMS = {
  "realtimedata.waternsw.com.au": /^\/cgi\/webservice\.(exe|pl)$/,
  "water-monitoring.information.qld.gov.au": /^\/cgi\/webservice\.(exe|pl)$/,
  "data.water.vic.gov.au": /^\/(WMIS\/)?cgi\/webservice\.(exe|pl)$/,
  "water.data.sa.gov.au": /^\/Export\/BulkExportJson$/,
};
const MAX_QUERY = 4000;
const MAX_REDIRECTS = 3;
const TIMEOUT_MS = 28000;

const allowed = (env) => (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);

function cors(origin) {
  return { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, OPTIONS", "Access-Control-Max-Age": "86400", Vary: "Origin" };
}

function reply(status, message, origin) {
  return new Response(JSON.stringify({ message }), { status, headers: { "Content-Type": "application/json", ...(origin ? cors(origin) : {}) } });
}

/** The upstream URL a request path names, or null when it is not an allowed host and path. */
export function upstreamUrl(pathname, search) {
  const match = /^\/([^/]+)(\/.*)$/.exec(pathname);
  if (!match) return null;
  const [, host, path] = match;
  const pattern = Object.hasOwn(UPSTREAMS, host) ? UPSTREAMS[host] : null;
  if (!pattern || !pattern.test(path) || search.length > MAX_QUERY) return null;
  return new URL(`https://${host}${path}${search}`);
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const permitted = allowed(env).includes(origin) ? origin : "";
    if (!permitted) return reply(403, "origin not allowed", "");
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(permitted) });
    if (request.method !== "GET") return reply(405, "only GET is supported", permitted);

    const here = new URL(request.url);
    let target = upstreamUrl(here.pathname, here.search);
    if (!target) return reply(404, "not an allowed agency service", permitted);

    try {
      for (let hops = 0; ; hops++) {
        const upstream = await fetch(target, { method: "GET", redirect: "manual", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(TIMEOUT_MS) });
        if (upstream.status >= 300 && upstream.status < 400 && upstream.headers.get("Location")) {
          const next = new URL(upstream.headers.get("Location"), target);
          const checked = upstreamUrl(`/${next.host}${next.pathname}`, next.search);
          if (!checked || hops >= MAX_REDIRECTS) return reply(502, "the agency redirected somewhere that is not allowed", permitted);
          target = checked;
          continue;
        }
        const headers = { "Content-Type": upstream.headers.get("Content-Type") || "application/json", "Cache-Control": "no-store", ...cors(permitted) };
        return new Response(upstream.body, { status: upstream.status, headers });
      }
    } catch (error) {
      return reply(502, `could not reach the agency: ${error && error.name === "TimeoutError" ? "timed out" : "request failed"}`, permitted);
    }
  },
};
