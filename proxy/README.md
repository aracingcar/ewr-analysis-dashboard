# Observed-data proxy

The Observed tab fetches gauge records from the state water agencies. Their services refuse requests from other websites (no CORS
headers), so when the dashboard is hosted as a static page (GitHub Pages) the requests go through this small Cloudflare Worker, which
adds the headers. The local server (`python3 run.py`) does not need it.

What it will and will not do is at the top of [worker.js](worker.js): GET only, only from the origins in `ALLOWED_ORIGINS`, only the four
agency hosts and their data-service paths, nothing else. It stores nothing and sees only public gauge IDs and dates.

## Deploy (about five minutes, free plan is plenty)

1. Make a free Cloudflare account (cloudflare.com), then in a terminal: `cd proxy && npx wrangler login`.
2. If your page is not at `https://aracingcar.github.io`, edit `ALLOWED_ORIGINS` in [wrangler.toml](wrangler.toml).
3. `npx wrangler deploy`. It prints the worker's address, like `https://ewr-observed-proxy.<your-name>.workers.dev`.
4. In the GitHub repository: Settings → Secrets and variables → Actions → Variables → New repository variable
   `OBSERVED_PROXY_URL` = that address (no trailing slash). Re-run the *Publish GitHub Pages* workflow.

The Observed tab then works on the page. To check the worker by hand:

```bash
curl -H "Origin: https://aracingcar.github.io" "https://<worker>/realtimedata.waternsw.com.au/cgi/webservice.exe?%7B...%7D"
```

Tests: `node --test tests/test_observed_proxy.js`.
