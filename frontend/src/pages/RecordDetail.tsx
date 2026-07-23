import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { ExtractedField, OccurrenceDetail } from "../api/types";
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
  const q = useQuery({ queryKey: ["detail", id], queryFn: () => api.detail(id) });

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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 12, padding: 12, flex: 1, overflow: "auto", minHeight: 0 }}>
        {/* left column: record fields */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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

        {/* right column: media + annotation */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
  const [note, setNote] = useState("");
  const [drafts, setDrafts] = useState<ExtractedField[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);
  const [pasteRaw, setPasteRaw] = useState("");
  const [copied, setCopied] = useState(false);

  const refresh = () => qc.invalidateQueries({ queryKey: ["detail", record.id] });

  // AI transcribe via copy-paste: fetch a ready prompt (lazy), then parse the
  // JSON the user pastes back from their own AI chat — no platform API cost.
  const promptQuery = useQuery({
    queryKey: ["extract-prompt", record.id],
    queryFn: () => api.extractPrompt(record.id),
    enabled: showPrompt,
  });
  const pasteMut = useMutation({
    mutationFn: () => api.extractPaste(record.id, pasteRaw),
    onSuccess: (res) => {
      setDrafts(res.fields); setModel(res.model); setShowPrompt(false); setPasteRaw("");
    },
  });
  const copyPrompt = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  };
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

  const createMut = useMutation({
    mutationFn: (status: string) => Promise.all(filled.map(({ fd, value }) =>
      api.createAnnotation(record.id, {
        field: fd.name, proposed_value: value, original_value: originalFor(record, fd.name),
        note: note || null,
        source: drafts.some((d) => d.field === fd.name && d.value === value) ? "ai" : "manual",
        status,
      }))),
    onSuccess: () => { setValues({}); setNote(""); refresh(); },
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
        {/* AI transcribe — copy-paste flow (no platform API cost) */}
        <Button small onClick={() => setShowPrompt((s) => !s)}>
          <Icon name="spark" size={11} />{tr("annotate.aiPrompt")}
        </Button>
        {showPrompt && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: 8, background: t.panelAlt, border: `1px solid ${t.borderSoft}` }}>
            <div style={{ fontSize: 10, color: t.fgMuted, lineHeight: 1.5 }}>{tr("annotate.aiPromptHint")}</div>
            {promptQuery.isLoading && <Spinner />}
            {promptQuery.data && (
              <>
                {promptQuery.data.image_url ? (
                  <a href={promptQuery.data.image_url} target="_blank" rel="noreferrer"
                    style={{ color: t.accent, fontSize: 11, display: "inline-flex", alignItems: "center", gap: 4 }}>
                    <Icon name="img" size={11} />{tr("annotate.openImage")} ↗
                  </a>
                ) : (
                  <div style={{ fontSize: 10, color: t.warn }}>{tr("annotate.noImageWarn")}</div>
                )}
                <textarea readOnly value={promptQuery.data.prompt}
                  onFocus={(e) => e.currentTarget.select()}
                  style={{ ...textareaStyle, height: 130 }} />
                <Button small onClick={() => copyPrompt(promptQuery.data!.prompt)}>
                  <Icon name={copied ? "check" : "down"} size={11} />
                  {copied ? tr("annotate.copied") : tr("annotate.copyPrompt")}
                </Button>
                <div style={{ fontSize: 10, color: t.fgMuted, marginTop: 2 }}>{tr("annotate.pasteHint")}</div>
                <textarea value={pasteRaw} onChange={(e) => setPasteRaw(e.target.value)}
                  placeholder={tr("annotate.pasteBack")} style={{ ...textareaStyle, height: 90 }} />
                {pasteMut.isError && (
                  <div style={{ fontSize: 10, color: t.danger }}>{(pasteMut.error as Error).message}</div>
                )}
                <Button primary small disabled={!pasteRaw.trim() || pasteMut.isPending}
                  onClick={() => pasteMut.mutate()}>
                  {pasteMut.isPending ? "…" : tr("annotate.parse")}
                </Button>
              </>
            )}
          </div>
        )}
        {model && (
          <div style={{ fontSize: 10, color: t.fgSubtle }}>
            {tr("annotate.aiHint")} <span style={{ fontFamily: t.mono }}>({model})</span>
          </div>
        )}
        {drafts.map((d, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 6px", background: t.panelAlt, border: `1px solid ${t.borderSoft}`, fontSize: 11 }}>
            <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted, width: 90, flexShrink: 0 }}>{d.field}</span>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.value}</span>
            <span style={{ fontSize: 9, color: t.ok, fontFamily: t.mono }}>{Math.round(d.confidence * 100)}%</span>
            <Button small onClick={() => { setVal(d.field, d.value); const g = groupOf(d.field); if (g) setActiveGroup(g); }}>{tr("annotate.apply")}</Button>
          </div>
        ))}
        {drafts.length > 1 && (
          <Button small onClick={() => setValues((s) => {
            const next = { ...s };
            for (const d of drafts) next[d.field] = d.value;
            return next;
          })}>{tr("annotate.applyAll")}</Button>
        )}

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
            {a.source === "ai" && <Icon name="spark" size={10} />}
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
