// @vitest-environment node
/**
 * The landing page must say, in every language, that this is testnet only.
 *
 * A visitor asked why the site gave so little detail about the testnet phase.
 * The page did carry a "Testnet first" card, so the claim was not absent, but
 * that phrase describes a practice and reads as "we test carefully" rather than
 * "everything here is testnet only and the money is not money". Somebody
 * arriving to try the marketplace should not have to reach the security page to
 * learn which of those is true.
 *
 * A status line is now the first thing in the hero. This asserts it, because a
 * disclosure held in place only by nobody having refactored the hero yet is the
 * same shape as every other defect this project has spent the week finding: a
 * property that is true, load-bearing, and unenforced.
 *
 * Checked at the message-catalogue level rather than by rendering, because the
 * failure worth catching is a locale losing the string. A missing key is a
 * render error in next-intl, so English alone passing tells you nothing about
 * the other eight.
 */
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const MESSAGES = resolve(__dirname, "../messages");

const locales = readdirSync(MESSAGES)
  .filter((f) => f.endsWith(".json"))
  .map((f) => f.replace(/\.json$/, ""));

function catalogue(locale: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(MESSAGES, `${locale}.json`), "utf8"));
}

interface Status {
  label?: string;
  body?: string;
  link?: string;
}

function hero(locale: string): Status {
  const home = catalogue(locale).home as Record<string, unknown>;
  const h = home.hero as Record<string, unknown>;
  return (h.status ?? {}) as Status;
}

describe("the landing page states its testnet status", () => {
  it("has locales to check at all", () => {
    // Otherwise every assertion below passes over an empty list.
    expect(locales.length).toBeGreaterThanOrEqual(9);
  });

  it.each(locales)("%s carries a label, a body and a link", (locale) => {
    const status = hero(locale);
    expect(status, `${locale} has no hero.status block`).toBeTruthy();
    for (const key of ["label", "body", "link"] as const) {
      const value = status[key];
      expect(value, `${locale} is missing hero.status.${key}`).toBeTruthy();
      expect(
        (value ?? "").trim().length,
        `${locale} hero.status.${key} is blank`,
      ).toBeGreaterThan(1);
    }
  });

  it.each(locales)("%s names the network and denies real value", (locale) => {
    const status = hero(locale);
    const text = `${status.label ?? ""} ${status.body ?? ""}`;

    // The network is a proper noun and stays untranslated, so it is the one
    // token that can be asserted the same way in every language.
    expect(text, `${locale} does not name Base Sepolia`).toContain("Sepolia");

    // The claim that matters. Asserted as "the body is substantial and mentions
    // the token" rather than by keyword, because "no real value" has no shared
    // spelling across nine languages and a keyword list would quietly stop
    // matching the moment a translation was improved.
    expect(text, `${locale} does not mention the settlement token`).toContain("USDC");
    expect(
      (status.body ?? "").length,
      `${locale} status body is too short to be saying anything`,
    ).toBeGreaterThan(40);
  });

  it("the hero renders the status before anything else", () => {
    const source = readFileSync(
      resolve(__dirname, "../components/landing/hero.tsx"),
      "utf8",
    );

    const status = source.indexOf("hero.status.label");
    const kicker = source.indexOf("hero.kicker");
    const title = source.indexOf("hero.title");

    expect(status, "the hero no longer renders the status line").toBeGreaterThan(-1);
    expect(status, "the status line moved below the kicker").toBeLessThan(kicker);
    expect(status, "the status line moved below the headline").toBeLessThan(title);
  });

  it("the status line is not animated in after the headline", () => {
    /**
     * The rest of the hero is staged to sequence reading. A disclosure that
     * fades in on a delay is one the fastest readers miss, which defeats the
     * point of putting it first.
     */
    const source = readFileSync(
      resolve(__dirname, "../components/landing/hero.tsx"),
      "utf8",
    );
    const status = source.indexOf("hero.status.label");
    const block = source.slice(Math.max(0, status - 600), status);

    expect(block, "the status line was wrapped in a staged animation").not.toMatch(
      /\{\.\.\.rise\([^)]*\)\}\s*[^]{0,200}$/,
    );
  });
});
