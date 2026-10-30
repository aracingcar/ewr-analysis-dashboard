// The observed-data CORS proxy (proxy/worker.js): what it forwards, to whom, and what it refuses. Upstream fetch is mocked.
const test = require("node:test");
const assert = require("node:assert/strict");

const ORIGIN = "https://aracingcar.github.io";
const ENV = { ALLOWED_ORIGINS: `${ORIGIN}, http://localhost:8000` };
const NSW = "realtimedata.waternsw.com.au";
const QUERY = "?%7B%22function%22%3A%22get_ts_traces%22%7D";

async function worker() {
  return (await import("../proxy/worker.js")).default;
}

function withUpstream(handler, body) {
  const real = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return handler(String(url), init); };
  return body(calls).finally(() => { globalThis.fetch = real; });
}

const ask = async (path, { method = "GET", origin = ORIGIN } = {}) => {
  const w = await worker();
  const headers = origin === null ? {} : { Origin: origin };
  return w.fetch(new Request(`https://proxy.example${path}`, { method, headers }), ENV);
};

test("forwards an allowed agency request and adds the CORS headers", () =>
  withUpstream(() => new Response('{"ok":1}', { headers: { "Content-Type": "application/json" } }), async (calls) => {
    const response = await ask(`/${NSW}/cgi/webservice.exe${QUERY}`);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), '{"ok":1}');
    assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
    assert.equal(response.headers.get("Vary"), "Origin");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, `https://${NSW}/cgi/webservice.exe${QUERY}`);
    assert.equal(calls[0].init.method, "GET");
    assert.deepEqual(Object.keys(calls[0].init.headers), ["Accept"]);  // no cookies or caller headers go upstream
  }));

test("answers the preflight for an allowed origin and refuses other origins and missing origins", () =>
  withUpstream(() => { throw new Error("must not be called"); }, async (calls) => {
    const preflight = await ask(`/${NSW}/cgi/webservice.exe`, { method: "OPTIONS" });
    assert.equal(preflight.status, 204);
    assert.equal(preflight.headers.get("Access-Control-Allow-Origin"), ORIGIN);
    for (const origin of ["https://evil.example", "https://aracingcar.github.io.evil.example", null]) {
      const refused = await ask(`/${NSW}/cgi/webservice.exe${QUERY}`, { origin });
      assert.equal(refused.status, 403);
      assert.equal(refused.headers.get("Access-Control-Allow-Origin"), null);
    }
    assert.equal(calls.length, 0);
  }));

test("only GET, only the listed hosts and service paths", () =>
  withUpstream(() => new Response("{}"), async (calls) => {
    assert.equal((await ask(`/${NSW}/cgi/webservice.exe`, { method: "POST" })).status, 405);
    for (const path of ["/example.com/cgi/webservice.exe", `/${NSW}/admin`, `/${NSW}/cgi/webservice.exe/../x`, "/constructor/x", "/__proto__/cgi/webservice.exe", "/", `/${NSW}`, "/data.water.vic.gov.au/cgi/other"]) {
      assert.equal((await ask(path)).status, 404, path);
    }
    assert.equal((await ask(`/${NSW}/cgi/webservice.exe?${"a".repeat(4001)}`)).status, 404);
    assert.equal(calls.length, 0);
    for (const path of ["/water-monitoring.information.qld.gov.au/cgi/webservice.pl", "/data.water.vic.gov.au/WMIS/cgi/webservice.exe", "/water.data.sa.gov.au/Export/BulkExportJson"]) {
      assert.equal((await ask(path + QUERY)).status, 200, path);
    }
  }));

test("follows a redirect within the allowed services, keeping the query", () =>
  withUpstream((url) => url.includes("/WMIS/") ? new Response('{"vic":1}') : new Response(null, { status: 301, headers: { Location: `https://data.water.vic.gov.au/WMIS/cgi/webservice.exe${QUERY}` } }), async (calls) => {
    const response = await ask(`/data.water.vic.gov.au/cgi/webservice.exe${QUERY}`);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), '{"vic":1}');
    assert.equal(calls.length, 2);
    assert.equal(calls[1].url, `https://data.water.vic.gov.au/WMIS/cgi/webservice.exe${QUERY}`);
  }));

test("refuses a redirect to another host or path, and redirect loops", () =>
  withUpstream((url) => new Response(null, { status: 302, headers: { Location: url.includes("loop") ? `https://${NSW}/cgi/webservice.exe?loop` : "https://evil.example/cgi/webservice.exe" } }), async () => {
    assert.equal((await ask(`/${NSW}/cgi/webservice.exe${QUERY}`)).status, 502);
    assert.equal((await ask(`/${NSW}/cgi/webservice.exe?loop`)).status, 502);
  }));

test("passes agency errors through and turns network failures into a 502", async () => {
  await withUpstream(() => new Response('{"error":"busy"}', { status: 503 }), async () => {
    const response = await ask(`/${NSW}/cgi/webservice.exe${QUERY}`);
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  });
  await withUpstream(() => { throw new TypeError("fetch failed"); }, async () => {
    const response = await ask(`/${NSW}/cgi/webservice.exe${QUERY}`);
    assert.equal(response.status, 502);
    assert.match((await response.json()).message, /could not reach/);
  });
});
