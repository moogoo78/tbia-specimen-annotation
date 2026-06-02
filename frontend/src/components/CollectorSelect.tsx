import { useEffect, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";

export interface CollectorRef { id: number; label: string; }

const box = (active: boolean) => (
  <div style={{
    width: 12, height: 12, border: `1px solid ${active ? t.accent : t.border}`,
    background: active ? t.accent : t.panel, flexShrink: 0, display: "flex",
    alignItems: "center", justifyContent: "center",
  }}>
    {active && (
      <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round">
        <path d="M1.5 4.2l1.8 1.8L7 2" />
      </svg>
    )}
  </div>
);

/** Searchable multi-select over /api/collectors, ranked by record count.
 *  Selecting collectors feeds the occurrence `collector_id` filter. */
export function CollectorSelect({ selected, onToggle }: {
  selected: CollectorRef[];
  onToggle: (c: CollectorRef) => void;
}) {
  const { t: tr } = useTranslation();
  const [raw, setRaw] = useState("");
  const [q, setQ] = useState("");

  // debounce the typed query into the request key
  useEffect(() => {
    const h = setTimeout(() => setQ(raw.trim()), 250);
    return () => clearTimeout(h);
  }, [raw]);

  const results = useQuery({
    queryKey: ["collectors", q],
    queryFn: () => api.collectors(q, 25),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const selectedIds = new Set(selected.map((c) => c.id));
  const rows = results.data ?? [];

  return (
    <div style={{ padding: "2px 6px 6px" }}>
      {/* currently-selected collectors */}
      {selected.map((c) => (
        <label key={c.id} onClick={() => onToggle(c)} style={rowStyle(true)}>
          {box(true)}
          <span style={labelStyle(true)} title={c.label}>{c.label}</span>
          <Icon name="x" size={9} />
        </label>
      ))}

      {/* search box */}
      <div style={{ position: "relative", margin: "4px 0 2px" }}>
        <span style={{ position: "absolute", left: 6, top: 5, color: t.fgSubtle }}>
          <Icon name="search" size={11} />
        </span>
        <input
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder={tr("collector.search")}
          style={{
            width: "100%", boxSizing: "border-box", padding: "4px 6px 4px 22px",
            fontFamily: t.sans, fontSize: 11, border: `1px solid ${t.border}`,
            background: t.panelAlt, outline: "none",
          }}
        />
      </div>

      {/* results */}
      <div style={{ maxHeight: 240, overflow: "auto" }}>
        {rows.length === 0 && (
          <div style={{ padding: "3px 6px", color: t.fgSubtle, fontSize: 10 }}>
            {results.isFetching ? "…" : tr("collector.none")}
          </div>
        )}
        {rows.map((c) => {
          const active = selectedIds.has(c.id);
          return (
            <label key={c.id} onClick={() => onToggle({ id: c.id, label: c.label })} style={rowStyle(active)}>
              {box(active)}
              <span style={labelStyle(active)} title={c.label}>
                {c.name || <span style={{ color: t.fgSubtle }}>{c.name_en}</span>}
                {c.name && c.name_en && (
                  <span style={{ color: t.fgSubtle, marginLeft: 4 }}>{c.name_en}</span>
                )}
              </span>
              <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>
                {c.n_records.toLocaleString()}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

const rowStyle = (active: boolean): React.CSSProperties => ({
  display: "flex", alignItems: "center", gap: 6, padding: "2px 4px",
  cursor: "pointer", background: active ? t.accentSoft : "transparent",
});

const labelStyle = (active: boolean): React.CSSProperties => ({
  flex: 1, fontSize: 11, color: active ? t.fg : t.fgMuted,
  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
});
