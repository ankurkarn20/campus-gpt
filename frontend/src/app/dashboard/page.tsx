"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AttendanceChart } from "@/components/AttendanceChart";
import { ChatProvider, useChat } from "@/components/ChatPanel";
import { EligibilityCard } from "@/components/EligibilityCard";
import { Card, Empty, Status, type Tone } from "@/components/ui";
import { WhatIf } from "@/components/WhatIf";
import {
  api, ApiError, formatDate, formatDateTime, formatRupees,
  type ActionItem, type Dashboard, type Fee, type Me,
} from "@/lib/api";

const ACTION_TONE: Record<ActionItem["kind"], Tone> = {
  fee_overdue: "critical",
  attendance_short: "critical",
  exam: "warning",
  assignment: "warning",
  fee_due: "warning",
};

const FEE_STATUS: Record<Fee["status"], [Tone, string]> = {
  paid: ["good", "Paid"],
  pending: ["neutral", "Pending"],
  partially_paid: ["warning", "Partly paid"],
  overdue: ["critical", "Overdue"],
  waived: ["neutral", "Waived"],
  cancelled: ["neutral", "Cancelled"],
};

const EXAM_LABEL = { quiz: "Quiz", mid_term: "Mid-term", end_term: "End-term" };

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const who = await api<Me>("/api/auth/me");
        setMe(who);
        if (who.role === "admin") return router.replace("/admin");
        setData(await api<Dashboard>("/api/student/dashboard"));
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
        else setError(err instanceof Error ? err.message : "Something went wrong");
      }
    })();
  }, [router]);

  async function logout() {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }

  if (error) return <Centered>Could not load your dashboard: {error}</Centered>;
  if (!me) return <Centered>Loading…</Centered>;

  const s = me.student;
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted">CampusGPT</p>
          <h1 className="text-2xl font-semibold">{s ? `Hello, ${s.name.split(" ")[0]}` : me.email}</h1>
          {s && (
            <p className="text-sm text-muted">
              {s.roll_no} · {s.program} · Semester {s.semester}, Section {s.section}
            </p>
          )}
        </div>
        <button onClick={logout} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface">
          Log out
        </button>
      </header>

      {!data ? (
        <Centered>Loading…</Centered>
      ) : (
        <ChatProvider suggestions={suggestions(data)}>
          <StudentDashboard data={data} />
        </ChatProvider>
      )}
    </div>
  );
}

/** Questions that this student's own data makes worth asking. */
function suggestions(d: Dashboard): string[] {
  const out = ["What do I need to take care of this week?"];
  const short = d.attendance.find((c) => c.status === "short");
  if (short) out.push(`Can I sit my ${short.title} end-term exam?`,
    `How many ${short.title} classes must I attend to reach 75%?`);
  if (!d.eligibility.admit_card_ok) out.push("Will I get my admit card for the end-term exams?");
  if (d.fees.some((f) => f.status === "overdue")) out.push("Which of my fees are overdue, and how much do I owe?");
  const exam = d.exams[0];
  if (exam) out.push(`When and where is my ${exam.title} ${EXAM_LABEL[exam.exam_type].toLowerCase()}?`);
  const spare = d.attendance.find((c) => c.can_miss >= 2);
  if (out.length < 4 && spare) out.push(`Can I miss 2 ${spare.title} classes?`);
  if (out.length < 4) out.push("What is the late fee if I pay my tuition after the due date?");
  if (out.length < 4) out.push("Any new notices about placements or hackathons?");
  return out.slice(0, 4);
}

const ACTION_QUESTION: Record<ActionItem["kind"], (item: ActionItem) => string> = {
  fee_overdue: () => "My fee is overdue. How much do I owe and what happens if I don't pay?",
  fee_due: () => "Which fees are due soon and how much are they?",
  attendance_short: (i) => `${i.title}. What should I do?`,
  exam: (i) => `Tell me about my upcoming exam: ${i.title}`,
  assignment: (i) => `What assignments are due this week? (${i.title})`,
};

