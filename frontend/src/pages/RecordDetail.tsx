import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { ExtractedField, OccurrenceDetail, TranscribeOptions } from "../api/types";
import { useAuth } from "../auth";
import { Button, CompletenessDots, GroupTag, Spinner, StatusPill } from "../components/ui";

// Annotatable form, mirroring docs/annotation-schema.md (parts + widgets).
type Widget = "input" | "textarea" | "select" | "date" | "dms";
type FieldDef = {
  name: string;               // tbia annotation field name (submitted as-is)
  widget: Widget;
  options?: string[];         // select
  hemis?: [string, string];   // dms: [positive, negative] hemisphere labels
  degMax?: number;            // dms: max degrees (lat 90 / lon 180)
  decimalField?: string;      // dms: sibling field auto-filled with the decimal value
};

// Controlled vocabularies (see annotation-schema.md).
const TYPE_STATUS_OPTIONS = [
  "HOLOTYPE", "ISOTYPE", "LECTOTYPE", "ISOLECTOTYPE", "SYNTYPE",
  "PARATYPE", "PARALECTOTYPE", "NEOTYPE", "EPITYPE", "ALLOTYPE", "COTYPE", "TOPOTYPE",
];
const COORD_SYS_OPTIONS = ["TWD67", "TWD97"];
const TAXON_RANK_OPTIONS = [
  "kingdom", "phylum", "class", "order", "family",
  "genus", "species", "subspecies", "variety", "form",
];

const ANNOTATABLE_GROUPS: { labelKey: string; fields: FieldDef[] }[] = [
  { labelKey: "annotate.grpCollection", fields: [
    { name: "catalogNumber", widget: "input" },
    { name: "typeStatus", widget: "select", options: TYPE_STATUS_OPTIONS },
  ] },
  { labelKey: "annotate.grpEvent", fields: [
    { name: "recordedBy", widget: "input" },
    { name: "recordNumber", widget: "input" },
    { name: "eventDate", widget: "date" },
  ] },
  { labelKey: "annotate.grpTaxonomy", fields: [
    { name: "annotationScientificName", widget: "input" },
    { name: "annotationVernacularName", widget: "input" },
    { name: "taxonRank", widget: "select", options: TAXON_RANK_OPTIONS },
  ] },
  { labelKey: "annotate.grpLocality", fields: [
    { name: "locality", widget: "input" },
    { name: "verbatimCoordinateSystem", widget: "select", options: COORD_SYS_OPTIONS },
    { name: "verbatimLatitude", widget: "input" },
    { name: "verbatimLongitude", widget: "input" },
    { name: "annotationLongitudeDMS", widget: "dms", hemis: ["東經", "西經"], degMax: 180, decimalField: "annotationLongitudeDecimal" },
    { name: "annotationLatitudeDMS", widget: "dms", hemis: ["北緯", "南緯"], degMax: 90, decimalField: "annotationLatitudeDecimal" },
    { name: "annotationLongitudeDecimal", widget: "input" },
    { name: "annotationLatitudeDecimal", widget: "input" },
    { name: "annotationCounty", widget: "input" },
    { name: "annotationMunicipality", widget: "input" },
  ] },
  { labelKey: "annotate.grpOther", fields: [
    { name: "full_text", widget: "textarea" },
    { name: "other", widget: "textarea" },
  ] },
];
const ALL_FIELDS: FieldDef[] = ANNOTATABLE_GROUPS.flatMap((g) => g.fields);

// Engine presets for the AI transcription pipeline, named by what the choice
// means to a curator (cost/accuracy) rather than by model. The model chain is
// shown as secondary text. `opts` undefined = let the server use its configured
// default (TRANSCRIBE_MODE / models).
const TRANSCRIBE_PRESETS: { labelKey: string; detail?: string; opts?: TranscribeOptions }[] = [
  { labelKey: "annotate.tmAuto" },
  { labelKey: "annotate.tmAccurate", detail: "Opus", opts: { mode: "single", field_model: "claude-opus-4-8" } },
  { labelKey: "annotate.tmCheap", detail: "Haiku→Opus", opts: { mode: "two_stage", ocr_model: "claude-haiku-4-5", field_model: "claude-opus-4-8" } },
];

// Composite widgets keep their parts under dotted sub-keys in the values map;
// these turn the sub-keys into the single string that gets submitted.
function serializeField(fd: FieldDef, values: Record<string, string>): string {
  if (fd.widget === "date") {
    const y = values["eventDate.y"] ?? "", mo = values["eventDate.mo"] ?? "", d = values["eventDate.d"] ?? "";
    if (!y && !mo && !d) return "";
    return `${y.padStart(4, "0")}-${(mo || "").padStart(2, "0")}-${(d || "").padStart(2, "0")}`;
  }
  if (fd.widget === "dms") {
    const deg = values[`${fd.name}.deg`] ?? "", min = values[`${fd.name}.min`] ?? "", sec = values[`${fd.name}.sec`] ?? "";
    if (!deg && !min && !sec) return "";
    const hemi = values[`${fd.name}.hemi`] ?? fd.hemis![0];
    return `${hemi} ${deg || 0}°${min || 0}'${sec || 0}"`;
  }
  return (values[fd.name] ?? "").trim();
}

// DMS -> signed decimal degrees (negative for the second/negative hemisphere).
function dmsToDecimal(fd: FieldDef, values: Record<string, string>): string {
  const deg = parseFloat(values[`${fd.name}.deg`] ?? "");
  if (!Number.isFinite(deg)) return "";
  const min = parseFloat(values[`${fd.name}.min`] ?? "") || 0;
  const sec = parseFloat(values[`${fd.name}.sec`] ?? "") || 0;
  const sign = (values[`${fd.name}.hemi`] ?? fd.hemis![0]) === fd.hemis![1] ? -1 : 1;
  return (sign * (deg + min / 60 + sec / 3600)).toFixed(6);
}

