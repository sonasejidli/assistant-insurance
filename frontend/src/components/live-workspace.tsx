import { ui } from "@/lib/ui-text";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { nanoid } from "nanoid";
import {
  ArrowUp,
  Copy,
  Menu,
  Moon,
  Plus,
  RotateCcw,
  ShieldCheck,
  Square,
  Sun,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Conversation, ConversationContent } from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import {
  documentPath,
  requestAnswer,
  type Answer,
  type Preview,
  type Source,
} from "@/lib/assistant-api";
import { uniqueWelcomeSuggestions } from "@/lib/welcome-suggestions";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

type Entry =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; text: string; result: Answer };

type PendingTurn = { id: string; controller: AbortController; before: Entry[]; draft: string };

type Thread = { id: number; messages: Entry[] };

const copy = ui.chat;

function sourceTitle(source: Source) {
  return source.law_name || source.document || source.doc || copy.source;
}

function sourceDetails(source: Source) {
  const article = source.article_number || source.article;
  const page = source.page_number ?? source.page;
  return [
    article && copy.article(article),
    source.clause && copy.clause(source.clause),
    page && copy.page(page),
  ]
    .filter(Boolean)
    .join(" · ");
}

function groupSources(sources: Source[]) {
  const groups = new Map<string, { source: Source; markers: Set<string> }>();
  for (const source of sources) {
    const passage = source.passage_id || source.chunk_id || source.url;
    const identity = JSON.stringify([
      source.document_id || source.doc || source.document,
      passage || source.id,
      source.article_number || source.article || "",
      source.clause || "",
    ]);
    const group = groups.get(identity);
    if (group) group.markers.add(source.id);
    else groups.set(identity, { source, markers: new Set([source.id]) });
  }
  return [...groups.values()];
}

function AnswerContent({
  entry,
  onOpen,
}: {
  entry: Extract<Entry, { role: "assistant" }>;
  onOpen: (source: Source) => void;
}) {
  const details = useRef<HTMLDetailsElement>(null);
  const cards = useRef(new Map<string, HTMLButtonElement>());
  const groups = groupSources(entry.result.verified_citations ?? entry.result.sources).map((group, index) => ({
    ...group,
    target: `${entry.id}-source-${index}`,
  }));
  const targets = new Map<string, string | null>();
  for (const group of groups) {
    for (const marker of group.markers) {
      targets.set(marker, targets.has(marker) ? null : group.target);
    }
  }
  const markdown = entry.text.replace(/\[(S[1-9]\d*)\]/g, (marker, id: string) => {
    const target = targets.get(id);
    return target ? `[\\[${id}\\]](#${target})` : marker;
  });

  function focusSource(target: string) {
    const card = cards.current.get(target);
    if (!card || !details.current) return;
    details.current.open = true;
    card.focus();
  }

  return (
    <>
      <MessageResponse
        translations={copy.markdown}
        className="chat-response"
        components={{
          a: ({ href, children }) => {
            const target = href?.slice(1);
            if (
              !href?.startsWith("#") ||
              !groups.some((group) => group.target === target) ||
              !target
            ) {
              return <span>{children}</span>;
            }
            return (
              <a
                href={href}
                className="font-medium underline underline-offset-2"
                onClick={(event) => {
                  event.preventDefault();
                  focusSource(target);
                }}
              >
                {children}
              </a>
            );
          },
        }}
      >
        {markdown}
      </MessageResponse>
      {groups.length > 0 && (
        <details className="message-sources" ref={details}>
          <summary>{copy.sources(groups.length)}</summary>
          {groups.map(({ source, markers, target }) => (
            <button
              key={target}
              id={target}
              ref={(node) => {
                if (node) cards.current.set(target, node);
                else cards.current.delete(target);
              }}
              type="button"
              className="source-card"
              onClick={() => onOpen(source)}
            >
              <strong>
                {[...markers].join(", ")} · {sourceTitle(source)}
              </strong>
              <span>{sourceDetails(source) || source.doc || source.document}</span>
            </button>
          ))}
        </details>
      )}
    </>
  );
}

