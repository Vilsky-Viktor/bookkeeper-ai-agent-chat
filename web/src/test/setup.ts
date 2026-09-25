import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";

// Explicit instead of relying on @testing-library/react's auto-cleanup, which only
// self-registers when it detects jest-style globals (afterEach etc.) on
// globalThis — this project doesn't enable Vitest's `globals` option, so it wouldn't
// otherwise run, and stale DOM would leak from one test into the next.
afterEach(cleanup);
