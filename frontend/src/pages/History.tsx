import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { api } from "../api/client";
import type { SamplingEvent, SamplingEventActor } from "../api/types";
import { Spinner } from "../components/ui";

// The curated chronology: collecting events as published literature records
// them. This is the upper, documented half of the platform's trip concept — the
// other half is derived per-collector from record dates on /collectors/:id.
//
// It reads as a document, not a search result: 37 rows spanning 1854–1988, in
// one page, filtered client-side once fetched. Data values stay Chinese; only
// the chrome is bilingual.
export function History() {
  const { t: tr } = useTranslation();
  const [q, setQ] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const events = useQuery({
    queryKey: ["sampling-events"],
    queryFn: () => api.samplingEvents(),
  });

  const rows = useMemo(() => {
    const all = events.data ?? [];
    const needle = q.trim().toLowerCase();
    const yf = from.trim() ? Number(from) : null;
    const yt = to.trim() ? Number(to) : null;
    return all.filter((e) => {
      // Overlap, not containment — an 1861–1866 survey belongs in an 1864+ window.
      if (yf != null && Number.isFinite(yf) && e.year_end < yf) return false;
      if (yt != null && Number.isFinite(yt) && e.year_start > yt) return false;
      if (!needle) return true;
      const hay = [
        e.verbatim_locality, e.event_remarks, e.narrative,
        ...e.actors.map((a) => a.recorded_by),
      ].join(" ").toLowerCase();
      return hay.includes(needle);
    });
  }, [events.data, q, from, to]);

  const citation = events.data?.[0]?.location_according_to ?? "";

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{tr("hist.title")}</h2>
      <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.6, margin: "6px 0 0", maxWidth: 760 }}>
        {tr("hist.blurb")}
      </p>
      {/* Provenance of everything on this page — DwC locationAccordingTo. */}
      {citation && (
        <p style={{ fontSize: 11, color: t.fgSubtle, margin: "6px 0 0", fontFamily: t.mono }}>
          {tr("hist.source")}: {citation}
        </p>
      )}

      {/* filters */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "14px 0" }}>
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          placeholder={tr("hist.filterPlaceholder")}
          style={{
            flex: "1 1 260px", minWidth: 200, padding: "5px 8px", fontSize: 12,
            border: `1px solid ${t.border}`, background: t.panel, color: t.fg, fontFamily: t.sans,
          }}
        />
        <input
          value={from} onChange={(e) => setFrom(e.target.value)} inputMode="numeric"
          placeholder={tr("hist.yearFrom")}
          style={{ width: 92, padding: "5px 8px", fontSize: 12, border: `1px solid ${t.border}`, background: t.panel, color: t.fg, fontFamily: t.mono }}
        />
        <input
          value={to} onChange={(e) => setTo(e.target.value)} inputMode="numeric"
          placeholder={tr("hist.yearTo")}
          style={{ width: 92, padding: "5px 8px", fontSize: 12, border: `1px solid ${t.border}`, background: t.panel, color: t.fg, fontFamily: t.mono }}
        />
        {(q || from || to) && (
          <button
            onClick={() => { setQ(""); setFrom(""); setTo(""); }}
            style={{ border: "none", background: "none", color: t.accent, fontSize: 11, cursor: "pointer", textDecoration: "underline" }}
          >{tr("hist.clear")}</button>
        )}
        <span style={{ fontSize: 11, color: t.fgSubtle, fontFamily: t.mono }}>
          {tr("hist.count", { n: rows.length })}
        </span>
      </div>

      {events.isLoading ? <Spinner /> : rows.length === 0 ? (
        <div style={{ padding: 20, fontSize: 12, color: t.fgSubtle }}>{tr("hist.empty")}</div>
      ) : (
        <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
          {rows.map((e, i) => (
            <EventRow key={e.id} ev={e} first={i === 0} />
          ))}
        </div>
      )}
    </div>
  );
}

function EventRow({ ev, first }: { ev: SamplingEvent; first: boolean }) {
  const { t: tr } = useTranslation();
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "96px minmax(140px, 200px) 1fr",
      gap: 12, padding: "10px 12px",
      borderTop: first ? "none" : `1px solid ${t.borderSoft}`,
    }}>
      {/* 年代 */}
      <div style={{ fontFamily: t.mono, fontSize: 12, color: t.fg, fontWeight: 600 }}>
        {ev.verbatim_event_date}
      </div>

      {/* 植物分類學者 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {ev.actors.map((a) => <Actor key={`${a.recorded_by}-${a.position}`} a={a} />)}
      </div>

      {/* 主要記事 + 採集地點 + 標本存放處 */}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, lineHeight: 1.6, color: t.fg }}>{ev.narrative}</div>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 5, fontSize: 11 }}>
          {ev.verbatim_locality && (
            <span style={{ color: t.fgMuted }}>
              <Label>{tr("hist.locality")}</Label> {ev.verbatim_locality}
            </span>
          )}
          <span style={{ color: t.fgMuted }}>
            <Label>{tr("hist.repository")}</Label>{" "}
            {ev.event_remarks || <span style={{ color: t.fgSubtle }}>{tr("hist.noRepository")}</span>}
          </span>
        </div>
      </div>
    </div>
  );
}

// An actor links to its collector's career page only when the name resolved to
// one; an unresolved name is plain text rather than a dead link.
function Actor({ a }: { a: SamplingEventActor }) {
  const { t: tr } = useTranslation();
  const nat = a.nationality ? <span style={{ color: t.fgSubtle, fontSize: 10 }}> {a.nationality}</span> : null;
  if (a.collector_id == null) {
    return (
      <span style={{ fontSize: 12, color: t.fgMuted }} title={tr("hist.unlinked")}>
        {a.recorded_by}{nat}
      </span>
    );
  }
  return (
    <Link to={`/collectors/${a.collector_id}`}
      style={{ fontSize: 12, color: t.accent, textDecoration: "none" }}>
      {a.recorded_by}{nat}
    </Link>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      fontSize: 9, textTransform: "uppercase", letterSpacing: 0.3, color: t.fgSubtle,
    }}>{children}</span>
  );
}
