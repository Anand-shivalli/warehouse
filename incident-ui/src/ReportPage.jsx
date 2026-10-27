import { useState, useEffect, useRef } from "react";
import { sendTrigger, startPathA, startPathB, confirmJob, getJob } from "./api";
import { Btn, inp } from "./ui";

const fileInp = `${inp} file:mr-3 file:rounded file:border-0 file:bg-[#262626] file:px-3 file:py-1 file:text-neutral-200`;

const Step = ({ n, title, children, locked }) => (
  <section className={`rounded-xl bg-[#1a1a1a] p-4 ${locked ? "opacity-40" : ""}`}>
    <h3 className="mb-3 flex items-center gap-3 text-sm font-medium text-neutral-200">
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-xs text-white">{n}</span>{title}
    </h3>
    {children}
  </section>
);
const FileInput = ({ label, accept, onChange }) => (
  <label className="block text-sm text-neutral-400"><span className="mb-1 block">{label}</span>
    <input type="file" accept={accept} onChange={(e) => onChange(e.target.files[0] || null)} className={fileInp} /></label>
);

const STEPS = [
  ["Incident triage", ["ConversationTriage"]],
  ["Extraction", ["ExtractionAgent", "TextExtractionAgent"]],
  ["Vision analysis", ["VisionAgent"]],
  ["Conflict check", ["ConflictCheck"]],
  ["Signal normalization", ["SignalNormalizer"]],
  ["Classification and flags", ["ComplianceClassifier"]],
  ["Document retrieval (SOPs, guidelines, RoHS)", ["RetrievalStep"]],
  ["Review 1: consistency", ["ReviewerPass1"]],
  ["Report writing", ["Composer"]],
  ["Procedure check", ["DeviationCheck"]],
  ["Citation check", ["ReportValidator"]],
  ["Review 2: grounding", ["ReviewerPass2", "Gate_Pass2"]],
];

