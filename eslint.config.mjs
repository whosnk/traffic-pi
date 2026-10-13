import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";
import { globalIgnores } from "eslint/config";

const eslintConfig = [
  globalIgnores(["tmp_abstreet_source/**"]),
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      "react-hooks/immutability": "off",
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default eslintConfig;
