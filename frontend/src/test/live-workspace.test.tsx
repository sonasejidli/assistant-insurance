import { StrictMode } from "react";
import { ui } from "@/lib/ui-text";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveWorkspace } from "@/components/live-workspace";
import { uniqueWelcomeSuggestions } from "@/lib/welcome-suggestions";

function reply(result: object) {
  return new Response(JSON.stringify(result), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function composer() {
  return screen.getByRole("textbox", { name: ui.chat.question });
}

async function send(message: string) {
  fireEvent.change(composer(), { target: { value: message } });
  await act(async () => {
    fireEvent.submit(composer().closest("form")!);
  });
}

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("live workspace", () => {
  it("shows an actual retrieved excerpt with a source link when the provider fails", async () => {
    const source = { id: "p1", law_name: "Retrieved Act", article: "20", clause: "20.0.2",
      text: "20.0.2. sığorta hadisəsi sığorta olunanın əmək funksiyalarını icra edərkən alkoqollu\niçkilərin təsirindən sərxoş\nvəziyyətdə olması halında baş verdikdə;",
      url: "/documents/act.pdf/preview/0",
      source_type: "law_or_code", legal_currency_verified: false };
    const fetcher = vi.fn()
      .mockResolvedValueOnce(reply({ answer: "", sources: [], warnings: [], delivery_status: "provider_timeout",
        delivery_message: "Service unavailable", retrieved_sources: [
          { ...source, id: "secondary", source_type: "textbook", text: "Secondary material" },
          source,
          { ...source, id: "p2", article: "15", text: "Another passage" },
        ] }))
      .mockResolvedValueOnce(reply({ answer: "No passages", sources: [], warnings: [], retrieved_sources: [] }))
      .mockResolvedValueOnce(reply({ text: "Actual excerpt", page: 1 }));
    vi.stubGlobal("fetch", fetcher);
    render(<LiveWorkspace />);
    await send("First question");
    await send("Second question");
    const turns = document.querySelectorAll<HTMLElement>(".chat-message.is-assistant");
    expect(turns).toHaveLength(2);
    const prose = "Bu bənd sığorta olunan şəxs işini görərkən alkoqollu içkilərin təsirindən sərxoş vəziyyətdə olduğu vaxt baş verən sığorta hadisəsinə aiddir. (20.0.2)";
    expect(within(turns[0]).getByText(prose)).toBeInTheDocument();
    expect(within(turns[0]).queryByText("Qanun mətnindən çıxarış")).not.toBeInTheDocument();
    expect(within(turns[0]).queryByText("Service unavailable")).not.toBeInTheDocument();
    expect(within(turns[0]).queryByText("Another passage")).not.toBeInTheDocument();
    expect(within(turns[1]).queryByText(prose)).not.toBeInTheDocument();
    const link = within(turns[0]).getByRole("link", { name: "Retrieved Act", exact: true });
    expect(link).toHaveAttribute("href", "/api/documents/act.pdf/preview/0");
    await act(async () => fireEvent.click(link));
    expect(fetcher).toHaveBeenLastCalledWith("/api/documents/act.pdf/preview/0", expect.anything());
  });

  it("deduplicates equivalent text across suggestion sources without merging distinct questions", () => {
    const first = "İş qəzası zamanı ziyanı kim ödəyir?";
    const distinct = "İş qəzası zamanı ziyan necə hesablanır?";
    expect(uniqueWelcomeSuggestions(
      [first, "  İŞ QƏZASI  ZAMANI ZİYANI KİM ÖDƏYİR  ?"],
      [first.normalize("NFD"), distinct],
    )).toEqual([first, distinct]);
  });

  it("keeps welcome suggestions unique across rerender and remount", () => {
    const expected = [
      "Avtomobil sahiblərinin icbari məsuliyyət sığortası hansı zərərləri əhatə edir?",
      "Sığorta iddiasını necə təqdim etməliyəm?",
      "İş qəzası zamanı ziyanı kim ödəyir?",
    ];
    const [original] = expected;
    const suggestions = () => [...document.querySelectorAll(".chat-empty .suggestions button")]
      .map((button) => button.textContent?.trim());
    ui.chat.suggestions.push(original.toLocaleUpperCase("az"));
    try {
      const tree = () => <StrictMode><LiveWorkspace /></StrictMode>;
      const workspace = render(tree());
      expect(suggestions()).toEqual(expected);
      workspace.rerender(tree());
      expect(suggestions()).toEqual(expected);
      workspace.unmount();
      render(tree());
      expect(suggestions()).toEqual(expected);
      expect(screen.queryByText(original.toLocaleUpperCase("az"))).not.toBeInTheDocument();
    } finally {
      ui.chat.suggestions.pop();
    }
  });

  it("shows only the final answer after internal retries and keeps an independent turn separate", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply({
        answer: "Verified final answer",
        sources: [],
        answer_mode: "FULL",
        diagnostics: [{ kind: "citation_validation_failed" }],
      }))
      .mockResolvedValueOnce(reply({
        answer: "",
        sources: [],
        delivery_status: "verification_failed",
        delivery_message: "Cavabı etibarlı şəkildə yoxlamaq mümkün olmadı.",
      }))
      .mockResolvedValueOnce(reply({ answer: "Independent answer", sources: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<LiveWorkspace />);
    const question = ui.chat.suggestions.at(-1)!;
    await act(async () => fireEvent.click(screen.getByRole("button", { name: question })));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText(question)).toHaveLength(1);
    expect(screen.getAllByText("Verified final answer")).toHaveLength(1);
    expect(screen.queryByText("citation_validation_failed")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: question })).not.toBeInTheDocument();
    await send("Könüllü tibbi sığortanı istədiyim vaxt ləğv edə bilərəmmi?");
    expect(screen.getAllByText("Cavabı etibarlı şəkildə yoxlamaq mümkün olmadı.")).toHaveLength(1);
    await send("Independent question");
    expect(screen.getAllByText("Independent answer")).toHaveLength(1);
    expect(container.querySelectorAll(".chat-message.is-assistant")).toHaveLength(3);
  });

  it("renders a cited cancellation partial as one direct final answer", async () => {
    const claim =
      "Sığortalı könüllü tibbi sığorta müqaviləsini səlahiyyətli orqanın müəyyən etdiyi qaydada ləğv edə bilər.";
    const qualification = "Bu bənd ləğvin istənilən vaxt mümkün olduğunu təsdiqləmir.";
    const fetchMock = vi.fn().mockResolvedValue(reply({
      answer: `${claim} [S1]\n\n${qualification}`,
      answer_mode: "PARTIAL",
      sources: [{ id: "S1", doc: "sığorts 4.pdf", clause: "6.1.1", text: "Müəyyən edilmiş qaydada ləğv etmək" }],
    }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<LiveWorkspace />);
    await send("Könüllü tibbi sığortanı istədiyim vaxt ləğv edə bilərəmmi?");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const answers = container.querySelectorAll(".chat-message.is-assistant");
    expect(answers).toHaveLength(1);
    expect(answers[0]).toHaveAttribute("data-answer-status", "PARTIAL");
    expect(answers[0]).toHaveTextContent(claim);
    expect(answers[0]).toHaveTextContent(qualification);
    expect(within(answers[0] as HTMLElement).getByRole("link", { name: "[S1]" })).toBeInTheDocument();
    expect(answers[0]).not.toHaveTextContent("Tapılan sənədlər bu suala tam cavab vermək üçün kifayət etmir.");
  });

  it("rejects non-final payloads and mismatched replies without leaking into the next turn", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply({ event: "citation_validation_failed" }))
      .mockResolvedValueOnce(new Response("data: {\"answer\":\"Unexpected\"}\n\n", {
        headers: { "Content-Type": "text/event-stream" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ answer: "Stale draft", sources: [] }), {
        headers: { "Content-Type": "application/json", "X-Request-ID": "older-turn" },
      }))
      .mockResolvedValueOnce(reply({ answer: "The authoritative reply", sources: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<LiveWorkspace />);
    for (const question of ["Invalid event", "Unexpected stream", "Stale reply"]) {
      await send(question);
      expect(await screen.findByText(ui.chat.failure)).toBeInTheDocument();
      expect(container.querySelectorAll(".chat-message.is-assistant")).toHaveLength(0);
    }
    await send("Independent question");
    expect(await screen.findByText("The authoritative reply")).toBeInTheDocument();
    expect(screen.queryByText(ui.chat.failure)).not.toBeInTheDocument();
    expect(container.querySelectorAll(".chat-message.is-assistant")).toHaveLength(1);
    expect(JSON.parse(fetchMock.mock.calls[3][1].body).history).toEqual([]);
  });

  it.each([
    ["verification_failed", "Cavabı etibarlı şəkildə yoxlamaq mümkün olmadı."],
    ["provider_rate_limit", "Cavab xidməti müvəqqəti əlçatan deyil. Bir qədər sonra yenidən cəhd edin."],
    ["provider_timeout", "Cavab xidməti vaxtında cavab vermədi. Yenidən cəhd edin."],
    ["provider_unavailable", "Cavab xidməti müvəqqəti işləmir. Bir qədər sonra yenidən cəhd edin."],
    ["internal_error", "Sorğunu emal etmək mümkün olmadı. Yenidən cəhd edin."],
  ])("shows %s as a status without answer text or source cards", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply({
      answer: "Unverified legal assertion [S1]",
      delivery_status: status,
      delivery_message: message,
      sources: [{ id: "S1", doc: "law.pdf", text: "Unverified passage" }],
    })));
    render(<LiveWorkspace />);
    await send("İcbari sığorta nəyi əhatə edir?");
    expect(await screen.findByText(message)).toHaveAttribute("role", "status");
    expect(screen.queryByText(/Unverified legal assertion|Unverified passage/)).not.toBeInTheDocument();
    expect(screen.queryByText(ui.chat.sources(1))).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: ui.chat.copy })).not.toBeInTheDocument();
  });

  it("shows the assistant without documents, language, or analysis controls", () => {
    render(<LiveWorkspace />);
    expect(composer()).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^documents$/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^language$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^analysis$/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: ui.chat.history })).toBeInTheDocument();
  });

  it("shows one welcome synchronously through StrictMode remount checks without asking the server", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(
      <StrictMode>
        <LiveWorkspace />
      </StrictMode>,
    );
    expect(composer()).toHaveFocus();
    expect(screen.getAllByText(ui.chat.welcome)).toHaveLength(1);
    rerender(
      <StrictMode>
        <LiveWorkspace />
      </StrictMode>,
    );
    expect(screen.getAllByText(ui.chat.welcome)).toHaveLength(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("routes Enter through one submit and consumes the draft and response once", async () => {
    const question = "Hansı xidmətlər üçün poliklinikadan göndəriş almalıyam?";
    const payload = {
      answer: "Long scope response",
      intent: "out_of_scope",
      language: "az",
      sources: [],
      follow_up_messages: ["Extra greeting"],
      quick_replies: [{ label: "Tibbi sığorta", question: "Tibbi sığorta nədir?" }],
    };
    let deliver!: (response: Response) => void;
    const fetchMock = vi.fn(
      (_url: string, _options: RequestInit) =>
        new Promise<Response>((resolve) => {
          deliver = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <StrictMode>
        <LiveWorkspace />
      </StrictMode>,
    );
    const form = composer().closest("form")!;
    const submits = vi.fn();
    form.addEventListener("submit", submits);
    fireEvent.change(composer(), { target: { value: question } });
    const submitButton = screen.getByRole("button", { name: ui.chat.send });
    const buttonClick = vi.fn();
    submitButton.addEventListener("click", buttonClick);
    fireEvent.keyDown(composer(), { key: "Enter", repeat: true });
    fireEvent.keyDown(composer(), { key: "Enter", shiftKey: true });
    expect(submits).not.toHaveBeenCalled();
    fireEvent.keyDown(composer(), { key: "Enter" });
    expect(submits).toHaveBeenCalledTimes(1);
    expect(buttonClick).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText(question)).toHaveLength(1);
    fireEvent.submit(form);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const requestId = new Headers(fetchMock.mock.calls[0][1].headers).get("X-Request-ID");
    expect(requestId).toBeTruthy();
    expect(container.querySelector(".is-user")).toHaveAttribute(
      "data-message-id",
      `user-${requestId}`,
    );
    await act(async () => {
      deliver(reply(payload));
      deliver(reply(payload));
    });
    expect(screen.getAllByText(ui.chat.outOfScope.az)).toHaveLength(1);
    expect(container.querySelector(".is-assistant")).toHaveAttribute(
      "data-message-id",
      `assistant-${requestId}`,
    );
    expect(screen.queryByRole("button", { name: "Tibbi sığorta" })).not.toBeInTheDocument();
    fireEvent.submit(form);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("adds exactly one answer per question and sends prior user questions as context", async () => {
    const fetchMock = vi.fn(async (_url: string, _options: RequestInit) =>
      reply({
        answer: "Example answer",
        sources: [],
        warnings: [],
        follow_up_messages: ["Automatic greeting"],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<LiveWorkspace />);

    const question = ui.chat.suggestions[0];
    await act(async () => fireEvent.click(screen.getByRole("button", { name: question })));
    expect(screen.getAllByText("Example answer")).toHaveLength(1);
    expect(screen.queryByText("Automatic greeting")).not.toBeInTheDocument();
    expect(screen.queryByText(ui.chat.welcome)).not.toBeInTheDocument();

    await send("What are the exceptions?");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toMatchObject({
      question: "What are the exceptions?",
      history: [question],
    });
    expect(screen.getAllByText("Example answer")).toHaveLength(2);
    expect(screen.getAllByText(question)).toHaveLength(1);
    expect(screen.getAllByText("What are the exceptions?")).toHaveLength(1);
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("X-Request-ID")).not.toBe(
      new Headers(fetchMock.mock.calls[1][1].headers).get("X-Request-ID"),
    );
    expect(screen.queryByText(ui.chat.waiting)).not.toBeInTheDocument();
  });

  it("blocks duplicate submits and keeps a stale reply from ending a new chat's loading state", async () => {
    const finish: Array<(response: Response) => void> = [];
    const fetchMock = vi.fn(
      (_url: string, _options: RequestInit) =>
        new Promise<Response>((resolve) => finish.push(resolve)),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<LiveWorkspace />);

    await send("First question");
    expect(screen.getByText("First question")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(ui.chat.waiting);
    await send("Duplicate submit");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: ui.chat.new }));
    expect(fetchMock.mock.calls[0][1].signal?.aborted).toBe(true);
    expect(screen.getAllByText(ui.chat.welcome)).toHaveLength(1);
    expect(composer()).toHaveFocus();
    expect(screen.queryByText("First question")).not.toBeInTheDocument();

    await send("Second question");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string).history).toEqual([]);
    await act(async () => finish[0](reply({ answer: "Late answer", sources: [] })));
    expect(screen.queryByText("Late answer")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(ui.chat.waiting);
    await act(async () => finish[1](reply({ answer: "Current answer", sources: [] })));
    expect(screen.getByText("Current answer")).toBeInTheDocument();
    expect(screen.queryByText(ui.chat.waiting)).not.toBeInTheDocument();
  });

  it("stops an unfinished turn and restores completed history when reopening a chat", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply({ answer: "Saved answer", sources: [] }))
      .mockImplementationOnce(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    render(<LiveWorkspace />);

    await send("Saved question");
    await send("Unfinished question");
    fireEvent.click(screen.getByRole("button", { name: ui.chat.stop }));
    expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(true);
    expect(composer()).toHaveValue("Unfinished question");
    expect(screen.queryByText(ui.chat.waiting)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: ui.chat.new }));
    fireEvent.click(screen.getByRole("button", { name: ui.chat.history }));
    fireEvent.click(screen.getByRole("button", { name: "Saved question" }));
    expect(screen.getByText("Saved answer")).toBeInTheDocument();
    expect(screen.queryByText("Unfinished question")).not.toBeInTheDocument();
    expect(screen.queryByText(ui.chat.welcome)).not.toBeInTheDocument();
  });

  it("renders one compact scope notice without adding the API's suggestions", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(reply({ answer: "Legal answer", sources: [] }))
        .mockResolvedValueOnce(
          reply({
            answer:
              "Bu köməkçi yalnız bazada olan Azərbaycan sığorta qanunvericiliyi ilə bağlı sualları cavablandırır. Aşağıdakı nümunələrdən birini soruşa bilərsiniz:",
            intent: "out_of_scope",
            language: "az",
            sources: [],
            quick_replies: [
              { label: "Tibbi sığorta", question: "Tibbi sığorta nədir?" },
              { label: "İş qəzası", question: "İş qəzası nədir?" },
            ],
            follow_up_messages: ["Unrequested follow-up"],
          }),
        ),
    );
    render(<LiveWorkspace />);
    await send("İcbari sığorta nədir?");
    await send("Sabah hava necə olacaq?");
    expect(screen.getAllByText("Sabah hava necə olacaq?")).toHaveLength(1);
    expect(screen.getAllByText("Legal answer")).toHaveLength(1);
    expect(screen.getAllByText(ui.chat.outOfScope.az)).toHaveLength(1);
    expect(screen.queryByText("Unrequested follow-up")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tibbi sığorta" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "İş qəzası" })).not.toBeInTheDocument();
    expect(screen.queryByText(ui.chat.welcome)).not.toBeInTheDocument();
  });

  it("groups repeated markers by passage and points each inline link to its own source card", async () => {
    const firstSource = {
      id: "S1",
      doc: "law.pdf",
      document_id: "law-v1",
      chunk_id: "passage-0",
      law_name: "İcbari sığortalar haqqında",
      article: "13",
      clause: "13.5",
      text: "Excerpt",
      url: "/documents/law.pdf/preview/0",
    };
    const secondSource = {
      ...firstSource,
      id: "S2",
      chunk_id: "passage-1",
      clause: "13.6",
      text: "Another excerpt",
      url: "/documents/law.pdf/preview/1",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        reply({
          answer:
            "Insurance protects property interests [S1]. Same passage [S3]. Different provision [S2]. Unmatched [S9].",
          warnings: [],
          sources: [firstSource, secondSource, { ...firstSource }, { ...firstSource, id: "S3" }],
        }),
      )
      .mockResolvedValueOnce(
        reply({ text: "Cited passage", page: 2, pdf_url: "/documents/law.pdf/pdf#page=2" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<LiveWorkspace />);
    await send("What is insurance?");

    const section = screen.getByText(ui.chat.sources(2)).closest("details")!;
    expect(section).not.toHaveAttribute("open");
    const first = screen.getByRole("link", { name: "[S1]" });
    const alias = screen.getByRole("link", { name: "[S3]" });
    const second = screen.getByRole("link", { name: "[S2]" });
    expect(first.getAttribute("href")).toBe(alias.getAttribute("href"));
    expect(first.getAttribute("href")).not.toBe(second.getAttribute("href"));
    expect(screen.queryByRole("link", { name: "[S9]" })).not.toBeInTheDocument();
    expect(screen.getByText(/Unmatched/)).toHaveTextContent("[S9]");
    fireEvent.click(alias);
    expect(section).toHaveAttribute("open");
    const cards = within(section).getAllByRole("button");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveFocus();
    expect(cards[0]).toHaveTextContent("S1, S3 · İcbari sığortalar haqqında");
    expect(cards[0]).toHaveTextContent("Maddə 13 · Bənd 13.5");
    expect(cards[1]).toHaveTextContent("Maddə 13 · Bənd 13.6");
    expect(first).toHaveAttribute("href", `#${cards[0].id}`);
    expect(second).toHaveAttribute("href", `#${cards[1].id}`);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => fireEvent.click(cards[0]));
    const passage = screen.getByRole("dialog");
    expect(passage).toHaveTextContent("Cited passage");
    expect(within(passage).getByRole("link")).toHaveAttribute(
      "href",
      "/api/documents/law.pdf/pdf#page=2",
    );
    expect(fetchMock).toHaveBeenLastCalledWith("/api/documents/law.pdf/preview/0", {
      signal: expect.any(AbortSignal),
    });
  });
});
