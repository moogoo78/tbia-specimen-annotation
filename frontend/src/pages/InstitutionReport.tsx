import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api, getToken } from "../api/client";
import type { Annotation, InstitutionReport as Report, ReportFilters, ReportRecord } from "../api/types";
import { useAuth } from "../auth";
import { Button, SourceTag, Spinner, StatusPill } from "../components/ui";
import { MediaViewer } from "../components/MediaGallery";
import { contributorLabel, isAnonymous } from "../contributors";
import { licenseLabel } from "../licenses";

// One institution's annotations, for the data provider that holds the records
// and for the reviewer working through them. A summary on top; below it a
// split pane — the annotated records on the left, the selected one on the
// right with its specimen image beside each old → new value.
//
// Public, like the record page it summarises: the server excludes drafts and
// withholds names that were not opted in. The right pane reads the record's own
// detail (`api.detail`), so the image and the history here are exactly what
// /record/:id shows.
//
// Filter state and the selected record are the query string (`status`,
// `field`, `ds`, `r`), so a provider can be sent a link to precisely the rows
// in question. Every write goes through `update()` — one URL write per handler.

const STATUSES = ["submitted", "accepted", "merged", "rejected"] as const;
const PAGE = 50;

export function InstitutionReport() {
  const { code = "" } = useParams();
  const { t: tr } = useTranslation();
  const { user } = useAuth();
  const isReviewer = user?.role === "reviewer" || user?.role === "admin";
  const [sp, setSp] = useSearchParams();

  const filters: ReportFilters = {
    status: sp.get("status") || undefined,
    field: sp.get("field") || undefined,
    tbia_dataset_id: sp.get("ds") || undefined,
  };
  const offset = Number(sp.get("offset") || 0);
  const selected = sp.get("r");

  const update = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === "") next.delete(k); else next.set(k, v);
    }
    setSp(next, { replace: true });
  }, [sp, setSp]);
  // A filter change resets the page and the selection, in the same write.
  const setFilter = (k: "status" | "field" | "ds", v: string | null) =>
    update({ [k]: sp.get(k) === v ? null : v, offset: null, r: null });

  const summary = useQuery({ queryKey: ["report", code], queryFn: () => api.institutionReport(code) });
  const records = useQuery({
    queryKey: ["reportRecords", code, filters, offset],
    queryFn: () => api.reportRecords(code, filters, PAGE, offset),
  });
  const items = records.data?.items ?? [];

  // Land on the first record so the pane is never empty when there is work.
  useEffect(() => {
    if (!selected && items.length > 0) update({ r: items[0].occurrence_id });
  }, [selected, items, update]);

  const move = useCallback((d: number) => {
    const i = items.findIndex((x) => x.occurrence_id === selected);
    const n = items[Math.max(0, Math.min(items.length - 1, i + d))];
    if (n && n.occurrence_id !== selected) update({ r: n.occurrence_id });
  }, [items, selected, update]);

  if (summary.isLoading) return <Spinner />;
  if (summary.isError || !summary.data) {
    return <div style={{ padding: 16, fontSize: 12, color: t.fgMuted }}>{tr("report.notFound")}</div>;
  }
  const s = summary.data;

  return (
    <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
      <Summary s={s} filters={filters} onFilter={setFilter} isReviewer={isReviewer} />
      <div style={{ flex: 1, minHeight: 560, display: "flex", borderTop: `1px solid ${t.border}`, flexWrap: "wrap" }}>
        <RecordList items={items} total={records.data?.total ?? 0} loading={records.isLoading}
          offset={offset} selected={selected} filters={filters}
          onSelect={(id) => update({ r: id })}
          onPage={(o) => update({ offset: o ? String(o) : null, r: null })}
          onClear={() => update({ status: null, field: null, ds: null, offset: null, r: null })} />
        <div style={{ flex: "1 1 520px", minWidth: 0 }}>
          {selected
            ? <ReviewPane id={selected} code={code} isReviewer={isReviewer} onMove={move} />
            : <div style={{ padding: 16, fontSize: 12, color: t.fgSubtle }}>{records.isLoading ? "" : tr("report.noRecords")}</div>}
        </div>
      </div>
    </div>
  );
}

