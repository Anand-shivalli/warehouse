import { INCIDENTS, DOCS, OVERVIEW } from "./mock";

// Set VITE_API_URL (for example http://localhost:8000) to use the real backend. Without it the UI runs on seed data.
const BASE = import.meta.env.VITE_API_URL;
const later = (v) => new Promise((r) => setTimeout(() => r(structuredClone(v)), 120));

async function http(path, opts = {}) {
  const res = await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

const stamp = (inc, actor, action, note) => inc.audit.push({ actor, action, note, at: new Date().toISOString() });

export const listIncidents = () => (BASE ? http("/api/incidents") : later(INCIDENTS));
export const getIncident = (id) => (BASE ? http(`/api/incidents/${id}`) : later(INCIDENTS.find((i) => i.incident_id === id)));
export const getOverview = () => (BASE ? http("/api/overview") : later(OVERVIEW));
export const listDocuments = () => (BASE ? http("/api/documents") : later(DOCS));

export function createIncident(body) {
  if (BASE) return http("/api/incidents", { method: "POST", body: JSON.stringify(body) });
  const id = "INC-" + (1049 + INCIDENTS.filter((i) => i.source === "manual").length);
  const t = new Date().toISOString();
  const inc = { incident_id: id, title: body.title, priority: body.priority, status: "new", incident_type: body.type, source: "manual", site_id: INCIDENTS[0].site_id,
    zone_id: body.zone, camera_id: null, equipment_id: body.equipment || "n/a", assigned_to: "Unassigned", occurred_at: t, received_at: t, affected: [body.zone],
    classification: null, evidence: [], detections: [], transcript: [], locations: [{ source_type: "Manual zone selection", method: "worker choice", lat: null, lon: null, accuracy_m: null, captured_at: t, validation: "unverified" }],
    runs: [], retrievals: [], report: null, audit: [] };
  stamp(inc, "You", "Incident created manually", body.description);
  INCIDENTS.unshift(inc);
  return later(inc);
}

// action: start_review | approve | reject | close. Approval is always a human action and is written to the audit trail.
export function reviewIncident(id, action, comment) {
  if (BASE) return http(`/api/incidents/${id}/review`, { method: "POST", body: JSON.stringify({ action, comment }) });
  const inc = INCIDENTS.find((i) => i.incident_id === id);
  const next = { start_review: "in_review", approve: "approved", reject: "rejected", close: "closed" }[action];
  const label = { start_review: "Review started", approve: "Approved report", reject: "Rejected report", close: "Closed incident" }[action];
  inc.status = next;
  if (inc.report) Object.assign(inc.report, { review_status: next, reviewed_by: "You", review_note: comment || null });
  if (action === "start_review") inc.assigned_to = "You";
  stamp(inc, "You", label, comment);
  return later(inc);
}