// Route wrapper: /record/:id
export function RecordDetail() {
  const { id = "" } = useParams();
  return <RecordDetailView id={id} />;
}

// Reusable record body. `embedded` (split pane) hides the back link.
export function RecordDetailView({ id, embedded }: { id: string; embedded?: boolean }) {
  const { t: tr } = useTranslation();
  // While an AI transcription request is queued, poll so the panel flips to
  // "processed" (and the new AI annotations appear) without a manual reload —
  // the batch worker runs on demand, so there's no completion event to wait on.
  const q = useQuery({
    queryKey: ["detail", id],
    queryFn: () => api.detail(id),
    refetchInterval: (query) => (query.state.data?.transcribe?.status === "pending" ? 20_000 : false),
  });

  // Draggable divider between the read-only fields (left) and the media +
  // annotation column (right). Width persists across records/sessions.
  const ANNOT_MIN = 320, ANNOT_MAX = 820;
  const [annotW, setAnnotW] = useState(() => {
    const s = Number(localStorage.getItem("tbia_annot_w"));
    return Number.isFinite(s) && s >= ANNOT_MIN ? Math.min(s, ANNOT_MAX) : 360;
  });
  const drag = useRef<{ x: number; w: number } | null>(null);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!drag.current) return;
      const next = drag.current.w - (e.clientX - drag.current.x);  // right column grows as you drag left
      setAnnotW(Math.max(ANNOT_MIN, Math.min(ANNOT_MAX, next)));
    };
    const onUp = () => {
      if (!drag.current) return;
      drag.current = null;
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);
  useEffect(() => { localStorage.setItem("tbia_annot_w", String(annotW)); }, [annotW]);
  const startDrag = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, w: annotW };
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
  };

  if (q.isLoading || !q.data) return <Spinner />;
  const r = q.data;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: t.panelAlt, overflow: "auto" }}>
      {/* header strip */}
      <div style={{ padding: "10px 16px", background: t.panel, borderBottom: `1px solid ${t.border}`, display: "flex", gap: 12, alignItems: "flex-start" }}>
        {!embedded && <Link to="/explore" style={{ color: t.fgMuted, display: "flex", alignItems: "center", marginTop: 4 }}><Icon name="back" size={16} /></Link>}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <GroupTag group={r.bio_group} />
            <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgMuted, fontWeight: 600 }}>{r.catalog_number}</span>
            <CompletenessDots row={r} size={8} />
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{String(r.id)}</span>
          </div>
          <h2 style={{ fontSize: 19, margin: "2px 0", fontWeight: 500 }}>
            <i>{r.scientific_name || <span style={{ color: t.danger }}>{tr("facet.missing_identification")}</span>}</i>
            <span style={{ color: t.fgMuted, fontSize: 13, fontWeight: 400 }}> {r.name_author}</span>
          </h2>
          <div style={{ fontSize: 12, color: t.fgMuted }}>
            {r.common_name_c ? r.common_name_c + " · " : ""}<span style={{ fontFamily: t.mono }}>{r.dataset_name}</span>
          </div>
        </div>
      </div>

      <div style={{ display: "flex", padding: 12, flex: 1, overflow: "auto", minHeight: 0 }}>
        {/* left column: record fields */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 10, paddingRight: 12 }}>
          <Section title={tr("detail.taxonomy")}><Taxonomy r={r} /></Section>
          <Section title={tr("detail.event")}>
            <CollectorField recordedBy={r.recorded_by as string} />
            <Field k={tr("col.date")} v={r.std_date} missing={!r.has_date} verbatim={r.event_date as string} />
            <Field k={tr("col.county")} v={[r.county, r.municipality].filter(Boolean).join(" ")} />
            <Field k={tr("col.locality")} v={r.locality} />
            <Field k={tr("detail.coordinates")}
              v={r.has_coordinates ? `${r.std_lat}, ${r.std_lon}` : null} missing={!r.has_coordinates}
              verbatim={[r.verbatim_latitude, r.verbatim_longitude].filter(Boolean).join(", ") || undefined} />
          </Section>
          <Section title={tr("detail.record")}>
            <Field k="basisOfRecord" v={r.basis_of_record as string} mono />
            <Field k="typeStatus" v={r.type_status as string} mono />
            <Field k="preservation" v={r.preservation as string} />
            <Field k="license" v={r.license as string} mono />
          </Section>
        </div>

        {/* draggable divider — drag left to widen the annotation column */}
        <div onMouseDown={startDrag} title={tr("detail.resize")} style={{
          width: 8, flexShrink: 0, cursor: "col-resize", alignSelf: "stretch",
          display: "flex", justifyContent: "center", position: "relative",
        }}>
          <div style={{ width: 2, background: t.border }} />
        </div>

        {/* right column: media + annotation */}
        <div style={{ width: annotW, flexShrink: 0, display: "flex", flexDirection: "column", gap: 10, paddingLeft: 12 }}>
          <Section title={`${tr("detail.media")} · ${r.media.length}`}>
            <MediaGallery urls={r.media} references={r.references_url as string} />
          </Section>
          <AnnotationPanel record={r} />
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
      <div style={{ padding: "4px 8px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`, fontSize: 10, fontWeight: 600, letterSpacing: 0.4, textTransform: "uppercase", color: t.fgMuted }}>{title}</div>
      <div style={{ padding: "8px 10px", fontSize: 12 }}>{children}</div>
    </div>
  );
}