function StudentDashboard({ data }: { data: Dashboard }) {
  const chat = useChat();
  const exams = data.exams.slice(0, 6);
  const assignments = data.assignments.slice(0, 6);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="This week" className="lg:col-span-3" action={<span className="text-xs text-subtle">as of {formatDate(data.today)}</span>}>
        {data.this_week.length === 0 ? (
          <Empty>Nothing needs your attention in the next seven days.</Empty>
        ) : (
          <ul className="divide-y divide-border">
            {data.this_week.map((item, i) => (
              <li key={i} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-2.5">
                <div>
                  <p className="text-sm font-medium">{item.title}</p>
                  <p className="text-sm text-muted">{item.detail}</p>
                </div>
                <div className="flex items-center gap-3">
                  <Status tone={ACTION_TONE[item.kind]}>
                    {item.kind.startsWith("fee") ? "Fees" : item.kind === "attendance_short" ? "Attendance" : item.kind === "exam" ? "Exam" : "Assignment"}
                  </Status>
                  <button onClick={() => chat.open(ACTION_QUESTION[item.kind](item))} className="text-xs text-accent hover:underline">
                    Ask
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <EligibilityCard data={data.eligibility} />

      <Card title="Attendance" className="lg:col-span-2">
        {data.attendance.length === 0 ? <Empty>No classes recorded yet.</Empty> : (
          <>
            <AttendanceChart courses={data.attendance} />
            <table className="mt-4 w-full text-sm">
              <thead className="text-left text-xs text-subtle">
                <tr><th className="py-1 font-medium">Course</th><th className="font-medium">Attended</th><th className="font-medium">Status</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.attendance.map((c) => (
                  <tr key={c.code}>
                    <td className="py-2 pr-2"><span className="text-muted">{c.code}</span> {c.title}</td>
                    <td className="pr-2 tabular-nums whitespace-nowrap">{c.attended}/{c.held} · {c.percentage}%</td>
                    <td>
                      {c.status === "short" ? <Status tone="critical">Attend next {c.classes_needed}</Status>
                        : c.status === "at_risk" ? <Status tone="warning">Can&apos;t miss any</Status>
                        : <Status tone="good">Can miss {c.can_miss}</Status>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <WhatIf courses={data.attendance} />
          </>
        )}
      </Card>

      <Card title="Fees">
        {data.fees.length === 0 ? <Empty>No invoices.</Empty> : (
          <ul className="space-y-3">
            {data.fees.map((f) => {
              const [tone, label] = FEE_STATUS[f.status];
              return (
                <li key={f.description} className="text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium">{f.description}</p>
                    <Status tone={tone}>{label}</Status>
                  </div>
                  <p className="text-muted tabular-nums">
                    {f.balance > 0 ? `${formatRupees(f.balance)} due ${formatDate(f.due_date)}` : formatRupees(f.amount)}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card title="Upcoming exams" action={<Count shown={exams.length} total={data.exams.length} />}>
        {exams.length === 0 ? <Empty>No upcoming exams.</Empty> : (
          <ul className="space-y-3 text-sm">
            {exams.map((e) => (
              <li key={`${e.code}-${e.exam_type}`}>
                <p className="font-medium">{e.title} <span className="font-normal text-muted">· {EXAM_LABEL[e.exam_type]}</span></p>
                <p className="text-muted">{formatDateTime(e.starts_at)} · Room {e.room} · {e.duration_minutes} min</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Assignments due" action={<Count shown={assignments.length} total={data.assignments.length} />}>
        {assignments.length === 0 ? <Empty>No assignments due.</Empty> : (
          <ul className="space-y-3 text-sm">
            {assignments.map((a) => (
              <li key={`${a.code}-${a.title}`} className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{a.title}</p>
                  <p className="text-muted">{a.code} · due {formatDateTime(a.due_at)}</p>
                </div>
                {a.submitted ? <Status tone="good">Submitted</Status> : <Status tone="neutral">To do</Status>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Notices">
        {data.notices.length === 0 ? <Empty>No notices.</Empty> : (
          <ul className="space-y-3 text-sm">
            {data.notices.map((n) => (
              <li key={`${n.published_at}-${n.title}`}>
                <details>
                  <summary className="cursor-pointer font-medium">{n.title}</summary>
                  <p className="mt-1 whitespace-pre-line text-muted">{n.body}</p>
                </details>
                <p className="text-xs text-subtle">{formatDate(n.published_at)}{n.audience !== "all" && ` · ${n.audience}`}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Count({ shown, total }: { shown: number; total: number }) {
  return total > shown ? <span className="text-xs text-subtle">next {shown} of {total}</span> : null;
}

function Centered({ children }: { children: React.ReactNode }) {
  return <main className="flex flex-1 items-center justify-center p-8 text-sm text-muted">{children}</main>;
}