// ── summary ─────────────────────────────────────────────────────────────────

function Tile({ label, value, tone, active, onClick }: {
  label: string; value: number; tone?: string; active?: boolean; onClick?: () => void;
}) {
  return (
    <button data-tile={label} onClick={onClick} disabled={!onClick} style={{
      textAlign: "left", padding: "8px 12px", minWidth: 110, cursor: onClick ? "pointer" : "default",
      background: active ? t.panelAlt : t.panel, color: t.fg,
      border: `1px solid ${active ? t.accent : t.border}`,
    }}>
      <div style={{ fontSize: 10, color: t.fgMuted, textTransform: "uppercase", letterSpacing: 0.3 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, fontFamily: t.mono, color: tone ?? t.fg }}>{value.toLocaleString()}</div>
    </button>
  );
}

const TONE: Record<string, string> = { submitted: t.warn, accepted: t.ok, rejected: t.danger, merged: t.accent };

function Summary({ s, filters, onFilter, isReviewer }: {
  s: Report; filters: ReportFilters; isReviewer: boolean;
  onFilter: (k: "status" | "field" | "ds", v: string | null) => void;
}) {
  const { t: tr } = useTranslation();
  const th: React.CSSProperties = { textAlign: "right", fontWeight: 500, color: t.fgMuted, padding: "3px 6px", fontSize: 10 };
  const td: React.CSSProperties = { textAlign: "right", fontFamily: t.mono, padding: "3px 6px", fontSize: 11 };
  const row = (active: boolean): React.CSSProperties => ({
    cursor: "pointer", background: active ? t.panelAlt : undefined, borderBottom: `1px solid ${t.borderSoft}`,
  });
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <Link to="/institutions" style={{ fontSize: 11, color: t.accent, textDecoration: "none" }}>
          ← {tr("inst.title")}
        </Link>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", margin: "6px 0 2px" }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0, flex: "1 1 auto", minWidth: 0 }}>
          <span style={{ fontFamily: t.mono, fontSize: 12, color: t.fgSubtle, marginRight: 8 }}>{s.code}</span>
          {s.name}
        </h2>
        {isReviewer && (
          // Kind-qualified, like the link that led here: a bare code that is
          // both curated and discovered would resolve to the curated one.
          <CsvButton path={`/api/reports/institutions/${encodeURIComponent(`${s.kind}:${s.code}`)}/export`}
            filename={`island_${s.code}_annotations.csv`} title={tr("report.exportAllHint")}
            label={tr("report.exportAll")} />
        )}
      </div>
      <div style={{ fontSize: 11, color: t.fgMuted, marginBottom: 12 }}>
        {tr("report.blurb", { records: s.n_records.toLocaleString(), datasets: s.n_datasets })}
        {s.last_activity && <> · {tr("report.lastActivity")} {s.last_activity.slice(0, 10)}</>}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        <Tile label={tr("report.total")} value={s.by_status.total}
          active={!filters.status} onClick={() => onFilter("status", null)} />
        <Tile label={tr("report.pendingRecords")} value={s.n_records_pending} tone={t.warn} />
        {STATUSES.map((st) => (
          <Tile key={st} label={tr(`status.${st}`)} value={s.by_status[st]} tone={TONE[st]}
            active={filters.status === st} onClick={() => onFilter("status", st)} />
        ))}
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-start" }}>
        <Panel title={tr("report.byField")}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead><tr>
              <th style={{ ...th, textAlign: "left" }}>{tr("annotate.field")}</th>
              {STATUSES.map((st) => <th key={st} style={th}>{tr(`status.${st}`)}</th>)}
              <th style={th}>{tr("report.total")}</th>
            </tr></thead>
            <tbody>
              {s.by_field.map((f) => (
                <tr key={f.field} onClick={() => onFilter("field", f.field)} style={row(filters.field === f.field)}>
                  <td style={{ ...td, textAlign: "left", color: t.accent }}>{f.field}</td>
                  {STATUSES.map((st) => <td key={st} style={{ ...td, color: f[st] ? TONE[st] : t.fgSubtle }}>{f[st] || "·"}</td>)}
                  <td style={{ ...td, fontWeight: 600 }}>{f.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title={tr("report.byDataset")}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead><tr>
              <th style={{ ...th, textAlign: "left" }}>{tr("report.dataset")}</th>
              <th style={th}>{tr("report.records")}</th>
              <th style={th}>{tr("status.submitted")}</th>
              <th style={th}>{tr("report.total")}</th>
              {isReviewer && <th style={th} />}
            </tr></thead>
            <tbody>
              {s.by_dataset.map((d) => (
                <tr key={d.tbia_dataset_id} onClick={() => onFilter("ds", d.tbia_dataset_id)}
                  style={row(filters.tbia_dataset_id === d.tbia_dataset_id)}>
                  <td style={{ ...td, textAlign: "left", fontFamily: t.sans, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={d.dataset_name ?? ""}>{d.dataset_name ?? d.tbia_dataset_id}</td>
                  <td style={td}>{d.n_records}</td>
                  <td style={{ ...td, color: d.submitted ? t.warn : t.fgSubtle }}>{d.submitted || "·"}</td>
                  <td style={{ ...td, fontWeight: 600 }}>{d.total}</td>
                  {isReviewer && (
                    <td style={td} onClick={(e) => e.stopPropagation()}>
                      {d.dataset_name && (
                        <CsvButton path={`/api/export/provider?dataset_name=${encodeURIComponent(d.dataset_name)}&format=csv`}
                          filename={`annotations-${d.dataset_name}.csv`} title={tr("report.exportCsv")} />
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title={tr("report.contributors")} narrow>
          {s.contributors.map((c) => (
            <div key={c.contributor_id} style={{ display: "flex", gap: 8, fontSize: 11, padding: "3px 0", borderBottom: `1px solid ${t.borderSoft}` }}>
              <Link to={`/contributors/${c.contributor_id}`} style={{
                flex: 1, color: isAnonymous(c.contributor_name) ? t.fgMuted : t.accent, textDecoration: "none",
                fontStyle: isAnonymous(c.contributor_name) ? "italic" : "normal",
              }} title={isAnonymous(c.contributor_name) ? tr("vol.anonymousHint") : undefined}>
                {contributorLabel(tr, c.contributor_name, c.contributor_id)}
              </Link>
              <span style={{ fontFamily: t.mono, color: t.fgMuted }}>{c.n_annotations}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function Panel({ title, narrow, children }: { title: string; narrow?: boolean; children: React.ReactNode }) {
  return (
    <div style={{
      flex: narrow ? "0 1 240px" : "1 1 360px", minWidth: 0, background: t.panel, border: `1px solid ${t.border}`,
    }}>
      <div style={{
        padding: "6px 10px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`,
        fontSize: 10, fontWeight: 600, textTransform: "uppercase", color: t.fgMuted, letterSpacing: 0.3,
      }}>{title}</div>
      <div style={{ padding: "4px 10px 8px", maxHeight: 260, overflow: "auto" }}>{children}</div>
    </div>
  );
}

/** A reviewer-only CSV, as a file. Both exports need the reviewer's bearer
 *  token, which a plain link cannot carry, so it is fetched and saved. */
function CsvButton({ path, filename, title, label }: {
  path: string; filename: string; title: string; label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      const token = getToken();
      const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(res.statusText);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("[report] export failed", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button small onClick={download} disabled={busy} title={title}>
      <Icon name="down" size={11} />{label && <span style={{ marginLeft: 4 }}>{label}</span>}
    </Button>
  );
}

// ── record list ────────────────────────────────────────────────────────────

function RecordList({ items, total, loading, offset, selected, filters, onSelect, onPage, onClear }: {
  items: ReportRecord[]; total: number; loading: boolean; offset: number; selected: string | null;
  filters: ReportFilters; onSelect: (id: string) => void; onPage: (o: number) => void; onClear: () => void;
}) {
  const { t: tr } = useTranslation();
  const filtered = !!(filters.status || filters.field || filters.tbia_dataset_id);
  return (
    <div style={{ flex: "0 1 360px", minWidth: 280, borderRight: `1px solid ${t.border}`, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`, fontSize: 11 }}>
        <span style={{ fontWeight: 600 }}>{tr("report.recordsN", { n: total.toLocaleString() })}</span>
        {filtered && (
          <>
            {[filters.status && tr(`status.${filters.status}`), filters.field, filters.tbia_dataset_id && tr("report.oneDataset")]
              .filter(Boolean).map((x) => (
                <span key={String(x)} style={{ fontSize: 10, fontFamily: t.mono, border: `1px solid ${t.border}`, padding: "0 4px", color: t.fgMuted }}>{x}</span>
              ))}
            <button onClick={onClear} style={{ border: "none", background: "none", color: t.accent, cursor: "pointer", fontSize: 10 }}>
              {tr("report.clear")}
            </button>
          </>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: t.fgSubtle }} title={tr("report.keysHint")}>j / k</span>
      </div>
      <div style={{ flex: 1, overflow: "auto", maxHeight: 720 }}>
        {loading && <Spinner />}
        {items.map((r) => {
          const on = r.occurrence_id === selected;
          return (
            <div key={r.occurrence_id} data-record={r.occurrence_id} onClick={() => onSelect(r.occurrence_id)} style={{
              display: "flex", gap: 8, padding: "6px 10px", cursor: "pointer",
              borderBottom: `1px solid ${t.borderSoft}`, borderLeft: `3px solid ${on ? t.accent : "transparent"}`,
              background: on ? t.panelAlt : undefined,
            }}>
              <div style={{ width: 44, height: 44, flexShrink: 0, background: t.panelAlt, border: `1px solid ${t.borderSoft}`, overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {r.thumbnail
                  ? <img src={r.thumbnail} loading="lazy" alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }}
                      onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }} />
                  : <Icon name="img" size={14} />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontStyle: "italic", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.scientific_name || <span style={{ fontStyle: "normal", color: t.fgSubtle }}>—</span>}
                </div>
                <div style={{ fontSize: 10, fontFamily: t.mono, color: t.fgMuted }}>{r.catalog_number || r.occurrence_id}</div>
                <div style={{ display: "flex", gap: 6, marginTop: 2, flexWrap: "wrap" }}>
                  {STATUSES.filter((st) => r.by_status[st] > 0).map((st) => (
                    <span key={st} style={{ fontSize: 10, color: TONE[st], fontFamily: t.mono }}>
                      ● {r.by_status[st]} {tr(`status.${st}`)}
                    </span>
                  ))}
                </div>
                <div style={{ fontSize: 10, color: t.fgSubtle, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.fields.join(" · ")}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {total > PAGE && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderTop: `1px solid ${t.borderSoft}`, fontSize: 10 }}>
          <Button small disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE))}>‹</Button>
          <span style={{ fontFamily: t.mono, color: t.fgMuted }}>
            {offset + 1}–{Math.min(total, offset + PAGE)} / {total}
          </span>
          <Button small disabled={offset + PAGE >= total} onClick={() => onPage(offset + PAGE)}>›</Button>
        </div>
      )}
    </div>
  );
}

// ── the selected record ────────────────────────────────────────────────────

function ReviewPane({ id, code, isReviewer, onMove }: {
  id: string; code: string; isReviewer: boolean; onMove: (d: number) => void;
}) {
  const { t: tr } = useTranslation();
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["detail", id], queryFn: () => api.detail(id) });

  // The detail payload already excludes drafts (annotations_store); kept as a
  // belt-and-braces filter so this pane cannot regress if that ever changes.
  const anns = useMemo(
    () => (detail.data?.annotations ?? []).filter((a) => a.status !== "draft"),
    [detail.data],
  );
  // Grouped by field, newest first within each (the payload is `created desc`).
  const groups = useMemo(() => {
    const m = new Map<string, Annotation[]>();
    for (const a of anns) m.set(a.field, [...(m.get(a.field) ?? []), a]);
    return [...m.entries()];
  }, [anns]);
  const pending = anns.filter((a) => a.status === "submitted");
  const [focus, setFocus] = useState(0);
  useEffect(() => setFocus(0), [id]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["detail", id] });
    qc.invalidateQueries({ queryKey: ["report", code] });
    qc.invalidateQueries({ queryKey: ["reportRecords", code] });
  };
  const review = useMutation({
    mutationFn: async (batch: { annId: number; status: string }[]) => {
      for (const b of batch) await api.updateAnnotation(b.annId, { status: b.status });
    },
    onSuccess: refresh,
    onError: refresh,
  });

  // j/k between records; a/r on the focused submitted row (reviewers only).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (el instanceof Element && el.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "j") onMove(1);
      else if (e.key === "k") onMove(-1);
      else if (isReviewer && !review.isPending && (e.key === "a" || e.key === "r")) {
        const target = pending[Math.min(focus, pending.length - 1)];
        if (target) review.mutate([{ annId: target.id, status: e.key === "a" ? "accepted" : "rejected" }]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onMove, isReviewer, pending, focus, review]);

  if (detail.isLoading) return <Spinner />;
  if (!detail.data) return <div style={{ padding: 16, fontSize: 12, color: t.fgSubtle }}>{tr("report.recordGone")}</div>;
  const r = detail.data;
  const focusedId = pending[Math.min(focus, pending.length - 1)]?.id;

  return (
    <div style={{ padding: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <span style={{ fontSize: 15, fontStyle: "italic", fontWeight: 600 }}>{r.scientific_name || "—"}</span>
        <span style={{ fontSize: 11, fontFamily: t.mono, color: t.fgMuted }}>{r.catalog_number}</span>
        <span style={{ fontSize: 11, color: t.fgSubtle }}>{r.dataset_name}</span>
        <span style={{ flex: 1 }} />
        <Link to={`/record/${r.id}`} style={{ fontSize: 11, color: t.accent }}>{tr("report.openRecord")} →</Link>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: "1 1 340px", minWidth: 0 }}>
          <MediaViewer urls={r.media} sizes={r.media_sizes} references={r["references"] as string} />
        </div>

        <div style={{ flex: "1 1 340px", minWidth: 0 }}>
          {isReviewer && pending.length > 1 && (
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
              <Button small primary disabled={review.isPending}
                onClick={() => review.mutate(pending.map((a) => ({ annId: a.id, status: "accepted" })))}>
                {tr("report.acceptAll", { n: pending.length })}
              </Button>
            </div>
          )}
          {groups.length === 0 && <div style={{ fontSize: 11, color: t.fgSubtle }}>{tr("report.noAnnotations")}</div>}
          {groups.map(([field, rows]) => (
            <div key={field} style={{ border: `1px solid ${t.border}`, background: t.panel, marginBottom: 8 }}>
              <div style={{ padding: "4px 8px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`, fontSize: 10, fontFamily: t.mono, color: t.fgMuted }}>
                {field}{rows.length > 1 && <span style={{ color: t.fgSubtle }}> · {rows.length}</span>}
              </div>
              {rows.map((a) => (
                <DiffRow key={a.id} a={a} focused={a.id === focusedId}
                  onFocus={() => { const i = pending.findIndex((p) => p.id === a.id); if (i >= 0) setFocus(i); }}
                  isReviewer={isReviewer} busy={review.isPending}
                  onReview={(status) => review.mutate([{ annId: a.id, status }])} />
              ))}
            </div>
          ))}
          {review.isError && <div style={{ fontSize: 11, color: t.danger }}>{String((review.error as Error).message)}</div>}
        </div>
      </div>
    </div>
  );
}

function DiffRow({ a, focused, onFocus, isReviewer, busy, onReview }: {
  a: Annotation; focused: boolean; onFocus: () => void;
  isReviewer: boolean; busy: boolean; onReview: (status: string) => void;
}) {
  const { t: tr } = useTranslation();
  // An AI value that differs from what was sent is a human correction — the
  // fact a reviewer most wants to see, since it says which reading to trust.
  const corrected = a.ai_value != null && a.ai_value !== a.proposed_value;
  return (
    <div data-diff={a.id} data-status={a.status} onClick={onFocus} style={{
      padding: "6px 8px", borderBottom: `1px solid ${t.borderSoft}`,
      borderLeft: `3px solid ${focused ? t.warn : "transparent"}`,
    }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 6, alignItems: "start", fontSize: 12 }}>
        <div>
          <div style={{ fontSize: 9, color: t.fgSubtle, textTransform: "uppercase" }}>{tr("report.old")}</div>
          <div style={{ color: t.fgMuted, textDecoration: a.original_value ? "line-through" : "none", wordBreak: "break-word" }}>
            {a.original_value || "∅"}
          </div>
        </div>
        <div style={{ color: t.fgSubtle, paddingTop: 12 }}>→</div>
        <div>
          <div style={{ fontSize: 9, color: t.fgSubtle, textTransform: "uppercase" }}>{tr("report.new")}</div>
          <div style={{ fontWeight: 600, wordBreak: "break-word" }}>{a.proposed_value || "∅"}</div>
        </div>
      </div>
      {corrected && (
        <div style={{ fontSize: 10, color: t.warn, marginTop: 3 }}>
          {tr("report.aiSaid")} <span style={{ fontFamily: t.mono }}>{a.ai_value}</span>
          {a.ai_confidence != null && ` (${Math.round(a.ai_confidence * 100)}%)`}
        </div>
      )}
      {a.note && <div style={{ fontSize: 10, color: t.fgMuted, marginTop: 2 }}>{a.note}</div>}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap", fontSize: 10 }}>
        <StatusPill status={a.status} />
        <SourceTag source={a.source} confidence={a.ai_value === a.proposed_value ? a.ai_confidence : null} />
        <Link to={`/contributors/${a.contributor_id}`} style={{
          color: t.fgSubtle, textDecoration: "none", fontStyle: isAnonymous(a.contributor_name) ? "italic" : "normal",
        }} title={isAnonymous(a.contributor_name) ? tr("vol.anonymousHint") : undefined}>
          {contributorLabel(tr, a.contributor_name, a.contributor_id)}
        </Link>
        <span style={{ color: t.fgSubtle, fontFamily: t.mono }}>{licenseLabel(a.license)}</span>
        <span style={{ color: t.fgSubtle, fontFamily: t.mono }}>{(a.modified || a.created || "").slice(0, 10)}</span>
        {isReviewer && a.status === "submitted" && (
          <span style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
            <Button small disabled={busy} onClick={() => onReview("accepted")}>{tr("annotate.accept")}</Button>
            <Button small danger disabled={busy} onClick={() => onReview("rejected")}>{tr("annotate.reject")}</Button>
          </span>
        )}
        {isReviewer && a.status === "accepted" && (
          <span style={{ marginLeft: "auto" }}>
            <Button small disabled={busy} onClick={() => onReview("merged")}>{tr("annotate.merge")}</Button>
          </span>
        )}
      </div>
    </div>
  );
}
