import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { CollectorBoardRow, CollectorSort } from "../api/types";
import { Spinner } from "../components/ui";

// Browsable index of every collector in the store.
//
// The distribution decides the defaults: 221 collectors hold 68% of the
// attributed records while 12,748 have fewer than ten, so the list is ranked
// (not alphabetical — two naming systems make A–Z useless) and the tail is
// hidden until asked for. The mapped column is the point: sorting by it turns
// the page into the georeferencing queue, by person.
const PAGE = 50;
const SORTS: CollectorSort[] = ["records", "gap", "recent"];

export function Collectors() {
  const { t: tr } = useTranslation();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<CollectorSort>("records");
  const [all, setAll] = useState(false);   // include the <10-record tail
  const [page, setPage] = useState(0);
  const minRecords = all ? 1 : 10;

  const board = useQuery({
    queryKey: ["collector-board", q, sort, minRecords, page],
    queryFn: () => api.collectorBoard({
      q, sort, minRecords, limit: PAGE, offset: page * PAGE,
    }),
    placeholderData: keepPreviousData,
  });

  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(0); };
  const items = board.data?.items ?? [];
  const total = board.data?.total ?? 0;
  const totals = board.data?.totals;

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{tr("coll.title")}</h2>
        <div style={{ flex: 1 }} />
        <input
          value={q} onChange={(e) => reset(setQ)(e.target.value)}
          placeholder={tr("coll.searchPlaceholder")}
          style={{
            padding: "4px 8px", fontSize: 12, fontFamily: t.sans, width: 220,
            border: `1px solid ${t.border}`, background: t.bg, color: t.fg,
          }} />
      </div>

      {totals && (
        <p style={{ fontSize: 11, color: t.fgMuted, margin: "0 0 12px" }}>
          {tr("coll.blurb", {
            records: totals.records.toLocaleString(),
            collectors: totals.collectors.toLocaleString(),
            mapped: totals.records ? Math.round((totals.mapped / totals.records) * 100) : 0,
          })}
        </p>
      )}

      <Discover minRecords={minRecords} />

      {/* sort + tail toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", margin: "14px 0 8px" }}>
        {SORTS.map((s) => (
          <Toggle key={s} on={sort === s} onClick={() => reset(setSort)(s)}
            label={tr(`coll.sort_${s}`)} />
        ))}
        <div style={{ flex: 1 }} />
        <Toggle on={all} onClick={() => reset(setAll)(!all)} label={tr("coll.showTail")} />
        <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgMuted }}>
          {total.toLocaleString()}
        </span>
      </div>

      {board.isLoading ? <Spinner /> : items.length === 0 ? (
        <div style={{ padding: 20, fontSize: 12, color: t.fgSubtle }}>{tr("coll.empty")}</div>
      ) : (
        <div style={{ background: t.panel, border: `1px solid ${t.border}`, maxWidth: 860 }}>
          <Row header />
          {items.map((c, i) => (
            <Row key={c.id} c={c} rank={sort === "random" ? undefined : page * PAGE + i + 1} />
          ))}
        </div>
      )}

      {total > PAGE && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 11 }}>
          <Toggle on={false} disabled={page === 0} onClick={() => setPage(page - 1)} label={`← ${tr("coll.prev")}`} />
          <span style={{ fontFamily: t.mono, color: t.fgMuted }}>
            {(page * PAGE + 1).toLocaleString()}–{Math.min((page + 1) * PAGE, total).toLocaleString()}
          </span>
          <Toggle on={false} disabled={(page + 1) * PAGE >= total}
            onClick={() => setPage(page + 1)} label={`${tr("coll.next")} →`} />
        </div>
      )}
    </div>
  );
}

// A handful of collectors picked at random, so the page isn't the same 50 names
// on every visit. Same pool as the list below it, so nothing unreachable-thin
// shows up here.
function Discover({ minRecords }: { minRecords: number }) {
  const { t: tr } = useTranslation();
  const [nonce, setNonce] = useState(1);
  const picks = useQuery({
    queryKey: ["collector-random", minRecords, nonce],
    queryFn: () => api.collectorBoard({ sort: "random", minRecords, limit: 6, nonce }),
    placeholderData: keepPreviousData,
  });

  return (
    <div style={{ background: t.panelAlt, border: `1px solid ${t.border}`, padding: "8px 10px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3, color: t.fgMuted }}>
          {tr("coll.discover")}
        </span>
        <div style={{ flex: 1 }} />
        <button onClick={() => setNonce(nonce + 1)} style={{
          display: "flex", alignItems: "center", gap: 4, border: `1px solid ${t.border}`,
          background: t.panel, color: t.fgMuted, fontSize: 10, fontFamily: t.sans,
          padding: "2px 8px", cursor: "pointer",
        }}>
          <Icon name="refresh" size={11} />{tr("coll.shuffle")}
        </button>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {(picks.data?.items ?? []).map((c) => (
          <Link key={c.id} to={`/collectors/${c.id}`} style={{
            flex: "1 1 200px", minWidth: 180, padding: "6px 8px", textDecoration: "none",
            border: `1px solid ${t.borderSoft}`, background: t.panel, color: t.fg,
          }}>
            <div style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {c.name || c.name_en}
            </div>
            <div style={{ fontSize: 10, color: t.fgMuted, fontFamily: t.mono }}>
              {c.n_records.toLocaleString()} · {c.mapped_pct}%{" "}
              {c.year_min != null && `· ${c.year_min}–${c.year_max}`}
            </div>
          </Link>
        ))}
      </div>
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
  { width: 34, textAlign: "right", fontFamily: t.mono, color: t.fgSubtle, flexShrink: 0 },
  { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  { width: 76, textAlign: "right", fontFamily: t.mono, flexShrink: 0 },
  { width: 130, flexShrink: 0 },
  { width: 92, textAlign: "right", fontFamily: t.mono, flexShrink: 0 },
];

function Row({ c, rank, header }: { c?: CollectorBoardRow; rank?: number; header?: boolean }) {
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
        <span style={cells[1]}>{tr("coll.collector")}</span>
        <span style={cells[2]}>{tr("coll.records")}</span>
        <span style={cells[3]}>{tr("coll.mapped")}</span>
        <span style={cells[4]}>{tr("coll.years")}</span>
      </div>
    );
  }
  if (!c) return null;
  return (
    <Link to={`/collectors/${c.id}`} style={{ ...base, textDecoration: "none", color: t.fg }}>
      <span style={cells[0]}>{rank ?? ""}</span>
      <span style={cells[1]}>
        {c.name || c.name_en}
        {c.name && c.name_en && (
          <span style={{ color: t.fgMuted, marginLeft: 6, fontSize: 11 }}>{c.name_en}</span>
        )}
      </span>
      <span style={{ ...cells[2], fontWeight: 600 }}>{c.n_records.toLocaleString()}</span>
      <span style={cells[3]}><MappedBar pct={c.mapped_pct} n={c.n_geo} /></span>
      <span style={{ ...cells[4], color: t.fgMuted, fontSize: 11 }}>
        {c.year_min != null ? `${c.year_min}–${c.year_max}` : "—"}
      </span>
    </Link>
  );
}

// Share of the collector's records that carry coordinates. Same green as the
// career timeline, and the same 1px floor so "a few" never reads as "none".
function MappedBar({ pct, n }: { pct: number; n: number }) {
  const { t: tr } = useTranslation();
  const w = n > 0 ? Math.max(1, Math.round(pct)) : 0;
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}
      title={tr("coll.mappedHint", { n: n.toLocaleString() })}>
      <span style={{ width: 60, height: 7, background: t.border, flexShrink: 0 }}>
        <span style={{ display: "block", width: `${w}%`, height: "100%", background: t.ok }} />
      </span>
      <span style={{ fontFamily: t.mono, fontSize: 10, color: n > 0 ? t.fgMuted : t.fgSubtle }}>
        {pct}%
      </span>
    </span>
  );
}
