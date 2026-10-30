import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { dateTime, ROLE_LABEL } from "../format";
import { useApp } from "../state";
import { LenderLogo, TenpaiMark } from "./ui";

const NAV = [
  { to: "/portfolio", label: "Portfolio health", roles: ["head_of_collections", "leadership"] },
  { to: "/today", label: "Today", roles: ["head_of_collections", "branch_manager", "credit_officer"] },
  { to: "/approvals", label: "Approvals", roles: ["head_of_collections", "branch_manager"] },
  { to: "/field-manager", label: "Field", roles: ["head_of_collections", "branch_manager"] },
  { to: "/field", label: "My visits", roles: ["credit_officer"] },
  { to: "/payments", label: "Payments", roles: ["head_of_collections", "branch_manager"] },
  { to: "/results", label: "Results", roles: ["head_of_collections", "leadership"] },
  { to: "/compliance", label: "Compliance", roles: ["head_of_collections", "branch_manager"] },
  { to: "/settings", label: "Settings", roles: ["head_of_collections"] },
];

export default function Layout() {
  const { meta, role } = useApp();
  const brand = meta?.tenant.brand ?? {};
  const loc = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => {
    setNavOpen(false);
  }, [loc.pathname]);

  return (
    <div className="flex min-h-full">
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-56 shrink-0 bg-slate text-white transition-transform md:static md:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="border-b border-white/10 px-4 py-4">
          <div className="flex items-center gap-2">
            <LenderLogo brand={brand} />
            <div className="min-w-0">
              <div className="truncate text-[14px] font-semibold leading-tight">{brand.lender_name ?? "…"}</div>
              <div className="local truncate text-[11px] text-white/60">{brand.lender_name_local}</div>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-[11px] text-white/50">
            <TenpaiMark size={13} />
            <span className="font-brand tracking-wide">tenpai</span>
          </div>
        </div>
        <nav className="py-2">
          {NAV.filter((n) => n.roles.includes(role)).map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `block px-4 py-2 text-[13px] ${isActive ? "bg-white/10 font-semibold text-white" : "text-white/75 hover:bg-white/5"}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      {navOpen && <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={() => setNavOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        {meta?.tenant.is_demo && (
          <div className="bg-warn-soft px-4 py-1 text-center text-[12px] font-medium text-[#7A5A1E]">
            Sample data. A fictional lender and borrowers; simulated results are labelled as simulated.
          </div>
        )}
        <TopBar onMenu={() => setNavOpen(true)} />
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { meta, tenant, setTenant, role, userId, setRole } = useApp();
  const scoped = role === "branch_manager" || role === "credit_officer";
  const people = meta?.users.filter((u) => u.role === role) ?? [];
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-sage-pale bg-white px-4 py-2">
      <button className="btn md:hidden" onClick={onMenu} aria-label="Menu">
        ☰
      </button>
      <div className="text-[12px] text-slate/70">
        <span className="font-medium text-slate">{dateTime(meta?.tenant.now, meta?.tenant.timezone)}</span>{" "}
        {meta?.tenant.timezone} · policy v{meta?.tenant.policy_version}
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <select className="input" value={tenant} onChange={(e) => setTenant(e.target.value)} title="Lender (tenant)">
          <option value="mm-demo">Myanmar demo</option>
          <option value="kh-demo">Cambodia demo</option>
        </select>
        <select
          className="input"
          value={role}
          onChange={(e) => setRole(e.target.value, undefined)}
          title="Role (demo role picker)"
        >
          {Object.entries(ROLE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        {scoped && (
          <select
            className="input max-w-[220px]"
            value={userId ?? meta?.user?.id ?? ""}
            onChange={(e) => setRole(role, Number(e.target.value))}
          >
            {people.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
                {u.branch_id ? ` · ${meta?.branches.find((b) => b.id === u.branch_id)?.name ?? ""}` : ""}
              </option>
            ))}
          </select>
        )}
        {meta?.tenant.is_demo && <DemoMenu />}
      </div>
    </div>
  );
}

function DemoMenu() {
  const { refresh, meta } = useApp();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string>();
  const [note, setNote] = useState<string>();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try {
      const out: any = await fn();
      if (out?.runs) {
        const r = out.runs[out.runs.length - 1];
        setNote(`Day run: ${r.reminders} reminders, ${r.invites} invites, ${r.visits_assigned} visits, ${r.promises_broken} promises broken`);
      } else setNote(`${label}: done`);
      refresh();
    } catch (e: any) {
      setNote(`${label} failed: ${e.message}`);
    } finally {
      setBusy(undefined);
    }
  };
  return (
    <div className="relative" ref={ref}>
      <button className="btn border-warn bg-warn-soft" onClick={() => setOpen(!open)}>
        Demo ▾
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-72 rounded-md border border-sage-pale bg-white p-2 shadow-lg">
          <div className="mb-1 px-1 text-[11px] text-slate/60">Clock: {dateTime(meta?.tenant.now, meta?.tenant.timezone)}</div>
          {[
            ["Advance clock one day", () => api.post("/demo/advance")],
            ["Run today's job now", () => api.post("/demo/run-daily")],
            ["Set time to 20:30 (quiet hours)", () => api.post("/demo/set-time", { hh: 20, mm: 30 })],
            ["Set time to 09:30", () => api.post("/demo/set-time", { hh: 9, mm: 30 })],
          ].map(([label, fn]) => (
            <button
              key={label as string}
              disabled={!!busy}
              className="block w-full rounded px-2 py-1.5 text-left hover:bg-bg"
              onClick={() => run(label as string, fn as () => Promise<unknown>)}
            >
              {busy === label ? "Working…" : (label as string)}
            </button>
          ))}
          <button
            disabled={!!busy}
            className="mt-1 block w-full rounded px-2 py-1.5 text-left text-danger hover:bg-danger-soft"
            onClick={() => confirm("Reset the demo tenant to fresh sample data?") && run("Reset demo tenant", () => api.post("/demo/reset"))}
          >
            {busy === "Reset demo tenant" ? "Resetting (about 30s)…" : "Reset demo tenant"}
          </button>
          <div className="mt-1 border-t border-sage-pale px-1 pt-1 text-[11px] text-slate/60">
            Borrower replies and payments: open a borrower and use the phone panel.
          </div>
          {note && <div className="mt-1 rounded bg-bg px-2 py-1 text-[11px]">{note}</div>}
        </div>
      )}
    </div>
  );
}