function Field({ k, v, mono, missing, verbatim }: {
  k: string; v: unknown; mono?: boolean; missing?: boolean; verbatim?: string;
}) {
  const { t: tr } = useTranslation();
  const has = v != null && v !== "";
  return (
    <div style={{ display: "flex", gap: 8, padding: "3px 0", alignItems: "baseline", lineHeight: 1.4, borderLeft: missing ? `2px solid ${t.danger}` : "2px solid transparent", paddingLeft: 6, marginLeft: -6 }}>
      <span style={{ width: 110, fontSize: 10, color: t.fgSubtle, flexShrink: 0 }}>{k}</span>
      <span style={{ flex: 1, fontSize: 12, fontFamily: mono ? t.mono : undefined, wordBreak: "break-word" }}>
        {has ? String(v) : <span style={{ color: t.danger, fontSize: 11 }}>{tr("detail.missing")}</span>}
        {!has && verbatim && <span style={{ color: t.warn, fontSize: 10, marginLeft: 6 }}>verbatim: {verbatim}</span>}
      </span>
    </div>
  );
}

// Collector value as a link that filters Explore to this collector's records.
// Resolves the raw recorded_by string to a canonical collector; falls back to
// plain text when unmapped (organization / unknown).
function CollectorField({ recordedBy }: { recordedBy?: string | null }) {
  const { t: tr } = useTranslation();
  const has = recordedBy != null && recordedBy !== "";
  const resolve = useQuery({
    queryKey: ["collector-resolve", recordedBy],
    queryFn: () => api.resolveCollector(recordedBy as string),
    enabled: has,
    staleTime: 5 * 60_000,
  });
  const c = resolve.data;
  return (
    <div style={{ display: "flex", gap: 8, padding: "3px 0", alignItems: "baseline", lineHeight: 1.4, paddingLeft: 6, marginLeft: -6 }}>
      <span style={{ width: 110, fontSize: 10, color: t.fgSubtle, flexShrink: 0 }}>{tr("detail.collector")}</span>
      <span style={{ flex: 1, fontSize: 12, wordBreak: "break-word" }}>
        {!has ? <span style={{ color: t.danger, fontSize: 11 }}>{tr("detail.missing")}</span>
          : c ? (
            <Link to="/explore" state={{ collector: { id: c.id, label: c.label } }}
              title={tr("collector.filterBy", { n: c.n_records.toLocaleString() })}
              style={{ color: t.accent, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 3 }}>
              <Icon name="user" size={11} />{String(recordedBy)}<Icon name="caretR" size={9} />
            </Link>
          ) : String(recordedBy)}
      </span>
    </div>
  );
}

function Taxonomy({ r }: { r: OccurrenceDetail }) {
  const chain = [
    [r.kingdom_c, r.kingdom], [r.phylum_c, r.phylum], [r.class_c, r.class_name],
    [r.order_c, r.order_name], [r.family_c, r.family], [r.genus_c, r.genus],
  ].filter(([, lat]) => lat) as [string, string][];
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 3, alignItems: "center", fontSize: 11, lineHeight: 1.8 }}>
      {chain.map(([cn, lat], i) => (
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
          <span style={{ padding: "0 5px", background: t.panelAlt, border: `1px solid ${t.borderSoft}` }}>
            <span style={{ fontFamily: t.mono }}>{lat}</span>{cn ? <span style={{ color: t.fgMuted }}> {cn}</span> : null}
          </span>
          {i < chain.length - 1 && <span style={{ color: t.fgSubtle }}>›</span>}
        </span>
      ))}
      {chain.length === 0 && <span style={{ color: t.danger }}>—</span>}
    </div>
  );
}

