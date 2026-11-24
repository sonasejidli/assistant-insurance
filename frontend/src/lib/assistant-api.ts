import { ui } from "@/lib/ui-text";

export interface Source {
  id: string;
  doc?: string;
  document?: string;
  document_id?: string;
  passage_id?: string;
  chunk_id?: string;
  article_number?: string;
  page?: number | null;
  page_number?: number | null;
  law_name?: string;
  law_number?: string;
  article?: string | null;
  clause?: string | null;
  text: string;
  url?: string | null;
}

export interface QuickReply {
  label: string;
  question: string;
}

export interface RetrievedSource extends Source {
  official_url?: string | null;
  version_id?: string | null;
  source_type: string;
  issuing_authority?: string | null;
  temporal_status: string;
  legal_currency_verified: boolean;
  effective_date?: string | null;
}

export interface Answer {
  answer: string;
  sources: Source[];
  retrieved_sources?: RetrievedSource[];
  verified_citations?: Source[];
  answer_status?: "verified" | "withheld" | "not_applicable";
  provider_status?: string | null;
  withheld_reason?: string | null;
  warnings: string[];
  disclaimer: string;
  quick_replies?: QuickReply[];
  intent?: string;
  answer_mode?: "FULL" | "PARTIAL" | "NOT_FOUND" | null;
  delivery_status?: "verification_failed" | "provider_rate_limit" | "provider_timeout" | "provider_unavailable" | "internal_error";
  delivery_message?: string;
  evidence_status?: string;
  follow_up_messages?: string[];
  language?: "az" | "en" | "ru";
}

export interface IndexedDocument {
  doc: string;
  metadata: Record<string, unknown>;
}
export interface Preview {
  text: string;
  page: number | null;
  pdf_url: string | null;
  original_url?: string | null;
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
  read: (response: Response) => Promise<T> = (response) => response.json(),
): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    if (response.status === 502 || response.status === 504) {
      throw new Error(ui.chat.serviceUnavailable);
    }
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string" ? body.detail : ui.chat.requestFailed(response.status),
    );
  }
  return read(response);
}

export function requestAnswer(init: RequestInit): Promise<Answer> {
  const expectedId = new Headers(init.headers).get("X-Request-ID");
  return apiRequest("/ask", init, async (response) => {
    const mediaType = response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase();
    const receivedId = response.headers.get("X-Request-ID");
    if (mediaType !== "application/json" || (expectedId && receivedId && receivedId !== expectedId)) {
      throw new Error(ui.chat.failure);
    }
    const result = await response.json();
    if (typeof result?.answer !== "string" || !Array.isArray(result.sources)) {
      throw new Error(ui.chat.failure);
    }
    return result;
  });
}

export function documentPath(path: string): string | null {
  return path.startsWith("/documents/") ? `/api${path}` : null;
}
