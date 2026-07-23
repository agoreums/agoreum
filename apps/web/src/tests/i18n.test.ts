import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { localeHreflang, localeNames, locales } from "@/i18n/routing";

const messagesDir = resolve(__dirname, "../messages");

type Messages = Record<string, unknown>;

function load(locale: string): Messages {
  return JSON.parse(
    readFileSync(resolve(messagesDir, `${locale}.json`), "utf-8"),
  ) as Messages;
}

/** Flattens nested catalogues to dotted key paths for comparison. */
function keyPaths(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value as Messages).flatMap(([key, child]) =>
    keyPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe("i18n catalogues", () => {
  const source = load("en");
  const sourceKeys = keyPaths(source).sort();

  it("declares a message file for every configured locale", () => {
    const files = readdirSync(messagesDir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => f.replace(/\.json$/, ""))
      .sort();

    expect(files).toEqual([...locales].sort());
  });

  it("declares a display name and hreflang for every locale", () => {
    for (const locale of locales) {
      expect(localeNames[locale], `missing name for ${locale}`).toBeTruthy();
      expect(localeHreflang[locale], `missing hreflang for ${locale}`).toBeTruthy();
    }
  });

  it.each(locales.filter((l) => l !== "en"))(
    "%s has exactly the same keys as the English source",
    (locale) => {
      expect(keyPaths(load(locale)).sort()).toEqual(sourceKeys);
    },
  );

  it.each(locales)("%s has no empty or untranslated-placeholder strings", (locale) => {
    const messages = load(locale);
    const empties: string[] = [];

    function walk(value: unknown, path: string) {
      if (typeof value === "string") {
        if (value.trim() === "" || value.startsWith("TODO")) empties.push(path);
        return;
      }
      if (typeof value === "object" && value !== null) {
        for (const [key, child] of Object.entries(value as Messages)) {
          walk(child, path ? `${path}.${key}` : key);
        }
      }
    }

    walk(messages, "");
    expect(empties).toEqual([]);
  });
});
