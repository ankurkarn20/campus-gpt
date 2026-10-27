"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AdminShell } from "@/components/AdminShell";
import { Card, Empty, Status, type Tone } from "@/components/ui";
import { api, ApiError, formatDateTime, type AdminDocument } from "@/lib/api";

// Mirrors campusgpt.documents.CATEGORIES.
const CATEGORIES = ["academic", "examinations", "fees", "hostel", "scholarships", "notices", "other"];
const ACCEPT = ".md,.txt,.pdf";
const POLL_MS = 2000;

const DOC_STATUS: Record<AdminDocument["status"], [Tone, string]> = {
  processing: ["warning", "Processing"],
  active: ["good", "Active"],
  superseded: ["neutral", "Superseded"],
  failed: ["critical", "Failed"],
};

const inProgress = (d: AdminDocument) => d.job?.state === "queued" || d.job?.state === "processing";

/** "hostel-rules_v2.pdf" -> "Hostel Rules V2" */
const titleFromFileName = (name: string) =>
  name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).trim();

export default function AdminPage() {
  return (
    <AdminShell title="Policy documents">
      <Documents />
    </AdminShell>
  );
}

function Documents() {
  const [docs, setDocs] = useState<AdminDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() =>
    api<AdminDocument[]>("/api/admin/documents").then(setDocs).catch((err) =>
      setError(err instanceof Error ? err.message : "Something went wrong")), []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Follow ingestion live: poll while any job is still queued or running.
  const busy = docs?.some(inProgress) ?? false;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  if (error) return <Empty>Could not load the documents: {error}</Empty>;
  if (!docs) return <Empty>Loading…</Empty>;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <UploadForm onUploaded={refresh} />
      <Card
        title="Documents" className="lg:col-span-2"
        action={busy && <span className="text-xs text-subtle">Updating every {POLL_MS / 1000} s…</span>}
      >
        {docs.length === 0 ? <Empty>No documents yet.</Empty> : <DocumentTable docs={docs} />}
      </Card>
    </div>
  );
}

function UploadForm({ onUploaded }: { onUploaded: () => Promise<void> }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("other");
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  function choose(f: File | null) {
    setFile(f);
    setMessage(null);
    if (f && !title) setTitle(titleFromFileName(f.name));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("title", title);
    body.append("category", category);
    setSending(true);
    try {
      const doc = await api<AdminDocument>("/api/admin/documents", { method: "POST", body });
      setMessage({ ok: true, text: `Queued “${doc.title}” (version ${doc.version}).` });
      setFile(null);
      setTitle("");
      if (fileInput.current) fileInput.current.value = "";
      await onUploaded();
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : "Could not reach the server" });
    } finally {
      setSending(false);
    }
  }

  const field = "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-accent";
  return (
    <Card title="Upload a document">
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm">
          <span className="font-medium">File</span>
          <input
            ref={fileInput} type="file" accept={ACCEPT} required
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
            className={`${field} file:mr-3 file:rounded file:border-0 file:bg-surface file:px-2 file:py-1 file:text-sm`}
          />
          <span className="mt-1 block text-xs text-subtle">Markdown, text or PDF with selectable text, up to 10 MB.</span>
        </label>
        <label className="block text-sm">
          <span className="font-medium">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} maxLength={200} className={field} />
          <span className="mt-1 block text-xs text-subtle">Reusing an existing title uploads a new version of it.</span>
        </label>
        <label className="block text-sm">
          <span className="font-medium">Category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={field}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>)}
          </select>
        </label>
        {message && (
          <p role={message.ok ? "status" : "alert"} className={`text-sm ${message.ok ? "text-good-text" : "text-critical"}`}>
            {message.text}
          </p>
        )}
        <button
          type="submit" disabled={sending || !file}
          className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {sending ? "Uploading…" : "Upload"}
        </button>
      </form>
    </Card>
  );
}

function DocumentTable({ docs }: { docs: AdminDocument[] }) {
  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[36rem] text-sm">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 font-medium">Document</th>
            <th className="py-2 pr-3 font-medium">Status</th>
            <th className="py-2 pr-3 font-medium">Ingestion</th>
            <th className="py-2 text-right font-medium">Chunks</th>
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => {
            const [tone, label] = DOC_STATUS[d.status];
            return (
              <tr key={d.id} className="border-b border-border align-top last:border-0">
                <td className="py-2.5 pr-3">
                  <p className="font-medium">{d.title}</p>
                  <p className="text-xs text-subtle">
                    v{d.version} · {d.category} · {d.file_name} · {formatDateTime(d.created_at)}
                  </p>
                </td>
                <td className="py-2.5 pr-3"><Status tone={tone}>{label}</Status></td>
                <td className="py-2.5 pr-3 text-xs">
                  <JobCell job={d.job} />
                </td>
                <td className="py-2.5 text-right tabular-nums">{d.chunks}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function JobCell({ job }: { job: AdminDocument["job"] }) {
  if (!job) return <span className="text-subtle">Bundled with the system</span>;
  if (job.state === "failed") return <span className="text-critical">{job.error}</span>;
  const retry = job.attempts > 1 ? ` (attempt ${job.attempts})` : "";
  return (
    <span className={job.state === "done" ? "text-muted" : "text-foreground"}>
      {job.state === "processing" && <span aria-hidden className="mr-1.5 inline-block size-2 animate-pulse rounded-full bg-warning" />}
      {(job.progress ?? job.state) + retry}
      {job.state === "queued" && job.error && <span className="block text-subtle">Last error: {job.error}</span>}
    </span>
  );
}
