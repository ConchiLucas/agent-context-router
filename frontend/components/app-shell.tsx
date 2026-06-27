import Link from "next/link";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/projects", label: "Projects" },
  { href: "/documents", label: "Documents" },
  { href: "/traces", label: "Traces" },
];

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "240px minmax(0, 1fr)",
        minHeight: "100vh",
      }}
    >
      <aside
        style={{
          borderRight: "1px solid var(--line)",
          background: "var(--panel)",
          padding: "1rem",
        }}
      >
        <strong>Agent Context Router</strong>
        <nav style={{ display: "grid", gap: "0.4rem", marginTop: "1rem" }}>
          {navItems.map((item) => (
            <Link className="badge" href={item.href} key={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main style={{ padding: "1.25rem", minWidth: 0 }}>{children}</main>
    </div>
  );
}

