import js from "@eslint/js";
import eslintConfigPrettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      // eslint-plugin-react-hooks still exports its config in the pre-flat-config
      // shape (`plugins: ["react-hooks"]` as a string array) rather than as a
      // spreadable flat config entry, so the plugin is registered here and only its
      // `rules` object is reused below instead of spreading the config directly.
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs["recommended-latest"].rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    },
  },
  eslintConfigPrettier,
  {
    // shadcn/ui components export their variant helpers next to the component.
    files: ["src/components/ui/**"],
    rules: { "react-refresh/only-export-components": "off" },
  },
  {
    // CLAUDE.md rule 2: an empty line before every block statement and every return
    // (not needed when it's the first statement of its block). `pnpm run lint --fix`
    // adds them.
    files: ["**/*.{ts,tsx}"],
    rules: {
      "padding-line-between-statements": ["error", { blankLine: "always", prev: "*", next: ["block-like", "return"] }],
    },
  },
);
