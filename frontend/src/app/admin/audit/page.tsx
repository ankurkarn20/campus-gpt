"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/AdminShell";
import { Card, Empty, Status, type Tone } from "@/components/ui";
import { api, formatDateTime, type AuditEntry, type AuditPage } from "@/lib/api";

const ACTIONS = ["login", "logout", "tool_call", "document_upload", "security_test"];
const OUTCOMES: AuditEntry["outcome"][] = ["success", "denied", "error"];
const OUTCOME_TONE: Record<AuditEntry["outcome"], Tone> = { success: "good", denied: "critical", error: "warning" };
const PAGE_SIZE = 50;

type Filters = { action: string; outcome: string; user: string };

function query(f: Filters, before?: number) {
  const q = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (f.action) q.set("action", f.action);
  if (f.outcome) q.set("outcome", f.outcome);
  if (f.user.trim()) q.set("user", f.user.trim());
  if (before) q.set("before", String(before));
  return `/api/admin/audit?${q}`;
}

export default function AuditPageView() {
  return (
    <AdminShell title="Audit log">
      <AuditLog />
    </AdminShell>
  );
}

function AuditLog() {
  const [filters, setFilters] = useState<Filters>({ action: "", outcome: "", user: "" });
  const [applied, setApplied] = useState<Filters>(filters);
  const [page, setPage] = useState<AuditPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((f: Filters) =>
    api<AuditPage>(query(f)).then((p) => { setPage(p); setError(null); })
      .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong")), []);

  useEffect(() => {
    void load(applied);
  }, [applied, load]);

  async function more() {
    if (!page?.next_before) return;
    const next = await api<AuditPage>(query(applied, page.next_before));
    setPage({ ...next, entries: [...page.entries, ...next.entries] });
  }

  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setFilters({ ...filters, [k]: e.target.value });
  const field = "rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-accent";

  return (
    <div className="space-y-4">
      {page && <Counts counts={page.counts} onPick={(action, outcome) => {
        const f = { ...filters, action, outcome };
        setFilters(f);
        setApplied(f);
      }} />}

      <Card title="Events" action={<button onClick={() => load(applied)} className="text-xs text-accent hover:underline">Refresh</button>}>
        <form
          onSubmit={(e) => { e.preventDefault(); setApplied(filters); }}
          className="mb-3 flex flex-wrap items-end gap-2 text-sm"
        >
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">Action</span>
            <select value={filters.action} onChange={set("action")} className={field}>
              <option value="">All</option>
              {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">Outcome</span>
            <select value={filters.outcome} onChange={set("outcome")} className={field}>
              <option value="">All</option>
              {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>
          <label className="flex min-w-48 flex-1 flex-col gap-1">
            <span className="text-xs text-muted">User email contains</span>
            <input value={filters.user} onChange={set("user")} placeholder="e.g. student.fees" className={field} />
          </label>
          <button type="submit" className="rounded-md bg-accent px-3 py-1.5 font-medium text-white">Filter</button>
        </form>

        {error ? <Empty>Could not load the audit log: {error}</Empty>
          : !page ? <Empty>Loading…</Empty>
          : page.entries.length === 0 ? <Empty>No events match.</Empty>
          : <EventTable entries={page.entries} />}
        {page?.next_before && (
          <button onClick={more} className="mt-3 text-sm text-accent hover:underline">Older events</button>
        )}
      </Card>
    </div>
  );
}

/** Last seven days: one tile per action, with its outcomes. Clicking an outcome filters. */
function Counts({ counts, onPick }: { counts: AuditPage["counts"]; onPick: (action: string, outcome: string) => void }) {
  const actions = [...new Set(counts.map((c) => c.action))];
  if (!actions.length) return null;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {actions.map((a) => (
        <div key={a} className="rounded-xl border border-border bg-surface p-3">
          <p className="text-xs text-muted">{a} · 7 days</p>
          <ul className="mt-1 space-y-0.5">
            {counts.filter((c) => c.action === a).map((c) => (
              <li key={c.outcome}>
                <button onClick={() => onPick(a, c.outcome)} className="flex w-full items-center justify-between gap-2 text-left hover:underline">
                  <Status tone={OUTCOME_TONE[c.outcome]}>{c.outcome}</Status>
                  <span className="text-sm font-semibold tabular-nums">{c.count}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function EventTable({ entries }: { entries: AuditEntry[] }) {
  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[40rem] text-sm">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 font-medium">When</th>
            <th className="py-2 pr-3 font-medium">User</th>
            <th className="py-2 pr-3 font-medium">Action</th>
            <th className="py-2 pr-3 font-medium">Outcome</th>
            <th className="py-2 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className="border-b border-border align-top last:border-0">
              <td className="whitespace-nowrap py-2 pr-3 text-muted">{formatDateTime(e.created_at)}</td>
              <td className="py-2 pr-3">
                {e.user ?? <span className="text-subtle">unknown</span>}
                {e.role && <span className="block text-xs text-subtle">{e.role}</span>}
              </td>
              <td className="py-2 pr-3">
                {e.action}
                {e.tool_name && <span className="block font-mono text-xs text-muted">{e.tool_name}</span>}
              </td>
              <td className="py-2 pr-3"><Status tone={OUTCOME_TONE[e.outcome]}>{e.outcome}</Status></td>
              <td className="max-w-xs break-words py-2 font-mono text-xs text-muted">
                {e.detail ? JSON.stringify(e.detail) : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
