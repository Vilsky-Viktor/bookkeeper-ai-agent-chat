import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FileAttachment from "./FileAttachment";

describe("FileAttachment", () => {
  it("renders a download link with the given url and filename", () => {
    render(<FileAttachment url="blob:mock-url" filename="transactions-2026-03-05.csv" />);
    const link = screen.getByRole("link", { name: "transactions-2026-03-05.csv" });
    expect(link).toHaveAttribute("href", "blob:mock-url");
    expect(link).toHaveAttribute("download", "transactions-2026-03-05.csv");
  });
});
