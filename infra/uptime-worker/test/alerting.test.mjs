/**
 * The alert state machine, exercised against the real Worker module.
 *
 * The parts worth testing are not the probes, which are a fetch, but the
 * transitions: alert once rather than every minute, only after the threshold,
 * and send exactly one all-clear on recovery. Getting those wrong produces
 * either a channel nobody reads or an outage nobody hears about, and neither
 * failure is visible until it matters.
 *
 * Run with: node --test
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import worker from "../src/worker.js";

/** An in-memory stand-in for the KV binding, with the same shape. */
function fakeKv() {
  const store = new Map();
  return {
    async get(key, opts) {
      const raw = store.get(key);
      if (raw === undefined) return null;
      return opts && opts.type === "json" ? JSON.parse(raw) : raw;
    },
    async put(key, value) {
      store.set(key, value);
    },
  };
}

/**
 * Drives the Worker with the site either up or down, collecting the Telegram
 * messages it tries to send.
 */
function harness() {
  const sent = [];
  let healthy = true;
  const env = {
    STATE: fakeKv(),
    TELEGRAM_BOT_TOKEN: "stub",
    TELEGRAM_CHAT_ID: "stub",
  };

  globalThis.fetch = async (url, init) => {
    const target = typeof url === "string" ? url : url.toString();
    if (target.includes("api.telegram.org")) {
      sent.push(JSON.parse(init.body).text);
      return new Response("{}", { status: 200 });
    }
    if (!healthy) return new Response("origin down", { status: 521 });
    if (target.includes("/health/live")) {
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("<html>ok</html>", { status: 200 });
  };

  return {
    sent,
    setHealthy(v) {
      healthy = v;
    },
    async tick() {
      await worker.fetch(null, env);
    },
  };
}

test("a single failed check does not alert", async () => {
  const h = harness();
  h.setHealthy(false);
  await h.tick();
  assert.equal(h.sent.length, 0, "alerted on the first failure");
});

test("alerts once the threshold is reached, then stays quiet", async () => {
  const h = harness();
  h.setHealthy(false);
  await h.tick();
  await h.tick();
  assert.equal(h.sent.length, 1, "did not alert at the threshold");
  assert.match(h.sent[0], /unreachable from outside/);
  assert.match(h.sent[0], /521/, "the alert should say what was seen");

  // Five more failing minutes must not produce five more messages.
  for (let i = 0; i < 5; i++) await h.tick();
  assert.equal(h.sent.length, 1, "repeated the alert every minute");
});

test("sends exactly one all-clear on recovery", async () => {
  const h = harness();
  h.setHealthy(false);
  await h.tick();
  await h.tick();
  h.setHealthy(true);
  await h.tick();
  assert.equal(h.sent.length, 2);
  assert.match(h.sent[1], /reachable again/);

  await h.tick();
  await h.tick();
  assert.equal(h.sent.length, 2, "kept announcing recovery");
});

test("a healthy site never sends anything", async () => {
  const h = harness();
  for (let i = 0; i < 10; i++) await h.tick();
  assert.equal(h.sent.length, 0);
});

test("a recovered blip below the threshold alerts neither way", async () => {
  const h = harness();
  h.setHealthy(false);
  await h.tick();
  h.setHealthy(true);
  await h.tick();
  assert.equal(h.sent.length, 0, "a one minute blip should be silent");
});

test("HTML served where live JSON is expected counts as down", async () => {
  const h = harness();
  // The cache trap: the page loads, so a naive check passes, but the API is
  // answering with something that is not live JSON.
  globalThis.fetch = async (url, init) => {
    const target = typeof url === "string" ? url : url.toString();
    if (target.includes("api.telegram.org")) {
      h.sent.push(JSON.parse(init.body).text);
      return new Response("{}", { status: 200 });
    }
    return new Response("<html>a cached page</html>", { status: 200 });
  };
  await h.tick();
  await h.tick();
  assert.equal(h.sent.length, 1, "a cached page passed as a healthy API");
});
