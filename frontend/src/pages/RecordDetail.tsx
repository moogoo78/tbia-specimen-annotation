import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { ExtractedField, MediaSize, OccurrenceDetail } from "../api/types";
import { useAuth } from "../auth";
import { Button, CompletenessDots, GroupTag, Spinner, StatusPill } from "../components/ui";
import { LICENSES, LICENSE_LABELS, LICENSE_URIS, asLicense, licenseLabel } from "../licenses";
import type { License } from "../licenses";
import { contributorLabel, isAnonymous } from "../contributors";

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

// A transcription offered to the form. Either route produces one: the platform's
// own AI (stored on the record's transcribe request, so it survives a reload) or
// the contributor's own AI chat (parsed from a paste). Neither is a contribution
// — an annotation exists only once a person submits one.
type Proposal = {
  fields: ExtractedField[];
  model: string | null;
  service?: string | null;
  extracted_at?: string | null;
};
type ProposalMeta = { confidence?: number | null; model?: string | null };
// What the AI said for a field the contributor is now editing. Kept even when
// they agree with it: "agreed" and "no AI involved" are different facts.
type AiSeed = { value: string; confidence: number | null; model: string | null };


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
  // The annotations, indexed by the field each one answers, so the record's own
  // fields can show what has been contributed to them.
  const enrich = enrichments(r.annotations);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, background: t.panelAlt, overflow: "auto" }}>
      {/* header strip */}
      <div style={{ padding: "10px 16px", background: t.panel, borderBottom: `1px solid ${t.border}`, display: "flex", gap: 12, alignItems: "flex-start" }}>
        {!embedded && <Link to="/explore" style={{ color: t.fgMuted, display: "flex", alignItems: "center", marginTop: 4 }}><Icon name="back" size={16} /></Link>}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <GroupTag group={r.bio_group} />
            <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgMuted, fontWeight: 600 }}
              title={enrich["catalogNumber"] ? `${tr("detail.wasValue")} ${r.catalog_number || "∅"}` : undefined}>
              {enrich["catalogNumber"]?.proposed_value || r.catalog_number}
            </span>
            <CompletenessDots row={r} size={8} />
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{String(r.id)}</span>
          </div>
          {/* The identification gap is the one this platform exists to close, so
              it is the one place the enrichment has to be visible without
              scrolling: a record annotated with a name reads as that name, with
              the status beside it and the provider's own value struck through
              below rather than replaced. */}
          <h2 style={{ fontSize: 19, margin: "2px 0", fontWeight: 500 }}>
            <i>{enrich["annotationScientificName"]?.proposed_value
              || r.scientific_name
              || <span style={{ color: t.danger }}>{tr("facet.missing_identification")}</span>}</i>
            <span style={{ color: t.fgMuted, fontSize: 13, fontWeight: 400 }}> {r.name_author}</span>
            {enrich["annotationScientificName"] && (
              <span style={{ marginLeft: 8, verticalAlign: "middle" }}>
                <StatusPill status={enrich["annotationScientificName"].status} />
              </span>
            )}
          </h2>
          {enrich["annotationScientificName"] && (
            <div style={{ fontSize: 10, color: t.fgSubtle, marginBottom: 2 }}>
              {tr("detail.wasValue")}{" "}
              {r.scientific_name
                ? <span style={{ textDecoration: "line-through" }}>{r.scientific_name}</span>
                : <span style={{ color: t.danger }}>{tr("facet.missing_identification")}</span>}
            </div>
          )}
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
            <Field k={tr("col.date")} v={r.standard_date} missing={!r.has_date}
              verbatim={r.event_date as string} ann={enrich["eventDate"]} />
            <Field k={tr("col.county")} v={[r.county, r.municipality].filter(Boolean).join(" ")}
              ann={enrich["annotationCounty"] || enrich["annotationMunicipality"]} />
            <Field k={tr("col.locality")} v={r.locality} ann={enrich["locality"]} />
            <Field k={tr("detail.coordinates")}
              v={r.has_coordinates ? `${r.standard_latitude}, ${r.standard_longitude}` : null} missing={!r.has_coordinates}
              verbatim={[r.verbatim_latitude, r.verbatim_longitude].filter(Boolean).join(", ") || undefined}
              ann={coordinateAnnotation(enrich)} />
          </Section>
          <Section title={tr("detail.record")}>
            <Field k="basisOfRecord" v={r.basis_of_record as string} mono />
            <Field k="typeStatus" v={r.type_status as string} mono ann={enrich["typeStatus"]} />
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
            <MediaGallery urls={r.media} sizes={r.media_sizes} references={r["references"] as string} />
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

