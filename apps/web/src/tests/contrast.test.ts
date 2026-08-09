// @vitest-environment node
/**
 * Colour contrast, measured rather than eyeballed.
 *
 * The design tokens are the single source of every foreground and background in
 * the app, so contrast can be computed from them directly instead of screenshot
 * inspection. This reads `globals.css`, resolves the token graph for each
 * palette, and applies the WCAG 2.1 relative-luminance formula.
 *
 * There are three themes but two palettes: "system" resolves to the light
 * tokens, or to the dark ones under `prefers-color-scheme: dark`. Both are
 * checked, so "it looks fine on my machine" cannot hide a failure that only
 * appears for somebody whose OS is set the other way.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(__dirname, "../styles/globals.css"),
  "utf8",
);

/** WCAG AA: 4.5:1 for body text, 3:1 for large text and UI boundaries. */
const AA_TEXT = 4.5;
const AA_LARGE = 3;

function parseDeclarations(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const match of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    const [, name, value] = match;
    if (name && value) out[name] = value.trim();
  }
  return out;
}

/**
 * The raw palette, before any theme overrides.
 *
 * Tailwind v4 declares design tokens in `@theme`, not `:root`. Reading the
 * wrong block silently yields an empty palette, so this asserts it found one.
 */
function paletteTokens(): Record<string, string> {
  const start = CSS.indexOf("@theme {");
  if (start === -1) throw new Error("no @theme block in globals.css");
  const tokens = parseDeclarations(CSS.slice(start, CSS.indexOf("\n}", start)));
  if (Object.keys(tokens).length === 0) {
    throw new Error("@theme block parsed to no tokens");
  }
  return tokens;
}

/** The declarations of the first block whose selector matches `selector`. */
function themeBlock(selector: string): Record<string, string> {
  const index = CSS.indexOf(selector);
  if (index === -1) throw new Error(`no block found for ${selector}`);
  const open = CSS.indexOf("{", index);
  const close = CSS.indexOf("\n  }", open);
  return parseDeclarations(CSS.slice(open, close));
}

function resolveToken(
  name: string,
  scopes: Record<string, string>[],
): string {
  let value: string | undefined;
  for (const scope of scopes) {
    if (scope[name] !== undefined) {
      value = scope[name];
      break;
    }
  }
  if (value === undefined) throw new Error(`unresolved token ${name}`);

  const reference = value.match(/^var\((--[\w-]+)\)$/);
  if (reference?.[1]) return resolveToken(reference[1], scopes);
  return value;
}

function toRgb(hex: string): [number, number, number] {
  const clean = hex.trim().replace("#", "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  if (!/^[0-9a-f]{6}$/i.test(full)) {
    throw new Error(`not a plain hex colour: ${hex}`);
  }
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

/** WCAG 2.1 relative luminance. */
function luminance(hex: string): number {
  const [r, g, b] = toRgb(hex).map((channel) => {
    const s = channel / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const lighter = Math.max(luminance(a), luminance(b));
  const darker = Math.min(luminance(a), luminance(b));
  return (lighter + 0.05) / (darker + 0.05);
}

const root = paletteTokens();
const dark = { ...themeBlock(':root[data-theme="dark"]') };
const light = { ...themeBlock(':root[data-theme="light"]') };

const palettes = {
  // "system" resolves to one of these two, so covering both covers all three
  // themes the user can select.
  dark: [dark, root],
  light: [light, root],
} satisfies Record<string, Record<string, string>[]>;

const SURFACES = ["--surface-base", "--surface-raised", "--surface-overlay"];

describe("theme contrast", () => {
  for (const [palette, scopes] of Object.entries(palettes)) {
    describe(palette, () => {
      const colour = (token: string) => resolveToken(token, scopes);

      it("primary text is legible on every surface", () => {
        for (const surface of SURFACES) {
          const ratio = contrast(colour("--text-primary"), colour(surface));
          expect(
            ratio,
            `--text-primary on ${surface} is ${ratio.toFixed(2)}:1`,
          ).toBeGreaterThanOrEqual(AA_TEXT);
        }
      });

      it("secondary text is legible on every surface", () => {
        for (const surface of SURFACES) {
          const ratio = contrast(colour("--text-secondary"), colour(surface));
          expect(
            ratio,
            `--text-secondary on ${surface} is ${ratio.toFixed(2)}:1`,
          ).toBeGreaterThanOrEqual(AA_TEXT);
        }
      });

      it("muted text stays readable rather than decorative", () => {
        // Muted carries real content (timestamps, counts, helper text), so it is
        // held to the body-text threshold, not the large-text one.
        for (const surface of SURFACES) {
          const ratio = contrast(colour("--text-muted"), colour(surface));
          expect(
            ratio,
            `--text-muted on ${surface} is ${ratio.toFixed(2)}:1`,
          ).toBeGreaterThanOrEqual(AA_TEXT);
        }
      });

      it("status colours are readable as text on every surface", () => {
        // Status text tells somebody an order failed or a payout landed, so it
        // is body text and held to 4.5:1, not the large-text threshold. These
        // are used directly as `text-danger-500` and friends in ~56 places, so
        // a failure here is a failure on real screens.
        const statuses = [
          "--color-success-500",
          "--color-warning-500",
          "--color-danger-500",
          "--color-signal-500",
        ];
        for (const status of statuses) {
          for (const surface of SURFACES) {
            const ratio = contrast(colour(status), colour(surface));
            expect(
              ratio,
              `${status} on ${surface} is ${ratio.toFixed(2)}:1`,
            ).toBeGreaterThanOrEqual(AA_TEXT);
          }
        }
      });

      it("interactive borders are visible against their surface", () => {
        // Focus rings and input borders are non-text UI, where 3:1 applies.
        const ratio = contrast(colour("--color-mark-peak"), colour("--surface-base"));
        expect(
          ratio,
          `--color-mark-peak on --surface-base is ${ratio.toFixed(2)}:1`,
        ).toBeGreaterThanOrEqual(AA_LARGE);
      });
    });
  }

  it("the system-dark branch mirrors the dark palette exactly", () => {
    // "system" is styled light by default and handed back to dark under
    // prefers-color-scheme. That makes the dark tokens exist in two places, so
    // a value changed in one and not the other would leave users whose OS is
    // dark on a half-updated palette. Nothing else catches that.
    // Compared by resolved value, not by declaration. The two blocks are not
    // textually identical and should not be: "system" has the light overrides
    // applied underneath it, so its dark branch has to reverse all four status
    // hues, while the explicit dark block only overrides the one that fails at
    // its palette default. What must match is what a user actually sees.
    const systemDarkScopes = [
      themeBlock("@media (prefers-color-scheme: dark)"),
      light,
      root,
    ];
    const explicitDarkScopes = [dark, root];

    const seen = [
      ...SURFACES,
      "--text-primary",
      "--text-secondary",
      "--text-muted",
      "--color-success-500",
      "--color-warning-500",
      "--color-danger-500",
      "--color-signal-500",
    ];
    for (const token of seen) {
      expect(
        resolveToken(token, systemDarkScopes),
        `${token} differs between the two dark palettes`,
      ).toBe(resolveToken(token, explicitDarkScopes));
    }
  });
});
