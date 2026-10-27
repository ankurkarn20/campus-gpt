"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AdminShell } from "@/components/AdminShell";
import { Card, Empty, Status } from "@/components/ui";
import { api, type Attack, type AttackResult } from "@/lib/api";
import { TOOL_LABELS } from "@/lib/chat";
import { postEventStream } from "@/lib/sse";

type Suite = { attacker: string; victim: string; attacks: Attack[] };
type Done = { students_before: number; students_after: number };

export default function SecurityPage() {
  return (
    <AdminShell title="Security demonstration">
      <Security />
    </AdminShell>
  );
}

function Security() {
  const [suite, setSuite] = useState<Suite | null>(null);
  const [results, setResults] = useState<Record<string, AttackResult>>({});
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState<Done | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Suite>("/api/admin/security/attacks").then(setSuite)
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"));
  }, []);

  async function run() {
    setResults({});
    setDone(null);
    setError(null);
    setRunning(true);
    try {
      await postEventStream("/api/admin/security/run", undefined, (e) => {
        if (e.kind === "result") {
          const r = e.data as AttackResult;
          setResults((prev) => ({ ...prev, [r.id]: r }));
        } else if (e.kind === "done") setDone(e.data as Done);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The run failed");
    } finally {
      setRunning(false);
    }
  }

  if (!suite) return error ? <Empty>Could not load the attacks: {error}</Empty> : <Empty>Loading…</Empty>;

  const finished = Object.values(results);
  const leaked = finished.filter((r) => r.verdict === "leaked").length;
  const current = running ? suite.attacks.find((a) => !results[a.id])?.id : undefined;

  return (
    <div className="space-y-4">
      <Card title="What this checks">
        <div className="space-y-2 text-sm text-muted">
          <p>
            Logged in as <span className="font-medium text-foreground">{suite.attacker}</span>, each prompt
            below asks the real chat model for <span className="font-medium text-foreground">{suite.victim}</span>&apos;s
            records. Afterwards, code (not the model) checks every tool result and the answer for the victim&apos;s
            name, roll number, email and course codes.
          </p>
          <p>
            A leak should be impossible by design: every tool reads the student id from the login session and
            refuses identity arguments. Whether the model obeys injected instructions is reported separately.
            Each tool call also appears in the <Link href="/admin/audit" className="text-accent hover:underline">audit log</Link>.
          </p>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            onClick={run} disabled={running}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {running ? `Running ${finished.length + 1} of ${suite.attacks.length}…` : finished.length ? "Run again" : "Run all attacks"}
          </button>
          {finished.length > 0 && !running && (
            <Status tone={leaked ? "critical" : "good"}>
              {finished.length - leaked} of {finished.length} blocked
            </Status>
          )}
          {done && (
            <Status tone={done.students_before === done.students_after ? "good" : "critical"}>
              Students table {done.students_before === done.students_after ? "intact" : "changed"} ({done.students_after.toLocaleString("en-IN")} rows)
            </Status>
          )}
        </div>
        {error && <p role="alert" className="mt-2 text-sm text-critical">{error}</p>}
      </Card>

      <ul className="space-y-3">
        {suite.attacks.map((a) => (
          <AttackRow key={a.id} attack={a} result={results[a.id]} active={a.id === current} />
        ))}
      </ul>
    </div>
  );
}

function AttackRow({ attack, result, active }: { attack: Attack; result?: AttackResult; active: boolean }) {
  return (
    <li className="rounded-xl border border-border bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted">{attack.category} · <span className="font-mono">{attack.id}</span></p>
          <p className="mt-1 break-words">{result?.prompt ?? attack.prompt}</p>
        </div>
        {result ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-subtle tabular-nums">{result.seconds}s</span>
            {result.verdict === "blocked"
              ? <Status tone="good">Blocked</Status>
              : <Status tone="critical">Leaked</Status>}
          </div>
        ) : active ? <Status tone="warning">Running…</Status> : <Status tone="neutral">Not run</Status>}
      </div>

      {result && (
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-subtle">Tools called:</span>
            {result.tools.length === 0 && <span className="text-muted">none</span>}
            {result.tools.map((t, i) => (
              <span
                key={i} title={JSON.stringify(t.arguments)}
                className={`rounded-full border border-border px-2 py-0.5 ${t.ok ? "text-muted" : "text-critical line-through decoration-critical"}`}
              >
                {TOOL_LABELS[t.tool] ?? t.tool}{t.ok ? "" : " (refused)"}
              </span>
            ))}
          </div>
          {[...result.leaks.map((l) => ["critical", l] as const), ...result.notes.map((n) => ["warning", n] as const)].map(([tone, text]) => (
            <p key={text}><Status tone={tone}>{text}</Status></p>
          ))}
          <details>
            <summary className="cursor-pointer text-xs text-accent">Model&apos;s answer</summary>
            <p className="mt-1 whitespace-pre-line rounded-md border border-border bg-background p-2 text-muted">
              {result.answer || "(no answer)"}
            </p>
          </details>
        </div>
      )}
    </li>
  );
}
