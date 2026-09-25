import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defaultFilter, exportFilename } from "./filters";

describe("defaultFilter", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 2, 15)); // March 15, 2026 (local time)
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("spans a rolling 30-day window ending today", () => {
    expect(defaultFilter()).toEqual({ from: "2026-02-14", to: "2026-03-15" });
  });

  it("rolls back across a year boundary correctly", () => {
    vi.setSystemTime(new Date(2026, 0, 10)); // January 10, 2026
    expect(defaultFilter()).toEqual({ from: "2025-12-12", to: "2026-01-10" });
  });
});

describe("exportFilename", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 2, 5, 9, 3, 7)); // March 5, 2026, 09:03:07
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("zero-pads month/day/hour/minute/second", () => {
    expect(exportFilename()).toBe("transactions-2026-03-05_09-03-07.csv");
  });
});
