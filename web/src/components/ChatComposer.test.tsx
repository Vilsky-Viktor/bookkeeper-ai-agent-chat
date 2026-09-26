import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../lib/i18n";
import ChatComposer from "./ChatComposer";

function wrapper({ children }: { children: ReactNode }) {
  return <LanguageProvider userId={null}>{children}</LanguageProvider>;
}

function renderComposer(overrides: Partial<Parameters<typeof ChatComposer>[0]> = {}) {
  const props = {
    value: "hello",
    onChange: vi.fn(),
    onSend: vi.fn(),
    onFileSelected: vi.fn(),
    textareaRef: createRef<HTMLTextAreaElement>(),
    streaming: false,
    recording: false,
    transcribing: false,
    micButtonProps: {},
    ...overrides,
  };
  const { container } = render(<ChatComposer {...props} />, { wrapper });
  return { props, container };
}

describe("ChatComposer", () => {
  it("sends on Enter but not on Shift+Enter", () => {
    const { props } = renderComposer();
    const textarea = screen.getByDisplayValue("hello");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(props.onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(props.onSend).toHaveBeenCalledTimes(1);
  });

  it("doesn't send while a turn is streaming, and locks the textarea", () => {
    const { props } = renderComposer({ streaming: true });
    const textarea = screen.getByDisplayValue("hello");
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(props.onSend).not.toHaveBeenCalled();
    expect(textarea).toBeDisabled();
  });

  it("hands a picked file to onFileSelected", () => {
    const { props, container } = renderComposer();
    const file = new File(["x"], "receipt.jpg", { type: "image/jpeg" });
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
    expect(props.onFileSelected).toHaveBeenCalledWith(file);
  });

  it("shows the stop state while recording and disables upload", () => {
    renderComposer({ recording: true });
    expect(screen.getByRole("button", { name: "Stop recording" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload receipt" })).toBeDisabled();
  });
});
