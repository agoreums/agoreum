import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

/**
 * ESLint flat config.
 *
 * eslint-config-next 16 ships native flat configs, so they are composed directly
 * rather than through the eslintrc compatibility shim.
 */
const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...nextCoreWebVitals,
  ...nextTypeScript,
  // eslint-config-next enables only a handful of jsx-a11y rules (alt text and
  // basic ARIA validity). The recommended set adds the ones that catch the
  // failures that actually strand a keyboard or screen reader user: unlabelled
  // controls, click handlers on non-interactive elements, and focus order.
  //
  // Only the rules are taken. eslint-config-next already registers the plugin,
  // and spreading the whole flat config redefines it, which is a hard error.
  { rules: jsxA11y.flatConfigs.recommended.rules },
  {
    rules: {
      // Our checkbox rows are `<label><input/><span><span>text</span></span></label>`:
      // the control is implicitly associated and the text is real, it is just
      // nested deeper than the default allowance of 2. Raised rather than
      // switched off, so a label with genuinely no text still fails.
      "jsx-a11y/label-has-associated-control": ["error", { depth: 4 }],
    },
  },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Locale-aware navigation must come from @/i18n/navigation. Importing these
      // directly from Next silently drops the active locale on navigation.
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "next/link",
              message:
                "Use `Link` from '@/i18n/navigation' so the active locale is preserved.",
            },
            {
              name: "next/navigation",
              importNames: ["redirect", "usePathname", "useRouter"],
              message:
                "Use the locale-aware equivalents from '@/i18n/navigation'.",
            },
          ],
        },
      ],
    },
  },
];

export default config;
