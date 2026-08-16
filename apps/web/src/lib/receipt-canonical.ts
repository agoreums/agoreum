/**
 * The exact bytes an Agoreum settlement receipt is signed over.
 *
 * This has to agree with `apps/api/app/modules/receipts/service.py::canonical`
 * character for character, in every language anybody writes a verifier in. It
 * is not a formatting preference: if the two disagree by one byte, a verifier
 * doing exactly what the published instructions say computes a different digest
 * and concludes a genuine receipt is forged. The reasonable reaction to a
 * signature that does not verify is to stop checking signatures, so a
 * divergence here does not cause a visible error, it quietly destroys the
 * feature.
 *
 * The specification, as published in the key document:
 *
 * - keys sorted at every level, not only the top
 * - no whitespace between tokens
 * - UTF-8
 * - no `\u` escaping of non-ASCII characters
 *
 * The last point is the one that was wrong. Python's `json.dumps` escapes
 * non-ASCII by default and `JSON.stringify` does not, and every receipt issued
 * so far happens to be pure ASCII, where the two agree exactly. The ambiguity
 * was real from the first receipt and unreachable until some field carried an
 * accent, which is the kind of defect this project keeps finding: correct
 * looking, untested, and waiting.
 *
 * Recursion rather than `JSON.stringify`'s replacer, deliberately. A replacer
 * sorts only the keys it is handed and leaves nested objects in their original
 * order, which produces a canonical form that is correct for flat payloads and
 * wrong for this one, since every receipt nests `order`, `settlement` and
 * `verify`.
 */
export function canonicalReceipt(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalReceipt).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const source = value as Record<string, unknown>;
    const entries = Object.keys(source)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalReceipt(source[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}
