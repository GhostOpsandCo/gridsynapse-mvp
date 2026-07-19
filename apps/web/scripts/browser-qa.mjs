import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";

const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const baseUrl = process.env.QA_BASE_URL ?? "http://127.0.0.1:3020";
const port = Number(process.env.QA_CDP_PORT ?? 9300 + (process.pid % 500));
const artifactDir = process.env.QA_ARTIFACT_DIR ?? "/tmp";
const userDataDir = `/tmp/gridsynapse-chrome-${process.pid}`;

if (!existsSync(chromePath)) throw new Error(`Chrome not found at ${chromePath}`);
mkdirSync(artifactDir, { recursive: true });

const chrome = spawn(chromePath, [
  "--headless=new",
  "--disable-gpu",
  `--remote-debugging-port=${port}`,
  "--remote-allow-origins=*",
  `--user-data-dir=${userDataDir}`,
  "--hide-scrollbars",
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForDebugger() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      if (response.ok) return response.json();
    } catch {}
    await sleep(250);
  }
  throw new Error("Chrome DevTools endpoint did not become ready");
}

function connect(url) {
  const socket = new WebSocket(url);
  let commandId = 0;
  const pending = new Map();
  const events = [];
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method) {
      events.push(message);
    }
  };
  return {
    events,
    ready: new Promise((resolve, reject) => {
      socket.onopen = resolve;
      socket.onerror = reject;
    }),
    send(method, params = {}) {
      return new Promise((resolve) => {
        const id = ++commandId;
        pending.set(id, resolve);
        socket.send(JSON.stringify({ id, method, params }));
      });
    },
    close: () => socket.close(),
  };
}

