import { Fragment, useState, useEffect, useCallback, useMemo } from "react";
import { listIncidents, getIncident, getOverview, listDocuments, createIncident, reviewIncident, mediaUrl, getRunOutput } from "./api";
import { ZONES, TYPES } from "./mock";
import { Btn, inp } from "./ui";
import { ReportPage } from "./ReportPage";

const ICONS = {
  home: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z", bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  review: "M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9", file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8",
  plus: "M12 5v14M5 12h14", right: "M9 6l6 6-6 6", down: "M6 9l6 6 6-6", left: "M15 6l-6 6 6 6", clock: "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3", x: "M6 6l12 12M18 6L6 18", lock: "M7 11V8a5 5 0 0 1 10 0v3M5 11h14v10H5z",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  sun: "M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
};
const STATUS = {
  new: ["New", "border-red-900 bg-red-950/60 text-red-300"], in_review: ["In review", "border-amber-900 bg-amber-950/60 text-amber-300"],
  approved: ["Approved", "border-blue-900 bg-blue-950/60 text-blue-300"], rejected: ["Rejected", "border-neutral-700 bg-neutral-800 text-neutral-300"],
  closed: ["Closed", "border-emerald-900 bg-emerald-950/60 text-emerald-300"],
};
const PRI = { P1: "bg-red-700", P2: "bg-orange-700", P3: "bg-yellow-600" };
const CAT = { near_miss: "Near miss", first_aid_case: "First-aid case", recordable_injury: "Recordable injury", serious_injury: "Serious injury", no_classification_needed: "No classification needed" };
const ACTIVE = ["new", "in_review", "approved"];
const NAV = [["dashboard", "Dashboard", "home"], ["report", "Report an incident", "mic"], ["incidents", "Incidents", "bolt"], ["reviews", "Review queue", "review"], ["documents", "Documents", "file"]];

const rel = (iso) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (m < 1) return "just now"; if (m < 60) return `${m} minutes ago`;
  const h = Math.round(m / 60); if (h < 24) return `${h} hour${h > 1 ? "s" : ""} ago`;
  const d = Math.round(h / 24); return `${d} day${d > 1 ? "s" : ""} ago`;
};
const fmt = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const Icon = ({ n, c = "h-5 w-5" }) => (
  <svg viewBox="0 0 24 24" className={c} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={ICONS[n]} /></svg>
);
const Pri = ({ p }) => <span className={`rounded px-2 py-0.5 text-xs font-semibold text-white ${PRI[p]}`}>{p}</span>;
const Pill = ({ s }) => (
  <span className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ${STATUS[s][1]}`}><Icon n="clock" c="h-3.5 w-3.5" />{STATUS[s][0]}</span>
);
const Chip = ({ children, tone = "bg-[#2a2a2a] text-neutral-300" }) => <span className={`rounded-full px-3 py-1 text-xs ${tone}`}>{children}</span>;
const Panel = ({ title, action, children, className = "" }) => (
  <section className={`rounded-xl bg-[#1a1a1a] p-4 ${className}`}>
    {(title || action) && <div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-medium text-neutral-200">{title}</h3>{action}</div>}
    {children}
  </section>
);
const Field = ({ label, children }) => <label className="block text-sm text-neutral-400"><span className="mb-1 block">{label}</span>{children}</label>;
const Skeleton = () => <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-[#1a1a1a]" />)}</div>;

function Spark({ data, id }) {
  const w = 240, h = 64, max = Math.max(...data), min = Math.min(...data), r = max - min || 1;
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, h - 6 - ((v - min) / r) * (h - 18)]);
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) { const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], mx = (x0 + x1) / 2; d += ` C${mx},${y0} ${mx},${y1} ${x1},${y1}`; }
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-16 w-full" aria-hidden="true">
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#2563eb" stopOpacity="0.04" /><stop offset="1" stopColor="#1d4ed8" stopOpacity="0.6" /></linearGradient></defs>
      <path d={`${d} L${w},${h} L0,${h} Z`} fill={`url(#${id})`} /><path d={d} fill="none" stroke="#3b5bff" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
const Kpi = ({ label, value, data, id }) => (
  <div className="overflow-hidden rounded-xl bg-[#1a1a1a]"><div className="px-4 pt-3"><p className="text-sm text-neutral-300">{label}</p><p className="text-2xl font-medium text-white">{value}</p></div><Spark data={data} id={id} /></div>
);

