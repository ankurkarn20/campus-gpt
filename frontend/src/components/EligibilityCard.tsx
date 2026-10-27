"use client";

import { useChat } from "@/components/ChatPanel";
import { Card, Status, type Tone } from "@/components/ui";
import { formatDate, formatRupees, type CourseEligibility, type Eligibility } from "@/lib/api";

// A course where the student can still miss this many classes or fewer is shown as a warning.
const TIGHT = 2;

function outlook(c: CourseEligibility): [Tone, string, string] {
  const spare = c.classes_left - c.attend_at_least;
  switch (c.status) {
    case "safe":
      return ["good", "Eligible", `Above 75% even if you miss all ${c.classes_left} classes left`];
    case "on_track":
      return [spare <= TIGHT ? "warning" : "good", spare === 0 ? "Attend every class" : `Can miss ${spare}`,
        `Attend at least ${c.attend_at_least} of the ${c.classes_left} classes left`];
    case "condonation_needed":
      return ["warning", "Needs condonation",
        `At most ${c.best_percentage}% even attending all ${c.classes_left}: only condonation (65–75%) can save it`];
    case "debarred":
      return ["critical", "Will be debarred",
        `At most ${c.best_percentage}% even attending every class: below the 65% condonation limit`];
  }
}

export function EligibilityCard({ data }: { data: Eligibility }) {
  const chat = useChat();
  return (
    <Card
      title="End-term eligibility" className="lg:col-span-3"
      action={
        <button onClick={() => chat.open("Am I eligible to sit all my end-term exams?")} className="text-xs text-accent hover:underline">
          Ask
        </button>
      }
    >
      <p className="mb-3 text-sm text-muted">
        Classes end {formatDate(data.last_teaching_day)}; end-term exams start {formatDate(data.end_term_starts)}.
        Forecast from your attendance so far and the classes still to come.
      </p>

      <div className="mb-4 rounded-lg border border-border bg-background p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium">Admit card (issued from {formatDate(data.admit_cards_from)})</p>
          {data.admit_card_ok
            ? <Status tone="good">No fee holds</Status>
            : <Status tone="critical">Blocked by unpaid fees</Status>}
        </div>
        {data.fee_holds.length > 0 && (
          <ul className="mt-1 text-muted">
            {data.fee_holds.map((h) => (
              <li key={h.description}>
                Pay {formatRupees(h.balance)}: {h.description} ({h.overdue ? "overdue since" : "due"} {formatDate(h.due_date)})
              </li>
            ))}
          </ul>
        )}
      </div>

      <ul className="grid gap-x-6 sm:grid-cols-2">
        {data.courses.map((c) => {
          const [tone, label, detail] = outlook(c);
          return (
            <li key={c.code} className="flex items-start justify-between gap-3 border-b border-border py-2.5 text-sm">
              <div>
                <p className="font-medium"><span className="font-normal text-muted">{c.code}</span> {c.title}</p>
                <p className="text-muted">{c.attended}/{c.held} now ({c.percentage}%) · {detail}</p>
              </div>
              <Status tone={tone}>{label}</Status>
            </li>
          );
        })}
      </ul>
      {data.condonation_limit_exceeded && (
        <p role="alert" className="mt-3 text-sm text-critical">
          More than two courses need condonation, but at most two can be condoned in a term.
        </p>
      )}
    </Card>
  );
}
