// Client for POST /api/chat, which answers with Server-Sent Events. EventSource only
// supports GET, so the stream is read from fetch() and parsed here.

export type ToolSource = {
  tool: string;
  arguments: Record<string, unknown>;
  result: unknown;
  ok: boolean;
};

export type ChatEvent =
  | { kind: "conversation"; data: { id: number } }
  | { kind: "status"; data: { text: string } }
  | { kind: "tool"; data: ToolSource }
  | { kind: "token"; data: { text: string } }
  | { kind: "done"; data: { message_id: number; conversation_id: number } }
  | { kind: "error"; data: { message: string } };

export async function streamChat(
  message: string,
  conversationId: number | null,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    credentials: "same-origin",
    signal,
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${res.status})`);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let kind = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) kind = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent({ kind, data: JSON.parse(data.join("\n")) } as ChatEvent);
    }
  }
}

// Plain-English names for the tools, shown on the "data used" chips.
export const TOOL_LABELS: Record<string, string> = {
  get_my_profile: "Your profile",
  get_my_attendance: "Attendance records",
  calculate_attendance_requirement: "Attendance calculator",
  get_my_exams: "Exam schedule",
  get_my_assignments: "Assignments",
  get_my_fee_status: "Fee records",
  search_notices: "Notices",
  get_my_weekly_summary: "This week",
  search_university_documents: "University documents",
};
