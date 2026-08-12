import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { api } from "../api/client";
import type { SpeciesRow, SpeciesScope, SpeciesSort } from "../api/types";
import { Spinner } from "../components/ui";
import { exploreUrl } from "./exploreUrl";

// The taxonomic index: every distinct scientific_name the store holds.
//
// It lists *names*, not taxa — nothing here is reconciled against TaiCOL, WCVP
// or any other checklist, so `Trema orientalis` and `Trema orientale` are two
// rows and neither is relabelled as the other. The page says so out loud
// (`sp.disclaimer`) because a ranked list of binomials otherwise reads as an
// authority it is not.
//
// The scope toggle is the point of the page as much as the list is: the default
// shows names at species rank or below, and widening it reveals the genus- and
// family-level identifications — 319,916 records stopping at a bare genus is
// the identification gap this platform exists to close, not noise to hide.
const PAGE = 50;
const SORTS: SpeciesSort[] = ["records", "name"];

export function Species() {
  const { t: tr } = useTranslation();
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<SpeciesScope>("species");
  const [sort, setSort] = useState<SpeciesSort>("records");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);

  const list = useQuery({
    queryKey: ["species", q, scope, sort, order, page],
    queryFn: () => api.species({ q, scope, sort, order, limit: PAGE, offset: page * PAGE }),
    placeholderData: keepPreviousData,
  });

  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(0); };
  const pickSort = (s: SpeciesSort) => {
    if (s === sort) setOrder(order === "desc" ? "asc" : "desc");
    else { setSort(s); setOrder(s === "name" ? "asc" : "desc"); }
    setPage(0);
  };

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const totals = list.data?.totals;

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{tr("sp.title")}</h2>
        <div style={{ flex: 1 }} />
        <input
          value={q} onChange={(e) => reset(setQ)(e.target.value)}
          placeholder={tr("sp.searchPlaceholder")}
          style={{
            padding: "4px 8px", fontSize: 12, fontFamily: t.sans, width: 220,
            border: `1px solid ${t.border}`, background: t.bg, color: t.fg,
          }} />
      </div>

      {totals && (
        <p style={{ fontSize: 11, color: t.fgMuted, margin: "0 0 6px" }}>
          {tr("sp.blurb", {
            names: totals.names.toLocaleString(),
            records: totals.records.toLocaleString(),
          })}
        </p>
      )}
      <p style={{ fontSize: 11, color: t.fgSubtle, margin: "0 0 12px", maxWidth: 720 }}>
        {tr("sp.disclaimer")}
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", margin: "0 0 8px" }}>
        {SORTS.map((s) => (
          <Toggle key={s} on={sort === s} onClick={() => pickSort(s)}
            label={`${tr(`sp.sort_${s}`)}${sort === s ? (order === "desc" ? " ↓" : " ↑") : ""}`} />
        ))}
        <div style={{ flex: 1 }} />
        <Toggle on={scope === "all"} onClick={() => reset(setScope)(scope === "all" ? "species" : "all")}
          label={tr("sp.allRanks")} />
        <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgMuted }}>
          {total.toLocaleString()}
        </span>
      </div>

      {list.isLoading ? <Spinner /> : items.length === 0 ? (
        <div style={{ padding: 20, fontSize: 12, color: t.fgSubtle }}>{tr("sp.empty")}</div>
      ) : (
        <div style={{ background: t.panel, border: `1px solid ${t.border}`, maxWidth: 980 }}>
          <Row header />
          {items.map((s, i) => <Row key={s.name} s={s} rank={page * PAGE + i + 1} />)}
        </div>
      )}

      {total > PAGE && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 11 }}>
          <Toggle on={false} disabled={page === 0} onClick={() => setPage(page - 1)} label={`← ${tr("sp.prev")}`} />
          <span style={{ fontFamily: t.mono, color: t.fgMuted }}>
            {(page * PAGE + 1).toLocaleString()}–{Math.min((page + 1) * PAGE, total).toLocaleString()}
          </span>
          <Toggle on={false} disabled={(page + 1) * PAGE >= total}
            onClick={() => setPage(page + 1)} label={`${tr("sp.next")} →`} />
        </div>
      )}
    </div>
  );
}

function Toggle({ on, label, onClick, disabled }: {
  on: boolean; label: string; onClick: () => void; disabled?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: "3px 10px", fontSize: 11, fontFamily: t.sans,
      cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.4 : 1,
      border: `1px solid ${on ? t.accent : t.border}`,
      background: on ? t.accentSoft : t.panel,
      color: on ? t.fg : t.fgMuted, fontWeight: on ? 600 : 400,
    }}>{label}</button>
  );
}

const cells: React.CSSProperties[] = [
  { width: 44, textAlign: "right", fontFamily: t.mono, color: t.fgSubtle, flexShrink: 0 },
  { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  { width: 92, flexShrink: 0, color: t.fgMuted, fontSize: 11 },
  { width: 120, flexShrink: 0, color: t.fgMuted, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  { width: 76, textAlign: "right", fontFamily: t.mono, flexShrink: 0 },
  { width: 92, textAlign: "right", fontFamily: t.mono, flexShrink: 0, color: t.fgMuted, fontSize: 11 },
];

function Row({ s, rank, header }: { s?: SpeciesRow; rank?: number; header?: boolean }) {
  const { t: tr } = useTranslation();
  const base: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 10, padding: "6px 10px",
    borderBottom: `1px solid ${t.borderSoft}`, fontSize: 12,
  };
  if (header) {
    return (
      <div style={{
        ...base, background: t.panelAlt, fontSize: 10, fontWeight: 600,
        textTransform: "uppercase", letterSpacing: 0.3, color: t.fgMuted,
      }}>
        <span style={cells[0]} />
        <span style={cells[1]}>{tr("sp.name")}</span>
        <span style={cells[2]}>{tr("sp.rank")}</span>
        <span style={cells[3]}>{tr("sp.family")}</span>
        <span style={cells[4]}>{tr("sp.records")}</span>
        <span style={cells[5]}>{tr("sp.years")}</span>
      </div>
    );
  }
  if (!s) return null;
  return (
    // Explore is handed the exact name, and `has_media` is cleared explicitly:
    // emptyFilters() defaults it to true, so without this the landing page would
    // report a smaller number than the row it was opened from.
    <Link
      to={exploreUrl({ scientific_name: [s.name], flags: { has_media: false } })}
      title={tr("sp.openHint", { name: s.name, n: s.n_records.toLocaleString() })}
      style={{ ...base, textDecoration: "none", color: t.fg }}
    >
      <span style={cells[0]}>{rank ?? ""}</span>
      <span style={cells[1]}>
        <i>{s.name}</i>
        {s.common_name_c && (
          <span style={{ color: t.fgMuted, marginLeft: 6, fontSize: 11 }}>{s.common_name_c}</span>
        )}
        {s.n_kingdoms > 1 && (
          <span title={tr("sp.homonymHint")} style={{
            marginLeft: 6, fontSize: 9, fontFamily: t.mono, color: t.fgSubtle,
            border: `1px solid ${t.borderSoft}`, padding: "0 3px",
          }}>{tr("sp.homonym")}</span>
        )}
      </span>
      <span style={cells[2]}>{s.taxon_rank || "—"}</span>
      <span style={cells[3]}>{s.family || "—"}</span>
      <span style={{ ...cells[4], fontWeight: 600 }}>{s.n_records.toLocaleString()}</span>
      <span style={cells[5]}>
        {s.year_min != null ? `${s.year_min}–${s.year_max}` : "—"}
      </span>
    </Link>
  );
}
