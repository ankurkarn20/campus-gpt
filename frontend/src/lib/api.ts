// Types mirror the FastAPI responses in backend/campusgpt/api.

export type StudentProfile = {
  name: string;
  roll_no: string;
  program: string;
  semester: number;
  section: string;
};

export type Me = { email: string; role: "student" | "admin"; student: StudentProfile | null };

export type CourseAttendance = {
  code: string;
  title: string;
  held: number;
  attended: number;
  percentage: number;
  status: "ok" | "at_risk" | "short";
  classes_needed: number;
  can_miss: number;
};

export type UpcomingExam = {
  code: string;
  title: string;
  exam_type: "quiz" | "mid_term" | "end_term";
  starts_at: string;
  duration_minutes: number;
  room: string;
};

export type AssignmentDue = {
  code: string;
  course: string;
  title: string;
  due_at: string;
  max_marks: number;
  submitted: boolean;
};

export type Fee = {
  description: string;
  amount: number;
  paid: number;
  balance: number;
  due_date: string;
  status: "paid" | "pending" | "partially_paid" | "overdue" | "waived" | "cancelled";
};

export type NoticeItem = { title: string; body: string; published_at: string; audience: string };

export type ActionItem = {
  kind: "fee_overdue" | "attendance_short" | "exam" | "assignment" | "fee_due";
  title: string;
  detail: string;
  when: string | null;
};

export type CourseEligibility = {
  code: string;
  title: string;
  held: number;
  attended: number;
  percentage: number;
  classes_left: number;
  status: "safe" | "on_track" | "condonation_needed" | "debarred";
  attend_at_least: number;
  best_percentage: number;
};

export type Eligibility = {
  term: string;
  last_teaching_day: string;
  end_term_starts: string;
  admit_cards_from: string;
  admit_card_ok: boolean;
  fee_holds: { description: string; balance: number; due_date: string; overdue: boolean }[];
  courses: CourseEligibility[];
  condonation_limit_exceeded: boolean;
};

export type Dashboard = {
  today: string;
  this_week: ActionItem[];
  attendance: CourseAttendance[];
  exams: UpcomingExam[];
  assignments: AssignmentDue[];
  fees: Fee[];
  notices: NoticeItem[];
  eligibility: Eligibility;
};

export type AdminDocument = {
  id: number;
  title: string;
  category: string;
  version: number;
  status: "processing" | "active" | "superseded" | "failed";
  file_name: string;
  created_at: string;
  chunks: number;
  job: {
    state: "queued" | "processing" | "done" | "failed";
    progress: string | null;
    attempts: number;
    error: string | null;
    updated_at: string;
  } | null;
};

export type AuditEntry = {
  id: number;
  created_at: string;
  user: string | null;
  role: "student" | "admin" | null;
  action: string;
  tool_name: string | null;
  outcome: "success" | "denied" | "error";
  detail: Record<string, unknown> | null;
};

export type AuditPage = {
  entries: AuditEntry[];
  next_before: number | null;
  counts: { action: string; outcome: AuditEntry["outcome"]; count: number }[];
};

export type Attack = { id: string; category: string; prompt: string };

export type AttackResult = {
  id: string;
  category: string;
  prompt: string;
  answer: string;
  tools: { tool: string; arguments: Record<string, unknown>; ok: boolean }[];
  verdict: "blocked" | "leaked";
  leaks: string[];
  notes: string[];
  seconds: number;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    // FormData sets its own multipart content type (with the boundary).
    headers: init?.body instanceof FormData
      ? init.headers
      : { "content-type": "application/json", ...init?.headers },
    credentials: "same-origin",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const IST = "Asia/Kolkata";

export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", {
    timeZone: IST, weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit",
  });

export const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", {
    timeZone: IST, day: "numeric", month: "short", year: "numeric",
  });

export const formatRupees = (n: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(n);
