// Runs tests/browser_parity/scenario.py against the in-browser server (src/browser_backend.py under Pyodide) and writes the answers as JSON.
//   node run_pyodide.mjs <site dir built by scripts/build_pages.py> <examples dir> <scenario.py> <output.json>
// Boots the same way as src/engine_worker.js: same Pyodide version, same packages, same files.json.
import { loadPyodide } from "pyodide";
import fs from "node:fs";
import path from "node:path";

const [site, examples, scenario, output] = process.argv.slice(2);
const worker = fs.readFileSync(path.join(site, "engine_worker.js"), "utf8");
const list = (name) => JSON.parse(worker.match(new RegExp(`const ${name} = (\\[.*?\\]);`, "s"))[1]);
const PY_PACKAGES = list("PY_PACKAGES"), PYPI_PACKAGES = list("PYPI_PACKAGES");

const py = await loadPyodide();
await py.loadPackage(PY_PACKAGES);
await py.runPythonAsync(`import micropip\nawait micropip.install(${JSON.stringify(PYPI_PACKAGES)}, deps=False)`);
for (const name of JSON.parse(fs.readFileSync(path.join(site, "files.json"), "utf8"))) {
  const target = "/app/" + name.replace(/^engine\//, "");
  py.FS.mkdirTree(path.dirname(target));
  py.FS.writeFile(target, new Uint8Array(fs.readFileSync(path.join(site, name))));
}
py.FS.mkdirTree("/examples");
for (const name of fs.readdirSync(examples)) if (name.endsWith(".csv")) py.FS.writeFile("/examples/" + name, new Uint8Array(fs.readFileSync(path.join(examples, name))));
py.FS.mkdirTree("/parity");
py.FS.writeFile("/parity/scenario.py", new Uint8Array(fs.readFileSync(scenario)));
const result = await py.runPythonAsync(`
import json, sys
sys.path[:0] = ["/app/src", "/parity"]
import browser_backend, scenario

def call(method, path, headers=None, body=b""):
    status, _, payload = browser_backend.handle(method, path, headers or {}, bytes(body))
    return status, payload

json.dumps(scenario.run(call, lambda name: open("/examples/" + name, "rb").read()))
`);
fs.writeFileSync(output, result);