// Light / dark theme. The choice is remembered in this browser; the inline script in index.html applies it before the page paints.
function useTheme() {
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem("theme") === "light" ? "light" : "dark"; } catch { return "dark"; } });
  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    try { localStorage.setItem("theme", theme); } catch { /* storage blocked: the theme still works for this visit */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "light" ? "dark" : "light"))];
}
const ThemeToggle = ({ theme, onToggle, className = "" }) => (
  <button onClick={onToggle} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`} title={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
    className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-neutral-400 transition hover:bg-[#1e1e1e] hover:text-neutral-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${className}`}>
    <Icon n={theme === "light" ? "moon" : "sun"} c="h-4 w-4" />{theme === "light" ? "Dark theme" : "Light theme"}
  </button>
);

function Shell({ route, go, counts, children, onCreate }) {
  const [theme, toggleTheme] = useTheme();
  return (
    <div className="min-h-screen bg-black text-neutral-200 lg:flex">
      <aside className="hidden w-64 shrink-0 p-3 lg:block">
        <div className="sticky top-3 flex h-[calc(100vh-1.5rem)] flex-col rounded-2xl bg-[#141414] p-4">
          <div className="mb-6 flex items-center gap-2 px-2 pt-2 text-white"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600"><Icon n="bolt" c="h-4 w-4" /></span><span className="text-lg font-semibold tracking-wide">AmbientWatch</span></div>
          <nav className="space-y-1" aria-label="Main">
            {NAV.map(([k, label, ic]) => (
              <button key={k} onClick={() => go(k)} aria-current={route[0] === k ? "page" : undefined}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${route[0] === k ? "bg-[#262626] text-white" : "text-neutral-400 hover:bg-[#1e1e1e] hover:text-neutral-200"}`}>
                <Icon n={ic} />{label}{k === "reviews" && counts.review > 0 && <span className="ml-auto rounded-full bg-amber-900/70 px-2 text-xs text-amber-200">{counts.review}</span>}
              </button>
            ))}
          </nav>
          <ThemeToggle theme={theme} onToggle={toggleTheme} className="mt-auto w-full" />
          <p className="mt-2 px-2 text-xs text-neutral-600">WH-07 Columbus<br />Signed in as P. Natarajan (Safety reviewer)</p>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <nav className="flex gap-1 overflow-x-auto border-b border-white/10 p-2 lg:hidden" aria-label="Main">
          {NAV.map(([k, label]) => <button key={k} onClick={() => go(k)} className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm ${route[0] === k ? "bg-[#262626] text-white" : "text-neutral-400"}`}>{label}</button>)}
          <ThemeToggle theme={theme} onToggle={toggleTheme} className="ml-auto whitespace-nowrap" />
        </nav>
        <main className="p-4 lg:p-6 lg:pl-3">{children}</main>
      </div>
    </div>
  );
}

function IncidentCard({ inc, onOpen }) {
  return (
    <button onClick={() => onOpen(inc.incident_id)} className="block w-full rounded-xl bg-[#1a1a1a] p-4 text-left transition hover:bg-[#202020] focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400">
      <div className="flex items-center justify-between gap-3"><div className="flex min-w-0 items-center gap-3"><Pri p={inc.priority} /><span className="truncate font-medium text-white">{inc.title}</span></div><Pill s={inc.status} /></div>
      <div className="mt-4 flex flex-wrap items-end justify-between gap-4 text-xs text-neutral-400">
        <div><p className="mb-2">Affected areas</p><div className="flex flex-wrap gap-2">{inc.affected.map((a) => <Chip key={a}>{a}</Chip>)}</div></div>
        <div className="flex gap-6"><div><p className="mb-2">Active since</p><Chip>{rel(inc.occurred_at)}</Chip></div><div><p className="mb-2">Assigned to</p><Chip>{inc.assigned_to}</Chip></div></div>
      </div>
    </button>
  );
}

