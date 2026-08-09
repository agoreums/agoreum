// @vitest-environment node
/**
 * Right-to-left correctness, checked mechanically.
 *
 * Arabic is a shipped locale, not a stretch goal, and RTL breakage is close to
 * invisible when you read left to right: the page still looks plausible, it is
 * just laid out backwards for the person using it. Tailwind's logical utilities
 * (`ms`/`me`, `ps`/`pe`, `start`/`end`) flip with direction; the physical ones
 * (`ml`, `pr`, `left`) do not. This fails the build when a physical one appears
 * in markup, which is the only reliable way to keep it from creeping back.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");

/** Physical utilities, each paired with the logical one to use instead. */
const PHYSICAL: Array<[RegExp, string]> = [
  [/\bml-[\w./[\]-]+/g, "ms-*"],
  [/\bmr-[\w./[\]-]+/g, "me-*"],
  [/\bpl-[\w./[\]-]+/g, "ps-*"],
  [/\bpr-[\w./[\]-]+/g, "pe-*"],
  [/\bborder-l-[\w./[\]-]+/g, "border-s-*"],
  [/\bborder-r-[\w./[\]-]+/g, "border-e-*"],
  [/\brounded-l-[\w./[\]-]+/g, "rounded-s-*"],
  [/\brounded-r-[\w./[\]-]+/g, "rounded-e-*"],
  [/\btext-left\b/g, "text-start"],
  [/\btext-right\b/g, "text-end"],
];

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry === "tests" || entry === "node_modules") continue;
      sourceFiles(path, out);
    } else if (entry.endsWith(".tsx")) {
      out.push(path);
    }
  }
  return out;
}

describe("right-to-left layout", () => {
  it("uses logical direction utilities rather than physical ones", () => {
    const offences: string[] = [];

    for (const file of sourceFiles(SRC)) {
      const contents = readFileSync(file, "utf8");
      const lines = contents.split("\n");

      // A deliberate LTR island opts out, and so does everything nested inside
      // it: within `dir="ltr"` the physical side is the correct one, because
      // that subtree does not flip. The island is tracked by indentation, which
      // holds because the source is Prettier-formatted.
      let islandIndent: number | null = null;

      lines.forEach((line, index) => {
        const indent = line.search(/\S/);
        if (islandIndent !== null && indent !== -1 && indent <= islandIndent) {
          islandIndent = null;
        }
        if (line.includes('dir="ltr"')) {
          islandIndent = indent;
          return;
        }
        if (islandIndent !== null) return;

        for (const [pattern, replacement] of PHYSICAL) {
          for (const match of line.match(pattern) ?? []) {
            offences.push(
              `${file.slice(SRC.length + 1)}:${index + 1} ` +
                `uses ${match}, should be ${replacement}`,
            );
          }
        }
      });
    }

    expect(offences, offences.join("\n")).toEqual([]);
  });
});
