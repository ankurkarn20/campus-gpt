"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { api, ApiError, type Me } from "@/lib/api";

const PAGES = [
  ["/admin", "Documents"],
  ["/admin/audit", "Audit log"],
  ["/admin/security", "Security"],
] as const;

/** Header, navigation and the admin-only check shared by the admin pages. Children render
 *  only once the user is known to be an administrator. */
export function AdminShell({ title, children }: { title: string; children: ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Me>("/api/auth/me").then((who) => {
      if (who.role !== "admin") router.replace("/dashboard");
      else setMe(who);
    }).catch((err) => {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(err instanceof Error ? err.message : "Something went wrong");
    });
  }, [router]);

  async function logout() {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }

  if (error) return <Centered>Could not load the admin console: {error}</Centered>;
  if (!me) return <Centered>Loading…</Centered>;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted">CampusGPT · Administrator · {me.email}</p>
          <h1 className="text-2xl font-semibold">{title}</h1>
        </div>
        <button onClick={logout} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface">
          Log out
        </button>
      </header>
      <nav className="mb-6 flex gap-1 overflow-x-auto border-b border-border text-sm">
        {PAGES.map(([href, label]) => (
          <Link
            key={href} href={href}
            aria-current={path === href ? "page" : undefined}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 ${path === href ? "border-accent font-medium text-foreground" : "border-transparent text-muted hover:text-foreground"}`}
          >
            {label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}

export function Centered({ children }: { children: ReactNode }) {
  return <main className="flex flex-1 items-center justify-center p-8 text-sm text-muted">{children}</main>;
}
