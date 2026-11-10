// Run from client/: node ../test/e2e_electron.js (needs playwright-core, vite preview on :5173, display or xvfb)
const { spawn } = require("child_process");
const http = require("http");
const req = (m) => require(require.resolve(m, { paths: [process.cwd()] }));
const { chromium } = req("playwright-core");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const health = () => new Promise((res) => {
  http.get("http://127.0.0.1:8000/health", (r) => { r.resume(); res(r.statusCode === 200); }).on("error", () => res(false));
});
const checks = [];
const check = (name, ok) => { checks.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}`); };

(async () => {
  const app = spawn(req("electron"), ["--no-sandbox", "--headless-test", "--remote-debugging-port=9222", "."], {
    stdio: "inherit",
  });
  try {
    let up = false;
    for (let i = 0; i < 60 && !up; i++) { up = await health(); if (!up) await sleep(1000); }
    check("agent /health responds", up);

    const browser = await chromium.connectOverCDP("http://127.0.0.1:9222");
    let page;
    for (let i = 0; i < 30 && !page; i++) { page = browser.contexts()[0]?.pages()[0]; if (!page) await sleep(1000); }
    await page.waitForSelector("[data-testid=server-connect]", { timeout: 30000 });
    check("UI exposes data-testid server-url-input", (await page.$("[data-testid=server-url-input]")) !== null);
    check("UI exposes data-testid server-connect", (await page.$("[data-testid=server-connect]")) !== null);
    await browser.close();
  } catch (e) {
    check(`unexpected error: ${e.message.split("\n")[0]}`, false);
  } finally {
    app.kill("SIGTERM");
    await sleep(5000);
    check("agent stopped after SIGTERM (no orphan)", !(await health()));
  }
  process.exit(checks.every(Boolean) ? 0 : 1);
})();