function Field({ k, v, mono, missing, verbatim, ann }: {
  k: string; v: unknown; mono?: boolean; missing?: boolean; verbatim?: string;
  /** An annotation to show in place of the provider's value — see `Enriched`. */
  ann?: Enrichment;
}) {
  const { t: tr } = useTranslation();
  const has = v != null && v !== "";
  // A filled gap stops being a gap: the red rule marks what still needs work,
  // and leaving it on a field somebody has just answered would say the
  // contribution never happened.
  const gap = missing && !ann;
  return (
    <div style={{ display: "flex", gap: 8, padding: "3px 0", alignItems: "baseline", lineHeight: 1.4, borderLeft: gap ? `2px solid ${t.danger}` : ann ? `2px solid ${t.ok}` : "2px solid transparent", paddingLeft: 6, marginLeft: -6 }}>
      <span style={{ width: 110, fontSize: 10, color: t.fgSubtle, flexShrink: 0 }}>{k}</span>
      <span style={{ flex: 1, fontSize: 12, fontFamily: mono && !ann ? t.mono : undefined, wordBreak: "break-word" }}>
        {ann
          ? <Enriched a={ann} original={v} mono={mono} />
          : has ? String(v) : <span style={{ color: t.danger, fontSize: 11 }}>{tr("detail.missing")}</span>}
        {!has && !ann && verbatim && <span style={{ color: t.warn, fontSize: 10, marginLeft: 6 }}>verbatim: {verbatim}</span>}
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
            <Link to={`/collectors/${c.id}`}
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
    [r.kingdom_c, r.kingdom], [r.phylum_c, r.phylum], [r.class_c, r["class"]],
    [r.order_c, r["order"]], [r.family_c, r.family], [r.genus_c, r.genus],
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

// ---------------------------------------------------------------------------
// Enrichment: an annotation shown as the record's own value.
//
// The occurrence store is read-only and stays that way — nothing here writes
// back. This is a *read-time overlay*: the record still ships its provider
// value, and the page shows the latest annotation on top of it with the
// original struck through beneath, so the two are never confused for one
// another. It is the whole point of the platform made visible on the record:
// until now a filled gap only showed up as a row in the annotation history,
// while the field it filled still read "missing".
//
// "Latest" is per field, and the detail payload arrives `created desc`, so the
// first row for a field is the newest. Two statuses are skipped rather than
// shown: `draft` is private working state that has no business on a public
// page, and `rejected` is a reviewer having said no — displaying either as the
// specimen's value would publish something nobody stands behind.
type Enrichment = OccurrenceDetail["annotations"][number];

const OVERLAY_SKIP = new Set(["draft", "rejected"]);

function enrichments(annotations: OccurrenceDetail["annotations"]): Record<string, Enrichment> {
  const out: Record<string, Enrichment> = {};
  for (const a of annotations) {
    if (OVERLAY_SKIP.has(a.status)) continue;
    if (!a.proposed_value) continue;
    if (!out[a.field]) out[a.field] = a;
  }
  return out;
}

/** A coordinate is two annotations, and a field is one value — so the pair is
 *  folded into a synthetic row reading "lat, lon". Either half alone still
 *  shows, because half a georeference is what a contributor may have had. The
 *  decimal fields are preferred over the verbatim ones: they are what the
 *  provider's own `standard_latitude/longitude` would be replaced by. */
function coordinateAnnotation(e: Record<string, Enrichment>): Enrichment | undefined {
  const lat = e["annotationLatitudeDecimal"] || e["annotationLatitudeDMS"] || e["verbatimLatitude"];
  const lon = e["annotationLongitudeDecimal"] || e["annotationLongitudeDMS"] || e["verbatimLongitude"];
  if (!lat && !lon) return undefined;
  const base = lat || lon;
  return {
    ...(base as Enrichment),
    proposed_value: [lat?.proposed_value, lon?.proposed_value].filter(Boolean).join(", "),
  };
}

/** The enriched value, with what it replaced. `original` is the record's own
 *  value rather than the annotation's `original_value`, so the strike-through
 *  is what the provider actually ships today even if an earlier annotation in
 *  the chain recorded something else. */
function Enriched({ a, original, mono }: { a: Enrichment; original?: unknown; mono?: boolean }) {
  const { t: tr } = useTranslation();
  const had = original != null && original !== "";
  return (
    <span>
      <span style={{ fontWeight: 600, fontFamily: mono ? t.mono : undefined }}>{a.proposed_value}</span>
      <span style={{ marginLeft: 6, display: "inline-flex", alignItems: "baseline", gap: 4 }}>
        <StatusPill status={a.status} />
      </span>
      <span style={{ display: "block", fontSize: 10, color: t.fgSubtle, marginTop: 1 }}>
        {tr("detail.wasValue")}{" "}
        {had
          ? <span style={{ textDecoration: "line-through" }}>{String(original)}</span>
          : <span style={{ color: t.danger }}>{tr("detail.missing")}</span>}
        {" · "}
        <Link to={`/contributors/${a.contributor_id}`} style={{
          color: t.fgSubtle, textDecoration: "none",
          fontStyle: isAnonymous(a.contributor_name) ? "italic" : "normal",
        }}>
          {contributorLabel(tr, a.contributor_name, a.contributor_id)}
        </Link>
      </span>
    </span>
  );
}

// Remembered across records: someone reading labels wants the big one every
// time, and re-picking it on each record is the annoyance the setting removes.
const MEDIA_SIZE_KEY = "tbia.mediaSize";

function MediaGallery({ urls, sizes, references }: { urls: string[]; sizes?: MediaSize[]; references?: string }) {
  const { t: tr } = useTranslation();
  // What a click opens. The thumbnails always stay on the URL the export
  // shipped — the point of the picker is reading a label full-screen, and
  // rendering 4096px into a 120px tile would cost 750KB an image for nothing.
  const ladder = sizes ?? [];
  const [pick, setPick] = useState<string | null>(() => localStorage.getItem(MEDIA_SIZE_KEY));
  const chosen = ladder.find((s) => s.size === pick) ?? ladder.find((s) => s.canonical) ?? null;
  const openUrls = chosen ? chosen.urls : urls;
  const choose = (size: string) => { setPick(size); localStorage.setItem(MEDIA_SIZE_KEY, size); };

  if (urls.length === 0) {
    return (
      <div style={{ fontSize: 11, color: t.fgSubtle }}>
        {tr("detail.noMedia")}
        {references && <div style={{ marginTop: 6 }}><a href={references} target="_blank" rel="noreferrer" style={{ color: t.accent, fontSize: 11 }}>references ↗</a></div>}
      </div>
    );
  }
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
        {urls.slice(0, 6).map((u, i) => (
          <a key={i} href={openUrls[i] ?? u} target="_blank" rel="noreferrer" style={{ aspectRatio: "1", border: `1px solid ${t.border}`, overflow: "hidden", background: t.panelAlt }}>
            <img src={u} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
          </a>
        ))}
      </div>
      {/* Absent entirely for sources that publish one rendition — most of them. */}
      {ladder.length > 1 && (
        <div style={{ marginTop: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10, color: t.fgMuted }}>{tr("detail.openAt")}</span>
            {ladder.map((s) => (
              <Button key={s.size} small primary={chosen?.size === s.size} onClick={() => choose(s.size)}>
                {s.long_edge}px
              </Button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 3 }}>{tr("detail.openAtHint")}</div>
        </div>
      )}
    </>
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
  // What the AI proposed for a field that was seeded from it, kept beside the
  // editable value. Lets submit tell apart ai (kept verbatim), mixed (AI value
  // then edited) and manual (typed) — and lets it send the AI's own value along,
  // so a correction is stored as data rather than inferred from a label.
  const [aiSeed, setAiSeed] = useState<Record<string, AiSeed>>({});
  // A transcription the contributor pasted back from their own AI chat (route
  // B). It wins over the stored server-side proposal while it is on screen: it
  // is the newer answer, and an explicit act rather than something that arrived.
  const [pasted, setPasted] = useState<Proposal | null>(null);
  // The proposal in force: whichever of the two the contributor is working from.
  // The server-side one lives on the record (transcribe.fields), so it survives
  // a reload and reaches whoever comes back for it later.
  const proposal: Proposal | null = useMemo(() => {
    if (pasted) return pasted;
    const q = record.transcribe;
    if (!q || !q.fields || q.fields.length === 0) return null;
    return { fields: q.fields, model: q.model, service: q.service, extracted_at: q.processed_at };
  }, [pasted, record.transcribe]);
  const [note, setNote] = useState("");
  // Terms this submission is released under. Applies to every field submitted
  // in one click — the form writes one annotation per filled field, and they
  // are one act of contribution, so splitting the grant between them would be
  // a distinction the contributor never made.
  //
  // Seeded from the contributor's own default (Dashboard → settings), which is
  // where a standing preference belongs; changing it here is a choice about
  // *this* submission and leaves the default alone.
  const [license, setLicense] = useState<License>(() => asLicense(user?.default_license));
  const profileLicense = asLicense(user?.default_license);
  // `user` arrives after the first paint (App fetches /auth/me), so the picker
  // would otherwise sit on the platform fallback while the contributor's own
  // default was already known. Only re-seeds while the form is untouched.
  const touchedLicense = useRef(false);
  useEffect(() => {
    if (!touchedLicense.current) setLicense(profileLicense);
  }, [profileLicense]);

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
  // Every edit clears the receipt: it reports the *last* submission, and left
  // sitting above a half-filled form it would read as a report on this one.
  // `setVal` is where typing lands (input, textarea and select all use it), and
  // the two composite widgets below call it out on their own paths.
  const setVal = (f: string, v: string) => { setReceipt(null); setValues((s) => ({ ...s, [f]: v })); };
  const groupOf = (name: string) =>
    ANNOTATABLE_GROUPS.find((g) => g.fields.some((f) => f.name === name))?.labelKey;
  // A DMS sub-part changed: store it and keep the sibling decimal field in sync.
  const setDms = (fd: FieldDef, part: "hemi" | "deg" | "min" | "sec", v: string) => {
    setReceipt(null);
    setValues((s) => {
      const next = { ...s, [`${fd.name}.${part}`]: v };
      if (fd.decimalField) next[fd.decimalField] = dmsToDecimal(fd, next);
      return next;
    });
  };

  // ai = kept the AI value verbatim; mixed = AI value the human edited;
  // manual = typed with no AI seed for this field.
  const sourceFor = (name: string, value: string): string => {
    const seed = aiSeed[name];
    if (seed === undefined) return "manual";
    return value === seed.value ? "ai" : "mixed";
  };
  // Record that a field was seeded from an AI proposal (used by sourceFor, and
  // sent with the submission as ai_value / ai_confidence / ai_model).
  const seed = (name: string, value: string, meta?: ProposalMeta) =>
    setAiSeed((s) => ({
      ...s,
      [name]: { value, confidence: meta?.confidence ?? null, model: meta?.model ?? null },
    }));

  // Apply an AI proposal into the form. Most fields are a plain string, but the
  // eventDate composite must be split into its year/month/day sub-inputs;
  // seed the serialized (padded) form so sourceFor still classifies it "ai".
  const applyDraft = (name: string, value: string, meta?: ProposalMeta) => {
    if (name !== "eventDate") { setVal(name, value); seed(name, value, meta); return; }
    const m = value.trim().match(/^(\d{4})(?:[-/.](\d{1,2}))?(?:[-/.](\d{1,2}))?/);
    const y = m?.[1] ?? "";
    const mo = m?.[2] ? String(parseInt(m[2], 10)) : "";
    const d = m?.[3] ? String(parseInt(m[3], 10)) : "";
    setReceipt(null);
    setValues((s) => ({ ...s, "eventDate.y": y, "eventDate.mo": mo, "eventDate.d": d }));
    seed(name, y ? `${y.padStart(4, "0")}-${(mo || "").padStart(2, "0")}-${(d || "").padStart(2, "0")}` : "", meta);
  };
  // Apply one proposed field, and bring its class tab forward so the value is
  // where the contributor is looking rather than behind a tab.
  const useProposed = (f: ExtractedField) => {
    applyDraft(f.field, f.value, { confidence: f.confidence, model: proposal?.model ?? null });
    const g = groupOf(f.field); if (g) setActiveGroup(g);
  };

  // Empty every field still holding its AI value verbatim, and forget the seed.
  // Only those: a value the contributor edited is theirs now, and clearing it
  // would throw away work rather than an AI's suggestion.
  const clearAi = () => {
    const drop = ALL_FIELDS.filter((fd) => {
      const s = aiSeed[fd.name];
      return s !== undefined && serializeField(fd, values) === s.value;
    });
    if (drop.length === 0) return;
    setValues((v) => {
      const next = { ...v };
      for (const fd of drop) {
        if (fd.widget === "date") { next["eventDate.y"] = ""; next["eventDate.mo"] = ""; next["eventDate.d"] = ""; }
        else if (fd.widget === "dms") { for (const part of ["deg", "min", "sec"]) next[`${fd.name}.${part}`] = ""; }
        else next[fd.name] = "";
        if (fd.decimalField) next[fd.decimalField] = "";
      }
      return next;
    });
    setAiSeed((s) => {
      const next = { ...s };
      for (const fd of drop) delete next[fd.name];
      return next;
    });
  };

  // ── Auto-fill ─────────────────────────────────────────────────────────────
  // A proposal lands in the widgets rather than waiting behind a button: the
  // contributor's job is to read the label and decide, and an empty form with a
  // list beside it makes them copy before they can judge.
  //
  // Twice never, though. It fills only fields that are *empty* — never over
  // typing, and never back into something deliberately cleared — and only once
  // per distinct proposal, so a poll or a re-render cannot undo an edit. A field
  // this contributor already submitted from the same AI value is skipped too:
  // coming back to a record should not re-offer work already done.
  const autoFilled = useRef<string>("");
  const proposalSig = proposal ? proposal.fields.map((f) => `${f.field}=${f.value}`).join("|") : "";
  useEffect(() => {
    if (!proposal || proposalSig === autoFilled.current) return;
    autoFilled.current = proposalSig;
    const acted = new Set(
      record.annotations
        .filter((a) => a.contributor_id === user?.id && a.ai_value != null)
        .map((a) => `${a.field}=${a.ai_value}`)
    );
    const got: string[] = [];
    for (const f of proposal.fields) {
      const fd = ALL_FIELDS.find((x) => x.name === f.field);
      if (!fd || serializeField(fd, values) !== "") continue;
      if (acted.has(`${f.field}=${f.value}`)) continue;
      applyDraft(f.field, f.value, { confidence: f.confidence, model: proposal.model ?? null });
      const g = groupOf(f.field);
      if (g && !got.includes(g)) got.push(g);
    }
    // Which tab to leave them on. Stay where the panel already is if that class
    // got something — it was chosen from the record's own gap, which is why the
    // contributor is here. Otherwise the first class that did, skipping "other":
    // full_text leads every transcription, so following the proposal's order
    // blindly would always land on the whole-label textarea and hide the fields.
    const next = got.includes(activeGroup) ? activeGroup
      : got.find((g) => g !== "annotate.grpOther") ?? got[0];
    if (next) setActiveGroup(next);
    // `values` is read, not tracked: re-running on every keystroke is exactly
    // what the signature guard above exists to prevent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposalSig, record.annotations, user?.id, activeGroup]);

  // What the last submission did, shown until the contributor starts typing
  // again. Submitting used to be silent — the form cleared and nothing said the
  // work had landed, let alone where it went. This is also the one moment a
  // contributor is guaranteed to be looking, so it is the cheapest place to
  // learn that their work has a page.
  const [receipt, setReceipt] = useState<{ n: number; draft: boolean } | null>(null);

  const createMut = useMutation({
    mutationFn: (status: string) => Promise.all(filled.map(({ fd, value }) => {
      const ai = aiSeed[fd.name];
      return api.createAnnotation(record.id, {
        field: fd.name, proposed_value: value, original_value: originalFor(record, fd.name),
        note: note || null,
        // The AI's own answer travels with the human's. Sent whether or not they
        // differ — agreement is as much a measurement of the transcription as a
        // correction is, and only the pair says which one this row records.
        source: sourceFor(fd.name, value),
        ai_value: ai?.value ?? null,
        ai_confidence: ai?.confidence ?? null,
        ai_model: ai?.model ?? null,
        status, license,
      });
    })),
    onSuccess: (created, status) => {
      setValues({}); setAiSeed({}); setNote(""); setPasted(null);
      setReceipt({ n: created.length, draft: status === "draft" });
      refresh();
    },
  });
  const reviewMut = useMutation({
    mutationFn: ({ annId, status }: { annId: number; status: string }) => api.updateAnnotation(annId, { status }),
    onSuccess: refresh,
  });
  // Relicensing an annotation already contributed — the contributor's own, at
  // any point in its life. What a provider already exported keeps the terms it
  // was exported with; this is what the next export will say.
  const relicenseMut = useMutation({
    mutationFn: ({ annId, license }: { annId: number; license: License }) =>
      api.updateAnnotation(annId, { license }),
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
        {/* Submitting used to say nothing at all. This is the confirmation and
            the way to the rest of your work, in the one place a contributor is
            certainly looking. The record's own history below still shows the
            new rows in context. */}
        {receipt && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6, padding: "6px 8px",
            background: t.accentSoft, border: `1px solid ${t.border}`, fontSize: 11,
          }}>
            <Icon name="check" size={12} />
            <span>{tr(receipt.draft ? "annotate.draftSavedN" : "annotate.submittedN", { n: receipt.n })}</span>
            <div style={{ flex: 1 }} />
            <Link to="/me" style={{ color: t.accent, textDecoration: "none", whiteSpace: "nowrap" }}>
              {tr("annotate.seeMine")} →
            </Link>
          </div>
        )}
        {createMut.isError && (
          <div style={{
            padding: "6px 8px", border: `1px solid ${t.danger}`, fontSize: 11, color: t.danger,
          }}>
            {tr("annotate.submitFailed")} — {(createMut.error as Error).message}
          </div>
        )}

        <AiAssist record={record} onProposal={setPasted} />

        {/* The proposal, kept on screen after it has been poured into the form:
            it is how a field the auto-fill skipped (one already filled, one
            already submitted) can still be applied by hand, and how a value can
            be checked against what the AI actually said after an edit. */}
        {proposal && (
          <ProposalList p={proposal} onUse={useProposed}
            onClear={clearAi} clearable={ALL_FIELDS.some((fd) => {
              const seeded = aiSeed[fd.name];
              return seeded !== undefined && serializeField(fd, values) === seeded.value;
            })} />
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
                  {serializeField(fd, values) !== "" && (
                    <SourceTag source={sourceFor(fd.name, serializeField(fd, values))}
                      confidence={aiSeed[fd.name]?.confidence ?? null} />
                  )}
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

          {/* Licence for this submission. Sits with the submit buttons rather
              than among the fields: it is a property of the contribution, not
              of any one value, and it is the last thing to confirm before the
              work leaves the contributor's hands. */}
          <div style={{ marginTop: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: t.fgMuted }}>{tr("annotate.license")}</span>
              <select
                value={license}
                onChange={(e) => { touchedLicense.current = true; setLicense(e.target.value as License); }}
                style={{ ...inputStyle, width: "auto", flex: 1 }}
              >
                {LICENSES.map((l) => <option key={l} value={l}>{LICENSE_LABELS[l]}</option>)}
              </select>
              <a href={LICENSE_URIS[license]} target="_blank" rel="noreferrer noopener"
                style={{ fontSize: 10, color: t.accent, whiteSpace: "nowrap" }}>{tr("annotate.licenseDeed")}</a>
            </div>
            <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 3, lineHeight: 1.4 }}>
              {tr("annotate.licenseHint")}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
            <Button primary small disabled={filled.length === 0 || createMut.isPending} onClick={() => createMut.mutate("submitted")}>{tr("annotate.submit")}</Button>
            <Button small disabled={filled.length === 0 || createMut.isPending} onClick={() => createMut.mutate("draft")}>{tr("annotate.saveDraft")}</Button>
            {filled.length > 0 && <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{filled.length} {tr("annotate.fieldsFilled")}</span>}
          </div>
        </div>

        <History annotations={record.annotations} isReviewer={isReviewer} userId={user.id}
          onReview={(annId, status) => reviewMut.mutate({ annId, status })}
          onRelicense={(annId, license) => relicenseMut.mutate({ annId, license })} />
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
// Neither route contributes anything: both end in a *proposal* the contributor
// reads, edits and submits — `onProposal` hands route B's up to the form (route
// A's arrives on the record itself, so it survives a reload).
function AiAssist({ record, onProposal }: {
  record: OccurrenceDetail; onProposal: (p: Proposal) => void;
}) {
  const { t: tr } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState<"queue" | "paste" | null>(null);
  const [pasteRaw, setPasteRaw] = useState("");
  const [copied, setCopied] = useState(false);

  const hasImage = record.media.length > 0;
  const q = record.transcribe;   // durable queue state (survives reload)

  // "Auto" sends no overrides, so what it runs is whatever the server is
  // configured for — ask, rather than showing an opaque "Auto". The same
  // response carries the route in force.
  const engineCfg = useQuery({
    queryKey: ["transcribe-config"],
    queryFn: () => api.transcribeConfig(),
    staleTime: 10 * 60_000,
  });
  // Which route this click takes is the admin's system-wide setting (Dashboard),
  // not a choice made here — under "now" it is every contributor's click that
  // runs and bills inline, not just an admin's. Until the config loads, assume
  // the queue: it is the default, and the cheap answer to be wrong about.
  const route: "queue" | "now" = engineCfg.data?.route === "now" ? "now" : "queue";
  // The server's model chain as "sonnet-5→opus-4-8" (the claude- prefix is noise
  // at this width). Read-only: the contributor doesn't pick an engine.
  const engineChain = (() => {
    const c = engineCfg.data;
    if (!c) return undefined;
    const short = (m: string) => m.replace(/^claude-/, "");
    return c.mode === "two_stage" && c.ocr_model
      ? `${short(c.ocr_model)}→${short(c.field_model)}`
      : short(c.field_model);
  })();

  // Prompt is fetched lazily — only once the user opens the copy-paste route.
  const promptQuery = useQuery({
    queryKey: ["extract-prompt", record.id],
    queryFn: () => api.extractPrompt(record.id),
    enabled: open === "paste",
  });
  const pasteMut = useMutation({
    mutationFn: () => api.extractPaste(record.id, pasteRaw),
    onSuccess: (res) => {
      onProposal({
        fields: res.fields, model: res.model, service: res.service, extracted_at: res.extracted_at,
      });
      setOpen(null); setPasteRaw("");
    },
  });
  // Queue this record for transcription (persists occ id + user id, then
  // best-effort Discord notification). Independent of submitting annotations.
  const queueMut = useMutation({
    mutationFn: () => api.scheduleTranscribe(record.id),
    onSuccess: () => { setOpen(null); qc.invalidateQueries({ queryKey: ["detail", record.id] }); },
  });
  // Run it here and now (admin). A pipeline failure comes back as a normal
  // response with status "failed", so it is read off the result rather than
  // caught as an error; the card stays open either way, because the outcome —
  // drafts written, or why not — is the thing worth reading.
  const nowMut = useMutation({
    mutationFn: () => api.transcribeNow(record.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["detail", record.id] }),
  });
  const running = queueMut.isPending || nowMut.isPending;
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
        {/* The walkthrough, from where the work actually happens. New tab on
            purpose: this panel sits above a half-filled annotation form (and,
            in Explore's split view, inside a search), and navigating away
            would discard both to read a help page. */}
        <Link to="/guide/ai-transcribe" target="_blank" rel="noreferrer" style={{
          display: "inline-flex", alignItems: "center", gap: 4, marginTop: 4,
          fontSize: 10, color: t.accent, textDecoration: "none",
        }}>
          <Icon name="spark" size={10} />{tr("annotate.aiWalk")} ↗
        </Link>
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

        {/* route A — the platform's own AI: queued for the batch worker, or,
            for an admin, run in the request they just made */}
        <OptionCard n={1}
          title={tr(route === "now" ? "annotate.optRunNowTitle" : "annotate.optQueueTitle")}
          what={tr(route === "now" ? "annotate.optRunNowWhat" : "annotate.optQueueWhat")}
          open={open === "queue"} onToggle={() => setOpen(open === "queue" ? null : "queue")}
          cta={route === "now" ? tr("annotate.optRunNowGo") : q ? tr("annotate.qAgain") : tr("annotate.optQueueGo")}
          disabled={!hasImage}
          meta={engineChain ? tr("annotate.engineIs", { name: engineChain }) : undefined}>
          <div style={{ fontSize: 10, color: t.fgSubtle }}>
            {tr(route === "now" ? "annotate.optRunNowSlow" : "annotate.optQueueSlow")}
          </div>
          {engineChain && (
            <div style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>
              {tr("annotate.engineIs", { name: engineChain })}
            </div>
          )}
          {(queueMut.isError || nowMut.isError) && (
            <div style={{ fontSize: 10, color: t.danger }}>
              {((queueMut.error || nowMut.error) as Error).message}
            </div>
          )}
          {/* run-now result: the pipeline reports its own failures in-band */}
          {nowMut.data && (
            <div style={{ fontSize: 10, color: nowMut.data.status === "failed" ? t.danger : t.ok }}>
              {nowMut.data.status === "failed"
                ? `${tr("annotate.qFailed")} — ${nowMut.data.error ?? ""}`
                : tr("annotate.nowDone", { n: nowMut.data.n_fields })}
            </div>
          )}
          {nowMut.isPending && <div style={{ fontSize: 10, color: t.warn }}>{tr("annotate.nowRunning")}</div>}
          <Button primary small disabled={!hasImage || running}
            onClick={() => (route === "now" ? nowMut : queueMut).mutate()}>
            {running ? "…" : (
              <>
                <Icon name={route === "now" ? "spark" : "down"} size={11} />
                {route === "now" ? tr("annotate.optRunNowGo") : q ? tr("annotate.qAgain") : tr("annotate.optQueueGo")}
              </>
            )}
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
                {/* One link per image: a record's media are views of the same
                    specimen (sheet, label close-up, determination slip), and the
                    prompt below asks the chat to read them together. */}
                {promptQuery.data.image_urls.length > 0 ? (
                  <>
                    {promptQuery.data.image_urls.map((url, i, all) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer"
                        style={{ color: t.accent, fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                        <Icon name="img" size={11} />
                        {all.length > 1 ? tr("annotate.step1n", { n: i + 1 }) : tr("annotate.step1")} ↗
                      </a>
                    ))}
                    <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 2 }}>
                      {tr(promptQuery.data.image_urls.length > 1 ? "annotate.step1hintMulti" : "annotate.step1hint")}
                    </div>
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

    </div>
  );
}

// The transcription, listed beside the form it has already been poured into.
// Not a queue of things to accept — the values are in the widgets — but the
// record of what the AI said: what it was sure about, and what it proposed for a
// field the auto-fill left alone because the contributor was already working in
// it, or had already submitted from the same proposal.
function ProposalList({ p, onUse, onClear, clearable }: {
  p: Proposal; onUse: (f: ExtractedField) => void; onClear: () => void; clearable: boolean;
}) {
  const { t: tr } = useTranslation();
  return (
    <div style={{ border: `1px solid ${t.borderSoft}`, background: t.panel, padding: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
        <span style={{ fontSize: 11, fontWeight: 600 }}>{tr("annotate.draftsTitle")} · {p.fields.length}</span>
        <div style={{ flex: 1 }} />
        {clearable && <Button small onClick={onClear}>{tr("annotate.clearAi")}</Button>}
        {p.fields.length > 1 && (
          <Button small onClick={() => p.fields.forEach(onUse)}>{tr("annotate.applyAll")}</Button>
        )}
      </div>
      <div style={{ fontSize: 10, color: t.fgMuted, lineHeight: 1.5, marginBottom: 6 }}>{tr("annotate.draftsHint")}</div>
      <div style={{ fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, marginBottom: 4 }}>
        {[p.service, p.model].filter(Boolean).join(" · ")}
        {p.extracted_at ? `, ${String(p.extracted_at).slice(0, 16).replace("T", " ")}` : ""}
      </div>
      {p.fields.map((d, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 6px", marginBottom: 3, background: t.panelAlt, border: `1px solid ${t.borderSoft}`, fontSize: 11 }}>
          <span style={{ fontSize: 10, color: t.fgMuted, width: 78, flexShrink: 0 }} title={d.field}>{tr(`fields.${d.field}`, d.field)}</span>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={d.value}>{d.value}</span>
          <span style={{ fontSize: 9, color: t.ok, fontFamily: t.mono }} title={tr("annotate.confidence")}>{Math.round(d.confidence * 100)}%</span>
          <Button small onClick={() => onUse(d)}>{tr("annotate.apply")}</Button>
        </div>
      ))}
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
        {when} · {tr("annotate.qBy", { who: contributorLabel(tr, q.requested_by, q.requested_by_id) })}
      </div>
    </div>
  );
}

// Value provenance: ai (kept verbatim) · mixed (AI, then human-edited) ·
// manual (typed). Legacy rows may be blank → treated as manual (no tag).
function SourceTag({ source, confidence }: { source: string; confidence?: number | null }) {
  const { t: tr } = useTranslation();
  if (source !== "ai" && source !== "mixed") return null;
  const tone = source === "ai" ? t.accent : t.warn;
  return (
    <span title={tr(`annotate.src_${source}`)} style={{
      display: "inline-flex", alignItems: "center", gap: 2, fontSize: 9,
      fontFamily: t.mono, color: tone, border: `1px solid ${tone}`, padding: "0 3px",
    }}>
      <Icon name="spark" size={8} />{tr(`annotate.src_${source}`)}
      {/* How sure the model was about the value now sitting in the widget —
          the one number that says which proposals to read twice. */}
      {confidence != null && <span title={tr("annotate.confidence")}>{Math.round(confidence * 100)}%</span>}
    </span>
  );
}

function History({ annotations, isReviewer, onReview, userId, onRelicense }: {
  annotations: OccurrenceDetail["annotations"]; isReviewer: boolean;
  onReview: (annId: number, status: string) => void;
  /** The signed-in contributor, or undefined when nobody is. Only their own
   *  rows get the licence picker — nobody restates someone else's terms. */
  userId?: number;
  onRelicense?: (annId: number, license: License) => void;
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
            {/* The terms it was contributed under — a reviewer decides whether
                to accept a value into the provider export, and the licence is
                half of what that decision rests on. Its contributor can change
                it here at any time, in any status: what an earlier export
                delivered stays as delivered, and this sets what the next one
                says. Everyone else reads it. */}
            {/* The byline opens that contributor's work. A name on a record was
                the end of the trail; it is now the way into everything else
                they have done. */}
            <span style={{ fontSize: 10, color: t.fgSubtle }}>— </span>
            <Link to={`/contributors/${a.contributor_id}`}
                  style={{ fontSize: 10, color: t.fgSubtle, textDecoration: "none",
                           fontStyle: isAnonymous(a.contributor_name) ? "italic" : "normal" }}
                  title={isAnonymous(a.contributor_name) ? tr("vol.anonymousHint") : undefined}>
              {contributorLabel(tr, a.contributor_name, a.contributor_id)}
            </Link>
            <span style={{ fontSize: 10, color: t.fgSubtle }}>·</span>
            {userId === a.contributor_id && onRelicense ? (
              <select value={asLicense(a.license)} title={tr("annotate.licenseChange")}
                onChange={(e) => onRelicense(a.id, e.target.value as License)}
                style={{
                  fontSize: 10, fontFamily: t.mono, color: t.fgMuted, padding: "1px 2px",
                  background: t.panelAlt, border: `1px solid ${t.borderSoft}`, cursor: "pointer",
                }}>
                {LICENSES.map((l) => <option key={l} value={l}>{LICENSE_LABELS[l]}</option>)}
              </select>
            ) : (
              <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{licenseLabel(a.license)}</span>
            )}
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
    taxonRank: r.taxon_rank, eventDate: r.standard_date, locality: r.locality,
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
