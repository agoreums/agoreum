/**
 * The browser must canonicalise a receipt to the same bytes the API signs.
 *
 * This is the one property the whole verification story rests on, and it fails
 * silently rather than loudly. If the two implementations disagree by a single
 * byte, the page tells an honest reader that a genuine receipt is invalid, and
 * the reasonable response to a signature that does not verify is to stop
 * trusting signatures.
 *
 * The expected strings here are literals rather than anything computed, and the
 * identical literals appear in `apps/api/tests/test_receipts.py`. That is
 * deliberate: pinning both sides to the same constants means a change to either
 * implementation turns one suite red, instead of both drifting together while
 * agreeing with each other and with nothing else. Three published SDKs once
 * called an endpoint this API had never served, agreeing perfectly among
 * themselves, which is the failure mode this arrangement is built to avoid.
 */
import { describe, expect, it } from "vitest";

import { canonicalReceipt } from "@/lib/receipt-canonical";

describe("canonicalReceipt", () => {
  it("does not escape non-ASCII, matching the API", () => {
    // The exact divergence that existed until 2026-08-16. Python escaped these
    // to \uXXXX by default and JavaScript never has.
    expect(canonicalReceipt({ note: "café", tick: "✓" })).toBe(
      '{"note":"café","tick":"✓"}',
    );
  });

  it("sorts keys at every level, not only the top", () => {
    // A JSON.stringify replacer sorts only the keys it is handed, which is
    // correct for a flat object and wrong for every real receipt, since they
    // all nest order, settlement and verify.
    expect(canonicalReceipt({ b: "ü", a: { y: 2, x: "日本" } })).toBe(
      '{"a":{"x":"日本","y":2},"b":"ü"}',
    );
  });

  it("emits no whitespace between tokens", () => {
    const output = canonicalReceipt({ a: 1, b: [1, 2], c: { d: true } });
    expect(output).toBe('{"a":1,"b":[1,2],"c":{"d":true}}');
    expect(output).not.toMatch(/\s/);
  });

  it("preserves array order while sorting object keys inside them", () => {
    // Arrays are ordered data and reordering them would change the meaning.
    expect(canonicalReceipt([{ b: 1, a: 2 }, "z", "a"])).toBe(
      '[{"a":2,"b":1},"z","a"]',
    );
  });

  it("canonicalises the shape a real receipt actually has", () => {
    // Trimmed from the receipt issued for order AGO-TMMR2TWH, the first real
    // settlement on Base Sepolia. Nesting and key order both matter here.
    const receipt = {
      type: "https://agoreum.xyz/schemas/settlement-receipt-v1",
      issuer: "agoreum.xyz",
      order: { status: "completed", id: "8b49e2b4", reference: "AGO-TMMR2TWH" },
      settlement: {
        network: "base-sepolia",
        chain_id: 84532,
        is_testnet: true,
        amount: "1.025000",
      },
    };

    expect(canonicalReceipt(receipt)).toBe(
      '{"issuer":"agoreum.xyz",' +
        '"order":{"id":"8b49e2b4","reference":"AGO-TMMR2TWH","status":"completed"},' +
        '"settlement":{"amount":"1.025000","chain_id":84532,"is_testnet":true,' +
        '"network":"base-sepolia"},' +
        '"type":"https://agoreum.xyz/schemas/settlement-receipt-v1"}',
    );
  });

  it("is stable when the same payload arrives with keys in another order", () => {
    // A verifier reparses JSON and gets whatever order their library produces,
    // so two spellings of the same object must canonicalise identically or a
    // valid receipt fails for them and not for us.
    const one = { settlement: { b: 2, a: 1 }, issuer: "agoreum.xyz" };
    const two = JSON.parse('{"issuer":"agoreum.xyz","settlement":{"a":1,"b":2}}');
    expect(canonicalReceipt(one)).toBe(canonicalReceipt(two));
  });
});
