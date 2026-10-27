// Client for POST /api/chat, which answers with Server-Sent Events.
import { postEventStream } from "@/lib/sse";

export type ToolSource = {
  tool: string;
  arguments: Record<string, unknown>;
  result: unknown;
  ok: boolean;
};

// A [Document §n] reference in an answer; verified when a retrieved passage backs it.
export type Citation = { cite: string; verified: boolean };

export type ChatEvent =
  | { kind: "conversation"; data: { id: number } }
  | { kind: "status"; data: { text: string } }
  | { kind: "tool"; data: ToolSource }
  | { kind: "token"; data: { text: string } }
  | { kind: "done"; data: { message_id: number; conversation_id: number; citations: Citation[] } }
  | { kind: "error"; data: { message: string } };

export function streamChat(
  message: string,
  conversationId: number | null,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return postEventStream("/api/chat", { message, conversation_id: conversationId },
    (e) => onEvent(e as ChatEvent), signal);
}

// Plain-English names for the tools, shown on the "data used" chips.
export const TOOL_LABELS: Record<string, string> = {
  get_my_profile: "Your profile",
  get_my_attendance: "Attendance records",
  calculate_attendance_requirement: "Attendance calculator",
  get_my_classes: "Timetable",
  get_my_exams: "Exam schedule",
  get_my_assignments: "Assignments",
  get_my_fee_status: "Fee records",
  search_notices: "Notices",
  get_my_weekly_summary: "This week",
  check_end_term_eligibility: "End-term eligibility",
  search_university_documents: "University documents",
};
