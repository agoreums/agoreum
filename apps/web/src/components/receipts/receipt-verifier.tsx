"use client";

import { useState } from "react";

import { canonicalReceipt } from "@/lib/receipt-canonical";

/**
 * Check an Agoreum settlement receipt, in the reader's own browser.
 *
 * The point of this component is what it does *not* do. It never sends the
 * receipt anywhere, never asks Agoreum whether the receipt is good, and never
 * consults any Agoreum endpoint except the one publishing the public key, which
 * is the same document a third party would fetch by hand. Everything else
 * happens locally. A verifier that had to ask us whether our own claim was
 * genuine would be worth precisely nothing.
 *
 * It also refuses to overstate its result, which is the harder half. Checking a
 * signature proves attribution and nothing else: that Agoreum said this, not
 * that it happened. Only the chain proves the second, so the outcome is
 * reported as two separate findings and the transaction is linked for the
 * reader to follow. Collapsing them into one green tick would teach exactly the
 * wrong lesson about what a signature is.
 */

const KEY_URL = "/.well-known/agoreum-receipts.json";

type Outcome = {
  attribution: "verified" | "failed" | "unsupported";
  detail: string;
  receipt?: Record<string, unknown>;
  keyId?: string;
};

function fromBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

/** Same reason as above: an encoder's output needs a concrete ArrayBuffer. */
function utf8(value: string): Uint8Array<ArrayBuffer> {
  const encoded = new TextEncoder().encode(value);
  const bytes = new Uint8Array(new ArrayBuffer(encoded.length));
  bytes.set(encoded);
  return bytes;
}

export function ReceiptVerifier() {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  async function verify() {
    setBusy(true);
    setOutcome(null);
    try {
      let document_: {
        receipt?: Record<string, unknown>;
        signature?: string;
        key_id?: string;
      };
      try {
        document_ = JSON.parse(input);
      } catch {
        setOutcome({
          attribution: "failed",
          detail:
            "That is not valid JSON. Paste the whole receipt document, including the receipt, signature and key_id fields.",
        });
        return;
      }

      if (!document_.receipt || !document_.signature) {
        setOutcome({
          attribution: "failed",
          detail:
            "This document has no signature. An unsigned receipt still carries the coordinates to check the settlement on chain, but there is no claim to attribute.",
          receipt: document_.receipt,
        });
        return;
      }

      if (!globalThis.crypto?.subtle) {
        setOutcome({
          attribution: "unsupported",
          detail:
            "This browser exposes no Web Crypto, so the signature cannot be checked here. The chain evidence below does not depend on it.",
          receipt: document_.receipt,
        });
        return;
      }

      const response = await fetch(KEY_URL, { cache: "no-store" });
      const jwks = (await response.json()) as {
        keys: { kid: string; x: string }[];
      };
      const jwk = jwks.keys?.find((k) => k.kid === document_.key_id);
      if (!jwk) {
        setOutcome({
          attribution: "failed",
          detail: `This receipt names key ${
            document_.key_id ?? "(none)"
          }, which is not among the keys Agoreum currently publishes. Either the receipt was not issued by Agoreum, or it predates a key rotation.`,
          receipt: document_.receipt,
        });
        return;
      }

      let key: CryptoKey;
      try {
        key = await crypto.subtle.importKey(
          "raw",
          fromBase64Url(jwk.x),
          { name: "Ed25519" },
          false,
          ["verify"],
        );
      } catch {
        setOutcome({
          attribution: "unsupported",
          detail:
            "This browser does not implement Ed25519 in Web Crypto, so the signature cannot be checked here. Recent Chrome, Safari and Firefox do. The chain evidence below does not depend on it.",
          receipt: document_.receipt,
          keyId: jwk.kid,
        });
        return;
      }

      const ok = await crypto.subtle.verify(
        "Ed25519",
        key,
        fromBase64Url(document_.signature),
        utf8(canonicalReceipt(document_.receipt)),
      );

      setOutcome({
        attribution: ok ? "verified" : "failed",
        detail: ok
          ? "The signature matches the key Agoreum publishes, so Agoreum made this exact statement and no character of it has been altered since."
          : "The signature does not match. Either something in the receipt was changed after it was issued, or it was not signed by the key it names.",
        receipt: document_.receipt,
        keyId: jwk.kid,
      });
    } finally {
      setBusy(false);
    }
  }

  const settlement =
    (outcome?.receipt?.settlement as Record<string, unknown> | undefined) ??
    undefined;
  const txHash = settlement?.transaction_hash as string | undefined;
  const chainId = settlement?.chain_id as number | undefined;
  const explorer =
    chainId === 8453
      ? "https://basescan.org/tx/"
      : "https://sepolia.basescan.org/tx/";

  return (
    <div className="flex flex-col gap-5">
      <label className="flex flex-col gap-2">
        <span className="text-sm text-[var(--text-secondary)]">
          Paste a receipt document
        </span>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={10}
          spellCheck={false}
          placeholder='{"receipt": {...}, "signature": "...", "key_id": "..."}'
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 font-mono text-xs text-[var(--text-primary)] outline-none focus:border-[var(--border-strong)]"
        />
      </label>

      <div>
        <button
          type="button"
          onClick={verify}
          disabled={busy || input.trim().length === 0}
          className="rounded-lg border border-[var(--border-strong)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] transition disabled:opacity-40"
        >
          {busy ? "Checking" : "Check this receipt"}
        </button>
      </div>

      {outcome ? (
        <div className="flex flex-col gap-4 rounded-lg border border-[var(--border)] p-4">
          <div>
            <p className="text-sm font-medium text-[var(--text-primary)]">
              {outcome.attribution === "verified"
                ? "Signature valid: Agoreum made this claim"
                : outcome.attribution === "unsupported"
                  ? "Signature not checked here"
                  : "Signature not valid"}
            </p>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              {outcome.detail}
            </p>
          </div>

          {txHash ? (
            <div className="border-t border-[var(--border)] pt-4">
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Now check what actually happened
              </p>
              <p className="mt-1 text-sm text-[var(--text-secondary)]">
                A signature proves who made a statement. It cannot prove the
                statement is true. This receipt says the settlement is
                transaction{" "}
                <a
                  className="break-all underline decoration-[var(--border-strong)] underline-offset-4"
                  href={`${explorer}${txHash}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {txHash}
                </a>{" "}
                on {settlement?.network as string}. Follow it. If the chain and
                this receipt disagree, the chain is correct.
              </p>
            </div>
          ) : outcome.receipt ? (
            <div className="border-t border-[var(--border)] pt-4">
              <p className="text-sm text-[var(--text-secondary)]">
                This receipt names no transaction hash, so there is nothing to
                follow on chain and the signature alone tells you only that
                Agoreum made the claim.
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
