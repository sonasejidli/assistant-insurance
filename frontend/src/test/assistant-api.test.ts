import { ui } from "@/lib/ui-text";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest, documentPath } from "@/lib/assistant-api";

afterEach(() => vi.unstubAllGlobals());

describe("assistant API", () => {
  it("sends requests through the same-origin proxy", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ answer: "Answer" }) });
    vi.stubGlobal("fetch", fetchMock);
    const options = { method: "POST", body: JSON.stringify({ question: "Insurance?" }) };
    await expect(apiRequest("/ask", options)).resolves.toEqual({ answer: "Answer" });
    expect(fetchMock).toHaveBeenCalledWith("/api/ask", options);
  });

  it("reports backend errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: "Service unavailable" }) }));
    await expect(apiRequest("/ask")).rejects.toThrow("Service unavailable");
  });

  it("explains when the assistant service is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
    await expect(apiRequest("/ask")).rejects.toThrow(ui.chat.serviceUnavailable);
  });

  it("only accepts document paths for source previews", () => {
    expect(documentPath("/documents/example.pdf/preview/0")).toBe("/api/documents/example.pdf/preview/0");
    expect(documentPath("https://example.com/documents/example.pdf")).toBeNull();
    expect(documentPath("//example.com/documents/example.pdf")).toBeNull();
  });
});
