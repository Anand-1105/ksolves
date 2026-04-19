"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/run", label: "Run All" },
  { href: "/audit", label: "Audit Log" },
  { href: "/learnings", label: "Learnings" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-border bg-bg-surface sticky top-0 z-50">
      <div className="flex items-center justify-between px-6 h-12">
        <div className="flex items-center gap-6">
          <span className="text-sm font-semibold text-text-primary tracking-tight">
            ShopWave<span className="text-accent"> Agent</span>
          </span>
          <nav className="flex items-center gap-1">
            {links.map((link) => {
              const active =
                link.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={clsx(
                    "px-3 py-1 text-xs rounded-input transition-colors",
                    active
                      ? "text-text-primary bg-bg-elevated"
                      : "text-text-muted hover:text-text-secondary hover:bg-bg-hover"
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </header>
  );
}