export function ReportPage() {
  const [trigFile, setTrigFile] = useState(null);
  const [trig, setTrig] = useState(null);
  const [armed, setArmed] = useState(false);
  const [path, setPath] = useState("A");
  const [audio, setAudio] = useState(null);
  const [media, setMedia] = useState(null);
  const [dialogue, setDialogue] = useState(null);
  const [video, setVideo] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [poll, setPoll] = useState(0);
  const [job, setJob] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  const wrap = async (fn) => { setBusy(true); setErr(""); try { await fn(); } catch (e) { setErr(String(e.message || e)); } setBusy(false); };

  const analyze = () => wrap(async () => {
    const r = await sendTrigger(trigFile);
    setTrig(r);
    setArmed(!!r.anomaly_detected);
  });

  const run = () => wrap(async () => {
    setJob(null);
    const { id } = path === "A" ? await startPathA(audio, media) : await startPathB(dialogue, video);
    setJobId(id);
  });

  const confirm = () => wrap(async () => {
    await confirmJob(jobId);
    setPoll((p) => p + 1); // restart polling
  });

  // poll the job until it finishes or waits for the human
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await getJob(jobId);
        if (stop) return;
        setJob(j);
        if (["completed", "failed", "awaiting_confirmation"].includes(j.status)) return;
      } catch (e) { if (!stop) setErr(String(e.message || e)); return; }
      timer.current = setTimeout(tick, 1500);
    };
    tick();
    return () => { stop = true; clearTimeout(timer.current); };
  }, [jobId, poll]);

  const seen = new Set((job?.events || []).map((e) => e.author));
  const canRun = path === "A" ? audio && media : armed && dialogue;   // Path A is direct intake: no ambient trigger needed
  const res = job?.result;

  return (
    <div className="space-y-4">
      <h1 className="text-sm text-neutral-400">Report an incident</h1>
      <p className="text-sm text-neutral-500">From a sound, a conversation or a photo to a verified incident report.</p>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-4">
          <Step n="1" title={path === "A" ? "Trigger signal (ambient audio, optional for Path A)" : "Trigger signal (ambient audio)"}>
            <FileInput label="Ambient audio events JSON" accept=".json" onChange={(f) => { setTrigFile(f); setTrig(null); setArmed(false); }} />
            <div className="mt-3"><Btn disabled={!trigFile || busy} onClick={analyze}>Analyze signal</Btn></div>
            {trig && (
              <div className={`mt-3 rounded-lg border p-3 text-sm ${trig.anomaly_detected ? "border-amber-900 bg-amber-950/40 text-amber-200" : "border-white/10 bg-[#111] text-neutral-400"}`}>
                <p className="font-medium">{trig.anomaly_detected ? "Acoustic anomaly detected. Submit report?" : "No acoustic anomaly detected."}</p>
                {trig.events.slice().sort((a, b) => b.score - a.score).slice(0, 3).map((e, i) => (
                  <p key={i} className="mt-1 text-xs">{e.label} at {Number(e.start_sec).toFixed(1)}s (score {Number(e.score).toFixed(2)})</p>))}
              </div>)}
          </Step>

          <Step n="2" title="Choose a path">
            <div className="grid grid-cols-2 gap-3">
              {[["A", "Path A: Direct intake", "Photo or video plus a spoken note"], ["B", "Path B: Team dialogue", "Conversation transcript JSON"]].map(([k, t, d]) => (
                <button key={k} onClick={() => setPath(k)}
                  className={`rounded-lg border p-3 text-left text-sm transition ${path === k ? "border-blue-500 bg-blue-950/40" : "border-white/10 bg-[#111] hover:bg-[#1c1c1c]"}`}>
                  <p className="text-white">{t}</p><p className="mt-1 text-xs text-neutral-500">{d}</p></button>))}
            </div>
          </Step>

          <Step n="3" title="Inputs">
            <div className="space-y-3">
              {path === "A" ? <>
                <FileInput label="Spoken note (audio)" accept="audio/*" onChange={setAudio} />
                <FileInput label="Incident photo or video clip (under 18 MB)" accept="image/*,video/*" onChange={setMedia} />
              </> : <>
                <FileInput label="Dialogue transcript JSON (WhisperX + pyannote)" accept=".json" onChange={setDialogue} />
                <FileInput label="Video clip (optional)" accept="video/*" onChange={setVideo} />
              </>}
              {path === "B" && !armed && <p className="text-xs text-amber-300">Path B needs an ambient audio signal with an anomaly (step 1).</p>}
              <Btn disabled={!canRun || busy} onClick={run}>Run pipeline</Btn>
            </div>
          </Step>
          {err && <p className="rounded-lg bg-red-950/40 p-3 text-sm text-red-300">{err}</p>}
        </div>

        <div className="space-y-4">
          <Step n="4" title="Pipeline" locked={!job}>
            {job ? <>
              <p className="mb-3 text-xs text-neutral-500"><span className="font-mono">job {job.id}</span> · {job.status.replace("_", " ")}</p>
              <ul className="space-y-2 text-sm">
                {STEPS.filter(([, a]) => path === "B" || !a.includes("ConversationTriage")).map(([label, authors]) => {
                  const done = authors.some((a) => seen.has(a));
                  return <li key={label} className="flex items-center gap-2"><span className={`h-2.5 w-2.5 rounded-full ${done ? "bg-emerald-500" : "bg-neutral-700"}`} /><span className={done ? "text-neutral-200" : "text-neutral-500"}>{label}</span></li>;
                })}
              </ul>
              {job.status === "awaiting_confirmation" && job.triage && (
                <div className="mt-4 rounded-lg border border-amber-900 bg-amber-950/40 p-3 text-sm text-amber-200">
                  <p className="font-medium">Incident detected in dialogue. Create a report?</p>
                  <p className="mt-1 text-xs">{job.triage.summary}</p>
                  <div className="mt-3"><Btn disabled={busy} onClick={confirm}>Create report</Btn></div>
                </div>)}
              {job.status === "failed" && <p className="mt-3 text-sm text-red-300">{job.error}</p>}
            </> : <p className="text-sm text-neutral-500">Run the pipeline to see progress here.</p>}
          </Step>

          <Step n="5" title="Result" locked={!res}>
            {res?.no_incident && <p className="text-sm text-neutral-400">No incident was detected in the dialogue.</p>}
            {res && !res.no_incident && <div className="space-y-3">
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-blue-950 px-3 py-1 text-blue-200">{res.category || "unclassified"}</span>
                {res.flags?.map((f) => <span key={f} className="rounded-full bg-red-950 px-3 py-1 text-red-300">{f}</span>)}
                <span className={`rounded-full px-3 py-1 ${res.needs_human_review ? "bg-amber-950 text-amber-300" : "bg-emerald-950 text-emerald-300"}`}>{res.needs_human_review ? "Needs human review" : "Review passed"}</span>
              </div>
              <p className="whitespace-pre-wrap rounded-lg bg-[#111] p-3 text-sm leading-relaxed text-neutral-200">{res.report || "No report was produced. See review notes."}</p>
              {res.needs_human_review && (res.validation?.notes || res.review1?.notes || res.review2?.notes) && <p className="text-xs text-amber-300">{[res.validation?.notes, res.review2?.notes || res.review1?.notes].filter(Boolean).join(" ")}</p>}
              {res.retrieval?.hits?.length > 0 && <div className="rounded-lg bg-[#111] p-3 text-xs text-neutral-400"><p className="mb-1 text-neutral-300">Documents retrieved</p>
                {res.retrieval.hits.map((h) => <p key={h.sid}>[{h.sid}] {h.doc} rev {h.rev} · {h.section || "untitled"} · p.{h.page}</p>)}</div>}
              {res.retrieval?.status && res.retrieval.status !== "ok" && <p className="text-xs text-amber-300">Document retrieval: {res.retrieval.status}</p>}
              <p className="text-xs text-neutral-500">AI-generated draft. A human reviewer approves it.</p>
            </div>}
            {!res && <p className="text-sm text-neutral-500">The report appears here when the pipeline finishes.</p>}
          </Step>
        </div>
      </div>
    </div>
  );
}