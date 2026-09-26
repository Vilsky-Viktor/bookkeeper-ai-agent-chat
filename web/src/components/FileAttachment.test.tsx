import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FileAttachment from "./FileAttachment";

function stubFetch(implementation: (url: string) => Promise<string>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => implementation(url).then((text) => ({ text: () => Promise.resolve(text) }) as Response)),
  );
}

describe("FileAttachment", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders a download link, exposing the filename via aria-label rather than visible text", () => {
    stubFetch(() => new Promise(() => {})); // never resolves — icon fallback, not under test here
    render(<FileAttachment url="blob:mock-url" filename="transactions-2026-03-05.csv" />);
    const link = screen.getByRole("link", { name: "transactions-2026-03-05.csv" });
    expect(link).toHaveAttribute("href", "blob:mock-url");
    expect(link).toHaveAttribute("download", "transactions-2026-03-05.csv");
    expect(screen.queryByText("transactions-2026-03-05.csv")).not.toBeInTheDocument();
  });

  it("shows a preview table of the CSV's first rows once fetched", async () => {
    stubFetch(() => Promise.resolve("Date,Amount\n2026-01-01,12.50\n2026-01-02,8.00"));
    render(<FileAttachment url="blob:mock-url" filename="export.csv" />);

    expect(await screen.findByText("Date")).toBeInTheDocument();
    expect(screen.getByText("12.50")).toBeInTheDocument();
    expect(screen.getByText("8.00")).toBeInTheDocument();
  });

  it("falls back to a generic file icon when the fetch fails", async () => {
    stubFetch(() => Promise.reject(new Error("network error")));
    const { container } = render(<FileAttachment url="blob:mock-url" filename="export.csv" />);

    await new Promise((resolve) => setTimeout(resolve, 0)); // flush the rejected fetch chain
    expect(container.querySelector("table")).not.toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument(); // the FileText icon
  });
});
