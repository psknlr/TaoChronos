// The console in a real browser (cloud/console/test/run.sh): register with an email code and a passkey (Chromium's
// virtual authenticator, through the DevTools protocol), keep the recovery codes, make a live key, sign out, sign in with
// the passkey alone, look at the security page, and be refused from another origin.  The code is read from the mail
// local workerd wrote (its Email Service stand-in), as a person reads it from their inbox.  The key it made is written
// to OUT, for run.sh to use against the API.  Needs Playwright with Chromium (not pinned here: a developer's check).
const { chromium } = require("playwright");
const fs = require("fs");
const [LOG, OUT] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (what, cond, detail = "") => { console.log(cond ? "ok  " : "FAIL", what, cond ? "" : detail); if (!cond) failed++; };

async function codeFor(address, after) {
  for (let i = 0; i < 40; i++) {
    const log = fs.readFileSync(LOG, "utf8");
    const blocks = log.split("send_email binding called with MessageBuilder:").slice(1).filter((b) => b.includes(`To: ${address}`));
    const files = blocks.map((b) => /Text: (\S+)/.exec(b)?.[1]).filter(Boolean).filter((f) => !after.includes(f));
    if (files.length) {
      const text = fs.readFileSync(files.at(-1), "utf8");
      after.push(files.at(-1));
      return /^ {4}(\d{8})$/m.exec(text)?.[1];
    }
    await sleep(250);
  }
  return null;
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  // (a 4xx the page asked for and handled — the signed-out check, the wrong code — is logged by the browser as a
  // failed resource: not an error of the page's)
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal",
    hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
  const seen = [];
  await page.goto(process.env.CONSOLE || "http://localhost:8788/");
  await page.getByRole("tab", { name: "Register" }).click();
  await page.fill("#email", "li.wei@example.org");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.waitForSelector("#code");
  const code = await codeFor("li.wei@example.org", seen);
  check("the code arrived by mail", /^\d{8}$/.test(code || ""), code);
  await page.fill("#code", "00000000" === code ? "11111111" : "00000000");
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.waitForSelector(".msg.error");
  check("a wrong code says how many attempts are left", /4 attempts left/.test(await page.textContent(".msg.error")), await page.textContent(".msg.error"));
  await page.fill("#code", code);
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.getByRole("button", { name: "Create a passkey" }).click();
  await page.waitForSelector(".codes");
  const codes = await page.$$eval(".codes span", (s) => s.map((x) => x.textContent));
  check("ten recovery codes, shown once", codes.length === 10 && codes.every((c) => /^[0-9A-Z]{4}(-[0-9A-Z]{4}){3}$/.test(c)), codes);
  const creds = await cdp.send("WebAuthn.getCredentials", { authenticatorId });
  check("the authenticator holds one discoverable passkey for localhost", creds.credentials.length === 1 && creds.credentials[0].isResidentCredential && creds.credentials[0].rpId === "localhost", creds);
  await page.getByRole("button", { name: "I have saved them" }).click();
  await page.waitForSelector(".stat");
  const stats = await page.$$eval(".stat b", (b) => b.map((x) => x.textContent));
  check("the organisation was provisioned with its trial: 40 credits", stats[0] === "40", stats);
  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === "__Host-tcs");
  check("the session is an HttpOnly, Secure, host-only cookie the page cannot read", session && session.httpOnly && session.secure && !session.domain.startsWith("."), session);
  check("no script sees it", (await page.evaluate(() => document.cookie)) === "");
  // a live key: made within the passkey's five minutes, shown once
  await page.getByRole("tab", { name: "API keys" }).click();
  await page.selectOption("#key-env", "live");
  await page.fill("#key-name", "lab server");
  await page.getByRole("button", { name: "Create" }).click();
  await page.waitForSelector(".secret");
  const key = (await page.textContent(".secret")).trim();
  check("a live key, shown once", /^tao_live_[0-9a-z]{26}_[0-9a-z]{46}$/.test(key), key);
  check("it is listed by its shown form only", (await page.textContent("table")).includes(`tao_live_…${key.slice(-4)}`) && !(await page.textContent("table")).includes(key.slice(9, 40)));
  fs.writeFileSync(OUT, key);
  // sign out; sign in with the passkey alone
  await page.click("#signout");
  await page.waitForSelector("text=Sign in with a passkey");
  check("signed out: the account is not readable", (await (await context.request.get(new URL("/account", page.url()).href)).status()) === 401);
  await page.getByRole("button", { name: "Sign in with a passkey" }).click();
  await page.waitForSelector(".stat");
  check("signed in again with the passkey alone", (await page.textContent("#who")) === "li.wei@example.org");
  await page.getByRole("tab", { name: "Security" }).click();
  await page.waitForSelector("text=Signed-in devices");
  const sec = await page.textContent("main");
  check("the security page: the passkey, ten recovery codes, this device, the events", /Recovery codes left: 10/.test(sec) && /this device/.test(sec) && /Passkey added/.test(sec) && /Registered/.test(sec), sec.slice(0, 600));
  // the same request from another origin is refused, whoever's cookie it carries
  const forged = await context.request.post(new URL("/auth/signout", page.url()).href, { headers: { Origin: "https://evil.example", "Content-Type": "application/json" }, data: {} });
  check("a change from another origin: 403", forged.status() === 403, forged.status());
  check("no script error on the page", errors.length === 0, errors);
  await browser.close();
  console.log("failed:", failed);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
