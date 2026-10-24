import "@testing-library/jest-dom/vitest";

import { afterEach } from "vitest";

// V1-058 R1: the page lives in the address; each test starts on Home.
afterEach(() => {
  window.history.replaceState(null, "", "/");
});
