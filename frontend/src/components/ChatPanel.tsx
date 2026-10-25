"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { DataUsed } from "@/components/DataUsed";
import { streamChat, type ToolSource } from "@/lib/chat";

type Turn = {
  role: "user" | "assistant";
  text: string;
  steps: string[];          // live status lines while tools run
  sources: ToolSource[];
  pending?: boolean;
  error?: string;
};

// Styles for Markdown answers (lists, tables, emphasis), scoped to the answer element.
const MARKDOWN = [
  "space-y-2 [&_ul]:list-disc [&_ol]:list-decimal [&_ul]:pl-5 [&_ol]:pl-5 [&_li]:mt-0.5",
  "[&_strong]:font-semibold [&_a]:text-accent [&_a]:underline [&_code]:font-mono",
  "[&_table]:w-full [&_table]:text-[13px] [&_th]:text-left [&_th]:font-semibold",
  "[&_th]:border-b [&_td]:border-b [&_th]:border-border [&_td]:border-border [&_th]:py-1 [&_td]:py-1 [&_th]:pr-2 [&_td]:pr-2",
].join(" ");

type ChatApi = { open: (question?: string) => void };

const ChatContext = createContext<ChatApi>({ open: () => {} });

/** Lets any card open the chat, optionally asking a question straight away. */
export const useChat = () => useContext(ChatContext);

export function ChatProvider({ suggestions, children }: {
  suggestions: string[]; children: React.ReactNode;
}) {
  const [visible, setVisible] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const send = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setTurns((t) => [...t, { role: "user", text: q, steps: [], sources: [] },
      { role: "assistant", text: "", steps: [], sources: [], pending: true }]);
    const update = (fn: (t: Turn) => Turn) =>
      setTurns((all) => [...all.slice(0, -1), fn(all[all.length - 1])]);
    try {
      await streamChat(q, conversationId, (e) => {
        switch (e.kind) {
          case "conversation": setConversationId(e.data.id); break;
          case "status": update((t) => ({ ...t, steps: [...t.steps, e.data.text] })); break;
          case "tool": update((t) => ({ ...t, sources: [...t.sources, e.data] })); break;
          case "token": update((t) => ({ ...t, text: t.text + e.data.text })); break;
          case "error": update((t) => ({ ...t, error: e.data.message })); break;
        }
      });
    } catch (err) {
      update((t) => ({ ...t, error: err instanceof Error ? err.message : "Request failed" }));
    } finally {
      update((t) => ({ ...t, pending: false }));
      setBusy(false);
    }
  }, [busy, conversationId]);

  const open = useCallback((question?: string) => {
    setVisible(true);
    if (question) void send(question);
  }, [send]);

  return (
    <ChatContext.Provider value={{ open }}>
      {children}
      {!visible && (
        <button
          onClick={() => setVisible(true)}
          className="fixed right-4 bottom-4 z-20 rounded-full bg-accent px-5 py-3 text-sm font-medium text-white shadow-lg"
        >
          Ask CampusGPT
        </button>
      )}
      {visible && (
        <ChatWindow
          turns={turns} busy={busy} suggestions={suggestions} onSend={send}
          onClose={() => setVisible(false)}
          onReset={() => { setTurns([]); setConversationId(null); }}
        />
      )}
    </ChatContext.Provider>
  );
}

function ChatWindow({ turns, busy, suggestions, onSend, onClose, onReset }: {
  turns: Turn[]; busy: boolean; suggestions: string[];
  onSend: (q: string) => void; onClose: () => void; onReset: () => void;
}) {
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    onSend(draft);
    setDraft("");
  }

  return (
    <aside
      aria-label="CampusGPT chat"
      className="fixed inset-0 z-30 flex flex-col border-border bg-surface sm:inset-y-0 sm:right-0 sm:left-auto sm:w-[440px] sm:border-l sm:shadow-xl"
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h2 className="font-semibold">CampusGPT</h2>
          <p className="text-xs text-subtle">Answers from your records. Synthetic demo data.</p>
        </div>
        <div className="flex gap-1">
          {turns.length > 0 && (
            <button onClick={onReset} disabled={busy} className="rounded-md px-2 py-1 text-sm whitespace-nowrap text-muted hover:bg-background disabled:opacity-50">
              New chat
            </button>
          )}
          <button onClick={onClose} aria-label="Close chat" className="rounded-md px-2 py-1 text-sm text-muted hover:bg-background">
            ✕
          </button>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {turns.length === 0 && (
          <div>
            <p className="text-sm text-muted">Ask about your attendance, exams, assignments, fees or notices. Try:</p>
            <ul className="mt-3 space-y-2">
              {suggestions.map((s) => (
                <li key={s}>
                  <button onClick={() => onSend(s)} className="w-full rounded-lg border border-border px-3 py-2 text-left text-sm hover:border-accent">
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((t, i) => t.role === "user" ? (
          <div key={i} className="ml-8 rounded-lg bg-accent px-3 py-2 text-sm text-white">{t.text}</div>
        ) : (
          <div key={i} className="text-sm">
            {t.pending && !t.text && (
              <ul className="space-y-1 text-xs text-muted" aria-live="polite">
                {(t.steps.length ? t.steps : ["Thinking"]).map((s, j, all) => (
                  <li key={j} className="flex items-center gap-2">
                    {j === all.length - 1
                      ? <span className="size-3 animate-spin rounded-full border-2 border-accent border-t-transparent" aria-hidden />
                      : <span aria-hidden className="text-good-text">✓</span>}
                    {s}…
                  </li>
                ))}
              </ul>
            )}
            {t.text && (
              <div className={MARKDOWN}>
                <Markdown remarkPlugins={[remarkGfm]}>{t.text}</Markdown>
              </div>
            )}
            {t.error && <p role="alert" className="mt-1 text-critical">{t.error}</p>}
            {!t.pending && <DataUsed sources={t.sources} />}
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-border p-3">
        <input
          value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={2000}
          placeholder="Ask a question…" aria-label="Your question"
          className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-accent"
        />
        <button type="submit" disabled={busy || !draft.trim()} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          Send
        </button>
      </form>
    </aside>
  );
}