export function Dashboard({ incidents, overview, go, setZone, onCreate }) {
  const active = incidents.filter((i) => ACTIVE.includes(i.status)).sort((a, b) => a.priority.localeCompare(b.priority) || new Date(b.occurred_at) - new Date(a.occurred_at));
  const sp = overview.sparks;
  const zoneState = (z) => { const o = active.filter((i) => i.zone_id === z); return [o.length, o.some((i) => i.priority === "P1") ? "bg-red-500" : o.length ? "bg-amber-400" : "bg-emerald-500"]; };
  return (
    <div className="space-y-6">
      <h1 className="text-sm text-neutral-400">Dashboard</h1>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Active incidents" value={active.length} data={sp.open} id="k1" />
        <Kpi label="Awaiting review" value={incidents.filter((i) => ["new", "in_review"].includes(i.status) && i.report).length} data={sp.review} id="k2" />
        <Kpi label="Resolved (30 days)" value={overview.resolved30d} data={sp.resolved} id="k3" />
        <Kpi label="Mean time to review" value={overview.meanReview} data={sp.tta} id="k4" />
        <Kpi label="Mean time to close" value={overview.meanClose} data={sp.ttr} id="k5" />
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <section>
          <div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-medium text-white">Active incidents</h2><Btn onClick={onCreate}><Icon n="plus" c="h-4 w-4" />Create incident</Btn></div>
          <div className="space-y-3">{active.length ? active.map((i) => <IncidentCard key={i.incident_id} inc={i} onOpen={(id) => go("incidents", id)} />) : <p className="rounded-xl bg-[#1a1a1a] p-6 text-sm text-neutral-400">No active incidents.</p>}</div>
        </section>
        <section className="space-y-6">
          <div><h2 className="mb-3 text-lg font-medium text-white">Zone status</h2>
            <div className="grid grid-cols-2 gap-3">
              {ZONES.map((z) => { const [n, dot] = zoneState(z); return (
                <button key={z} onClick={() => { setZone(z); go("incidents"); }} className="flex items-center gap-3 rounded-xl bg-[#1a1a1a] px-4 py-3 text-left text-sm transition hover:bg-[#202020]">
                  <span className={`h-2.5 w-2.5 rounded-full ${dot}`} /><span className="flex-1">{z}</span><span className="text-xs text-neutral-500">{n || ""}</span><Icon n="right" c="h-4 w-4 text-neutral-500" />
                </button>); })}
            </div></div>
          <div><h2 className="mb-3 text-lg font-medium text-white">System health</h2>
            <div className="space-y-2">{overview.pipeline.map((p) => (
              <div key={p.name} className="flex items-center gap-3 rounded-xl bg-[#1a1a1a] px-4 py-3 text-sm"><span className={`h-2.5 w-2.5 rounded-full ${p.state === "ok" ? "bg-emerald-500" : "bg-amber-400"}`} /><span className="flex-1">{p.name}</span>{p.note && <span className="text-xs text-amber-300">{p.note}</span>}</div>))}</div></div>
        </section>
      </div>
    </div>
  );
}

export function IncidentsPage({ incidents, go, title, preset, zone, setZone }) {
  const [q, setQ] = useState(""); const [st, setSt] = useState(preset || "all"); const [pri, setPri] = useState("all");
  useEffect(() => setSt(preset || "all"), [preset]);
  const rows = useMemo(() => incidents.filter((i) =>
    (st === "all" || i.status === st) && (pri === "all" || i.priority === pri) && (!zone || i.zone_id === zone) &&
    (!q || `${i.incident_id} ${i.title} ${i.zone_id} ${i.incident_type}`.toLowerCase().includes(q.toLowerCase()))), [incidents, q, st, pri, zone]);
  return (
    <div className="space-y-4">
      <h1 className="text-sm text-neutral-400">{title}</h1>
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1"><span className="pointer-events-none absolute left-3 top-2.5 text-neutral-500"><Icon n="search" c="h-4 w-4" /></span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by ID, title, zone or type" aria-label="Search incidents" className={`${inp} pl-9`} /></div>
        <select value={pri} onChange={(e) => setPri(e.target.value)} aria-label="Priority" className={`${inp} w-auto`}><option value="all">All priorities</option>{["P1", "P2", "P3"].map((p) => <option key={p}>{p}</option>)}</select>
        {zone && <button onClick={() => setZone(null)} className="inline-flex items-center gap-1 rounded-full bg-blue-950 px-3 py-1.5 text-xs text-blue-200">{zone}<Icon n="x" c="h-3 w-3" /></button>}
      </div>
      {!preset && <div className="flex flex-wrap gap-2">{["all", ...Object.keys(STATUS)].map((s) => (
        <button key={s} onClick={() => setSt(s)} className={`rounded-full px-3 py-1 text-xs transition ${st === s ? "bg-blue-600 text-white" : "bg-[#1a1a1a] text-neutral-400 hover:text-neutral-200"}`}>{s === "all" ? "All" : STATUS[s][0]}</button>))}</div>}
      <div className="overflow-hidden rounded-xl bg-[#1a1a1a]">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-white/10 text-xs text-neutral-500"><tr><th className="px-4 py-3 font-medium">Incident</th><th className="hidden px-4 py-3 font-medium md:table-cell">Zone</th><th className="hidden px-4 py-3 font-medium lg:table-cell">Type</th><th className="px-4 py-3 font-medium">Status</th><th className="hidden px-4 py-3 font-medium md:table-cell">Assigned</th><th className="hidden px-4 py-3 font-medium lg:table-cell">Active since</th></tr></thead>
          <tbody>{rows.map((i) => (
            <tr key={i.incident_id} onClick={() => go("incidents", i.incident_id)} className="cursor-pointer border-b border-white/5 transition last:border-0 hover:bg-[#202020]">
              <td className="px-4 py-3"><div className="flex items-center gap-3"><Pri p={i.priority} /><div className="min-w-0"><button className="block truncate text-left font-medium text-white focus:outline-none focus-visible:underline" onClick={(e) => { e.stopPropagation(); go("incidents", i.incident_id); }}>{i.title}</button><span className="font-mono text-xs text-neutral-500">{i.incident_id}</span></div></div></td>
              <td className="hidden px-4 py-3 text-neutral-300 md:table-cell">{i.zone_id}</td><td className="hidden px-4 py-3 text-neutral-300 lg:table-cell">{i.incident_type}</td>
              <td className="px-4 py-3"><Pill s={i.status} /></td><td className="hidden px-4 py-3 text-neutral-300 md:table-cell">{i.assigned_to}</td><td className="hidden px-4 py-3 text-neutral-400 lg:table-cell">{rel(i.occurred_at)}</td></tr>))}</tbody>
        </table>
        {!rows.length && <p className="p-8 text-center text-sm text-neutral-500">No incidents match these filters.</p>}
      </div>
    </div>
  );
}

