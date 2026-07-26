import { defineConfig } from "tsup";

// Dual ESM + CJS output with type declarations, so the SDK works from `import`
// and `require` alike, on Node, browsers, and edge runtimes.
export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  clean: true,
  sourcemap: true,
  target: "es2022",
  outExtension({ format }) {
    return { js: format === "cjs" ? ".cjs" : ".js" };
  },
});
