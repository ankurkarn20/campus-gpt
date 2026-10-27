"use client";

import { useChat } from "@/components/ChatPanel";
import { Card, Empty } from "@/components/ui";
import { formatDateTime, type ClassMeeting, type ClassSlot } from "@/lib/api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];
const hhmm = (t: string) => t.slice(0, 5);

/** The weekly timetable as a grid (times down, days across), with the next class above it
 *  and highlighted in the grid. */
export function TimetableCard({ slots, next }: { slots: ClassSlot[]; next: ClassMeeting[] }) {
  const chat = useChat();
  const times = [...new Set(slots.map((s) => s.starts_at))].sort();
  const at = (weekday: number, time: string) => slots.find((s) => s.weekday === weekday && s.starts_at === time);
  const upcoming = next[0];
  const isNext = (s: ClassSlot) =>
    !!upcoming && s.code === upcoming.code && s.day === upcoming.day && s.starts_at === upcoming.starts_at.slice(11, 19);

  return (
    <Card
      title="Timetable" className="lg:col-span-3"
      action={<button onClick={() => chat.open("When is my next class?")} className="text-xs text-accent hover:underline">Ask</button>}
    >
      {slots.length === 0 ? <Empty>No timetable yet.</Empty> : (
        <>
          <p className="mb-3 text-sm">
            {upcoming ? (
              <>
                <span className="text-muted">Next: </span>
                <span className="font-medium">{upcoming.title}</span>
                <span className="text-muted"> · {formatDateTime(upcoming.starts_at)} · Room {upcoming.room} · {upcoming.faculty}</span>
              </>
            ) : <span className="text-muted">No more classes this term.</span>}
          </p>
          <div className="-mx-5 overflow-x-auto px-5">
            <table className="w-full min-w-[40rem] table-fixed border-collapse text-xs">
              <thead>
                <tr className="text-left text-muted">
                  <th className="w-14 py-1 font-medium" />
                  {DAYS.map((d) => <th key={d} className="px-1 py-1 font-medium">{d}</th>)}
                </tr>
              </thead>
              <tbody>
                {times.map((t) => (
                  <tr key={t} className="border-t border-border">
                    <td className="py-1.5 pr-2 align-top tabular-nums text-muted">{hhmm(t)}</td>
                    {DAYS.map((_, wd) => {
                      const s = at(wd, t);
                      return (
                        <td key={wd} className="p-1 align-top">
                          {s && (
                            <div
                              title={`${s.title}, ${hhmm(s.starts_at)}–${hhmm(s.ends_at)}, room ${s.room}, ${s.faculty}`}
                              className={`rounded-md border px-1.5 py-1 ${isNext(s) ? "border-accent bg-accent/10" : "border-border bg-background"}`}
                            >
                              <p className="truncate font-medium">{s.title}</p>
                              <p className="truncate text-muted">{s.code} · {s.room}</p>
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