async function runViewport({ name, width, height, mobile }) {
  const targets = await waitForDebugger();
  const target = targets.find((item) => item.type === "page");
  if (!target) throw new Error("No browser page target found");
  const cdp = connect(target.webSocketDebuggerUrl);
  await cdp.ready;
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Console.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  const navigationStartedAt = Date.now();
  await cdp.send("Page.navigate", { url: baseUrl });
  await sleep(250);

  const evaluate = async (expression) => {
    const response = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.result?.exceptionDetails) throw new Error(response.result.exceptionDetails.text ?? "Browser evaluation failed");
    return response.result?.result?.value;
  };
  const clickButton = async (label) => evaluate(`(() => {
    const button = [...document.querySelectorAll("button")].find((item) => item.textContent.trim().toLowerCase() === ${JSON.stringify(label.toLowerCase())});
    if (!button) return false;
    button.click();
    return true;
  })()`);
  const clickButtonStartingWith = async (label) => evaluate(`(() => {
    const button = [...document.querySelectorAll("button")].find((item) => item.textContent.trim().toLowerCase().startsWith(${JSON.stringify(label.toLowerCase())}));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  let readyMs = null;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const ready = await evaluate(`document.body.innerText.includes("GridSynapse Compute Optimizer") && !document.body.innerText.includes("Loading GridSynapse")`);
    if (ready) {
      readyMs = Date.now() - navigationStartedAt;
      break;
    }
    await sleep(125);
  }
  const snapshot = async () => evaluate(`(() => ({
    title: document.title,
    headings: [...document.querySelectorAll("h1,h2")].map((item) => item.textContent.trim()).filter(Boolean).slice(0, 10),
    buttons: [...document.querySelectorAll("button")].map((item) => item.textContent.trim()).filter(Boolean),
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight,
    overflowElements: [...document.querySelectorAll("body *")].map((item) => {
      const rect = item.getBoundingClientRect();
      return { tag: item.tagName, className: typeof item.className === "string" ? item.className : "", right: Math.round(rect.right), left: Math.round(rect.left), width: Math.round(rect.width) };
    }).filter((item) => item.right > document.documentElement.clientWidth + 1 || item.left < -1).slice(0, 12),
  }))()`);

  const initial = { ...(await snapshot()), readyMs };
  const nav = [];
  for (const label of ["Workloads", "Market inputs", "Review & approve", "Data quality", "Recommendation"]) {
    const clicked = await clickButton(label);
    await sleep(650);
    nav.push({ label, clicked, ...(await snapshot()) });
  }

  const actions = [];
  if (name === "desktop") {
    const placementShortcutClicked = await clickButtonStartingWith("Review 3 placements");
    await sleep(500);
    const placementReached = await evaluate(`(() => { const target = document.querySelector(".table-wrap--placements"); if (!target) return false; const top = target.getBoundingClientRect().top; return top >= 0 && top < window.innerHeight; })()`);
    actions.push({ action: "open recommended placements", passed: placementShortcutClicked && placementReached });

    await clickButton("Workloads");
    await sleep(300);
    const workloadCountBefore = await evaluate(`document.querySelectorAll(".workload-edit-card").length`);
    const addClicked = await clickButton("Add workload");
    await sleep(300);
    const workloadCountAfter = await evaluate(`document.querySelectorAll(".workload-edit-card").length`);
    actions.push({ action: "add workload", passed: addClicked && workloadCountAfter === workloadCountBefore + 1, before: workloadCountBefore, after: workloadCountAfter });
    const removeClicked = await evaluate(`(() => { const items = [...document.querySelectorAll(".workload-edit-card")]; const button = items.at(-1)?.querySelector("button[aria-label^='Remove']"); if (!button) return false; button.click(); return true; })()`);
    await sleep(250);
    actions.push({ action: "remove workload", passed: removeClicked && await evaluate(`document.querySelectorAll(".workload-edit-card").length`) === workloadCountBefore });
    const templateClicked = await clickButton("Template");
    await sleep(250);
    actions.push({ action: "download workload template", passed: templateClicked && (await evaluate(`document.body.innerText.includes("Workload template downloaded")`)) });
    const importAvailable = await evaluate(`[...document.querySelectorAll("button")].some((item) => item.textContent.trim() === "Import JSON")`);
    const importDispatched = await evaluate(`(async () => {
      const response = await fetch("http://127.0.0.1:8080/api/v2/live-market/scenario?refresh=false");
      if (!response.ok) return false;
      const snapshot = await response.json();
      const input = document.querySelector("input[type=file]");
      if (!input) return false;
      const transfer = new DataTransfer();
      transfer.items.add(new File([JSON.stringify({ workloads: snapshot.scenario.workloads })], "workloads.json", { type: "application/json" }));
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    await sleep(750);
    actions.push({ action: "import workload JSON", passed: importAvailable && importDispatched && (await evaluate(`document.body.innerText.includes("workloads imported and validated")`)) });
    const validateClicked = await clickButton("Validate and optimize");
    await sleep(3000);
    actions.push({ action: "validate workload changes", passed: validateClicked && (await evaluate(`document.body.innerText.includes("Recommendation updated")`)) });

    await clickButton("Review & approve");
    await sleep(300);
    const profileClicked = await clickButtonStartingWith("Cost first");
    await sleep(150);
    const applyClicked = await clickButton("Apply and optimize");
    await sleep(3000);
    actions.push({ action: "apply objective", passed: profileClicked && applyClicked && (await evaluate(`document.body.innerText.includes("Cost first active")`)) });
    const approveClicked = await clickButton("Approve plan");
    await sleep(500);
    actions.push({ action: "approve plan", passed: approveClicked && (await evaluate(`document.body.innerText.includes("Plan approved")`)) });
    const revisionClicked = await clickButton("Request revision");
    await sleep(500);
    actions.push({ action: "request revision", passed: revisionClicked && (await evaluate(`document.body.innerText.includes("Revision requested")`)) });
    const exportChecks = await evaluate(`(async () => {
      const links = [...document.querySelectorAll(".export-actions a")];
      const results = [];
      for (const link of links) {
        const response = await fetch(link.href);
        results.push({ label: link.textContent.trim(), status: response.status, contentType: response.headers.get("content-type") });
      }
      return results;
    })()`);
    actions.push({ action: "export JSON and CSV", passed: exportChecks.length === 2 && exportChecks.every((item) => item.status === 200), exports: exportChecks });

    await clickButton("Market inputs");
    await sleep(250);
    const refreshClicked = await clickButton("Refresh");
    await sleep(3500);
    actions.push({ action: "refresh market", passed: refreshClicked && (await evaluate(`document.body.innerText.includes("A100-80GB provider catalog")`)) });
    const reviewClicked = await clickButton("Review recommendation");
    await sleep(250);
    actions.push({ action: "market to review", passed: reviewClicked && (await evaluate(`document.body.innerText.includes("Choose what the optimizer should protect first")`)) });

    await clickButton("Data quality");
    await sleep(250);
    const sourceRecordsOpened = await evaluate(`(() => { const details = document.querySelector(".source-records"); if (!details) return false; details.open = true; details.dispatchEvent(new Event("toggle")); return details.open && !!details.querySelector(".source-record-list"); })()`);
    actions.push({ action: "open source records", passed: sourceRecordsOpened });
    const qualityReviewClicked = await clickButton("Review & approve");
    await sleep(250);
    actions.push({ action: "data quality to review", passed: qualityReviewClicked && (await evaluate(`document.body.innerText.includes("Choose what the optimizer should protect first")`)) });
  }

  await clickButton("Recommendation");
  await sleep(300);
  const layout = await cdp.send("Page.getLayoutMetrics");
  const screenshotHeight = Math.min(name === "desktop" ? 4200 : 5600, Math.ceil(layout.result.contentSize.height));
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width, height: screenshotHeight, scale: 1 },
  });
  const screenshotPath = `${artifactDir}/gridsynapse-v2-final-${name}.png`;
  writeFileSync(screenshotPath, Buffer.from(screenshot.result.data, "base64"));

  const errors = cdp.events.filter((event) =>
    event.method === "Runtime.exceptionThrown" ||
    (event.method === "Log.entryAdded" && ["error", "warning"].includes(event.params?.entry?.level)) ||
    (event.method === "Console.messageAdded" && ["error", "warning"].includes(event.params?.message?.level))
  ).map((event) => ({ method: event.method, params: event.params }));
  const final = await snapshot();
  cdp.close();
  return { name, initial, final, nav, actions, errors, screenshotPath };
}

try {
  const desktop = await runViewport({ name: "desktop", width: 1440, height: 1000, mobile: false });
  const mobile = await runViewport({ name: "mobile", width: 390, height: 844, mobile: true });
  const report = { baseUrl, desktop, mobile };
  writeFileSync(`${artifactDir}/gridsynapse-browser-qa.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  const failures = [desktop, mobile].flatMap((result) => [
    ...(result.errors.length ? [`${result.name}: console errors`] : []),
    ...(result.final.scrollWidth > result.final.clientWidth ? [`${result.name}: horizontal overflow`] : []),
    ...result.nav.filter((item) => !item.clicked).map((item) => `${result.name}: missing ${item.label}`),
    ...result.actions.filter((item) => !item.passed).map((item) => `${result.name}: ${item.action} failed`),
  ]);
  if (failures.length) {
    console.error(`QA failures:\n- ${failures.join("\n- ")}`);
    process.exitCode = 1;
  }
} finally {
  chrome.kill("SIGTERM");
  await sleep(400);
  rmSync(userDataDir, { recursive: true, force: true, maxRetries: 4, retryDelay: 150 });
}
