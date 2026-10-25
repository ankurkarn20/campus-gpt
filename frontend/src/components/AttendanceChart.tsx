"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import type { CourseAttendance } from "@/lib/api";

// One series (attendance %), so one hue; courses below 75% switch to the critical status
// colour, and the table beside the chart repeats the status as text.
export function AttendanceChart({ courses }: { courses: CourseAttendance[] }) {
  return (
    <ResponsiveContainer width="100%" height={40 + courses.length * 36}>
      <BarChart data={courses} layout="vertical" margin={{ top: 24, right: 16, bottom: 0, left: 0 }} barCategoryGap={8}>
        <CartesianGrid horizontal={false} stroke="var(--grid)" />
        <XAxis
          type="number" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} unit="%"
          tick={{ fill: "var(--subtle)", fontSize: 12 }} axisLine={false} tickLine={false}
        />
        <YAxis
          type="category" dataKey="code" width={64}
          tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false}
        />
        <Tooltip
          cursor={{ fill: "var(--grid)", opacity: 0.4 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const c = payload[0].payload as CourseAttendance;
            return (
              <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-sm">
                <p className="font-medium">{c.title}</p>
                <p className="text-muted">
                  {c.percentage}% · {c.attended} of {c.held} classes
                </p>
              </div>
            );
          }}
        />
        <ReferenceLine
          x={75} stroke="var(--muted)" strokeDasharray="4 4"
          label={{ value: "75% required", position: "top", fill: "var(--muted)", fontSize: 11 }}
        />
        <Bar dataKey="percentage" radius={[0, 4, 4, 0]} maxBarSize={20}>
          {courses.map((c) => (
            <Cell key={c.code} fill={c.status === "short" ? "var(--critical)" : "var(--accent)"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