function MediaGallery({ urls, references }: { urls: string[]; references?: string }) {
  const { t: tr } = useTranslation();
  if (urls.length === 0) {
    return (
      <div style={{ fontSize: 11, color: t.fgSubtle }}>
        {tr("detail.noMedia")}
        {references && <div style={{ marginTop: 6 }}><a href={references} target="_blank" rel="noreferrer" style={{ color: t.accent, fontSize: 11 }}>references ↗</a></div>}
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
      {urls.slice(0, 6).map((u, i) => (
        <a key={i} href={u} target="_blank" rel="noreferrer" style={{ aspectRatio: "1", border: `1px solid ${t.border}`, overflow: "hidden", background: t.panelAlt }}>
          <img src={u} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
        </a>
      ))}
    </div>
  );
}

// ── Annotation workflow ────────────────────────────────────────────────────
function AnnotationPanel({ record }: { record: OccurrenceDetail }) {
  const { t: tr } = useTranslation();
  const { user } = useAuth();
  const qc = useQueryClient();
  // Start on the class most likely to have a gap to fill.
  const [activeGroup, setActiveGroup] = useState(
    !record.has_identification ? "annotate.grpTaxonomy" :
    !record.has_coordinates ? "annotate.grpLocality" :
    !record.has_date ? "annotate.grpEvent" : "annotate.grpTaxonomy"
  );
  // Proposed values keyed by field — many fields can be edited at once.
  const [values, setValues] = useState<Record<string, string>>({});
  // AI value that was applied into a field (from a draft). Lets submit tell
  // apart ai (kept verbatim), mixed (AI value then edited), manual (typed).
  const [aiSeed, setAiSeed] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");

  const refresh = () => qc.invalidateQueries({ queryKey: ["detail", record.id] });

  // The record's holding-institution code (from registry.json, keyed by the
  // record's tbia_dataset_id) — shown as a read-only prefix on catalogNumber.
  const registry = useQuery({ queryKey: ["registry"], queryFn: () => api.registry(), staleTime: Infinity });
  const institutionCode = useMemo(() => {
    const dsid = record.tbia_dataset_id as string | undefined;
    const insts = registry.data?.institutions;
    if (!dsid || !insts) return null;
    for (const [code, ent] of Object.entries(insts)) {
      if (ent.datasets && dsid in ent.datasets) return code;
    }
    return null;
  }, [registry.data, record.tbia_dataset_id]);

  // Fields (across every class) that currently hold a proposed value.
  const filled = ALL_FIELDS
    .map((fd) => ({ fd, value: serializeField(fd, values) }))
    .filter((x) => x.value !== "");
  const setVal = (f: string, v: string) => setValues((s) => ({ ...s, [f]: v }));
  const groupOf = (name: string) =>
    ANNOTATABLE_GROUPS.find((g) => g.fields.some((f) => f.name === name))?.labelKey;
  // A DMS sub-part changed: store it and keep the sibling decimal field in sync.
  const setDms = (fd: FieldDef, part: "hemi" | "deg" | "min" | "sec", v: string) =>
    setValues((s) => {
      const next = { ...s, [`${fd.name}.${part}`]: v };
      if (fd.decimalField) next[fd.decimalField] = dmsToDecimal(fd, next);
      return next;
    });

  // ai = kept the AI value verbatim; mixed = AI value the human edited;
  // manual = typed with no AI seed for this field.
  const sourceFor = (name: string, value: string): string => {
    const seed = aiSeed[name];
    if (seed === undefined) return "manual";
    return value === seed ? "ai" : "mixed";
  };
  // Record that a field was seeded from an AI draft (used by sourceFor).
  const seed = (name: string, value: string) => setAiSeed((s) => ({ ...s, [name]: value }));

  // Apply an AI draft into the form. Most fields are a plain string, but the
  // eventDate composite must be split into its year/month/day sub-inputs;
  // seed the serialized (padded) form so sourceFor still classifies it "ai".
  const applyDraft = (name: string, value: string) => {
    if (name !== "eventDate") { setVal(name, value); seed(name, value); return; }
    const m = value.trim().match(/^(\d{4})(?:[-/.](\d{1,2}))?(?:[-/.](\d{1,2}))?/);
    const y = m?.[1] ?? "";
    const mo = m?.[2] ? String(parseInt(m[2], 10)) : "";
    const d = m?.[3] ? String(parseInt(m[3], 10)) : "";
    setValues((s) => ({ ...s, "eventDate.y": y, "eventDate.mo": mo, "eventDate.d": d }));
    seed(name, y ? `${y.padStart(4, "0")}-${(mo || "").padStart(2, "0")}-${(d || "").padStart(2, "0")}` : "");
  };

  const createMut = useMutation({
    mutationFn: (status: string) => Promise.all(filled.map(({ fd, value }) =>
      api.createAnnotation(record.id, {
        field: fd.name, proposed_value: value, original_value: originalFor(record, fd.name),
        note: note || null,
        source: sourceFor(fd.name, value),
        status,
      }))),
    onSuccess: () => { setValues({}); setAiSeed({}); setNote(""); refresh(); },
  });
  const reviewMut = useMutation({
    mutationFn: ({ annId, status }: { annId: number; status: string }) => api.updateAnnotation(annId, { status }),
    onSuccess: refresh,
  });

  const isReviewer = user?.role === "reviewer" || user?.role === "admin";

  if (!user) {
    return (
      <Section title={tr("detail.annotations")}>
        <div style={{ fontSize: 12, color: t.fgMuted }}>
          <Link to="/login" style={{ color: t.accent }}>{tr("annotate.loginToAnnotate")} →</Link>
        </div>
        <History annotations={record.annotations} isReviewer={false} onReview={() => {}} />
      </Section>
    );
  }

  return (
    <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
      <div style={{ padding: "4px 8px", background: t.accentSoft, borderBottom: `1px solid ${t.borderSoft}`, fontSize: 10, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: t.accent, display: "flex", alignItems: "center", gap: 5 }}>
        <Icon name="spark" size={11} />{tr("annotate.title")}
      </div>
      <div style={{ padding: 10, display: "flex", flexDirection: "column", gap: 8 }}>
        <AiAssist record={record} onUse={(field, value) => {
          applyDraft(field, value);
          const g = groupOf(field); if (g) setActiveGroup(g);
        }} />

        {/* manual form — class tabs, each editing all its fields at once */}
        <div style={{ borderTop: `1px solid ${t.borderSoft}`, paddingTop: 8 }}>
          {/* class tab nav */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 2, borderBottom: `1px solid ${t.borderSoft}`, marginBottom: 8 }}>
            {ANNOTATABLE_GROUPS.map((g) => {
              const active = activeGroup === g.labelKey;
              const n = g.fields.filter((f) => serializeField(f, values) !== "").length;
              return (
                <button key={g.labelKey} onClick={() => setActiveGroup(g.labelKey)} style={{
                  padding: "4px 9px", fontSize: 11, fontFamily: t.sans, cursor: "pointer",
                  border: "none", background: "transparent",
                  color: active ? t.fg : t.fgMuted, fontWeight: active ? 600 : 400,
                  borderBottom: active ? `2px solid ${t.accent}` : "2px solid transparent", marginBottom: -1,
                  display: "flex", alignItems: "center", gap: 4,
                }}>
                  {tr(g.labelKey)}
                  {n > 0 && <span style={{ fontSize: 9, fontFamily: t.mono, color: t.accent }}>·{n}</span>}
                </button>
              );
            })}
          </div>

          {/* every field in the active class */}
          {ANNOTATABLE_GROUPS.find((g) => g.labelKey === activeGroup)!.fields.map((fd) => {
            const orig = originalFor(record, fd.name);
            return (
              <div key={fd.name} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: t.fgMuted }}>{tr(`fields.${fd.name}`, fd.name)}</span>
                  {serializeField(fd, values) !== "" && <SourceTag source={sourceFor(fd.name, serializeField(fd, values))} />}
                  {orig != null && (
                    <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      title={orig}>{tr("annotate.current")}: {orig}</span>
                  )}
                </div>
                {fd.widget === "textarea" ? (
                  <textarea value={values[fd.name] ?? ""} onChange={(e) => setVal(fd.name, e.target.value)}
                    placeholder={tr("annotate.proposed")} style={{ ...textareaStyle, height: fd.name === "full_text" ? 110 : 70 }} />
                ) : fd.widget === "select" ? (
                  <select value={values[fd.name] ?? ""} onChange={(e) => setVal(fd.name, e.target.value)} style={inputStyle}>
                    <option value="">—</option>
                    {fd.options!.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : fd.widget === "date" ? (
                  <div style={{ display: "flex", gap: 4 }}>
                    <input inputMode="numeric" value={values["eventDate.y"] ?? ""} onChange={(e) => setVal("eventDate.y", e.target.value)}
                      placeholder="YYYY" style={{ ...inputStyle, width: 64 }} />
                    <select value={values["eventDate.mo"] ?? ""} onChange={(e) => setVal("eventDate.mo", e.target.value)} style={{ ...inputStyle, width: 60 }}>
                      <option value="">MM</option>
                      {Array.from({ length: 12 }, (_, i) => String(i + 1)).map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                    <input inputMode="numeric" value={values["eventDate.d"] ?? ""} onChange={(e) => setVal("eventDate.d", e.target.value)}
                      placeholder="DD" style={{ ...inputStyle, width: 52 }} />
                  </div>
                ) : fd.widget === "dms" ? (
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <select value={values[`${fd.name}.hemi`] ?? fd.hemis![0]} onChange={(e) => setDms(fd, "hemi", e.target.value)} style={{ ...inputStyle, width: 62 }}>
                      {fd.hemis!.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <input inputMode="numeric" value={values[`${fd.name}.deg`] ?? ""} onChange={(e) => setDms(fd, "deg", e.target.value)}
                      placeholder="0" style={{ ...inputStyle, width: 52 }} /><span style={{ fontSize: 11, color: t.fgSubtle }}>°</span>
                    <input inputMode="numeric" value={values[`${fd.name}.min`] ?? ""} onChange={(e) => setDms(fd, "min", e.target.value)}
                      placeholder="0" style={{ ...inputStyle, width: 44 }} /><span style={{ fontSize: 11, color: t.fgSubtle }}>′</span>
                    <input inputMode="numeric" value={values[`${fd.name}.sec`] ?? ""} onChange={(e) => setDms(fd, "sec", e.target.value)}
                      placeholder="0" style={{ ...inputStyle, width: 44 }} /><span style={{ fontSize: 11, color: t.fgSubtle }}>″</span>
                  </div>
                ) : fd.name === "catalogNumber" && institutionCode ? (
                  <div style={{ display: "flex", alignItems: "stretch" }}>
                    <span title="institutionCode" style={{
                      display: "flex", alignItems: "center", padding: "0 7px", fontSize: 12,
                      fontFamily: t.mono, color: t.fgMuted, background: t.panelAlt,
                      border: `1px solid ${t.border}`, borderRight: "none", whiteSpace: "nowrap",
                    }}>{institutionCode}</span>
                    <input value={values[fd.name] ?? ""} onChange={(e) => setVal(fd.name, e.target.value)}
                      placeholder={tr("annotate.proposed")} style={{ ...inputStyle, width: "auto", flex: 1, minWidth: 0, borderLeft: "none" }} />
                  </div>
                ) : (
                  <input value={values[fd.name] ?? ""} onChange={(e) => setVal(fd.name, e.target.value)}
                    placeholder={tr("annotate.proposed")} style={inputStyle} />
                )}
              </div>
            );
          })}

          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={tr("annotate.note")} style={inputStyle} />
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
            <Button primary small disabled={filled.length === 0 || createMut.isPending} onClick={() => createMut.mutate("submitted")}>{tr("annotate.submit")}</Button>
            <Button small disabled={filled.length === 0 || createMut.isPending} onClick={() => createMut.mutate("draft")}>{tr("annotate.saveDraft")}</Button>
            {filled.length > 0 && <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{filled.length} {tr("annotate.fieldsFilled")}</span>}
          </div>
        </div>

        <History annotations={record.annotations} isReviewer={isReviewer}
          onReview={(annId, status) => reviewMut.mutate({ annId, status })} />
      </div>
    </div>
  );
}

// ── AI assist ──────────────────────────────────────────────────────────────
// One block for both AI routes, because they do the same job and the user only
// needs to pick one:
//   A. queue it — the server-side batch worker writes the proposals back as
//      submitted annotations (arrives later, shows up in History).
//   B. do it yourself — copy the prompt into your own AI chat, paste the JSON
//      reply back (no platform API cost, results land in the form immediately).
// `onUse` loads one proposed value into the manual form below.
function AiAssist({ record, onUse }: { record: OccurrenceDetail; onUse: (field: string, value: string) => void }) {
  const { t: tr } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState<"queue" | "paste" | null>(null);
  const [preset, setPreset] = useState(0);   // index into TRANSCRIBE_PRESETS
  const [pasteRaw, setPasteRaw] = useState("");
  const [copied, setCopied] = useState(false);
  const [drafts, setDrafts] = useState<ExtractedField[]>([]);
  // Provenance of the last pasted AI draft: service · model (date).
  const [prov, setProv] = useState<{ model: string; service?: string | null; extracted_at?: string | null } | null>(null);

  const hasImage = record.media.length > 0;
  const q = record.transcribe;   // durable queue state (survives reload)

  // "Auto" sends no overrides, so what it runs is whatever the server is
  // configured for — ask, rather than showing an opaque "Auto".
  const engineCfg = useQuery({
    queryKey: ["transcribe-config"],
    queryFn: () => api.transcribeConfig(),
    staleTime: 10 * 60_000,
  });
  // Model chain for a preset, "sonnet-5→opus-4-8" style (the claude- prefix is
  // noise at this width; the full ids stay in the title attribute).
  const chainOf = (i: number): string | undefined => {
    if (i !== 0) return TRANSCRIBE_PRESETS[i].detail;
    const c = engineCfg.data;
    if (!c) return undefined;
    const short = (m: string) => m.replace(/^claude-/, "");
    return c.mode === "two_stage" && c.ocr_model
      ? `${short(c.ocr_model)}→${short(c.field_model)}`
      : short(c.field_model);
  };

  // Prompt is fetched lazily — only once the user opens the copy-paste route.
  const promptQuery = useQuery({
    queryKey: ["extract-prompt", record.id],
    queryFn: () => api.extractPrompt(record.id),
    enabled: open === "paste",
  });
  const pasteMut = useMutation({
    mutationFn: () => api.extractPaste(record.id, pasteRaw),
    onSuccess: (res) => {
      setDrafts(res.fields); setProv({ model: res.model, service: res.service, extracted_at: res.extracted_at });
      setOpen(null); setPasteRaw("");
    },
  });
  // Queue this record for transcription (persists occ id + user id, then
  // best-effort Discord notification). Independent of submitting annotations.
  const queueMut = useMutation({
    mutationFn: (opts?: TranscribeOptions) => api.scheduleTranscribe(record.id, opts),
    onSuccess: () => { setOpen(null); qc.invalidateQueries({ queryKey: ["detail", record.id] }); },
  });
  const copyPrompt = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  };

  return (
    <div style={{ border: `1px solid ${t.borderSoft}`, background: t.panelAlt }}>
      <div style={{ padding: "6px 8px", borderBottom: `1px solid ${t.borderSoft}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, fontWeight: 600 }}>
          <Icon name="spark" size={12} />{tr("annotate.aiTitle")}
        </div>
        <div style={{ fontSize: 10, color: t.fgMuted, lineHeight: 1.6, marginTop: 3 }}>{tr("annotate.aiWhat")}</div>
        {!hasImage && (
          <div style={{ fontSize: 10, color: t.warn, lineHeight: 1.5, marginTop: 4, display: "flex", gap: 4 }}>
            <Icon name="alert" size={11} /><span>{tr("annotate.aiNoImage")}</span>
          </div>
        )}
      </div>

      {/* durable queue state — replaces the old 5-second "已排程" flash */}
      {q && <QueueStatus q={q} />}

      <div style={{ padding: 8, display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 10, color: t.fgSubtle }}>{tr("annotate.aiPickHint")}</div>

        {/* route A — hand it to the platform's batch worker */}
        <OptionCard n={1} title={tr("annotate.optQueueTitle")} what={tr("annotate.optQueueWhat")}
          open={open === "queue"} onToggle={() => setOpen(open === "queue" ? null : "queue")}
          cta={q ? tr("annotate.qAgain") : tr("annotate.optQueueGo")} disabled={!hasImage}
          meta={tr("annotate.engineIs", {
            name: [tr(TRANSCRIBE_PRESETS[preset].labelKey), chainOf(preset)].filter(Boolean).join(" · "),
          })}>
          <div style={{ fontSize: 10, color: t.fgSubtle }}>{tr("annotate.optQueueSlow")}</div>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, color: t.fgMuted }}>
            {tr("annotate.aiEngine")}
            <select value={preset} onChange={(e) => setPreset(Number(e.target.value))} style={{ ...inputStyle, width: "auto", flex: 1, fontSize: 11 }}>
              {TRANSCRIBE_PRESETS.map((p, i) => {
                const chain = chainOf(i);
                return <option key={i} value={i}>{tr(p.labelKey)}{chain ? ` — ${chain}` : ""}</option>;
              })}
            </select>
          </label>
          {queueMut.isError && <div style={{ fontSize: 10, color: t.danger }}>{(queueMut.error as Error).message}</div>}
          <Button primary small disabled={!hasImage || queueMut.isPending}
            onClick={() => queueMut.mutate(TRANSCRIBE_PRESETS[preset].opts)}>
            {queueMut.isPending ? "…" : <><Icon name="down" size={11} />{q ? tr("annotate.qAgain") : tr("annotate.optQueueGo")}</>}
          </Button>
        </OptionCard>

        {/* route B — the user's own AI chat, three explicit steps */}
        <OptionCard n={2} title={tr("annotate.optPasteTitle")} what={tr("annotate.optPasteWhat")}
          open={open === "paste"} onToggle={() => setOpen(open === "paste" ? null : "paste")}
          cta={tr("annotate.optPasteGo")}>
          {promptQuery.isLoading && <Spinner />}
          {promptQuery.data && (
            <>
              <Step n={1} label={tr("annotate.step1")}>
                {promptQuery.data.image_url ? (
                  <>
                    <a href={promptQuery.data.image_url} target="_blank" rel="noreferrer"
                      style={{ color: t.accent, fontSize: 11, display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <Icon name="img" size={11} />{tr("annotate.step1")} ↗
                    </a>
                    <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 2 }}>{tr("annotate.step1hint")}</div>
                  </>
                ) : (
                  <div style={{ fontSize: 10, color: t.warn }}>{tr("annotate.step1none")}</div>
                )}
              </Step>
              <Step n={2} label={tr("annotate.step2")}>
                <textarea readOnly value={promptQuery.data.prompt}
                  onFocus={(e) => e.currentTarget.select()}
                  style={{ ...textareaStyle, height: 110 }} />
                <div style={{ marginTop: 4 }}>
                  <Button small onClick={() => copyPrompt(promptQuery.data!.prompt)}>
                    <Icon name={copied ? "check" : "down"} size={11} />
                    {copied ? tr("annotate.copied") : tr("annotate.copyPrompt")}
                  </Button>
                </div>
              </Step>
              <Step n={3} label={tr("annotate.step3")}>
                <textarea value={pasteRaw} onChange={(e) => setPasteRaw(e.target.value)}
                  placeholder={tr("annotate.pasteBack")} style={{ ...textareaStyle, height: 80 }} />
                {pasteMut.isError && (
                  <div style={{ fontSize: 10, color: t.danger, marginTop: 2 }}>{(pasteMut.error as Error).message}</div>
                )}
                <div style={{ marginTop: 4 }}>
                  <Button primary small disabled={!pasteRaw.trim() || pasteMut.isPending} onClick={() => pasteMut.mutate()}>
                    {pasteMut.isPending ? "…" : tr("annotate.parse")}
                  </Button>
                </div>
              </Step>
            </>
          )}
        </OptionCard>
      </div>

      {/* proposals from route B — route A's land in History instead */}
      {drafts.length > 0 && (
        <div style={{ borderTop: `1px solid ${t.borderSoft}`, padding: 8, background: t.panel }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
            <span style={{ fontSize: 11, fontWeight: 600 }}>{tr("annotate.draftsTitle")} · {drafts.length}</span>
            <div style={{ flex: 1 }} />
            {drafts.length > 1 && (
              <Button small onClick={() => drafts.forEach((d) => onUse(d.field, d.value))}>{tr("annotate.applyAll")}</Button>
            )}
          </div>
          <div style={{ fontSize: 10, color: t.fgMuted, lineHeight: 1.5, marginBottom: 6 }}>{tr("annotate.draftsHint")}</div>
          {prov && (
            <div style={{ fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, marginBottom: 4 }}>
              {[prov.service, prov.model].filter(Boolean).join(" · ")}{prov.extracted_at ? `, ${prov.extracted_at}` : ""}
            </div>
          )}
          {drafts.map((d, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 6px", marginBottom: 3, background: t.panelAlt, border: `1px solid ${t.borderSoft}`, fontSize: 11 }}>
              <span style={{ fontSize: 10, color: t.fgMuted, width: 78, flexShrink: 0 }} title={d.field}>{tr(`fields.${d.field}`, d.field)}</span>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={d.value}>{d.value}</span>
              <span style={{ fontSize: 9, color: t.ok, fontFamily: t.mono }} title={tr("annotate.confidence")}>{Math.round(d.confidence * 100)}%</span>
              <Button small onClick={() => onUse(d.field, d.value)}>{tr("annotate.apply")}</Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Collapsed: a numbered row you can read in one glance, plus `meta` — the
// current value of a setting that lives inside, so it's discoverable without
// opening the card. Expanded: its controls (meta hides, the real control shows).
function OptionCard({ n, title, what, cta, open, onToggle, disabled, meta, children }: {
  n: number; title: string; what: string; cta: string; open: boolean;
  onToggle: () => void; disabled?: boolean; meta?: string; children: React.ReactNode;
}) {
  return (
    <div style={{ border: `1px solid ${open ? t.accent : t.borderSoft}`, background: t.panel, opacity: disabled && !open ? 0.55 : 1 }}>
      <button onClick={onToggle} style={{
        width: "100%", textAlign: "left", display: "flex", gap: 7, padding: "7px 8px",
        border: "none", background: "transparent", cursor: "pointer", fontFamily: t.sans,
      }}>
        <span style={{
          flexShrink: 0, width: 16, height: 16, display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 10, fontFamily: t.mono, color: open ? t.bg : t.fgMuted,
          background: open ? t.accent : t.panelAlt, border: `1px solid ${open ? t.accent : t.border}`,
        }}>{n}</span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 600, color: t.fg }}>
            {title}
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 10, fontWeight: 400, color: t.accent }}>{open ? "" : cta} </span>
            <Icon name={open ? "caretD" : "caretR"} size={10} />
          </span>
          <span style={{ display: "block", fontSize: 10, color: t.fgMuted, lineHeight: 1.6, marginTop: 3 }}>{what}</span>
          {meta && !open && (
            <span style={{ display: "inline-block", fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, marginTop: 4, padding: "0 4px", border: `1px solid ${t.borderSoft}`, background: t.panelAlt }}>{meta}</span>
          )}
        </span>
      </button>
      {open && (
        <div style={{ padding: "0 8px 8px 31px", display: "flex", flexDirection: "column", gap: 6 }}>{children}</div>
      )}
    </div>
  );
}

function Step({ n, label, children }: { n: number; label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: t.fgMuted, marginBottom: 3 }}>
        <span style={{ fontFamily: t.mono, color: t.accent }}>{n}.</span> {label}
      </div>
      {children}
    </div>
  );
}

// What happened to the queued request — and, since the batch worker is run
// on demand (no ETA to promise), what the contributor can do instead of wait.
function QueueStatus({ q }: { q: NonNullable<OccurrenceDetail["transcribe"]> }) {
  const { t: tr } = useTranslation();
  const tone = q.status === "failed" ? t.danger : q.status === "done" ? t.ok : t.warn;
  const label = q.status === "failed" ? tr("annotate.qFailed")
    : q.status === "done" ? tr("annotate.qDone") : tr("annotate.qPending");
  const what = q.status === "failed" ? tr("annotate.qFailedWhat")
    : q.status === "done" ? tr("annotate.qDoneWhat") : tr("annotate.qPendingWhat");
  const when = (q.processed_at || q.created || "").slice(0, 16).replace("T", " ");
  return (
    <div style={{ padding: "6px 8px", borderBottom: `1px solid ${t.borderSoft}`, background: t.panel, borderLeft: `2px solid ${tone}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: tone, fontWeight: 600 }}>
        <Icon name={q.status === "failed" ? "alert" : q.status === "done" ? "check" : "cog"} size={11} />{label}
      </div>
      <div style={{ fontSize: 10, color: t.fgMuted, lineHeight: 1.6, marginTop: 3 }}>{what}</div>
      {q.status === "pending" && (
        <div style={{ fontSize: 10, color: t.fgSubtle, lineHeight: 1.6, marginTop: 3 }}>{tr("annotate.qPendingAlt")}</div>
      )}
      {q.status === "failed" && q.error && (
        <div style={{ fontSize: 10, color: t.danger, marginTop: 3, wordBreak: "break-word" }}>{q.error}</div>
      )}
      <div style={{ fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, marginTop: 3 }}>
        {when}{q.requested_by ? ` · ${tr("annotate.qBy", { who: q.requested_by })}` : ""}
      </div>
    </div>
  );
}

// Value provenance: ai (kept verbatim) · mixed (AI, then human-edited) ·
// manual (typed). Legacy rows may be blank → treated as manual (no tag).
function SourceTag({ source }: { source: string }) {
  const { t: tr } = useTranslation();
  if (source !== "ai" && source !== "mixed") return null;
  const tone = source === "ai" ? t.accent : t.warn;
  return (
    <span title={tr(`annotate.src_${source}`)} style={{
      display: "inline-flex", alignItems: "center", gap: 2, fontSize: 9,
      fontFamily: t.mono, color: tone, border: `1px solid ${tone}`, padding: "0 3px",
    }}>
      <Icon name="spark" size={8} />{tr(`annotate.src_${source}`)}
    </span>
  );
}

function History({ annotations, isReviewer, onReview }: {
  annotations: OccurrenceDetail["annotations"]; isReviewer: boolean;
  onReview: (annId: number, status: string) => void;
}) {
  const { t: tr } = useTranslation();
  if (annotations.length === 0) return null;
  return (
    <div style={{ borderTop: `1px solid ${t.borderSoft}`, paddingTop: 8 }}>
      <div style={{ fontSize: 10, color: t.fgSubtle, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.3 }}>{tr("annotate.history")}</div>
      {annotations.map((a) => (
        <div key={a.id} style={{ padding: "4px 0", borderBottom: `1px solid ${t.borderSoft}`, fontSize: 11 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted }}>{a.field}</span>
            <span style={{ flex: 1 }} />
            <SourceTag source={a.source} />
            <StatusPill status={a.status} />
          </div>
          <div style={{ marginTop: 1 }}>
            <span style={{ color: t.fgSubtle, textDecoration: "line-through" }}>{a.original_value || "∅"}</span>
            {" → "}<span style={{ fontWeight: 600 }}>{a.proposed_value}</span>
          </div>
          {a.note && <div style={{ color: t.fgMuted, fontSize: 10 }}>{a.note}</div>}
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
            <span style={{ fontSize: 10, color: t.fgSubtle }}>— {a.contributor_name}</span>
            {isReviewer && (a.status === "submitted" || a.status === "draft") && (
              <span style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
                <Button small onClick={() => onReview(a.id, "accepted")}>{tr("annotate.accept")}</Button>
                <Button small danger onClick={() => onReview(a.id, "rejected")}>{tr("annotate.reject")}</Button>
              </span>
            )}
            {isReviewer && a.status === "accepted" && (
              <Button small onClick={() => onReview(a.id, "merged")}>{tr("annotate.merge")}</Button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// Current occurrence value shown as reference. `annotation*` fields are ones
// TBIA doesn't hold (annotation-schema.md), so they have no original value.
function originalFor(r: OccurrenceDetail, field: string): string | null {
  const map: Record<string, unknown> = {
    catalogNumber: r.catalog_number, typeStatus: r.type_status,
    recordedBy: r.recorded_by, recordNumber: r.record_number,
    taxonRank: r.taxon_rank, eventDate: r.std_date, locality: r.locality,
  };
  const v = map[field];
  return v == null ? null : String(v);
}

const inputStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", padding: "5px 7px", fontSize: 12,
  border: `1px solid ${t.border}`, background: t.panelAlt, outline: "none", fontFamily: t.sans,
};

const textareaStyle: React.CSSProperties = {
  ...inputStyle, resize: "vertical", fontFamily: t.mono, fontSize: 11, lineHeight: 1.4,
};
