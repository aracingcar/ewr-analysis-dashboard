// Web worker that runs the dashboard's Python server code (src/server.py, via src/browser_backend.py) in the browser with Pyodide.
// The page posts {id, method, path, headers, body}; the worker answers {id, status, headers, body}. Started lazily by the page when it is
// hosted without the local analysis server (see installBrowserEngine in dashboard_template.html). Files are listed in files.json, which
// scripts/build_pages.py writes next to this file.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const PY_PACKAGES = ["pandas", "numpy", "scipy", "h5py", "netcdf4", "xarray", "cachetools", "requests", "lxml", "micropip"];
const PYPI_PACKAGES = ["py_ewr==2.4.11", "mdba-gauge-getter==0.5.1"];  // pure Python; their dependencies come from Pyodide above (numpy 2 is fine for py_ewr's use)

importScripts(PYODIDE + "pyodide.js");

const status = (text) => self.postMessage({ type: "status", text });
let ready = null;

async function boot() {
  status("Downloading the Python engine (first visit only, about 50 MB)…");
  const py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage(PY_PACKAGES);
  status("Installing the EWR tool (py_ewr)…");
  await py.runPythonAsync(`import micropip\nawait micropip.install(${JSON.stringify(PYPI_PACKAGES)}, deps=False)`);
  status("Loading the dashboard's analysis code…");
  const files = await (await fetch("files.json")).json();
  await Promise.all(files.map(async (name) => {
    const response = await fetch(name);
    if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
    const target = "/app/" + name.replace(/^engine\//, "");
    py.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
    py.FS.writeFile(target, new Uint8Array(await response.arrayBuffer()));
  }));
  py.runPython(`
import sys
sys.path.insert(0, "/app/src")
import browser_backend

def call(method, path, headers, body):
    status, out, payload = browser_backend.handle(method, path, dict(headers), bytes(body.to_py()))
    return status, out, payload
`);
  status("");
  return py;
}

self.onmessage = async ({ data: { id, method, path, headers, body } }) => {
  try {
    const py = await (ready ||= boot());
    const result = py.globals.get("call")(method, path, py.toPy(headers), body);
    const [code, out, payload] = result.toJs({ dict_converter: Object.fromEntries });
    result.destroy();
    self.postMessage({ id, status: code, headers: out, body: payload }, [payload.buffer]);
  } catch (error) {
    ready = null;  // let the next request retry the download
    status("");
    self.postMessage({ id, error: String(error && error.message || error) });
  }
};
