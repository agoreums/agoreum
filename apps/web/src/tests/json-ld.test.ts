import { describe, expect, it } from "vitest";

import { serializeJsonLd } from "@/components/seo/json-ld";

/**
 * JSON-LD is injected with `dangerouslySetInnerHTML`, and the payload carries
 * agent names and service titles, which any visitor can set and publish without
 * review. `JSON.stringify` alone does not escape `<`, so a name containing
 * `</script>` closes the element and the rest is parsed as markup. The CSP allows
 * `script-src 'unsafe-inline'`, so that markup would run.
 *
 * These assert the property that matters, that nothing which can begin a tag
 * survives serialisation, rather than pinning one exact payload shape.
 */
describe("serializeJsonLd", () => {
  it("escapes a script-closing sequence in a user-controlled value", () => {
    const out = serializeJsonLd({ name: "</script><script>alert(1)</script>" });
    expect(out).not.toContain("</script>");
    expect(out).not.toContain("<");
    expect(out).toContain("\\u003c");
  });

  it("leaves no character that can start or end a tag", () => {
    const out = serializeJsonLd({
      name: "<img src=x onerror=alert(1)>",
      description: "a & b > c < d",
    });
    expect(out).not.toMatch(/[<>&]/);
  });

  it("escapes the line terminators that are legal in JSON but not in JS", () => {
    const out = serializeJsonLd({ name: "line\u2028sep\u2029para" });
    expect(out).not.toMatch(/[\u2028\u2029]/);
    expect(out).toContain("\\u2028");
    expect(out).toContain("\\u2029");
  });

  it("still produces JSON that parses back to the original value", () => {
    const value = { name: "</script> & <b>bold</b>", n: 42, nested: { a: ["<"] } };
    expect(JSON.parse(serializeJsonLd(value))).toEqual(value);
  });
});
