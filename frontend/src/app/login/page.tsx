"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, ApiError, type Me } from "@/lib/api";

const DEMO_ACCOUNTS = [
  ["student.regular@demo.campusgpt.example", "Regular student"],
  ["student.shortage@demo.campusgpt.example", "Attendance shortage"],
  ["student.fees@demo.campusgpt.example", "Fees overdue"],
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<Me>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server");
      setBusy(false);
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold">CampusGPT</h1>
        <p className="mt-1 text-sm text-muted">Sign in with your university account.</p>

        <form onSubmit={submit} className="mt-6 space-y-4 rounded-xl border border-border bg-surface p-6">
          <label className="block text-sm">
            <span className="font-medium">Email</span>
            <input
              type="email" required autoComplete="username" value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 outline-none focus:ring-2 focus:ring-accent"
            />
          </label>
          <label className="block text-sm">
            <span className="font-medium">Password</span>
            <input
              type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 outline-none focus:ring-2 focus:ring-accent"
            />
          </label>
          {error && (
            <p role="alert" className="text-sm text-critical">{error}</p>
          )}
          <button
            type="submit" disabled={busy}
            className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="mt-6 text-xs text-muted">
          <p className="font-medium">Demo accounts (synthetic data)</p>
          <ul className="mt-1 space-y-1">
            {DEMO_ACCOUNTS.map(([addr, label]) => (
              <li key={addr}>
                <button type="button" onClick={() => setEmail(addr)} className="underline-offset-2 hover:underline">
                  {label}
                </button>{" "}
                <span className="text-subtle">{addr}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </main>
  );
}
