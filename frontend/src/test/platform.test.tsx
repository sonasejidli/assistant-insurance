import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Platform } from "@/components/platform";
import { ui } from "@/lib/ui-text";

vi.mock("@/components/live-workspace", () => ({
  LiveWorkspace: () => <div>Test chat</div>,
}));

const copy = ui.account;
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function fillSignup() {
  window.history.replaceState(null, "", "/signup");
  render(<Platform />);
  fireEvent.change(screen.getByLabelText(copy.email), { target: { value: "NEW@example.com" } });
  fireEvent.change(screen.getByLabelText(copy.password), { target: { value: "valid password" } });
  return screen.getByRole("button", { name: copy.register });
}

describe("platform navigation", () => {
  it("opens chat from the Azerbaijani landing page", async () => {
    render(<Platform />);
    fireEvent.click(screen.getByRole("link", { name: ui.landing.start }));
    expect(await screen.findByText("Test chat")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/workspace");
  });

  it("defaults to sign in, validates fields, and offers guest access", async () => {
    render(<Platform />);
    fireEvent.click(screen.getByRole("link", { name: copy.login }));
    expect(screen.getByRole("heading", { name: copy.login })).toBeInTheDocument();
    expect(screen.getByLabelText(copy.email)).toHaveFocus();
    expect(screen.getByLabelText(copy.password)).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    fireEvent.click(screen.getByRole("button", { name: copy.login }));
    expect(screen.getByText(copy.invalidEmail)).toBeInTheDocument();
    expect(screen.getByText(copy.invalidPassword)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: copy.register }));
    expect(screen.getByLabelText(copy.password)).toHaveAttribute("autocomplete", "new-password");
    fireEvent.click(screen.getByRole("button", { name: copy.showPassword }));
    expect(screen.getByLabelText(copy.password)).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("link", { name: copy.guest }));
    expect(await screen.findByText("Test chat")).toBeInTheDocument();
  });

  it("posts only normalized email and password, guards against duplicate submits, and opens chat", async () => {
    let finish!: (result: Response) => void;
    const request = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    vi.stubGlobal("fetch", request);
    const button = fillSignup();
    const form = button.closest("form")!;
    fireEvent.submit(form);
    expect(screen.getByRole("button", { name: copy.loading })).toBeDisabled();
    fireEvent.submit(form);
    expect(request).toHaveBeenCalledExactlyOnceWith("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "new@example.com", password: "valid password" }),
    });
    await act(async () => finish(new Response(null, { status: 201 })));
    expect(await screen.findByText("Test chat")).toBeInTheDocument();
  });

  it.each([
    [409, "duplicate_email", copy.duplicate],
    [422, "invalid_account_input", copy.validation],
    [500, "account_storage_error", copy.failure],
  ])("shows the correct message for status %s", async (status, detail, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail }, { status })),
    );
    fireEvent.click(fillSignup());
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(window.location.pathname).toBe("/signup");
  });

  it("opens the assistant for old documents links", async () => {
    window.history.replaceState(null, "", "/workspace?view=documents");
    render(<Platform />);
    expect(await screen.findByText("Test chat")).toBeInTheDocument();
  });
});
