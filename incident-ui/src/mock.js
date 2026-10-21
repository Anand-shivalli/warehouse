// Seed data shaped like the tables in the architecture workbook (incidents, assets, detections, locations,
// agent_runs, retrieval_events, incident_reports, audit_logs, documents). Replaced by the real API when VITE_API_URL is set.
const now = Date.now();
const ago = (m) => new Date(now - m * 60000).toISOString();
const hex = (s) => { let h = 2166136261, o = ""; for (let i = 0; i < 48; i++) { h ^= s.charCodeAt(i % s.length) + i; h = Math.imul(h, 16777619) >>> 0; o += (h & 15).toString(16); } return o; };

export const SITE = "WH-07 Columbus";
export const ZONES = ["Dock A", "Dock B", "Bay 4", "Cold Storage", "Pick Aisles", "Shipping"];
export const TYPES = ["Fall", "PPE violation", "Fire / smoke", "Spill", "Forklift near miss", "Equipment damage"];
const COORD = { "Dock A": [39.9612, -83.0003], "Dock B": [39.9614, -82.9996], "Bay 4": [39.9608, -83.0011], "Cold Storage": [39.9603, -83.0020], "Pick Aisles": [39.9606, -83.0007], Shipping: [39.9617, -83.0015] };
const SOP = { Fall: ["SOP-021", "B", "Slip, trip and fall response", 3], "PPE violation": ["SOP-009", "D", "PPE requirements by zone", 2], "Fire / smoke": ["SOP-030", "A", "Fire and smoke response", 5],
  Spill: ["SOP-014", "C", "Chemical spill response", 6], "Forklift near miss": ["SOP-017", "E", "Powered industrial truck safety", 4], "Equipment damage": ["SOP-025", "B", "Racking inspection", 7] };
const MODEL = { Fall: "pose-fall 1.3", "PPE violation": "ppe-yolo 2.0", "Fire / smoke": "fire-smoke 1.1", "Forklift near miss": "proximity 0.9" };
const REVIEWER = "P. Natarajan";

