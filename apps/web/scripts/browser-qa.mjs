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
    } else if (message.method) events.push(message);
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

  const evaluate = async (expression) => {
    const response = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (response.result?.exceptionDetails) throw new Error(response.result.exceptionDetails.text ?? "Browser evaluation failed");
    return response.result?.result?.value;
  };
  const clickButton = async (label) => evaluate(`(() => {
    const normalized = ${JSON.stringify(label.toLowerCase())};
    const button = [...document.querySelectorAll("button")].find((item) => item.textContent.trim().toLowerCase() === normalized);
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  const clickStartingWith = async (label) => evaluate(`(() => {
    const normalized = ${JSON.stringify(label.toLowerCase())};
    const button = [...document.querySelectorAll("button")].find((item) => item.textContent.trim().toLowerCase().startsWith(normalized));
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  const waitForText = async (text, timeout = 6000) => {
    const attempts = Math.ceil(timeout / 150);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (await evaluate(`document.body.innerText.toLowerCase().includes(${JSON.stringify(text.toLowerCase())})`)) return true;
      await sleep(150);
    }
    return false;
  };
  const snapshot = async () => evaluate(`(() => ({
    title: document.title,
    headings: [...document.querySelectorAll("h1,h2")].map((item) => item.textContent.trim()).filter(Boolean).slice(0, 12),
    buttons: [...document.querySelectorAll("button")].map((item) => item.textContent.trim()).filter(Boolean),
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight,
    overflowElements: [...document.querySelectorAll("body *")].map((item) => {
      const rect = item.getBoundingClientRect();
      return { tag: item.tagName, className: typeof item.className === "string" ? item.className : "", right: Math.round(rect.right), left: Math.round(rect.left), width: Math.round(rect.width) };
    }).filter((item) => item.right > document.documentElement.clientWidth + 1 || item.left < -1).slice(0, 12),
  }))()`);

  const navigationStartedAt = Date.now();
  await cdp.send("Page.navigate", { url: baseUrl });
  const ready = await waitForText("ai compute procurement control plane", 12000);
  const initial = { ...(await snapshot()), ready, readyMs: Date.now() - navigationStartedAt };
  const nav = [];
  for (const label of ["Queue", "Decision", "Procurement", "Runs", "Outcomes"]) {
    const clicked = await clickButton(label);
    await sleep(250);
    nav.push({ label, clicked, ...(await snapshot()) });
  }

  const actions = [];
  if (name === "desktop") {
    await clickButton("Decision");
    await sleep(200);
    const approveClicked = await clickButton("Approve decision");
    const approved = await waitForText("decision approved", 5000);
    actions.push({ action: "approve decision", passed: approveClicked && approved });

    const procurementClicked = await clickButton("Procurement");
    await sleep(250);
    const buildClicked = await clickButton("Build commitment");
    const commitmentCreated = await waitForText("validated compute commitment", 6000);
    actions.push({ action: "build compute commitment", passed: procurementClicked && buildClicked && commitmentCreated });

    const manifestText = await evaluate(`document.body.innerText.includes("Inspectable SkyPilot planning artifact")`);
    actions.push({ action: "generate SkyPilot planning artifact", passed: manifestText });

    const verifyClicked = await clickButton("Verify dry run");
    const verified = await waitForText("dry run ready", 5000);
    actions.push({ action: "verify dry run", passed: verifyClicked && verified });

    const simulationClicked = await clickButton("Approve simulated run");
    const simulationApproved = await waitForText("approved for launch", 5000);
    actions.push({ action: "approve zero-spend simulation", passed: simulationClicked && simulationApproved });

    await clickButton("Runs");
    await sleep(200);
    const provisionClicked = await clickStartingWith("Simulate provisioning");
    const provisioning = await waitForText("provisioning recorded", 4000);
    const runClicked = await clickStartingWith("Mark simulated run active");
    const running = await waitForText("running recorded", 4000);
    const completeClicked = await clickStartingWith("Complete simulated run");
    const completed = await waitForText("completed recorded", 4000);
    actions.push({ action: "simulate run lifecycle", passed: provisionClicked && provisioning && runClicked && running && completeClicked && completed });

    await clickButton("Outcomes");
    await sleep(200);
    const reconcileClicked = await clickButton("Reconcile outcome");
    const reconciled = await waitForText("compute commitment reconciled", 5000);
    actions.push({ action: "reconcile outcome", passed: reconcileClicked && reconciled });
  }

  await clickButton(name === "desktop" ? "Outcomes" : "Queue");
  await sleep(250);
  const layout = await cdp.send("Page.getLayoutMetrics");
  const screenshotHeight = Math.min(name === "desktop" ? 4200 : 5600, Math.ceil(layout.result.contentSize.height));
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width, height: screenshotHeight, scale: 1 },
  });
  const screenshotPath = `${artifactDir}/gridsynapse-procurement-${name}.png`;
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
    ...(!result.initial.ready ? [`${result.name}: application did not become ready`] : []),
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
