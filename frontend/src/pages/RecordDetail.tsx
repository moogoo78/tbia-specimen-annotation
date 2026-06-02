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

const ANNOTATABLE = ["scientificName", "taxonRank", "eventDate", "decimalLatitude", "decimalLongitude", "locality"];

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
        {!embedded && <Link to="/" style={{ color: t.fgMuted, display: "flex", alignItems: "center", marginTop: 4 }}><Icon name="back" size={16} /></Link>}
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
            <Link to="/" state={{ collector: { id: c.id, label: c.label } }}
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
  const [field, setField] = useState(
    !record.has_identification ? "scientificName" :
    !record.has_coordinates ? "decimalLatitude" :
    !record.has_date ? "eventDate" : "scientificName"
  );
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [drafts, setDrafts] = useState<ExtractedField[]>([]);
  const [model, setModel] = useState<string | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ["detail", record.id] });

  const extractMut = useMutation({
    mutationFn: () => api.extract(record.id),
    onSuccess: (res) => { setDrafts(res.fields); setModel(res.model); },
  });
  const createMut = useMutation({
    mutationFn: (status: string) => api.createAnnotation(record.id, {
      field, proposed_value: value, original_value: originalFor(record, field),
      note: note || null, source: drafts.some((d) => d.field === field && d.value === value) ? "ai" : "manual",
      status,
    }),
    onSuccess: () => { setValue(""); setNote(""); refresh(); },
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
        {/* AI extract */}
        <Button small onClick={() => extractMut.mutate()} disabled={extractMut.isPending}>
          <Icon name="spark" size={11} />{extractMut.isPending ? "…" : tr("annotate.aiExtract")}
        </Button>
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
            <Button small onClick={() => { setField(d.field); setValue(d.value); }}>{tr("annotate.apply")}</Button>
          </div>
        ))}

        {/* manual form */}
        <div style={{ borderTop: `1px solid ${t.borderSoft}`, paddingTop: 8 }}>
          <select value={field} onChange={(e) => setField(e.target.value)} style={inputStyle}>
            {ANNOTATABLE.map((f) => <option key={f} value={f}>{tr(`fields.${f}`, f)}</option>)}
          </select>
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={tr("annotate.proposed")} style={{ ...inputStyle, marginTop: 6 }} />
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={tr("annotate.note")} style={{ ...inputStyle, marginTop: 6 }} />
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <Button primary small disabled={!value || createMut.isPending} onClick={() => createMut.mutate("submitted")}>{tr("annotate.submit")}</Button>
            <Button small disabled={!value || createMut.isPending} onClick={() => createMut.mutate("draft")}>{tr("annotate.saveDraft")}</Button>
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

function originalFor(r: OccurrenceDetail, field: string): string | null {
  const map: Record<string, unknown> = {
    scientificName: r.scientific_name, taxonRank: r.taxon_rank, eventDate: r.std_date,
    decimalLatitude: r.std_lat, decimalLongitude: r.std_lon, locality: r.locality,
  };
  const v = map[field];
  return v == null ? null : String(v);
}

const inputStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", padding: "5px 7px", fontSize: 12,
  border: `1px solid ${t.border}`, background: t.panelAlt, outline: "none", fontFamily: t.sans,
};