const RAW = [
  { id: "INC-1048", title: "Forklift near miss at Dock A", pri: "P1", status: "new", type: "Forklift near miss", source: "edge", zone: "Dock A", cam: "CAM-A2", equip: "Forklift FL-12", mins: 5, who: "Unassigned", cat: "near_miss", conf: 0.86, flags: [],
    summary: "A forklift and a pedestrian came within about one metre at the Dock A crossing. No contact was recorded.",
    observed: ["Proximity model fired 6 s into the clip.", "The pedestrian stepped back and the forklift stopped."], interp: ["Near miss with high potential severity at a shared crossing."], unknown: ["Whether the pedestrian was inside the marked walkway."], recs: ["Review Dock A crossing signage.", "Brief operators on horn use at blind corners."] },
  { id: "INC-1047", title: "Chemical spill in Bay 4", pri: "P2", status: "in_review", type: "Spill", source: "worker", zone: "Bay 4", equip: "55-gal drum", mins: 58, who: "P. Natarajan", cat: "near_miss", conf: 0.91, flags: [],
    summary: "A drum tipped off a pallet and released blue liquid onto the floor. The area was coned off and cleanup was called. Nobody was injured.",
    observed: ["Drum cap broken, liquid on the concrete floor.", "Worker in PPE contained the spill with absorbent pads."], interp: ["Near miss: high potential severity, no injury."], unknown: ["Identity of the liquid.", "Why the pallet stack shifted."], recs: ["Confirm substance from the SDS.", "Inspect Bay 4 pallet stacking."],
    transcript: [["0:04", "SPEAKER_00", "That drum just tipped off the pallet in Bay 4."], ["0:11", "SPEAKER_01", "Cap broke, blue liquid on the floor. Stay back until we know what it is."], ["0:19", "SPEAKER_00", "Nobody was near it. Dave is fine."]] },
  { id: "INC-1046", title: "Worker fall in pick aisle", pri: "P1", status: "in_review", type: "Fall", source: "edge", zone: "Pick Aisles", cam: "CAM-P7", equip: "Aisle 14", mins: 31, who: "P. Natarajan", cat: "recordable_injury", conf: 0.78, flags: ["OSHA_recordable"],
    summary: "A worker fell in aisle 14 and stayed down for several seconds. Medical treatment was requested.",
    observed: ["Pose model detected a fall and a sustained low posture.", "A colleague reached the worker within 20 s."], interp: ["Possible recordable injury pending treatment details."], unknown: ["Cause of the fall (wet floor, trip hazard).", "Treatment given."], recs: ["Inspect aisle 14 floor.", "Complete the OSHA 301 form if treatment is confirmed."],
    transcript: [["0:03", "SPEAKER_00", "Man down in aisle 14, get the first aider."], ["0:09", "SPEAKER_01", "He says his wrist hurts. Calling medical."]] },
  { id: "INC-1045", title: "Missing hard hat, Dock B", pri: "P3", status: "new", type: "PPE violation", source: "edge", zone: "Dock B", cam: "CAM-B1", equip: "Dock door 3", mins: 74, who: "Unassigned", pending: true },
  { id: "INC-1044", title: "Smoke detected in Cold Storage", pri: "P1", status: "approved", type: "Fire / smoke", source: "edge", zone: "Cold Storage", cam: "CAM-C3", equip: "Compressor unit 2", mins: 190, who: "P. Natarajan", cat: "near_miss", conf: 0.83, flags: [], by: REVIEWER, note: "Confirmed overheated compressor housing; maintenance ticket raised.",
    summary: "Light smoke was seen near compressor unit 2. The unit was isolated and no fire developed.",
    observed: ["Smoke signature detected for 14 s.", "Compressor was powered off by the shift lead."], interp: ["Near miss with high potential severity."], unknown: ["Root cause of the overheating."], recs: ["Service compressor unit 2.", "Add the unit to the weekly thermal check."] },
  { id: "INC-1043", title: "Pallet rack damage, Shipping", pri: "P2", status: "approved", type: "Equipment damage", source: "worker", zone: "Shipping", equip: "Rack S-12", mins: 380, who: "A. Romero", cat: "no_classification_needed", conf: 0.7, flags: [], by: "A. Romero", note: "Upright bent by forklift contact; rack tagged out.",
    summary: "A worker photographed a bent upright on rack S-12. No injury reported.",
    observed: ["Photo shows a deformed upright at the base."], interp: ["Equipment damage with no injury; structural risk until inspected."], unknown: ["Date and cause of the impact."], recs: ["Tag out rack S-12 until inspected."] },
  { id: "INC-1041", title: "Hand laceration at Shipping", pri: "P2", status: "closed", type: "Equipment damage", source: "worker", zone: "Shipping", equip: "Strapping tool", mins: 2900, who: "A. Romero", cat: "first_aid_case", conf: 0.88, flags: [], by: "A. Romero", note: "First aid given on site; guard replaced.",
    summary: "A worker cut a hand on a strapping tool and received first aid on site.",
    observed: ["Worker described a minor cut and on-site first aid."], interp: ["First-aid case."], unknown: [], recs: ["Replace worn tool guard."] },
  { id: "INC-1039", title: "False fall alert at Dock A", pri: "P3", status: "rejected", type: "Fall", source: "edge", zone: "Dock A", cam: "CAM-A2", equip: "Dock door 1", mins: 4300, who: "P. Natarajan", cat: "first_aid_case", conf: 0.52, flags: [], by: REVIEWER, note: "Rejected: worker crouched to lift a box, camera glare. Not a fall.",
    summary: "The edge model flagged a fall, but the clip shows a worker crouching to lift a box.",
    observed: ["Posture returned to standing within 2 s."], interp: ["Likely false positive."], unknown: [], recs: ["Add this clip to the false-positive review set."] },
];

