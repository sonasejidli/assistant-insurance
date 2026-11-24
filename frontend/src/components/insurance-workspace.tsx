import { useState, useEffect, useRef, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import {
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  BrainCircuit,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  CircleHelp,
  Copy,
  FileText,
  Folder,
  History,
  Layers,
  LayoutDashboard,
  ListFilter,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Paperclip,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  ThumbsDown,
  ThumbsUp,
  X,
  AlertTriangle,
  Download,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageContent,
  MessageResponse,
  MessageActions,
  MessageAction,
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputButton,
  usePromptInputAttachments,
} from "@/components/ai-elements/prompt-input";
import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
} from "recharts";
import {
  sources,
  initialQuestion,
  initialAnswer,
  filterSources,
  simulatedAnswer,
  type LegalSource,
} from "@/lib/insurance-data";
import logo from "@/assets/insurance-mark.png";

type View =
  "assistant" | "dashboard" | "knowledge" | "documents" | "evaluation" | "analytics" | "settings";
const nav = [
  { name: "AI Assistant", path: "/" as const, icon: MessageSquare, view: "assistant" },
  { name: "Knowledge Base", path: "/knowledge-base" as const, icon: BookOpen, view: "knowledge" },
  { name: "Documents", path: "/documents" as const, icon: FileText, view: "documents" },
  { name: "Evaluation", path: "/evaluation" as const, icon: ShieldCheck, view: "evaluation" },
  { name: "Analytics", path: "/analytics" as const, icon: ChartNoAxesCombined, view: "analytics" },
  { name: "Settings", path: "/settings" as const, icon: Settings, view: "settings" },
];
const history = [
  "İcbari sığorta üzrə öhdəliklər",
  "Sığorta ödənişindən imtina halları",
  "Avtomobil sığortası və zərər",
  "Müqavilənin ləğvi şərtləri",
];
const titles: Record<View, string> = {
  assistant: "AI Assistant",
  dashboard: "Project overview",
  knowledge: "Knowledge Base",
  documents: "Documents",
  evaluation: "Evaluation",
  analytics: "Analytics",
  settings: "Settings",
};
function IconButton({
  label,
  children,
  onClick,
}: {
  label: string;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label} onClick={onClick}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
function Choice({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className="w-auto min-w-28 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">All {label.toLowerCase()}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            {o}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
function Attachments() {
  const a = usePromptInputAttachments();
  return (
    <div className="flex min-w-0 items-center gap-2">
      <PromptInputButton tooltip="Attach document" onClick={() => a.openFileDialog()}>
        <Paperclip />
      </PromptInputButton>
      {a.files.map((f) => (
        <span key={f.id} className="flex max-w-44 items-center gap-1 truncate text-xs">
          <FileText className="size-3" />
          {f.filename}
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label="Remove attachment"
            onClick={() => a.remove(f.id)}
          >
            <X />
          </Button>
        </span>
      ))}
    </div>
  );
}
function Highlight({ text, query }: { text: string; query: string }) {
  if (!query.trim()) return <>{text}</>;
  const at = text.toLocaleLowerCase("az").indexOf(query.toLocaleLowerCase("az"));
  return at < 0 ? (
    <>{text}</>
  ) : (
    <>
      {text.slice(0, at)}
      <mark className="bg-accent text-accent-foreground">{text.slice(at, at + query.length)}</mark>
      {text.slice(at + query.length)}
    </>
  );
}

export function InsuranceWorkspace({ view = "assistant" }: { view?: View }) {
  const [collapsed, setCollapsed] = useState(false);
  const [right, setRight] = useState(true);
  const [project, setProject] = useState("Azerbaijan Insurance Law");
  const [projects, setProjects] = useState([
    "Azerbaijan Insurance Law",
    "Motor Insurance Research",
  ]);
  const [newProject, setNewProject] = useState(false);
  const [name, setName] = useState("");
  const [historySearch, setHistorySearch] = useState("");
  const [activeHistory, setActiveHistory] = useState(history[0]);
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([
    { role: "user", text: initialQuestion },
    { role: "assistant", text: initialAnswer },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [feedback, setFeedback] = useState<Record<number, string>>({});
  const [mode, setMode] = useState("Hybrid");
  const [preview, setPreview] = useState<LegalSource | null>(null);
  const [page, setPage] = useState(12);
  const [docVersion, setDocVersion] = useState("2024");
  const [query, setQuery] = useState("");
  const [insurance, setInsurance] = useState("all");
  const [category, setCategory] = useState("all");
  const [language, setLanguage] = useState("all");
  const [version, setVersion] = useState("all");
  const [sort, setSort] = useState("relevance");
  const [showFilters, setShowFilters] = useState(true);
  const [evaluation, setEvaluation] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [citations, setCitations] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (window.innerWidth < 1100) setRight(false);
    if (window.innerWidth < 640) setCollapsed(true);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);
  useEffect(() => {
    if (notice) {
      const t = setTimeout(() => setNotice(""), 3500);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [notice]);
  const openDoc = (s: LegalSource) => {
    setPreview(s);
    setPage(s.page);
    setDocVersion(s.version);
  };
  const answer = (text: string, regenerate = false) => {
    if (loading || !text.trim()) return;
    if (!regenerate) setMessages((m) => [...m, { role: "user", text }]);
    else setMessages((m) => m.slice(0, -1));
    setLoading(true);
    setInput("");
    timer.current = setTimeout(() => {
      setMessages((m) => [...m, { role: "assistant", text: simulatedAnswer(text) }]);
      setLoading(false);
    }, 1300);
  };
  const results = filterSources(query, insurance, category, language, version).sort((a, b) =>
    sort === "date" ? b.date.localeCompare(a.date) : b.relevance - a.relevance,
  );
  const startChat = () => {
    setMessages([]);
    setActiveHistory("New conversation");
    setInput("");
  };
  return (
    <TooltipProvider>
      <div className="workspace">
        <aside className={`left-panel ${collapsed ? "collapsed" : ""}`}>
          <div
            className={`flex h-[72px] shrink-0 items-center ${collapsed ? "justify-center" : "gap-2.5 px-5"}`}
          >
            <img src={logo} alt="Insurance Intelligence" className="size-8 object-contain" />
            {!collapsed && (
              <div className="text-sm font-semibold leading-4">
                Insurance
                <br />
                <span className="font-normal text-muted-foreground">Intelligence</span>
              </div>
            )}
          </div>
          {!collapsed && (
            <div className="px-3">
              <div className="rounded-md border border-border bg-card p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="section-label">Workspace</span>
                  <span className="text-[9px] text-muted-foreground">PRO</span>
                </div>
                <Select value={project} onValueChange={setProject}>
                  <SelectTrigger
                    className="h-auto border-0 p-0 text-xs shadow-none"
                    aria-label="Project selector"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                variant="ghost"
                className="mt-2 w-full justify-start text-xs text-muted-foreground"
                onClick={() => setNewProject(true)}
              >
                <Plus />
                New project
              </Button>
            </div>
          )}
          <nav className={`mt-5 space-y-1 ${collapsed ? "px-2" : "px-3"}`}>
            {nav.map((n) => (
              <Tooltip key={n.name}>
                <TooltipTrigger asChild>
                  <Button
                    asChild
                    variant="ghost"
                    className={`nav-item ${view === n.view ? "active" : ""} ${collapsed ? "justify-center px-0" : ""}`}
                  >
                    <Link
                      to={n.path}
                      onClick={() => {
                        if (window.innerWidth < 640) setCollapsed(true);
                      }}
                    >
                      <n.icon />
                      {!collapsed && n.name}
                      {!collapsed && n.view === "knowledge" && (
                        <span className="ml-auto text-[10px]">24</span>
                      )}
                    </Link>
                  </Button>
                </TooltipTrigger>
                {collapsed && <TooltipContent side="right">{n.name}</TooltipContent>}
              </Tooltip>
            ))}
          </nav>
          {!collapsed && (
            <>
              <div className="mt-7 px-5">
                <div className="flex items-center justify-between">
                  <span className="section-label">Projects</span>
                  <IconButton label="New project" onClick={() => setNewProject(true)}>
                    <Plus className="size-3.5" />
                  </IconButton>
                </div>
                {projects.map((p) => (
                  <Button
                    key={p}
                    variant="ghost"
                    className="h-8 w-full justify-start truncate px-0 text-[11px] text-muted-foreground"
                    onClick={() => setProject(p)}
                  >
                    <Folder className="size-3.5" />
                    <span className="truncate">{p}</span>
                  </Button>
                ))}
              </div>
              <div className="mt-6 flex min-h-0 flex-1 flex-col px-3">
                <div className="flex items-center justify-between px-2">
                  <span className="section-label">Conversations</span>
                  <IconButton label="New conversation" onClick={startChat}>
                    <Plus className="size-3.5" />
                  </IconButton>
                </div>
                <div className="relative mt-2">
                  <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
                  <Input
                    aria-label="Search conversations"
                    placeholder="Search conversations"
                    value={historySearch}
                    onChange={(e) => setHistorySearch(e.target.value)}
                    className="h-8 border-0 bg-muted pl-8 text-[11px]"
                  />
                </div>
                <div className="mt-5 px-2 text-[10px] text-muted-foreground">Today</div>
                <div className="mt-2 space-y-1 overflow-auto">
                  {history
                    .filter((h) => h.toLowerCase().includes(historySearch.toLowerCase()))
                    .map((h, i) => (
                      <Button
                        key={h}
                        variant="ghost"
                        className={`h-9 w-full justify-start px-2 text-[11px] ${activeHistory === h ? "bg-muted text-foreground" : "text-muted-foreground"}`}
                        onClick={() => {
                          setActiveHistory(h);
                          setMessages([
                            { role: "user", text: i === 0 ? initialQuestion : h },
                            { role: "assistant", text: initialAnswer },
                          ]);
                        }}
                      >
                        <MessageSquare className="size-3.5" />
                        <span className="truncate">{h}</span>
                      </Button>
                    ))}
                  {historySearch &&
                    !history.some((h) => h.toLowerCase().includes(historySearch.toLowerCase())) && (
                      <p className="p-3 text-xs text-muted-foreground">No conversations found</p>
                    )}
                </div>
              </div>
            </>
          )}
          <div className="mt-auto border-t border-border p-3">
            {!collapsed && (
              <div className="mb-3 flex items-center gap-2 px-1">
                <span className="size-1.5 rounded-full bg-success" />
                <span className="text-[10px] text-muted-foreground">All systems operational</span>
                <span className="ml-auto rounded border border-border px-1.5 text-[9px]">DEMO</span>
              </div>
            )}
            <div className="flex items-center gap-2">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-secondary text-xs font-medium">
                AM
              </div>
              {!collapsed && (
                <div className="flex-1">
                  <div className="text-xs">Aysel Məmmədova</div>
                  <div className="text-[10px] text-muted-foreground">Legal researcher</div>
                </div>
              )}
              <IconButton
                label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                onClick={() => setCollapsed(!collapsed)}
              >
                {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
              </IconButton>
            </div>
          </div>
        </aside>
        <main className="center-panel">
          <header className="workspace-header">
            <div className="flex min-w-0 items-center gap-3">
              {collapsed && (
                <IconButton label="Open navigation" onClick={() => setCollapsed(false)}>
                  <PanelLeftOpen />
                </IconButton>
              )}
              <div>
                <div className="flex items-center gap-2 text-sm font-medium">
                  <span>{titles[view]}</span>
                  {view === "assistant" && (
                    <span className="rounded border border-border px-1.5 py-0.5 text-[9px] font-normal text-muted-foreground">
                      RAG
                    </span>
                  )}
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <Folder className="size-3" />
                  <span className="max-w-40 truncate">{project}</span>
                  <ChevronRight className="size-3" />
                  <span className="hidden sm:inline">Insurance legislation</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {view === "assistant" && (
                <>
                  <span className="hidden items-center gap-1.5 text-[10px] text-muted-foreground xl:flex">
                    <span className="size-1.5 rounded-full bg-success" />
                    Knowledge connected
                  </span>
                  <IconButton label="New conversation" onClick={startChat}>
                    <Plus />
                  </IconButton>
                  <IconButton
                    label={right ? "Hide sources" : "Show sources"}
                    onClick={() => setRight(!right)}
                  >
                    {right ? <PanelRightClose /> : <PanelRightOpen />}
                  </IconButton>
                </>
              )}
              {view !== "assistant" && (
                <Button variant="outline" size="sm" asChild>
                  <Link to="/dashboard">
                    <LayoutDashboard />
                    Overview
                  </Link>
                </Button>
              )}
            </div>
          </header>
          {view === "assistant" ? (
            <>
              <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-5 text-[10px] text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Layers className="size-3.5" />
                  Insurance legislation
                  <span className="rounded bg-muted px-1.5 py-0.5">24 documents</span>
                </div>
                <Select value={mode} onValueChange={setMode}>
                  <SelectTrigger
                    aria-label="Retrieval mode"
                    className="h-6 w-auto gap-2 border-0 p-0 text-[10px] shadow-none"
                  >
                    <SlidersHorizontal className="size-3" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["Hybrid", "Dense", "Keyword"].map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Conversation className="min-h-0 flex-1">
                <ConversationContent className="chat-width gap-7 px-5 py-8 lg:px-8">
                  {messages.length > 0 && (
                    <div className="mb-1 flex items-center justify-center gap-3 text-[10px] text-muted-foreground">
                      <span className="h-px w-10 bg-border" />
                      Today, November 17
                      <span className="h-px w-10 bg-border" />
                    </div>
                  )}
                  {messages.length === 0 && (
                    <div className="py-24 text-center">
                      <img
                        src={logo}
                        className="mx-auto mb-5 size-14"
                        alt="Insurance Intelligence"
                      />
                      <h1 className="text-xl font-semibold">Insurance Intelligence</h1>
                      <p className="mt-2 text-sm text-muted-foreground">Azerbaijan Insurance Law</p>
                    </div>
                  )}
                  {messages.map((m, i) => (
                    <Message key={i} from={m.role} className="max-w-full fade-in">
                      {m.role === "user" ? (
                        <>
                          <div className="mb-1 flex justify-end gap-2 text-[10px] text-muted-foreground">
                            You<span>09:12</span>
                          </div>
                          <MessageContent className="text-[13px] leading-6">
                            {m.text}
                          </MessageContent>
                        </>
                      ) : (
                        <>
                          <div className="mb-2 flex items-center gap-2">
                            <img src={logo} className="size-6" alt="" />
                            <span className="text-xs font-medium">Insurance Intelligence</span>
                            <span className="rounded bg-accent px-1.5 py-0.5 text-[9px] text-accent-foreground">
                              Assistant
                            </span>
                            <span className="ml-auto text-[10px] text-muted-foreground">09:12</span>
                          </div>
                          <MessageContent className="w-full">
                            <MessageResponse className="chat-response">{m.text}</MessageResponse>
                          </MessageContent>
                          {citations && m.text === initialAnswer && (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {sources.slice(0, 3).map((s) => (
                                <Button
                                  key={s.id}
                                  size="sm"
                                  variant="outline"
                                  className="h-7 gap-1.5 px-2 text-[10px] text-muted-foreground"
                                  onClick={() => openDoc(s)}
                                >
                                  <span className="text-primary">{s.id}</span>
                                  <FileText className="size-3" />
                                  {s.article}
                                  <ArrowUpRight className="size-3" />
                                </Button>
                              ))}
                            </div>
                          )}
                          <div className="mt-2 flex items-start gap-2 rounded-md border border-warning/15 bg-warning/5 p-3 text-[10px] leading-5 text-muted-foreground">
                            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
                            <span>
                              Sintetik nümayiş məlumatlarıdır. Təsdiqlənmiş hüquqi məlumat və ya
                              hüquqi məsləhət deyil.
                            </span>
                          </div>
                          <MessageActions className="mt-1 text-muted-foreground">
                            <MessageAction
                              tooltip="Copy response"
                              onClick={() => {
                                navigator.clipboard.writeText(m.text).then(
                                  () => setNotice("Response copied"),
                                  () => setNotice("Unable to copy response"),
                                );
                              }}
                            >
                              <Copy />
                            </MessageAction>
                            <MessageAction
                              tooltip="Regenerate response"
                              disabled={loading || i !== messages.length - 1}
                              onClick={() => answer(messages[i - 1]?.text || initialQuestion, true)}
                            >
                              <RefreshCw />
                            </MessageAction>
                            <span className="mx-1 h-3 w-px bg-border" />
                            <MessageAction
                              tooltip="Helpful"
                              className={feedback[i] === "up" ? "text-success" : ""}
                              onClick={() => setFeedback({ ...feedback, [i]: "up" })}
                            >
                              <ThumbsUp />
                            </MessageAction>
                            <MessageAction
                              tooltip="Not helpful"
                              className={feedback[i] === "down" ? "text-warning" : ""}
                              onClick={() => setFeedback({ ...feedback, [i]: "down" })}
                            >
                              <ThumbsDown />
                            </MessageAction>
                            <span className="ml-auto text-[10px]">
                              3 sources · simulated response
                            </span>
                          </MessageActions>
                        </>
                      )}
                    </Message>
                  ))}
                  {loading && (
                    <div className="flex items-center gap-3 py-3">
                      <img src={logo} className="size-6" alt="" />
                      <Shimmer>Searching demonstration sources…</Shimmer>
                    </div>
                  )}
                </ConversationContent>
                <ConversationScrollButton />
              </Conversation>
              <div className="chat-width shrink-0 px-5 pb-4 pt-3 lg:px-8">
                <div className="mb-3 flex flex-wrap gap-2">
                  {["Sığorta ödənişi müddətləri", "İmtina halları hansılardır?"].map((s) => (
                    <Button
                      key={s}
                      variant="outline"
                      size="sm"
                      className="h-7 rounded-full px-3 text-[10px] text-muted-foreground"
                      disabled={loading}
                      onClick={() => answer(s)}
                    >
                      {s}
                      <ArrowUpRight className="size-3" />
                    </Button>
                  ))}
                </div>
                <PromptInput
                  className="composer"
                  onSubmit={({ text, files }) => {
                    if (files.length && !text.trim())
                      answer("Əlavə edilmiş sığorta sənədini izah et");
                    else answer(text);
                  }}
                >
                  <PromptInputTextarea
                    aria-label="Ask an insurance question"
                    placeholder="Sığorta qanunvericiliyi haqqında sual verin…"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    disabled={loading}
                  />
                  <PromptInputFooter>
                    <Attachments />
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-muted-foreground">
                        AZ <ChevronDown className="inline size-3" />
                      </span>
                      <PromptInputSubmit
                        disabled={!input.trim() && !loading}
                        status={loading ? "submitted" : "ready"}
                        onStop={() => {
                          if (timer.current) clearTimeout(timer.current);
                          setLoading(false);
                        }}
                      >
                        {!loading && <ArrowUp />}
                      </PromptInputSubmit>
                    </div>
                  </PromptInputFooter>
                </PromptInput>
                <div className="mt-2.5 flex items-center justify-center gap-1.5 text-center text-[9px] text-muted-foreground">
                  <ShieldCheck className="size-3" />
                  Demo workspace · Synthetic data, not verified legal information
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 overflow-auto p-6 lg:p-8">
              <div className="mb-7 flex items-end justify-between gap-4">
                <div>
                  <span className="section-label">{project}</span>
                  <h1 className="mt-2 text-2xl font-semibold">{titles[view]}</h1>
                </div>
                <span className="rounded border border-warning/20 bg-warning/5 px-2 py-1 text-[10px] text-warning">
                  Demonstration data
                </span>
              </div>
              {view === "dashboard" && (
                <>
                  <Stats />
                  <div className="mt-8 flex items-center justify-between">
                    <h2 className="text-sm font-medium">Recent documents</h2>
                    <Button variant="ghost" size="sm" asChild>
                      <Link to="/documents">
                        View all
                        <ArrowUpRight />
                      </Link>
                    </Button>
                  </div>
                  <DocumentRows items={sources} onOpen={openDoc} />
                  <div className="mt-7 border-t border-border pt-5 text-xs text-muted-foreground">
                    Last indexing: 17 November 2026, 08:45 ·{" "}
                    <span className="text-success">Completed</span>
                  </div>
                </>
              )}
              {(view === "knowledge" || view === "documents") && (
                <>
                  <div className="flex gap-3">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-3 size-4 text-muted-foreground" />
                      <Input
                        className="pl-10"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        aria-label="Search legislation"
                        placeholder="Search by question, law number, or article…"
                      />
                    </div>
                    <IconButton label="Toggle filters" onClick={() => setShowFilters(!showFilters)}>
                      <ListFilter />
                    </IconButton>
                  </div>
                  {showFilters && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Choice
                        label="Insurance types"
                        value={insurance}
                        onChange={setInsurance}
                        options={["İcbari", "Könüllü", "Ümumi"]}
                      />
                      <Choice
                        label="Categories"
                        value={category}
                        onChange={setCategory}
                        options={["Qanun", "Qaydalar"]}
                      />
                      <Choice
                        label="Languages"
                        value={language}
                        onChange={setLanguage}
                        options={["AZ", "EN"]}
                      />
                      <Choice
                        label="Versions"
                        value={version}
                        onChange={setVersion}
                        options={["2024", "2023"]}
                      />
                      <Select value={sort} onValueChange={setSort}>
                        <SelectTrigger className="w-36 text-xs" aria-label="Sort documents">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="relevance">Relevance</SelectItem>
                          <SelectItem value="date">Document date</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  <div className="my-5 text-xs text-muted-foreground">
                    {results.length} {view === "knowledge" ? "retrieved passages" : "documents"}
                  </div>
                  {results.length === 0 ? (
                    <div className="py-20 text-center">
                      <Search className="mx-auto mb-4 size-7 text-muted-foreground" />
                      <h2 className="text-base">No matching documents</h2>
                      <Button
                        className="mt-4"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setQuery("");
                          setInsurance("all");
                          setCategory("all");
                          setLanguage("all");
                          setVersion("all");
                        }}
                      >
                        Clear filters
                      </Button>
                    </div>
                  ) : view === "documents" ? (
                    <DocumentRows items={results} onOpen={openDoc} />
                  ) : (
                    <div className="space-y-4">
                      {results.map((s) => (
                        <div key={s.id} className="source-card p-5">
                          <div className="flex justify-between">
                            <Button
                              variant="link"
                              className="h-auto p-0 text-sm"
                              onClick={() => openDoc(s)}
                            >
                              <Highlight text={s.title} query={query} />
                              <ArrowUpRight />
                            </Button>
                            <span className="text-xs text-success">{s.relevance}% relevance</span>
                          </div>
                          <div className="my-2 text-xs text-muted-foreground">
                            № {s.number} · {s.article} · Clause {s.clause} · Page {s.page} · v
                            {s.version}
                          </div>
                          <p className="text-xs leading-6 text-muted-foreground">
                            <Highlight text={s.text} query={query} />
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
              {view === "evaluation" && (
                <>
                  <div className="flex items-center justify-between border-y border-border py-5">
                    <div>
                      <h2 className="font-medium">Legal retrieval benchmark</h2>
                      <p className="mt-1 text-xs text-muted-foreground">
                        12 synthetic questions · Azerbaijan insurance legislation
                      </p>
                    </div>
                    <Button
                      disabled={evaluating}
                      onClick={() => {
                        setEvaluating(true);
                        timer.current = setTimeout(() => {
                          setEvaluation(true);
                          setEvaluating(false);
                        }, 1500);
                      }}
                    >
                      {evaluating ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                      {evaluating ? "Evaluating…" : "Run evaluation"}
                    </Button>
                  </div>
                  {!evaluation ? (
                    <div className="py-20 text-center">
                      <ShieldCheck className="mx-auto mb-4 size-9 text-muted-foreground" />
                      <h3 className="font-medium">No evaluation results yet</h3>
                    </div>
                  ) : (
                    <>
                      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
                        {[
                          ["Retrieval recall", "91.7%"],
                          ["Citation coverage", "83.3%"],
                          ["Questions evaluated", "12"],
                        ].map(([l, v]) => (
                          <div key={l} className="source-card p-5">
                            <p className="text-xs text-muted-foreground">{l}</p>
                            <p className="mt-3 text-2xl">{v}</p>
                          </div>
                        ))}
                      </div>
                      <p className="mt-5 text-xs text-warning">
                        Simulated metrics do not measure legal correctness.
                      </p>
                    </>
                  )}
                </>
              )}
              {view === "analytics" && (
                <>
                  <Stats />
                  <h2 className="mb-6 mt-9 font-medium">Conversation activity</h2>
                  <div className="h-72 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={[
                          { day: "Mon", n: 8 },
                          { day: "Tue", n: 14 },
                          { day: "Wed", n: 11 },
                          { day: "Thu", n: 22 },
                          { day: "Fri", n: 18 },
                          { day: "Sat", n: 9 },
                          { day: "Sun", n: 16 },
                        ]}
                      >
                        <CartesianGrid stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="day" stroke="var(--muted-foreground)" fontSize={11} />
                        <YAxis stroke="var(--muted-foreground)" fontSize={11} />
                        <ChartTooltip
                          contentStyle={{
                            background: "var(--popover)",
                            border: "1px solid var(--border)",
                            borderRadius: 6,
                          }}
                        />
                        <Area
                          dataKey="n"
                          name="Conversations"
                          stroke="var(--primary)"
                          fill="var(--accent)"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="mt-5 text-xs text-muted-foreground">
                    Synthetic activity · 11–17 November 2026
                  </p>
                </>
              )}
              {view === "settings" && (
                <div className="max-w-2xl">
                  <h2 className="mb-4 text-sm font-medium">Workspace preferences</h2>
                  <label className="text-xs text-muted-foreground" htmlFor="project-name">
                    Project name
                  </label>
                  <Input
                    id="project-name"
                    className="mt-2"
                    value={project}
                    onChange={(e) => setProject(e.target.value)}
                  />
                  <div className="mt-7 flex items-center justify-between border-y border-border py-5">
                    <div>
                      <h3 className="text-sm">Source citations</h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Include source references in assistant responses
                      </p>
                    </div>
                    <Switch
                      aria-label="Source citations"
                      checked={citations}
                      onCheckedChange={setCitations}
                    />
                  </div>
                  <div className="mt-5 flex items-center justify-between">
                    <span className="text-sm">Retrieval mode</span>
                    <Select value={mode} onValueChange={setMode}>
                      <SelectTrigger aria-label="Default retrieval mode" className="w-36">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {["Hybrid", "Dense", "Keyword"].map((m) => (
                          <SelectItem key={m} value={m}>
                            {m}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    className="mt-8"
                    onClick={() => setNotice("Preferences saved for this session")}
                  >
                    <Check />
                    Save preferences
                  </Button>
                  <p className="mt-6 text-xs text-muted-foreground">
                    Demo workspace · Preferences apply to the current session only.
                  </p>
                </div>
              )}
            </div>
          )}
        </main>
        {view === "assistant" && right && (
          <aside className="sources-panel">
            <div className="flex h-[72px] items-center justify-between border-b border-border px-5">
              <div className="flex items-center gap-2 text-sm font-medium">
                <BookOpen className="size-4 text-primary" />
                Sources & retrieval
              </div>
              <IconButton label="Close sources" onClick={() => setRight(false)}>
                <PanelRightClose />
              </IconButton>
            </div>
            <div className="p-5">
              <div className="flex items-center justify-between">
                <span className="section-label">Retrieved sources</span>
                <span className="rounded bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                  3 chunks
                </span>
              </div>
              <p className="mb-5 mt-2 text-[10px] leading-5 text-muted-foreground">
                Supporting passages from your knowledge base.
              </p>
              <div className="space-y-3">
                {sources.slice(0, 3).map((s) => (
                  <SourceCard key={s.id} source={s} onOpen={() => openDoc(s)} />
                ))}
              </div>
              <div className="mt-6 border-t border-border pt-5">
                <div className="flex items-center justify-between">
                  <span className="section-label">Retrieval details</span>
                  <SlidersHorizontal className="size-3.5 text-muted-foreground" />
                </div>
                <dl className="mt-4 space-y-3 text-[11px]">
                  {[
                    ["Search mode", mode === "Hybrid" ? "Hybrid (Dense + BM25)" : mode],
                    ["Knowledge base", "Insurance legislation"],
                    ["Reranking", "Enabled (simulated)"],
                    ["Document versions", "Latest active"],
                  ].map(([a, b]) => (
                    <div key={a} className="flex justify-between gap-3">
                      <dt className="text-muted-foreground">{a}</dt>
                      <dd className={a === "Reranking" ? "text-success" : ""}>{b}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <div className="mt-6 flex gap-2 rounded-md border border-border p-3">
                <CircleHelp className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <p className="text-[10px] leading-5 text-muted-foreground">
                  Relevance reflects retrieval similarity, not legal correctness. Scores are
                  simulated; backend ranking scores are unavailable.
                </p>
              </div>
              <div className="mt-5 flex items-center justify-between text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <History className="size-3" />
                  Last indexed
                </span>
                <span>17 Nov 2026, 08:45</span>
              </div>
            </div>
          </aside>
        )}
        <Dialog open={newProject} onOpenChange={setNewProject}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>New project</DialogTitle>
            </DialogHeader>
            <label htmlFor="new-project" className="text-xs text-muted-foreground">
              Project name
            </label>
            <Input
              id="new-project"
              placeholder="e.g. Health Insurance Research"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Button
              disabled={!name.trim()}
              onClick={() => {
                setProjects((p) => [...p, name.trim()]);
                setProject(name.trim());
                setName("");
                setNewProject(false);
                startChat();
              }}
            >
              Create project
            </Button>
          </DialogContent>
        </Dialog>
        <Dialog
          open={!!preview}
          onOpenChange={(o) => {
            if (!o) setPreview(null);
          }}
        >
          <DialogContent className="max-h-[90dvh] max-w-4xl overflow-auto">
            <DialogHeader>
              <DialogTitle className="pr-5 text-base">{preview?.title}</DialogTitle>
            </DialogHeader>
            {preview && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
                  <span className="text-xs text-muted-foreground">
                    № {preview.number} · Synthetic document preview
                  </span>
                  <div className="flex items-center gap-2">
                    <Select value={docVersion} onValueChange={setDocVersion}>
                      <SelectTrigger className="h-8 w-24 text-xs" aria-label="Document version">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="2024">v2024</SelectItem>
                        <SelectItem value="2023">v2023</SelectItem>
                      </SelectContent>
                    </Select>
                    <IconButton
                      label="Previous page"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                      <ChevronLeft />
                    </IconButton>
                    <span className="text-xs">Page {page}</span>
                    <IconButton
                      label="Next page"
                      onClick={() => setPage((p) => Math.min(48, p + 1))}
                    >
                      <ChevronRight />
                    </IconButton>
                  </div>
                </div>
                <div className="grid gap-5 md:grid-cols-[150px_1fr]">
                  <aside className="space-y-2">
                    <p className="section-label mb-3">Document hierarchy</p>
                    {["Ümumi müddəalar", preview.article, "Əlaqəli istinadlar"].map((t, i) => (
                      <Button
                        key={t}
                        variant="ghost"
                        className="h-auto w-full justify-start whitespace-normal px-2 py-2 text-xs"
                        onClick={() => setPage(i === 0 ? 1 : preview.page)}
                      >
                        {t}
                      </Button>
                    ))}
                    <p className="pt-5 text-[10px] text-muted-foreground">Related reference</p>
                    <Button
                      variant="link"
                      className="h-auto whitespace-normal p-0 text-xs"
                      onClick={() => {
                        const related = sources[2];
                        if (related) openDoc(related);
                      }}
                    >
                      Sığorta fəaliyyəti haqqında
                    </Button>
                  </aside>
                  <div className="document-page">
                    <p className="text-center text-[9px] font-sans">
                      SİNTETİK NÜMAYİŞ · TƏSDİQLƏNMİŞ HÜQUQİ MƏLUMAT DEYİL
                    </p>
                    <h2 className="mt-8 text-center text-xl font-bold">
                      AZƏRBAYCAN RESPUBLİKASININ QANUNU
                    </h2>
                    <h3 className="my-6 text-center text-lg">{preview.title}</h3>
                    <p className="text-center text-xs">
                      № {preview.number} · Nümayiş versiyası {docVersion}
                    </p>
                    <h4 className="mb-4 mt-12 font-bold">
                      {page === preview.page
                        ? `${preview.article}. Sığorta münasibətləri`
                        : `Səhifə ${page}. Ümumi müddəalar`}
                    </h4>
                    <p className="text-sm leading-8">
                      {page === preview.page
                        ? `${preview.clause}. ${preview.text}`
                        : "Bu səhifə sənəd naviqasiyasını nümayiş etdirmək üçün yaradılmış sintetik nümunədir. Təsdiqlənmiş hüquqi mətn deyil."}
                    </p>
                    <div className="mt-20 border-t border-document-foreground/20 pt-4 text-center text-xs">
                      {page}
                    </div>
                  </div>
                </div>
              </>
            )}
          </DialogContent>
        </Dialog>
        {notice && (
          <div
            role="status"
            className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-md border border-border bg-popover px-5 py-3 text-xs shadow-lg"
          >
            {notice}
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}
function SourceCard({ source: s, onOpen }: { source: LegalSource; onOpen: () => void }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="source-card overflow-hidden">
      <div className="p-3.5">
        <div className="mb-3 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <span className="flex size-5 items-center justify-center rounded bg-accent text-primary">
              {s.id}
            </span>
            <FileText className="size-3" />
            Legal document
          </span>
          <span className="text-[10px] text-success">{s.relevance}% match</span>
        </div>
        <Button
          variant="ghost"
          className="h-auto w-full justify-start whitespace-normal p-0 text-left text-xs font-medium hover:bg-transparent"
          onClick={onOpen}
        >
          {s.title}
          <ArrowUpRight className="ml-auto size-3.5 shrink-0 text-muted-foreground" />
        </Button>
        <p className="mb-3 mt-1 text-[10px] text-muted-foreground">Qanun № {s.number}</p>
        <div className="flex flex-wrap gap-1.5 text-[9px] text-muted-foreground">
          <span className="rounded border border-border px-1.5 py-0.5">{s.article}</span>
          <span className="rounded border border-border px-1.5 py-0.5">{s.clause}</span>
          <span className="rounded border border-border px-1.5 py-0.5">Page {s.page}</span>
          <span className="rounded border border-border px-1.5 py-0.5">v{s.version}</span>
        </div>
        <p
          className={`mt-3 text-[10px] leading-[1.8] text-muted-foreground ${expanded ? "" : "line-clamp-3"}`}
        >
          {s.text}
        </p>
      </div>
      <Button
        variant="ghost"
        className="h-8 w-full justify-between rounded-none border-t border-border px-3.5 text-[10px] text-muted-foreground"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? "Collapse passage" : "View full passage"}
        <ChevronDown className={`size-3 ${expanded ? "rotate-180" : ""}`} />
      </Button>
    </div>
  );
}
function Stats() {
  return (
    <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
      {[
        ["Total documents", "24", FileText],
        ["Indexed chunks", "1,248", Layers],
        ["Active versions", "3", History],
        ["Conversations", "98", MessageSquare],
      ].map(([label, value, Icon]) => {
        const I = Icon as typeof FileText;
        return (
          <div key={String(label)} className="source-card p-5">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="text-[11px]">{String(label)}</span>
              <I className="size-4" />
            </div>
            <p className="mt-4 text-2xl font-medium">{String(value)}</p>
          </div>
        );
      })}
    </div>
  );
}
function DocumentRows({
  items,
  onOpen,
}: {
  items: LegalSource[];
  onOpen: (s: LegalSource) => void;
}) {
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[500px] text-left text-xs">
        <thead className="border-y border-border text-[10px] text-muted-foreground">
          <tr>
            <th className="py-3 font-normal">Document</th>
            <th className="font-normal">Version</th>
            <th className="font-normal">Updated</th>
            <th className="font-normal">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.id} className="border-b border-border">
              <td className="py-4">
                <Button
                  variant="ghost"
                  className="h-auto justify-start p-0 text-xs"
                  onClick={() => onOpen(s)}
                >
                  <FileText className="text-primary" />
                  <span>
                    {s.title}
                    <span className="mt-1 block text-left text-[10px] text-muted-foreground">
                      № {s.number} · {s.article}
                    </span>
                  </span>
                </Button>
              </td>
              <td className="text-muted-foreground">v{s.version}</td>
              <td className="text-muted-foreground">{s.date}</td>
              <td className="text-success">Indexed</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