const Dl = ({ rows }) => <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-sm">{rows.map(([k, v]) => [<dt key={k} className="text-neutral-500">{k}</dt>, <dd key={k + "v"} className="min-w-0 break-words text-neutral-200">{v ?? "n/a"}</dd>])}</dl>;
const Th = ({ cols }) => <thead className="text-xs text-neutral-500"><tr>{cols.map((c) => <th key={c} className="pb-2 pr-4 font-medium">{c}</th>)}</tr></thead>;
const List = ({ items, empty = "None recorded." }) => items?.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-neutral-300">{items.map((t, i) => <li key={i}>{t}</li>)}</ul> : <p className="text-sm text-neutral-500">{empty}</p>;

// Photo, audio and video kept as evidence, shown in the page. Needs the real backend (VITE_API_URL); seed data has no files.
function EvidenceViewer({ inc }) {
  const items = inc.evidence.filter((e) => e.has_file && mediaUrl(inc.incident_id, e.asset_id));
  if (!items.length) return null;
  return <div className="mb-4 grid gap-3 md:grid-cols-2">{items.map((e) => {
    const u = mediaUrl(inc.incident_id, e.asset_id);
    return <div key={e.asset_id} className="rounded-lg bg-[#111] p-3"><p className="mb-2 text-xs text-neutral-400">{e.type} · {e.name}</p>
      {e.type === "photo" ? <a href={u} target="_blank" rel="noreferrer"><img src={u} alt={e.name} className="max-h-72 w-full rounded object-contain" /></a>
        : e.type === "audio" ? <audio controls preload="metadata" src={u} className="w-full" />
        : e.type === "video" ? <video controls preload="metadata" src={u} className="max-h-72 w-full rounded" />
        : <a href={u} target="_blank" rel="noreferrer" className="text-sm text-blue-300 underline">Open {e.name}</a>}</div>;
  })}</div>;
}

// One row per agent with its metrics; open a row to see what that agent produced.
function AgentRuns({ inc }) {
  const [open, setOpen] = useState(null); const [out, setOut] = useState({}); const [err, setErr] = useState("");
  const toggle = async (id) => {
    if (open === id) return setOpen(null);
    setOpen(id); setErr("");
    if (!(id in out)) { try { const r = await getRunOutput(inc.incident_id, id); setOut((o) => ({ ...o, [id]: r.output })); } catch (e) { setErr(String(e.message || e)); } }
  };
  const tok = (m) => (!m ? "" : m.total_tokens != null ? `${m.input_tokens} in / ${m.output_tokens} out` : "n/a (code step)");
  if (!inc.runs.length) return <p className="text-sm text-neutral-500">No agent runs yet.</p>;
  return <>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><Th cols={["Run", "Agent", "Status", "Started", "Duration", "Tokens", "Tool calls", ""]} /><tbody>
      {inc.runs.map((x) => <Fragment key={x.run_id}>
        <tr className="border-t border-white/5">
          <td className="py-2 pr-4 font-mono text-xs text-neutral-500">{x.run_id}</td><td className="py-2 pr-4">{x.agent}</td>
          <td className="py-2 pr-4"><Chip tone={x.status === "completed" ? "bg-emerald-950 text-emerald-300" : "bg-amber-950 text-amber-300"}>{x.status}</Chip></td>
          <td className="py-2 pr-4 text-neutral-400">{fmt(x.started_at)}</td><td className="py-2 pr-4 text-neutral-400">{x.duration_s != null ? `${x.duration_s}s` : "n/a"}</td>
          <td className="py-2 pr-4 text-xs text-neutral-400">{tok(x.metrics)}</td><td className="py-2 pr-4 text-neutral-400">{x.metrics?.tool_calls ?? ""}</td>
          <td className="py-2"><button onClick={() => toggle(x.run_id)} className="text-xs text-blue-300 hover:underline">{open === x.run_id ? "Hide" : "Output"}</button></td>
        </tr>
        {open === x.run_id && <tr><td colSpan={8} className="pb-3">
          {x.metrics?.model && <p className="mb-1 text-xs text-neutral-500">Model: {x.metrics.model}</p>}
          {x.metrics?.error && <p className="mb-1 text-xs text-red-300">{x.metrics.error}</p>}
          {err ? <p className="text-xs text-red-300">{err}</p> : <pre className="max-h-72 overflow-auto rounded-lg bg-[#111] p-3 text-xs text-neutral-300">{out[x.run_id] ? JSON.stringify(out[x.run_id].output ?? "No structured output for this step.", null, 2) : "Loading..."}</pre>}
        </td></tr>}
      </Fragment>)}
    </tbody></table></div>
    <p className="mt-3 text-xs text-neutral-500">Durations come from event timestamps, so they are approximate. Agents that run in parallel overlap. Code steps (retrieval, validation, gates) use no model tokens.</p>
  </>;
}