const build = (r) => {
  const occ = r.mins, recv = occ - 1, T = (o) => ago(occ - o);
  const st = r.status, sop = SOP[r.type], [lat, lon] = COORD[r.zone];
  const ev = r.source === "edge"
    ? [["video", `${r.id}_clip.mp4`, "4.2 MB", "edge-" + r.cam], ["audio", `${r.id}_audio.mp3`, "310 KB", "edge-" + r.cam]]
    : [["photo", `${r.id}_photo.jpg`, "2.6 MB", "worker app"]];
  const rs = { new: "draft", in_review: "in_review", approved: "approved", rejected: "rejected", closed: "closed" }[st];
  const audit = [{ actor: r.source === "edge" ? "Edge service" : "Worker app", action: "Incident created", at: ago(recv) }];
  if (!r.pending) audit.push({ actor: "Orchestrator", action: "Classified and draft report v1 generated", at: T(4) });
  if (["in_review", "approved", "rejected", "closed"].includes(st)) audit.push({ actor: r.who, action: "Review started", at: T(12) });
  if (["approved", "closed"].includes(st)) audit.push({ actor: r.by, action: "Approved report v1", at: T(25), note: r.note });
  if (st === "rejected") audit.push({ actor: r.by, action: "Rejected report v1", at: T(25), note: r.note });
  if (st === "closed") audit.push({ actor: r.by, action: "Closed incident", at: T(60), note: r.note });
  return {
    incident_id: r.id, title: r.title, priority: r.pri, status: st, incident_type: r.type, source: r.source,
    site_id: SITE, zone_id: r.zone, camera_id: r.cam || null, equipment_id: r.equip, assigned_to: r.who,
    occurred_at: ago(occ), received_at: ago(recv), affected: [r.zone, r.equip],
    classification: r.pending ? null : { category: r.cat, confidence: r.conf, flags: r.flags },
    evidence: ev.map(([type, name, size, up], i) => ({ asset_id: `AST-${r.id.slice(4)}${i + 1}`, type, name, size, checksum: hex(name), captured_at: ago(occ), uploaded_at: ago(recv), uploader: up })),
    detections: r.source === "edge" ? [{ model: MODEL[r.type] || "edge-model 1.0", event: r.type, confidence: r.conf || 0.8, offset_s: 6 }] : [],
    transcript: (r.transcript || []).map(([t, speaker, text]) => ({ t, speaker, text })),
    locations: r.source === "edge"
      ? [{ source_type: "Camera registry", method: "camera to zone mapping v3", lat, lon, accuracy_m: null, captured_at: ago(occ), validation: "mapped" }]
      : [{ source_type: r.id === "INC-1047" ? "Photo EXIF" : "Manual zone selection", method: r.id === "INC-1047" ? "EXIF GPS" : "worker choice", lat: r.id === "INC-1047" ? lat + 0.00004 : null, lon: r.id === "INC-1047" ? lon - 0.00003 : null, accuracy_m: r.id === "INC-1047" ? 8 : null, captured_at: ago(occ), validation: r.id === "INC-1047" ? "valid" : "unverified" }],
    runs: r.pending ? [{ run_id: "RUN-" + r.id.slice(4) + "A", agent: "ClassifierAgent 1.2", status: "running", started_at: ago(3), duration_s: null }]
      : [{ run_id: "RUN-" + r.id.slice(4) + "A", agent: "ClassifierAgent 1.2", status: "completed", started_at: T(2), duration_s: 9 },
         { run_id: "RUN-" + r.id.slice(4) + "B", agent: "SOP search tool", status: "completed", started_at: T(3), duration_s: 2 },
         { run_id: "RUN-" + r.id.slice(4) + "C", agent: "FinalReportAgent 1.2", status: "completed", started_at: T(4), duration_s: 14 }],
    retrievals: r.pending ? [] : [{ query: `${r.type} response ${r.zone}`, hits: [{ doc: sop[0], rev: sop[1], section: sop[2], page: sop[3], score: 0.82 }, { doc: "SOP-001", rev: "F", section: "Incident reporting duties", page: 2, score: 0.64 }] }],
    report: r.pending ? null : {
      report_id: "RPT-" + r.id.slice(4), version: 1, review_status: rs, generated_by: "FinalReportAgent 1.2", summary: r.summary,
      observed: r.observed, interpretation: r.interp, unknowns: r.unknown, recommendations: r.recs,
      citations: [{ doc: sop[0], rev: sop[1], section: sop[2], page: sop[3] }], reviewed_by: r.by || null, review_note: r.note || null },
    audit,
  };
};

export const INCIDENTS = RAW.map(build);

export const DOCS = [
  { document_id: "SOP-014", title: "Chemical spill response", type: "SOP", revision: "C", status: "Effective", effective_from: "2026-03-01", ingestion: "Indexed", pages: 12 },
  { document_id: "SOP-017", title: "Powered industrial truck safety", type: "SOP", revision: "E", status: "Effective", effective_from: "2026-06-15", ingestion: "Indexed", pages: 18 },
  { document_id: "SOP-017", title: "Powered industrial truck safety", type: "SOP", revision: "D", status: "Superseded", effective_from: "2025-02-10", ingestion: "Indexed", pages: 17 },
  { document_id: "SOP-021", title: "Slip, trip and fall response", type: "SOP", revision: "B", status: "Effective", effective_from: "2026-01-20", ingestion: "Indexed", pages: 9 },
  { document_id: "SOP-030", title: "Fire and smoke response", type: "SOP", revision: "A", status: "Draft", effective_from: null, ingestion: "Processing", pages: 14 },
  { document_id: "ROHS-2291", title: "Supplier declaration: Voltrex Ltd, part VX-220", type: "RoHS", revision: "A", status: "Pending verification", effective_from: "2026-08-02", ingestion: "Needs review", pages: 3, warning: "Exemption field extracted with low confidence." },
];

export const OVERVIEW = {
  sparks: { open: [2, 3, 3, 4, 3, 5, 4, 3, 4, 3, 4, 5], review: [1, 1, 2, 3, 2, 2, 3, 4, 3, 2, 3, 2], resolved: [0, 2, 1, 3, 1, 2, 4, 2, 1, 3, 2, 4], tta: [52, 47, 44, 49, 41, 39, 43, 40, 38, 41, 36, 38], ttr: [8, 7.4, 7.9, 6.8, 7.1, 6.5, 6.9, 6.3, 6.6, 6.1, 6.4, 6.2] },
  resolved30d: 14, meanReview: "38 min", meanClose: "6.2 h",
  pipeline: [{ name: "Edge detection", state: "ok" }, { name: "Ingestion API", state: "ok" }, { name: "Classifier agent", state: "ok" }, { name: "Report agent", state: "ok" }, { name: "Document indexer", state: "warn", note: "1 document needs review" }],
};