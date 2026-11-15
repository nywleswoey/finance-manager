// Correctness-only lint for the React app and its Playwright suite: undefined names, unused
// bindings, and the rules of hooks. No formatter and no style rules on purpose: the inventory
// spec reads source text (the `<table` count, the literal `640` sites), so a reformat is a
// test change, not a free one. Run: `npm run lint` (`make lint-web` from the root).
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  { ignores: ["dist/", "node_modules/", "playwright-report/", "test-results/"] },
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      // `_x` names a binding kept for its position (destructuring, callback arity)
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_",
                                    caughtErrors: "none" }],
      // `try { … } catch {}` is how a best-effort call (logout, error-body parse) says so
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
  {
    files: ["src/**/*.jsx"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The views reset their state when a prop changes by calling setState at the top of the
      // effect that refetches. That is a deliberate pattern here, not a bug; the React Compiler
      // rule that flags it is off until the data hooks are extracted.
      "react-hooks/set-state-in-effect": "off",
      // JSX uses the imported component names; without this the React import of each
      // component looks unused to core eslint.
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_|^[A-Z]",
                                    caughtErrors: "none" }],
    },
  },
];