export function IncidentDetail({ inc, onReview, back, initialTab = "overview" }) {
  const [tab, setTab] = useState(initialTab); const [note, setNote] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const r = inc.report, tabs = [["overview", "Overview"], ["evidence", "Evidence"], ["location", "Location"], ["trace", "Agent trace"], ["report", "Report & review"]];
  const act = async (a) => { setBusy(true); setErr(""); try { await onReview(a, note); setNote(""); } catch (e) { setErr(String(e.message || e)); } setBusy(false); };
  const can = { new: ["start_review"], in_review: ["approve", "reject"], approved: ["close"] }[inc.status] || [];
  return (
    <div className="space-y-5">
      <button onClick={back} className="inline-flex items-center gap-1 text-sm text-neutral-400 hover:text-white"><Icon n="left" c="h-4 w-4" />Incidents</button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><div className="flex items-center gap-3"><Pri p={inc.priority} /><h1 className="text-xl font-medium text-white">{inc.title}</h1></div><p className="mt-1 font-mono text-xs text-neutral-500">{inc.incident_id} · {inc.site_id} · {inc.zone_id}</p></div><Pill s={inc.status} />
      </div>
      <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-white/10">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm transition ${tab === k ? "border-blue-500 text-white" : "border-transparent text-neutral-400 hover:text-neutral-200"}`}>{l}</button>)}
      </div>

      {tab === "overview" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Details"><Dl rows={[["Source", inc.source], ["Site", inc.site_id], ["Zone", inc.zone_id], ["Camera", inc.camera_id], ["Equipment", inc.equipment_id], ["Occurred (event time)", fmt(inc.occurred_at)], ["Received by platform", fmt(inc.received_at)], ["Assigned to", inc.assigned_to]]} /></Panel>
          <Panel title="AI classification">{inc.classification ? <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2"><span className="text-lg font-medium text-white">{CAT[inc.classification.category]}</span>{inc.classification.flags.map((f) => <Chip key={f} tone="bg-red-950 text-red-300">{f}</Chip>)}</div>
            <div><div className="mb-1 flex justify-between text-xs text-neutral-400"><span>Model confidence</span><span>{Math.round(inc.classification.confidence * 100)}%</span></div><div className="h-2 rounded-full bg-[#2a2a2a]"><div className="h-2 rounded-full bg-blue-500" style={{ width: `${inc.classification.confidence * 100}%` }} /></div></div>
            <p className="text-xs text-neutral-500">Classification is a draft until a reviewer approves it.</p></div> : <p className="text-sm text-neutral-400">Classification is running. Results appear here when the agent finishes.</p>}</Panel>
          <Panel title="Activity" className="lg:col-span-2"><ol className="space-y-3">{[...inc.audit].reverse().map((a, i) => <li key={i} className="flex gap-3 text-sm"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" /><div><p className="text-neutral-200">{a.action} <span className="text-neutral-500">by {a.actor}</span></p>{a.note && <p className="text-neutral-400">{a.note}</p>}<p className="text-xs text-neutral-600">{fmt(a.at)}</p></div></li>)}</ol></Panel>
        </div>)}

      {tab === "evidence" && (
        <div className="space-y-4">
          <Panel title="Evidence assets">{inc.evidence.length ? <><EvidenceViewer inc={inc} /><div className="overflow-x-auto"><table className="w-full text-left text-sm"><Th cols={["Type", "File", "Size", "Checksum", "Captured", "Source"]} /><tbody>{inc.evidence.map((e) => <tr key={e.asset_id} className="border-t border-white/5"><td className="py-2 pr-4"><Chip>{e.type}</Chip></td><td className="py-2 pr-4">{e.name}</td><td className="py-2 pr-4 text-neutral-400">{e.size}</td><td className="py-2 pr-4 font-mono text-xs text-neutral-500">{e.checksum.slice(0, 12)}</td><td className="py-2 pr-4 text-neutral-400">{fmt(e.captured_at)}</td><td className="py-2 text-neutral-400">{e.uploader}</td></tr>)}</tbody></table></div></> : <p className="text-sm text-neutral-500">No files attached.</p>}</Panel>
          <Panel title="Edge detections">{inc.detections.length ? <table className="w-full text-left text-sm"><Th cols={["Model", "Event", "Confidence", "Offset"]} /><tbody>{inc.detections.map((d, i) => <tr key={i} className="border-t border-white/5"><td className="py-2 pr-4 font-mono text-xs">{d.model}</td><td className="py-2 pr-4">{d.event}</td><td className="py-2 pr-4">{Math.round(d.confidence * 100)}%</td><td className="py-2">{d.offset_s}s</td></tr>)}</tbody></table> : <p className="text-sm text-neutral-500">No model detections for this incident.</p>}</Panel>
          <Panel title="Transcript">{inc.transcript.length ? <><div className="space-y-2">{inc.transcript.map((l, i) => <p key={i} className="text-sm"><span className="font-mono text-xs text-neutral-500">{l.t}</span> <span className="text-blue-300">{l.speaker}</span> <span className="text-neutral-300">{l.text}</span></p>)}</div><p className="mt-3 text-xs text-neutral-500">{inc.transcript.some((l) => l.transcript_type === "ai_generated") ? "Machine transcript of the spoken note, written by the AI from the audio. It can contain mistakes; listen to the recording above. " : ""}A transcript is evidence of what was said, not a verified fact.</p></> : <p className="text-sm text-neutral-500">No transcript registered.</p>}</Panel>
        </div>)}

      {tab === "location" && (
        <div className="space-y-4">
          <p className="flex items-start gap-2 rounded-xl border border-white/10 bg-[#141414] p-3 text-xs text-neutral-400"><Icon n="lock" c="h-4 w-4 shrink-0" />Precise coordinates are restricted by role and each view is logged. Camera-mapped locations come from the camera registry, not live GPS.</p>
          {inc.locations.map((l, i) => <Panel key={i} title={l.source_type} action={<Chip tone={l.validation === "valid" ? "bg-emerald-950 text-emerald-300" : "bg-[#2a2a2a] text-neutral-300"}>{l.validation}</Chip>}>
            <Dl rows={[["Method", l.method], ["Coordinates", l.lat != null ? `${l.lat.toFixed(5)}, ${l.lon.toFixed(5)}` : "Not available"], ["Accuracy", l.accuracy_m != null ? `${l.accuracy_m} m` : "n/a (fixed or unverified)"], ["Captured", fmt(l.captured_at)], ["Resolved zone", inc.zone_id]]} /></Panel>)}
        </div>)}

      {tab === "trace" && (
        <div className="space-y-4">
          <Panel title="Agent runs"><AgentRuns inc={inc} /></Panel>
          <Panel title="Sources retrieved">{inc.retrievals.length ? inc.retrievals.map((q, i) => <div key={i} className="mb-3 last:mb-0"><p className="mb-2 text-xs text-neutral-500">Query: {q.query}</p><div className="space-y-2">{q.hits.map((h, k) => <div key={k} className="flex items-center justify-between rounded-lg bg-[#111] px-3 py-2 text-sm"><span>{h.doc} rev {h.rev} · {h.section} · p.{h.page}</span><span className="text-xs text-neutral-500">score {h.score}</span></div>)}</div></div>) : <p className="text-sm text-neutral-500">No retrieval recorded.</p>}<p className="mt-3 text-xs text-neutral-500">Only currently effective revisions are retrieved. A similar passage is context, not proof.</p></Panel>
        </div>)}

      {tab === "report" && (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          {r ? <div className="space-y-4">
            <div className={`rounded-xl border p-3 text-sm ${["approved", "closed"].includes(r.review_status) ? "border-blue-900 bg-blue-950/40 text-blue-200" : r.review_status === "rejected" ? "border-neutral-700 bg-neutral-900 text-neutral-300" : "border-amber-900 bg-amber-950/40 text-amber-200"}`}>
              {["approved", "closed"].includes(r.review_status) ? `Approved by ${r.reviewed_by}.` : r.review_status === "rejected" ? `Rejected by ${r.reviewed_by}.` : "AI-generated draft. Not an approved finding."} {r.review_note}</div>
            <Panel title={`Report v${r.version}`} action={<span className="text-xs text-neutral-500">{r.generated_by}</span>}><p className="text-sm leading-relaxed text-neutral-200">{r.summary}</p></Panel>
            <Panel title="Observed facts"><List items={r.observed} /></Panel><Panel title="Interpretation"><List items={r.interpretation} /></Panel><Panel title="Unknowns"><List items={r.unknowns} empty="No open unknowns." /></Panel><Panel title="Recommended follow-up"><List items={r.recommendations} /></Panel>
            {r.procedure_check?.length > 0 && <Panel title="Procedure check (advisory)"><div className="space-y-3">{r.procedure_check.map((p, k) => <div key={k} className="rounded-lg bg-[#111] p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><Chip tone={p.status === "followed" ? "bg-emerald-950 text-emerald-300" : p.status === "possible_deviation" ? "bg-amber-950 text-amber-300" : "bg-[#2a2a2a] text-neutral-400"}>{p.status === "followed" ? "Followed" : p.status === "possible_deviation" ? "Possible deviation" : "Cannot tell"}</Chip><span className="text-neutral-200">{p.requirement}</span></div>
              {p.evidence_quote && <p className="mt-2 text-xs text-neutral-300">Reported: "{p.evidence_quote}"</p>}
              {p.explanation && <p className="mt-1 text-xs text-neutral-400">{p.explanation}</p>}
              <p className="mt-1 text-xs text-neutral-500">{p.source?.doc} rev {p.source?.rev} · {p.source?.section} · p.{p.source?.page}</p></div>)}</div>
              <p className="mt-3 text-xs text-neutral-500">Compares what was reported with the retrieved procedures. Silence in the report is not a deviation. A safety reviewer decides.</p></Panel>}
            <Panel title="Sources"><div className="flex flex-wrap gap-2">{r.citations.map((c, k) => <Chip key={k}>{c.doc} rev {c.rev} · {c.section} · p.{c.page}</Chip>)}</div></Panel>
          </div> : <Panel title="Report"><p className="text-sm text-neutral-400">No report yet. The report agent runs after classification finishes.</p></Panel>}
          <Panel title="Review" className="h-fit">
            {can.length ? <div className="space-y-3">
              <Field label={can.includes("reject") ? "Comment (required to reject)" : "Comment"}><textarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} className={inp} placeholder="Add context for the audit trail" /></Field>
              <div className="flex flex-wrap gap-2">
                {can.includes("start_review") && <Btn disabled={busy || !r} onClick={() => act("start_review")}>Start review</Btn>}
                {can.includes("approve") && <Btn disabled={busy} onClick={() => act("approve")}>Approve report</Btn>}
                {can.includes("reject") && <Btn kind="danger" disabled={busy || !note.trim()} onClick={() => act("reject")}>Reject</Btn>}
                {can.includes("close") && <Btn disabled={busy} onClick={() => act("close")}>Close incident</Btn>}
              </div>
              {err && <p className="text-sm text-red-400">{err}</p>}<p className="text-xs text-neutral-500">Approval is a human decision and is recorded in the audit log.</p></div>
              : <p className="text-sm text-neutral-400">{inc.status === "closed" ? "This incident is closed." : "This report was rejected and no further review actions are available."}</p>}
          </Panel>
        </div>)}
    </div>
  );
}

export function DocumentsPage({ docs }) {
  const tone = { Effective: "bg-emerald-950 text-emerald-300", Superseded: "bg-[#2a2a2a] text-neutral-400", Draft: "bg-amber-950 text-amber-300", "Pending verification": "bg-amber-950 text-amber-300" };
  return (
    <div className="space-y-4"><h1 className="text-sm text-neutral-400">Documents</h1>
      <p className="text-sm text-neutral-400">SOPs and RoHS declarations the agents search. Only effective, approved revisions are used as current guidance.</p>
      <div className="overflow-x-auto rounded-xl bg-[#1a1a1a] p-4"><table className="w-full text-left text-sm"><Th cols={["Document", "Type", "Rev", "Status", "Effective from", "Indexing"]} />
        <tbody>{docs.map((d, i) => <tr key={i} className="border-t border-white/5"><td className="py-3 pr-4"><p className="text-white">{d.title}</p><p className="font-mono text-xs text-neutral-500">{d.document_id} · {d.pages} pages</p>{d.warning && <p className="text-xs text-amber-300">{d.warning}</p>}</td><td className="py-3 pr-4">{d.type}</td><td className="py-3 pr-4">{d.revision}</td><td className="py-3 pr-4"><Chip tone={tone[d.status]}>{d.status}</Chip></td><td className="py-3 pr-4 text-neutral-400">{d.effective_from || "n/a"}</td><td className="py-3 text-neutral-400">{d.ingestion}</td></tr>)}</tbody></table></div></div>
  );
}

function CreateModal({ onClose, onCreate }) {
  const [f, setF] = useState({ title: "", priority: "P2", zone: ZONES[0], type: TYPES[0], equipment: "", description: "" }); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async () => { setBusy(true); setErr(""); try { await onCreate(f); } catch (e) { setErr(String(e.message || e)); setBusy(false); } };
  useEffect(() => { const k = (e) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Create incident" onClick={(e) => e.stopPropagation()} className="w-full max-w-lg space-y-4 rounded-2xl bg-[#161616] p-6">
        <div className="flex items-center justify-between"><h2 className="text-lg font-medium text-white">Create incident</h2><button onClick={onClose} aria-label="Close" className="text-neutral-400 hover:text-white"><Icon n="x" /></button></div>
        <Field label="Title"><input value={f.title} onChange={set("title")} className={inp} placeholder="Short description of what happened" autoFocus /></Field>
        <div className="grid grid-cols-2 gap-3"><Field label="Zone"><select value={f.zone} onChange={set("zone")} className={inp}>{ZONES.map((z) => <option key={z}>{z}</option>)}</select></Field>
          <Field label="Type"><select value={f.type} onChange={set("type")} className={inp}>{TYPES.map((z) => <option key={z}>{z}</option>)}</select></Field>
          <Field label="Priority"><select value={f.priority} onChange={set("priority")} className={inp}>{["P1", "P2", "P3"].map((z) => <option key={z}>{z}</option>)}</select></Field>
          <Field label="Equipment (optional)"><input value={f.equipment} onChange={set("equipment")} className={inp} /></Field></div>
        <Field label="Description"><textarea value={f.description} onChange={set("description")} rows={3} className={inp} /></Field>
        {err && <p className="text-sm text-red-400">{err}</p>}
        <div className="flex justify-end gap-2"><Btn kind="ghost" onClick={onClose}>Cancel</Btn><Btn disabled={busy || !f.title.trim()} onClick={submit}>Create incident</Btn></div>
      </div>
    </div>
  );
}

const parse = () => (window.location.hash.replace(/^#\/?/, "") || "dashboard").split("/");

function DetailRoute({ id, go, reload }) {
  const [inc, setInc] = useState(null); const [err, setErr] = useState("");
  useEffect(() => { setInc(null); setErr(""); getIncident(id).then((v) => (v ? setInc(v) : setErr("Incident not found."))).catch((e) => setErr(String(e.message || e))); }, [id]);
  if (err) return <p className="rounded-xl bg-[#1a1a1a] p-6 text-sm text-red-400">{err}</p>;
  if (!inc) return <Skeleton />;
  return <IncidentDetail inc={inc} back={() => go("incidents")} onReview={async (a, c) => { setInc(await reviewIncident(id, a, c)); reload(); }} />;
}

export default function App() {
  const [route, setRoute] = useState(parse); const [incidents, setIncidents] = useState(null); const [overview, setOverview] = useState(null); const [docs, setDocs] = useState(null);
  const [err, setErr] = useState(""); const [creating, setCreating] = useState(false); const [zone, setZone] = useState(null);
  useEffect(() => { const h = () => setRoute(parse()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  const go = useCallback((view, id) => { window.location.hash = id ? `/${view}/${id}` : `/${view}`; window.scrollTo(0, 0); }, []);
  const load = useCallback(async () => { try { const [i, o, d] = await Promise.all([listIncidents(), getOverview(), listDocuments()]); setIncidents(i); setOverview(o); setDocs(d); setErr(""); } catch (e) { setErr(String(e.message || e)); } }, []);
  useEffect(() => { load(); }, [load]);
  const counts = { review: (incidents || []).filter((i) => ["new", "in_review"].includes(i.status) && i.report).length };
  const [view, id] = route;
  let body;
  if (err) body = <div className="rounded-xl bg-[#1a1a1a] p-6"><p className="text-sm text-red-400">Could not load data: {err}</p><div className="mt-3"><Btn onClick={load}>Retry</Btn></div></div>;
  else if (view === "report") body = <ReportPage />;
  else if (!incidents || !overview || !docs) body = <Skeleton />;
  else if (view === "incidents" && id) body = <DetailRoute id={id} go={go} reload={load} />;
  else if (view === "incidents") body = <IncidentsPage incidents={incidents} go={go} title="Incidents" zone={zone} setZone={setZone} />;
  else if (view === "reviews") body = <IncidentsPage incidents={incidents.filter((i) => i.report)} go={go} title="Review queue" preset="in_review" zone={null} setZone={setZone} />;
  else if (view === "documents") body = <DocumentsPage docs={docs} />;
  else body = <Dashboard incidents={incidents} overview={overview} go={go} setZone={setZone} onCreate={() => setCreating(true)} />;
  return (
    <Shell route={route} go={(v) => { setZone(null); go(v); }} counts={counts}>
      {body}
      {creating && <CreateModal onClose={() => setCreating(false)} onCreate={async (f) => { const inc = await createIncident(f); setCreating(false); await load(); go("incidents", inc.incident_id); }} />}
    </Shell>
  );
}