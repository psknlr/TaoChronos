// The console in a real browser (cloud/console/test/run.sh): register with an email code and a passkey (Chromium's
// virtual authenticator, through the DevTools protocol), keep the recovery codes, make a live key, sign out, sign in with
// the passkey alone, look at the security page; sign in by the mailbox and a recovery code, try to move the account to
// an address another person has (answered as any other: only that address's owner learns it, by mail), move it to a new
// one; and be refused from another origin.  Each code is read from the mail local workerd wrote (its Email Service
// stand-in), as a person reads it from their inbox.  The key it made is written to OUT, for run.sh to use against the
// API.  Needs Playwright with Chromium (not pinned here: a developer's check).
const { chromium } = require("playwright");
const fs = require("fs");
const [LOG, OUT] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (what, cond, detail = "") => { console.log(cond ? "ok  " : "FAIL", what, cond ? "" : detail); if (!cond) failed++; };

// the newest mail to an address, not read before, that `test` accepts (a mail leaves from the outbox a moment after
// the step that wrote it): its text
async function mailFor(address, after, test = () => true) {
  for (let i = 0; i < 40; i++) {
    const log = fs.readFileSync(LOG, "utf8");
    const blocks = log.split("send_email binding called with MessageBuilder:").slice(1).filter((b) => b.includes(`To: ${address}`));
    const files = blocks.map((b) => /Text: (\S+)/.exec(b)?.[1]).filter(Boolean).filter((f) => !after.includes(f));
    for (const file of files.reverse()) {
      const text = fs.readFileSync(file, "utf8");
      if (test(text)) { after.push(file); return text; }
    }
    await sleep(250);
  }
  return null;
}
const CODE = /^ {4}(\d{8})$/m;
const codeFor = async (address, after) => CODE.exec((await mailFor(address, after, (t) => CODE.test(t))) || "")?.[1] || null;

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
  const stats = await page.$$eval("section:has(#org-id) .stat b", (b) => b.map((x) => x.textContent));
  check("the organisation was provisioned with its trial: 40 credits", stats[0] === "40", stats);
  const allowance = await page.$$eval("#allowance .stat b", (b) => b.map((x) => x.textContent));
  check("the overview shows the person's daily allowance: none used of five", allowance[0] === "0 / 5" && allowance[2] === "5", allowance);
  check("the page shows the organisation's id, to quote when asking for credits", /Organisation id: org_[0-9a-z]{26} /.test(await page.textContent("#org-id")), await page.textContent("#org-id"));
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
  const owners = await page.$$eval("table tbody tr td:nth-child(4)", (td) => td.map((x) => x.textContent));
  check("and as the person's own: its owner is you", owners[0] === "you", owners);
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
  check("and the account's id, to quote when the owner assigns a key", /Account id: usr_[0-9a-z]{26}/.test(await page.textContent("#account-id")), await page.textContent("#account-id"));
  // another person, in a browser of their own: an account without a passkey
  const theirs = await browser.newContext({ locale: "en-US" });
  const other = await theirs.newPage();
  await other.goto(process.env.CONSOLE || "http://localhost:8788/");
  await other.getByRole("tab", { name: "Register" }).click();
  await other.fill("#email", "zhang.min@example.org");
  await other.getByRole("button", { name: "Send code" }).click();
  await other.waitForSelector("#code");
  await other.fill("#code", (await codeFor("zhang.min@example.org", seen)) || "");
  await other.getByRole("button", { name: "Confirm" }).click();
  await other.getByRole("button", { name: "Not now: sign in by email" }).click();
  await other.waitForSelector(".stat");
  check("another person registers, without a passkey", (await other.textContent("#who")) === "zhang.min@example.org");
  await theirs.close();
  // signed in by the mailbox: a passkey guards the account, so a recovery code completes it
  await page.click("#signout");
  await page.waitForSelector("text=Sign in with a passkey");
  await page.fill("#email", "li.wei@example.org");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.waitForSelector("#code");
  await page.fill("#code", (await codeFor("li.wei@example.org", seen)) || "");
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.waitForSelector("#recovery");
  await page.fill("#recovery", codes[0].toLowerCase().replaceAll("-", " "));
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.waitForSelector(".stat");
  check("signed in by an email code and a recovery code (typed as a person may type it)", (await page.textContent("#who")) === "li.wei@example.org");
  check("its owner is told a recovery code was used", /signed in to with a recovery code/.test((await mailFor("li.wei@example.org", seen, (t) => /recovery code/.test(t))) || ""));
  await page.getByRole("tab", { name: "Security" }).click();
  await page.waitForSelector("#new-email");
  check("nine recovery codes left", /Recovery codes left: 9/.test(await page.textContent("main")));
  // a move to the other person's address — with the page's clock past the session's touch, so that it asks for the
  // passkey first and then sends the change once (its Turnstile token is good once: no second try after a touch)
  const posts = [];
  const record = (r) => { if (r.method() === "POST") posts.push(new URL(r.url()).pathname); };
  page.on("request", record);
  await page.evaluate(() => { const real = Date.now; window.__realNow = real; Date.now = () => real() + 6 * 60_000; });
  await page.fill("#new-email", "zhang.min@example.org");
  await page.getByRole("button", { name: "Change email" }).click();
  await page.waitForSelector("#code");
  page.off("request", record);
  await page.evaluate(() => { Date.now = window.__realNow; });
  check("the passkey is asked first, then the change is sent once", JSON.stringify(posts) === JSON.stringify(["/auth/stepup/options", "/auth/stepup/verify", "/account/email/start"]), posts);
  check("an address that has an account is answered as any other: a code is asked for", (await page.textContent("main")).includes("A code was sent to zhang.min@example.org"));
  const told = await mailFor("zhang.min@example.org", seen, (t) => /already has an account/.test(t));
  check("its owner alone is told, by a mail with no code in it", !!told && !CODE.test(told), told);
  // a move to an address nobody has: its code, typed here, moves the account; the old address is told, the new one masked
  await page.getByRole("button", { name: "Back" }).click();
  await page.waitForSelector("#new-email"); // the page comes back to the tab it was on
  await page.fill("#new-email", "wei.li@example.net");
  await page.getByRole("button", { name: "Change email" }).click();
  await page.waitForSelector("#code");
  await page.fill("#code", (await codeFor("wei.li@example.net", seen)) || "");
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.waitForSelector("#new-email");
  check("the account moved to the new address", (await page.textContent("#who")) === "wei.li@example.net", await page.textContent("#who"));
  const moved = await mailFor("li.wei@example.org", seen, (t) => /address was just changed/.test(t));
  check("the old address is told where to, masked", !!moved && moved.includes("changed to w…@example.net") && !moved.includes("wei.li@example.net"), moved);
  // the same request from another origin is refused, whoever's cookie it carries
  const forged = await context.request.post(new URL("/auth/signout", page.url()).href, { headers: { Origin: "https://evil.example", "Content-Type": "application/json" }, data: {} });
  check("a change from another origin: 403", forged.status() === 403, forged.status());
  check("no script error on the page", errors.length === 0, errors);
  await browser.close();
  console.log("failed:", failed);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
