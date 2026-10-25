"use client";

import { useState } from "react";

import { useChat } from "@/components/ChatPanel";
import { Status } from "@/components/ui";
import type { CourseAttendance } from "@/lib/api";

// Mirrors backend/campusgpt/calc.py with integer arithmetic: no rounding decides the
// outcome. a / h >= 3/4  <=>  4a >= 3h.
const meets = (attended: number, held: number) => held === 0 || 4 * attended >= 3 * held;
const needed = (attended: number, held: number) =>
  meets(attended, held) ? 0 : 3 * held - 4 * attended;   // smallest x: 4(a+x) >= 3(h+x)

export function WhatIf({ courses }: { courses: CourseAttendance[] }) {
  const chat = useChat();
  const [code, setCode] = useState(
    (courses.find((c) => c.status !== "ok") ?? courses[0]).code);
  const [miss, setMiss] = useState(2);
  const c = courses.find((x) => x.code === code) ?? courses[0];
  const held = c.held + miss;
  const percent = held ? (100 * c.attended) / held : 100;
  const ok = meets(c.attended, held);

  return (
    <div className="mt-5 rounded-lg border border-border p-4">
      <h3 className="text-sm font-semibold">What if I skip?</h3>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-muted">Course</span>
          <select
            value={code} onChange={(e) => setCode(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1"
          >
            {courses.map((x) => <option key={x.code} value={x.code}>{x.code} {x.title}</option>)}
          </select>
        </label>
        <label className="flex flex-1 items-center gap-2">
          <span className="text-muted whitespace-nowrap">Miss next {miss} {miss === 1 ? "class" : "classes"}</span>
          <input
            type="range" min={0} max={15} value={miss} onChange={(e) => setMiss(+e.target.value)}
            className="min-w-24 flex-1 accent-[var(--accent)]"
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm">
          <span className="text-2xl font-semibold tabular-nums">{percent.toFixed(2)}%</span>{" "}
          <span className="text-muted">({c.attended}/{held} classes)</span>
        </p>
        {ok
          ? <Status tone="good">Still at least 75%</Status>
          : <Status tone="critical">Below 75%: then attend {needed(c.attended, held)} in a row</Status>}
      </div>
      <button
        onClick={() => chat.open(`What happens if I miss the next ${miss} ${c.title} classes?`)}
        className="mt-2 text-xs text-accent hover:underline"
      >
        Ask CampusGPT about this →
      </button>
    </div>
  );
}
