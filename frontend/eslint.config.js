import js from "@eslint/js"
import globals from "globals"
import reactHooks from "eslint-plugin-react-hooks"
import reactRefresh from "eslint-plugin-react-refresh"
import tseslint from "typescript-eslint"

/**
 * v0.1 shipped no linter in the frontend at all: the eslint-disable comments
 * scattered through the admin panel referred to a config that did not exist, so
 * nothing enforced them and dead imports accumulated. [F1]
 */
export default tseslint.config(
  { ignores: ["dist", "node_modules", "coverage"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // v7 flags every "fetch on mount" effect, because setState lands in the
      // effect body. That is the correct pattern for loading a view's data and
      // the alternative (a data library) is not in this codebase, so the rule is
      // advisory here rather than blocking. Purity and dependency rules, which
      // catch real bugs, stay errors.
      "react-hooks/set-state-in-effect": "warn",
      // Unused arguments are noise in event handlers; unused values are not.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // The design system forbids raw hex in components — colours come from the
      // token layer so the admin panel and the app cannot drift apart.
      "no-restricted-syntax": [
        "warn",
        {
          selector: "Literal[value=/^#[0-9a-fA-F]{3,8}$/]",
          message: "از توکن‌های رنگ طراحی استفاده کنید، نه کد رنگ خام.",
        },
      ],
    },
  },
  {
    files: ["**/*.test.{ts,tsx}", "src/test/**"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
)
