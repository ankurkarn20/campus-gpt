"use client";

import { useState } from "react";

import { TOOL_LABELS, type ToolSource } from "@/lib/chat";

// Shows exactly which records an answer was based on: one chip per tool call, expanding
// to the rows the tool returned.
export function DataUsed({ sources }: { sources: ToolSource[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!sources.length) return null;
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-subtle">Data used:</span>
        {sources.map((s, i) => (
          <button
            key={i} type="button" onClick={() => setOpen(open === i ? null : i)}
            aria-expanded={open === i}
            className={`rounded-full border px-2 py-0.5 text-xs ${open === i ? "border-accent text-accent" : "border-border text-muted hover:text-foreground"} ${s.ok ? "" : "line-through decoration-critical"}`}
            title={s.ok ? undefined : "This lookup failed"}
          >
            {TOOL_LABELS[s.tool] ?? s.tool}
          </button>
        ))}
      </div>
      {open !== null && sources[open] && <SourceDetail source={sources[open]} />}
    </div>
  );
}

function SourceDetail({ source }: { source: ToolSource }) {
  const args = Object.entries(source.arguments).filter(([, v]) => v !== null && v !== "");
  return (
    <div className="mt-2 overflow-x-auto rounded-md border border-border bg-background p-2 text-xs">
      <p className="mb-1 font-mono text-subtle">
        {source.tool}({args.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
      </p>
      <Value value={source.result} />
    </div>
  );
}

function Value({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (!value.length) return <p className="text-muted">No records.</p>;
    if (typeof value[0] !== "object" || value[0] === null) return <p>{value.join(", ")}</p>;
    const cols = Object.keys(value[0] as object).filter((c) => c !== "body");
    return (
      <table className="w-full">
        <thead>
          <tr>{cols.map((c) => <th key={c} className="pr-3 text-left font-medium text-subtle whitespace-nowrap">{c}</th>)}</tr>
        </thead>
        <tbody>
          {value.map((row, i) => (
            <tr key={i} className="border-t border-border">
              {cols.map((c) => <td key={c} className="pr-3 py-0.5 align-top whitespace-nowrap">{format((row as Record<string, unknown>)[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (value && typeof value === "object") {
    return (
      <dl className="grid grid-cols-[auto_1fr] gap-x-3">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-subtle">{k}</dt>
            <dd>{v && typeof v === "object" ? <Value value={v} /> : format(v)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <p>{format(value)}</p>;
}

function format(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
