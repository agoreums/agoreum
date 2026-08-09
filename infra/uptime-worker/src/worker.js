/**
 * Uptime check for agoreum.xyz, running on Cloudflare's cron.
 *
 * The on-droplet monitor cannot report that the droplet is gone, because it goes
 * down with it. A reboot drill confirmed that: it sent nothing during the outage
 * and only reported a problem once it was already back.
 *
 * There are deliberately two external checks. This one runs every minute and is
 * the primary. A GitHub Actions workflow runs the same probes on a five minute
 * schedule as a redundant secondary, so that a fault in Cloudflare's scheduler
 * or in this Worker does not leave the site unwatched. They share no
 * infrastructure with each other or with the droplet.
 *
 * Checking the public URL is meaningful, and that was verified rather than
 * assumed: `always_online` is off, the HTML is not cached at the edge, and when
 * the origin went down during the drill the public URL returned HTTP 521 rather
 * than a stale page. The API probe additionally requires live JSON, which a
 * static cache cannot fake, so if edge caching is ever turned on this check does
 * not quietly become a test of Cloudflare's cache.
 */

const SITE = "https://agoreum.xyz/en";
const API = "https://agoreum.xyz/api/v1/health/live";

// Two consecutive failures, so roughly two minutes. A single failed minute is
// usually a blip, and an alert channel that cries wolf gets muted.
const THRESHOLD = 2;
const STATE_KEY = "uptime:state";

async function probe(url, expectJson) {
  try {
    const response = await fetch(url, {
      headers: {
        "User-Agent": "agoreum-uptime-worker",
        "Cache-Control": "no-cache",
      },
      // Belt and braces against ever measuring the edge cache rather than the
      // origin, even if caching is turned on for this zone later.
      cf: { cacheTtl: 0, cacheEverything: false },
    });

    if (response.status !== 200) return { ok: false, detail: `HTTP ${response.status}` };

    if (expectJson) {
      const body = await response.json();
      if (body.status !== "ok") return { ok: false, detail: `status ${body.status}` };
    }
    return { ok: true, detail: "HTTP 200" };
  } catch (err) {
    // A body that is not JSON lands here too, which is the case worth catching:
    // a cached HTML page served where live JSON was expected.
    return { ok: false, detail: err.name || "error" };
  }
}

async function telegram(env, text) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) {
    throw new Error("telegram credentials are not bound to this Worker");
  }
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: env.TELEGRAM_CHAT_ID,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`telegram rejected the message: HTTP ${response.status}`);
  }
}

async function runCheck(env) {
  const [site, api] = await Promise.all([probe(SITE, false), probe(API, true)]);

  const failures = [];
  if (!site.ok) failures.push(`site ${site.detail}`);
  if (!api.ok) failures.push(`api ${api.detail}`);

  const stored = await env.STATE.get(STATE_KEY, { type: "json" });
  const state = stored || { consecutiveFailures: 0, alerted: false };

  if (failures.length > 0) {
    state.consecutiveFailures += 1;
    console.log(`unhealthy (${state.consecutiveFailures}): ${failures.join(", ")}`);

    if (state.consecutiveFailures >= THRESHOLD && !state.alerted) {
      await telegram(
        env,
        "<b>Agoreum is unreachable from outside</b>\n" +
          `${failures.join("\n")}\n` +
          `failed ${state.consecutiveFailures} checks in a row\n` +
          "checked from Cloudflare, not from the droplet",
      );
      state.alerted = true;
      state.downSince = new Date().toISOString();
      console.log("alerted: down");
    }
  } else {
    if (state.alerted) {
      const since = state.downSince ? ` (down since ${state.downSince})` : "";
      await telegram(
        env,
        `<b>Agoreum is reachable again</b>\nsite and API both answering${since}`,
      );
      console.log("alerted: recovered");
      delete state.downSince;
    } else {
      console.log("healthy");
    }
    state.consecutiveFailures = 0;
    state.alerted = false;
  }

  state.lastCheck = new Date().toISOString();
  await env.STATE.put(STATE_KEY, JSON.stringify(state));
  return state;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runCheck(env));
  },

  /**
   * No route is attached to this Worker, so this is reachable only through
   * `wrangler dev` and the workers.dev subdomain if one is ever enabled. It
   * exists so the check can be exercised on demand during setup rather than
   * waiting for the cron.
   */
  async fetch(request, env) {
    const state = await runCheck(env);
    return new Response(JSON.stringify(state, null, 2), {
      headers: { "Content-Type": "application/json" },
    });
  },
};
