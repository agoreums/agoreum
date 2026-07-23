import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

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