function sourceExcerpt(result: Answer) {
  if (result.answer_status !== "withheld" && !result.delivery_status) return undefined;
  return result.retrieved_sources?.find((source) =>
    ["law_or_code", "government_resolution_or_regulation", "other_normative_act"].includes(source.source_type) &&
    source.text.trim() &&
    ((source.official_url && /^https?:\/\//i.test(source.official_url)) || (source.url && documentPath(source.url))),
  );
}

function presentExcerpt(source: Source) {
  const text = source.text.trim();
  const numbered = /^(\d+(?:[.-]\d+)*)(?:\.)?\s+(.+)$/s.exec(text);
  const provision = numbered && numbered[1] === source.clause ? numbered[1] : undefined;
  const passage = (provision && numbered ? numbered[2] : text).replace(/[;.]$/, "");
  const intoxication = /^sığorta hadisəsi sığorta olunanın əmək funksiyalarını icra edərkən (.+) təsirindən sərxoş vəziyyətdə olması halında baş verdikdə$/i.exec(passage.replace(/\s+/g, " "));
  const message = intoxication
    ? `Bu bənd sığorta olunan şəxs işini görərkən ${intoxication[1]} təsirindən sərxoş vəziyyətdə olduğu vaxt baş verən sığorta hadisəsinə aiddir.`
    : `${passage.charAt(0).toLocaleUpperCase("az")}${passage.slice(1)}.`;
  return `${message}${provision ? ` (${provision})` : ""}`;
}

function AssistantResponse({
  entry,
  onOpen,
}: {
  entry: Extract<Entry, { role: "assistant" }>;
  onOpen: (source: Source) => void;
}) {
  const excerpt = sourceExcerpt(entry.result);
  if (!excerpt) {
    if (entry.result.delivery_status) {
      return <p role="status" className="message-warning">{entry.result.delivery_message || copy.failure}</p>;
    }
    return <AnswerContent entry={entry} onOpen={onOpen} />;
  }
  const officialUrl = excerpt.official_url && /^https?:\/\//i.test(excerpt.official_url) ? excerpt.official_url : null;
  const previewUrl = excerpt.url && documentPath(excerpt.url);
  return (
    <section className="chat-response space-y-3">
      <p className="whitespace-pre-wrap">{presentExcerpt(excerpt)}</p>
      <p className="text-sm">
        <a
          className="underline underline-offset-2"
          href={officialUrl || previewUrl || undefined}
          target={officialUrl ? "_blank" : undefined}
          rel={officialUrl ? "noreferrer" : undefined}
          onClick={officialUrl ? undefined : (event) => { event.preventDefault(); onOpen(excerpt); }}
        >
          {sourceTitle(excerpt)}
        </a>
      </p>
    </section>
  );
}

export function LiveWorkspace({ onHome }: { onHome?: () => void }) {
  const [messages, setMessages] = useState<Entry[]>([]);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadId, setThreadId] = useState(0);
  const nextThreadId = useRef(1);
  const pendingRequest = useRef<PendingTurn | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const [input, setInput] = useState("");
  const draft = useRef("");
  const composing = useRef(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState<Record<string, "up" | "down">>({});
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<Source | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewStatus, setPreviewStatus] = useState<"loading" | "error" | null>(null);
  const previewRequest = useRef<AbortController | null>(null);
  const [sidebar, setSidebar] = useState(false);
  const [dark, setDark] = useState(
    () => window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ?? false,
  );
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(
    () => () => {
      pendingRequest.current?.controller.abort();
      previewRequest.current?.abort();
    },
    [],
  );

  useEffect(() => {
    bottom.current?.scrollIntoView?.({
      block: "end",
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches
        ? "instant"
        : "smooth",
    });
  }, [messages, loading]);

  useEffect(() => {
    composer.current?.focus();
  }, [threadId]);

  function cancelTurn() {
    const turn = pendingRequest.current;
    pendingRequest.current = null;
    turn?.controller.abort();
    setLoading(false);
    return turn;
  }

  function stop() {
    const turn = cancelTurn();
    if (turn) {
      setMessages(turn.before);
      updateInput(turn.draft);
      composer.current?.focus();
    }
  }

  function switchThread(id: number, entries: Entry[]) {
    const completed = cancelTurn()?.before ?? messages;
    closeSource();
    setThreads((previous) => {
      const others = previous.filter((thread) => thread.id !== threadId && thread.id !== id);
      return completed.length ? [{ id: threadId, messages: completed }, ...others] : others;
    });
    setThreadId(id);
    setMessages(entries);
    updateInput("");
    setError("");
    setFeedback({});
    setNotice("");
    setSidebar(false);
  }

  function updateInput(text: string) {
    draft.current = text;
    setInput(text);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.current.trim() || composing.current) return;
    void ask(draft.current);
  }

  function handleComposerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      composing.current
    )
      return;
    event.preventDefault();
    if (!event.repeat && !pendingRequest.current && draft.current.trim().length >= 2) {
      event.currentTarget.form?.requestSubmit();
    }
  }

  function settleTurn(id: string) {
    if (pendingRequest.current?.id !== id) return false;
    pendingRequest.current = null;
    setLoading(false);
    return true;
  }

  async function ask(text: string, previous = messages) {
    const question = text.trim();
    if (pendingRequest.current) return;
    if (question.length < 2 || question.length > 500) {
      setError(copy.length);
      return;
    }
    const turnId = nanoid();
    const next: Entry[] = [...previous, { id: `user-${turnId}`, role: "user", text: question }];
    const controller = new AbortController();
    const turn = { id: turnId, controller, before: messages, draft: question };
    pendingRequest.current = turn;
    setMessages(next);
    updateInput("");
    setError("");
    setNotice("");
    setLoading(true);
    try {
      const history = previous
        .filter((entry) => entry.role === "user")
        .slice(-5)
        .map((entry) => entry.text);
      const result = await requestAnswer({
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-Request-ID": turnId },
        body: JSON.stringify({ question, language: "auto", mode: "question", history }),
      });
      if (controller.signal.aborted || !settleTurn(turnId)) return;
      setMessages([
        ...next,
        {
          id: `assistant-${turnId}`,
          role: "assistant",
          text:
            result.intent === "out_of_scope"
              ? copy.outOfScope[result.language ?? "az"]
              : result.answer,
          result,
        },
      ]);
    } catch {
      if (!controller.signal.aborted && settleTurn(turnId)) {
        setMessages(turn.before);
        updateInput(turn.draft);
        setError(copy.failure);
      }
    }
  }

  async function copyAnswer(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(copy.copied);
    } catch {
      setNotice(copy.copyFailed);
    }
  }

  async function openSource(source: Source) {
    previewRequest.current?.abort();
    setSelected(source);
    setPreview(null);
    setPreviewStatus(null);
    const path = source.url && documentPath(source.url);
    if (!path) return;
    const controller = new AbortController();
    previewRequest.current = controller;
    setPreviewStatus("loading");
    try {
      const response = await fetch(path, { signal: controller.signal });
      if (!response.ok) throw new Error(copy.unavailableSource);
      const passage = (await response.json()) as Preview;
      if (!controller.signal.aborted) {
        setPreview(passage);
        setPreviewStatus(null);
      }
    } catch {
      if (!controller.signal.aborted) setPreviewStatus("error");
    }
  }

  function closeSource() {
    previewRequest.current?.abort();
    setSelected(null);
  }

  const originalUrl = preview?.pdf_url || preview?.original_url;
  const originalSection = originalUrl && documentPath(originalUrl);

  const lastQuestion = messages.map((entry) => entry.role).lastIndexOf("user");
  const latestAnswer = messages
    .map((entry) => entry.role === "assistant" && !!entry.result)
    .lastIndexOf(true);

  return (
    <div className={`workspace ${dark ? "dark" : ""}`}>
      <main className="center-panel">
        <header className="workspace-header">
          <div className="workspace-title">
            <Button
              variant="ghost"
              className="icon-action"
              aria-label={copy.history}
              aria-expanded={sidebar}
              aria-controls="chat-history"
              onClick={() => setSidebar(!sidebar)}
            >
              <Menu />
            </Button>
            <h1>{copy.heading}</h1>
          </div>
          <div className="workspace-actions">
            <Button
              variant="ghost"
              className="icon-action"
              aria-label={dark ? copy.light : copy.dark}
              onClick={() => setDark(!dark)}
            >
              {dark ? <Sun /> : <Moon />}
            </Button>
            <Button
              variant="outline"
              className="new-chat"
              onClick={() => switchThread(nextThreadId.current++, [])}
            >
              <Plus /> {copy.new}
            </Button>
          </div>
        </header>
        <div className="workspace-body">
          <aside id="chat-history" className="left-panel" hidden={!sidebar}>
            <h2>{copy.history}</h2>
            {threads.length === 0 && <p>{copy.noHistory}</p>}
            {threads.map((thread) => (
              <Button
                key={thread.id}
                variant="ghost"
                className="history-item"
                onClick={() => switchThread(thread.id, thread.messages)}
              >
                {thread.messages.find((entry) => entry.role === "user")?.text || copy.thread}
              </Button>
            ))}
            {onHome && (
              <Button variant="ghost" onClick={onHome}>
                {copy.home}
              </Button>
            )}
          </aside>
          <div className="chat-panel">
            {messages.length === 0 ? (
              <section className="chat-empty">
                <span className="chat-shield">
                  <ShieldCheck size={28} aria-hidden="true" />
                </span>
                <p className="chat-welcome" lang="az">
                  {copy.welcome}
                </p>
                <div className="suggestions">
                  {uniqueWelcomeSuggestions(copy.suggestions).map((question) => (
                    <Button type="button" key={question} variant="outline" onClick={() => void ask(question)}>
                      {question}
                    </Button>
                  ))}
                </div>
              </section>
            ) : (
              <Conversation className="chat-log" initial="instant" resize="instant">
                <ConversationContent className="chat-width transcript">
                  {messages.map((entry, index) => (
                    <Message
                      key={entry.id}
                      data-message-id={entry.id}
                      from={entry.role}
                      className="chat-message"
                      data-answer-status={
                        entry.role === "assistant"
                          ? entry.result.delivery_status ||
                            entry.result.answer_mode ||
                            entry.result.evidence_status ||
                            entry.result.intent
                          : undefined
                      }
                    >
                      {entry.role === "assistant" && (
                        <ShieldCheck className="message-avatar" size={20} aria-hidden="true" />
                      )}
                      <MessageContent className="chat-message-content">
                        {entry.role === "user" ? (
                          <span className="whitespace-pre-wrap">{entry.text}</span>
                        ) : (
                          <>
                            <AssistantResponse entry={entry} onOpen={(source) => void openSource(source)} />
                            {(entry.result?.warnings ?? []).map((warning) => (
                              <p key={warning} className="message-warning">
                                {warning}
                              </p>
                            ))}
                            {entry.result && (
                              <div className="message-actions" aria-label={copy.actions}>
                                {!entry.result.delivery_status && (
                                  <Button
                                    variant="ghost"
                                    className="icon-action"
                                    aria-label={copy.copy}
                                    title={copy.copy}
                                    onClick={() => {
                                      const excerpt = sourceExcerpt(entry.result);
                                      void copyAnswer(excerpt ? presentExcerpt(excerpt) : entry.text);
                                    }}
                                  >
                                    <Copy />
                                  </Button>
                                )}
                                {index === latestAnswer && index > lastQuestion && (
                                  <Button
                                    variant="ghost"
                                    className="icon-action"
                                    aria-label={copy.regenerate}
                                    title={copy.regenerate}
                                    disabled={loading}
                                    onClick={() => {
                                      setFeedback({});
                                      void ask(
                                        messages[lastQuestion].text,
                                        messages.slice(0, lastQuestion),
                                      );
                                    }}
                                  >
                                    <RotateCcw />
                                  </Button>
                                )}
                                {!entry.result.delivery_status && (
                                  <>
                                    <Button
                                      variant="ghost"
                                      className="icon-action"
                                      aria-label={copy.helpful}
                                      title={copy.helpful}
                                      aria-pressed={feedback[entry.id] === "up"}
                                      onClick={() => setFeedback({ ...feedback, [entry.id]: "up" })}
                                    >
                                      <ThumbsUp />
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      className="icon-action"
                                      aria-label={copy.unhelpful}
                                      title={copy.unhelpful}
                                      aria-pressed={feedback[entry.id] === "down"}
                                      onClick={() => setFeedback({ ...feedback, [entry.id]: "down" })}
                                    >
                                      <ThumbsDown />
                                    </Button>
                                  </>
                                )}
                              </div>
                            )}
                          </>
                        )}
                      </MessageContent>
                    </Message>
                  ))}
                  {loading && (
                    <div className="typing-indicator" role="status">
                      <span className="sr-only">{copy.waiting}</span>
                      <i />
                      <i />
                      <i />
                    </div>
                  )}
                  <div ref={bottom} />
                </ConversationContent>
              </Conversation>
            )}
            <div className="chat-width chat-composer">
              {notice && (
                <p className="chat-notice" role="status">
                  {notice}
                </p>
              )}
              {error && (
                <p role="alert" className="field-error">
                  {error}
                </p>
              )}
              <form className="composer w-full" onSubmit={submit}>
                <InputGroup className="overflow-hidden">
                  <InputGroupTextarea
                    ref={composer}
                    className="field-sizing-content max-h-48 min-h-16"
                    aria-label={copy.question}
                    placeholder={copy.placeholder}
                    value={input}
                    readOnly={loading}
                    onChange={(event) => updateInput(event.currentTarget.value)}
                    onKeyDown={handleComposerKey}
                    onCompositionStart={() => {
                      composing.current = true;
                    }}
                    onCompositionEnd={() => {
                      composing.current = false;
                    }}
                    maxLength={500}
                  />
                  <InputGroupAddon align="block-end" className="justify-between gap-1">
                    {loading ? (
                      <button
                        className="send-button"
                        type="button"
                        aria-label={copy.stop}
                        onClick={stop}
                      >
                        <Square size={16} />
                      </button>
                    ) : (
                      <InputGroupButton
                        type="submit"
                        variant="default"
                        size="icon-sm"
                        className="send-button"
                        aria-label={copy.send}
                        disabled={input.trim().length < 2}
                      >
                        <ArrowUp size={20} />
                      </InputGroupButton>
                    )}
                  </InputGroupAddon>
                </InputGroup>
              </form>
              <p className="chat-disclaimer" lang="en">
                {copy.disclaimer}
              </p>
            </div>
          </div>
        </div>
      </main>
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) closeSource();
        }}
      >
        {selected && (
          <DialogContent closeLabel={copy.close} className={`passage-dialog ${dark ? "dark" : ""}`}>
            <DialogTitle>{`${selected.id} · ${sourceTitle(selected)}`}</DialogTitle>
            <DialogDescription>
              {[
                selected.doc || selected.document,
                preview?.page &&
                  preview.page !== (selected.page_number ?? selected.page) &&
                  copy.page(preview.page),
                sourceDetails(selected),
              ]
                .filter(Boolean)
                .join(" · ")}
            </DialogDescription>
            {previewStatus === "loading" && (
              <div className="passage-skeleton" role="status">
                <span className="sr-only">{copy.loadingSource}</span>
              </div>
            )}
            {previewStatus === "error" && <p role="status">{copy.unavailableSource}</p>}
            <p className="whitespace-pre-wrap">{preview?.text || selected.text}</p>
            {originalSection && (
              <a
                className="text-link"
                href={originalSection}
                target="_blank"
                rel="noreferrer"
                title={preview?.page ? copy.pdfPage(preview.page) : copy.originalPdf}
              >
                {`${selected.id} · ${sourceTitle(selected)}`}
              </a>
            )}
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}
