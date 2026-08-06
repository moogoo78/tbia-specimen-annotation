import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { emptyFilters, type Trip } from "../api/types";
import { MapView } from "../components/MapView";
import { Spinner } from "../components/ui";

// A collector's lifetime of work: when they collected, on which trips, and how
// much of it is on the map.
//
// Dates carry this page — ~99% of records have one — while coordinates usually
// do not (the median collector has zero). So the timeline and trip list lead,
// and the map's job is to state the gap and offer the work.
export function Collector() {
  const { t: tr } = useTranslation();
  const { id } = useParams();
  const cid = Number(id);
  const [sel, setSel] = useState<{ from: string; to: string } | null>(null);

  const career = useQuery({
    queryKey: ["career", cid],
    queryFn: () => api.collectorCareer(cid),
    enabled: Number.isFinite(cid),
  });

  // Records for the current selection (whole career when nothing is selected).
  // bbox=world constrains the fetch to rows that actually have coordinates —
  // the same trick Explore uses so the map isn't mostly empty pages.
  const mapFilters = useMemo(() => ({
    ...emptyFilters(), collector_id: [cid], bbox: "-180,-90,180,90",
    ...(sel ? { date_from: sel.from, date_to: sel.to } : {}),
  }), [cid, sel]);
  const mapRows = useQuery({
    queryKey: ["career-map", cid, sel?.from, sel?.to],
    queryFn: () => api.search(mapFilters, "standard_date", "asc", 500, 0),
    enabled: Number.isFinite(cid),
  });

  if (career.isLoading) return <Spinner />;
  if (career.isError || !career.data) {
    return <div style={{ padding: 20, color: t.fgSubtle }}>{tr("career.notFound")}</div>;
  }

  const { collector, summary: s, years, trips } = career.data;
  const unmapped = s.n_records - s.n_geo;
  const gapFilters = { collector: { id: cid, label: collector.label }, missing_coordinates: true };

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{collector.name || collector.name_en}</h2>
        {collector.name && collector.name_en && (
          <span style={{ fontSize: 12, color: t.fgMuted }}>{collector.name_en}</span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgMuted }}>
          {s.year_min != null ? `${s.year_min}–${s.year_max}` : "—"}
        </span>
      </div>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "8px 0 14px", fontSize: 11, color: t.fgMuted }}>
        <Stat n={s.n_records} label={tr("career.records")} />
        <Stat n={s.n_trips} label={tr("career.trips")} />
        <Stat n={s.n_days} label={tr("career.days")} />
        <Stat n={s.n_geo} label={tr("career.mapped")} />
        {s.n_undated > 0 && <Stat n={s.n_undated} label={tr("career.undated")} muted />}
      </div>

      {/* the gap — the reason this page exists */}
      {unmapped > 0 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", marginBottom: 14,
          background: t.accentSoft, border: `1px solid ${t.border}`, maxWidth: 760, flexWrap: "wrap",
        }}>
          <Icon name="map" size={13} />
          <span style={{ fontSize: 12, flex: 1, minWidth: 260 }}>
            {tr("career.gap", {
              mapped: s.n_geo.toLocaleString(), total: s.n_records.toLocaleString(),
              unmapped: unmapped.toLocaleString(),
            })}
          </span>
          <Link to="/explore" state={gapFilters} style={{
            fontSize: 11, color: t.accent, textDecoration: "none", border: `1px solid ${t.border}`,
            padding: "3px 8px", background: t.panel, whiteSpace: "nowrap",
          }}>
            {tr("career.gapCta")} →
          </Link>
        </div>
      )}

      {years.length === 0 ? (
        <div style={{ padding: 16, fontSize: 12, color: t.fgSubtle, background: t.panel, border: `1px solid ${t.border}` }}>
          {tr("career.noDates")}
        </div>
      ) : (
        <Timeline years={years} sel={sel} onSelect={setSel} />
      )}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(300px, 1fr) 1.2fr", gap: 14, marginTop: 14, alignItems: "start" }}>
        {/* trips */}
        <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: t.panelAlt,
            borderBottom: `1px solid ${t.borderSoft}`, fontSize: 10, fontWeight: 600,
            textTransform: "uppercase", letterSpacing: 0.3, color: t.fgMuted,
          }}>
            <span>{tr("career.trips")}</span>
            <span style={{ fontFamily: t.mono }}>{trips.length.toLocaleString()}</span>
            <div style={{ flex: 1 }} />
            {sel && (
              <button onClick={() => setSel(null)} style={{
                border: "none", background: "none", color: t.accent, fontSize: 10,
                cursor: "pointer", textDecoration: "underline",
              }}>{tr("career.clearSel")}</button>
            )}
          </div>
          {/* How a trip is defined — otherwise the grouping is unexplained. */}
          <div style={{
            padding: "6px 10px", fontSize: 10, lineHeight: 1.5, color: t.fgSubtle,
            borderBottom: `1px solid ${t.borderSoft}`, background: t.bg,
          }}>
            {tr("career.tripRule", { gap: career.data.gap })}
          </div>
          {trips.length === 0 ? (
            <div style={{ padding: 14, fontSize: 12, color: t.fgSubtle }}>{tr("career.noTrips")}</div>
          ) : (
            <div style={{ maxHeight: 520, overflow: "auto" }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 8, padding: "3px 10px",
                fontSize: 9, textTransform: "uppercase", letterSpacing: 0.3,
                color: t.fgSubtle, borderBottom: `1px solid ${t.borderSoft}`,
                position: "sticky", top: 0, background: t.panel,
              }}>
                <span>{tr("career.tripDates")}</span>
                <div style={{ flex: 1 }} />
                <span>{tr("career.days")}</span>
                <span>{tr("career.records")}</span>
                <span style={{ width: 34, textAlign: "right", color: t.ok }}>
                  {tr("career.mapped")}
                </span>
              </div>
              {trips.map((trip) => (
                <TripRow key={trip.start} trip={trip}
                  active={sel?.from === trip.start && sel?.to === trip.end}
                  onClick={() => setSel(
                    sel?.from === trip.start && sel?.to === trip.end
                      ? null : { from: trip.start, to: trip.end })} />
              ))}
            </div>
          )}
        </div>

        {/* map */}
        <div style={{ background: t.panel, border: `1px solid ${t.border}`, display: "flex", flexDirection: "column", height: 560 }}>
          <div style={{
            padding: "6px 10px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`,
            fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3, color: t.fgMuted,
          }}>
            {sel ? `${sel.from} → ${sel.to}` : tr("career.wholeCareer")}
          </div>
          {mapRows.isLoading ? <Spinner /> :
            (mapRows.data?.items.length ?? 0) === 0 ? (
              <div style={{ padding: 16, fontSize: 12, color: t.fgSubtle }}>
                {s.n_geo === 0 ? tr("career.noCoords") : tr("career.noCoordsInSelection")}
              </div>
            ) : <MapView rows={mapRows.data!.items} />}
        </div>
      </div>
    </div>
  );
}

function Stat({ n, label, muted }: { n: number; label: string; muted?: boolean }) {
  return (
    <span style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
      <span style={{ fontFamily: t.mono, fontSize: 14, fontWeight: 600, color: muted ? t.fgMuted : t.fg }}>
        {n.toLocaleString()}
      </span>
      <span>{label}</span>
    </span>
  );
}

// Per-year activity. Plain SVG — the project has no charting dependency and one
// bar chart doesn't justify adding one. Clicking a year selects that year.
function Timeline({ years, sel, onSelect }: {
  years: { year: number; count: number; mapped: number }[];
  sel: { from: string; to: string } | null;
  onSelect: (s: { from: string; to: string } | null) => void;
}) {
  const { t: tr } = useTranslation();
  const max = Math.max(...years.map((y) => y.count), 1);
  const W = 14, H = 64, GAP = 2;
  const width = years.length * (W + GAP);
  return (
    <div style={{ background: t.panel, border: `1px solid ${t.border}`, padding: "8px 10px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 6 }}>
        <span style={{ fontSize: 10, color: t.fgMuted, textTransform: "uppercase", letterSpacing: 0.3 }}>
          {tr("career.timeline")}
        </span>
        <Swatch color={t.border} label={tr("career.legendAll")} />
        <Swatch color={t.ok} label={tr("career.legendMapped")} />
        <span style={{ fontSize: 10, color: t.fgSubtle }}>{tr("career.legendHint")}</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <svg width={Math.max(width, 200)} height={H + 16} style={{ display: "block" }}>
          {years.map((y, i) => {
            const h = Math.max(2, Math.round((y.count / max) * H));
            // Keep a 1px line for a tiny mapped share, so "a few" never renders
            // identically to "none" (呂碧鳳: 117 of 38,778 rounds to zero).
            const mh = y.mapped > 0 ? Math.max(1, Math.round((y.mapped / max) * H)) : 0;
            const x = i * (W + GAP);
            const on = sel?.from === `${y.year}-01-01`;
            return (
              <g key={y.year} onClick={() => onSelect(on ? null : { from: `${y.year}-01-01`, to: `${y.year}-12-31` })}
                style={{ cursor: "pointer" }}>
                <title>{`${y.year}: ${y.count.toLocaleString()} (${y.mapped.toLocaleString()} mapped)`}</title>
                <rect x={x} y={H - h} width={W} height={h} fill={on ? t.accent : t.border} />
                {/* georeferenced portion, so the gap is visible year by year */}
                {mh > 0 && <rect x={x} y={H - mh} width={W} height={mh} fill={t.ok} />}
                {i % 5 === 0 && (
                  <text x={x} y={H + 12} fontSize="9" fill={t.fgSubtle} fontFamily="monospace">{y.year}</text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: t.fgMuted }}>
      <span style={{ width: 8, height: 8, background: color, display: "inline-block" }} />
      {label}
    </span>
  );
}

function TripRow({ trip, active, onClick }: { trip: Trip; active: boolean; onClick: () => void }) {
  const span = trip.start === trip.end ? trip.start : `${trip.start} → ${trip.end}`;
  return (
    <div onClick={onClick} style={{
      padding: "5px 10px", borderBottom: `1px solid ${t.borderSoft}`, cursor: "pointer",
      background: active ? t.accentSoft : "transparent",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
        <span style={{ fontFamily: t.mono, color: t.fg }}>{span}</span>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted }}>{trip.n_days}d</span>
        <span style={{ fontFamily: t.mono, fontSize: 10, fontWeight: 600 }}>{trip.n_records.toLocaleString()}</span>
        <span style={{
          fontFamily: t.mono, fontSize: 10, color: trip.n_mapped > 0 ? t.ok : t.fgSubtle, width: 34, textAlign: "right",
        }}>{trip.n_mapped.toLocaleString()}</span>
      </div>
      {trip.place && (
        <div style={{ fontSize: 10, color: t.fgSubtle, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {trip.place}
        </div>
      )}
    </div>
  );
}
