import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { CollectorSelect, type CollectorRef } from "./CollectorSelect";
import type { FacetResult, Filters, Registry, SourceKind } from "../api/types";

type ArrayKey = "bio_group" | "kingdom_c" | "county" | "taxon_rank"
  | "basis_of_record" | "type_status" | "dataset_name";
type FlagKey = "missing_coordinates" | "missing_date" | "missing_identification" | "has_media";

const SECTIONS: ArrayKey[] = [
  "bio_group", "kingdom_c", "county", "taxon_rank", "type_status", "dataset_name",
];
const FLAGS: FlagKey[] = ["missing_identification", "missing_coordinates", "missing_date", "has_media"];

export function FacetPanel({ facets, filters, onToggle, onToggleFlag, onClear,
  registry, selectedSources, onToggleSource,
  selectedCollectors, onToggleCollector, onRecordRange, width = 232 }: {
  facets?: FacetResult;
  filters: Filters;
  onToggle: (key: ArrayKey, value: string) => void;
  onToggleFlag: (flag: FlagKey) => void;
  onClear: () => void;
  registry?: Registry;
  selectedSources: string[];
  onToggleSource: (key: string) => void;
  selectedCollectors: CollectorRef[];
  onToggleCollector: (c: CollectorRef) => void;
  onRecordRange: (from?: number, to?: number) => void;
  width?: number;
}) {
  const { t: tr } = useTranslation();
  const [open, setOpen] = useState<Record<string, boolean>>({
    source: true, collector: false, record_number: false, completeness: true, bio_group: true,
    county: true, taxon_rank: false, kingdom_c: false, type_status: false, dataset_name: false,
  });
  const [srcOpen, setSrcOpen] = useState<Record<string, boolean>>({});

  const recordActive = filters.record_number_from != null || filters.record_number_to != null;
  const activeCount =
    selectedSources.length +
    selectedCollectors.length +
    (recordActive ? 1 : 0) +
    FLAGS.filter((f) => filters[f]).length +
    SECTIONS.reduce((n, s) => n + filters[s].length, 0);

  const header = (
    <div style={{
      padding: "8px 10px", display: "flex", alignItems: "center", gap: 6,
      borderBottom: `1px solid ${t.borderSoft}`, background: t.panelAlt,
      position: "sticky", top: 0, zIndex: 1,
    }}>
      <Icon name="filter" size={11} />
      <span style={{ fontWeight: 600, fontSize: 11, letterSpacing: 0.3 }}>{tr("search.filters")}</span>
      {activeCount > 0 && <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>({activeCount})</span>}
      <div style={{ flex: 1 }} />
      {activeCount > 0 && (
        <button onClick={onClear} style={{ border: "none", background: "none", color: t.fgMuted, fontSize: 10, cursor: "pointer", textDecoration: "underline" }}>
          {tr("search.clear")}
        </button>
      )}
    </div>
  );

  const sectionHead = (key: string, label: string, count?: number) => (
    <div onClick={() => setOpen((o) => ({ ...o, [key]: !o[key] }))} style={{
      display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", cursor: "pointer",
      background: open[key] ? "transparent" : t.panelAlt, fontSize: 11, fontWeight: 600,
      letterSpacing: 0.2, color: t.fgMuted,
    }}>
      <Icon name={open[key] ? "caretD" : "caretR"} size={10} />
      <span>{label}</span>
      {count ? <span style={{ color: t.accent, fontFamily: t.mono }}>·{count}</span> : null}
    </div>
  );

  // checkbox supports an optional indeterminate (partial) state, drawn as a dash.
  const checkbox = (active: boolean, partial = false) => (
    <div style={{
      width: 12, height: 12, border: `1px solid ${active || partial ? t.accent : t.border}`,
      background: active || partial ? t.accent : t.panel, flexShrink: 0, display: "flex",
      alignItems: "center", justifyContent: "center",
    }}>
      {active && <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round"><path d="M1.5 4.2l1.8 1.8L7 2" /></svg>}
      {!active && partial && <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round"><path d="M1.5 4h5" /></svg>}
    </div>
  );

  const comp = facets?.completeness;

  return (
    <div style={{
      width, flexShrink: 0, background: t.panel, borderRight: `1px solid ${t.border}`,
      overflow: "auto", fontFamily: t.sans, fontSize: 12,
    }}>
      {header}

      {/* Source — institution / aggregator from the registry */}
      <div style={{ borderBottom: `1px solid ${t.borderSoft}` }}>
        {sectionHead("source", tr("facet.source"), selectedSources.length)}
        {open.source && registry && (
          <div style={{ padding: "0 6px 6px" }}>
            {(["institutions", "aggregators"] as SourceKind[]).map((kind) => {
              const entries = Object.entries(registry[kind] || {});
              if (entries.length === 0) return null;
              // Only caption the kind when both kinds are present (otherwise it duplicates the header).
              const showKind = (["institutions", "aggregators"] as SourceKind[])
                .filter((k) => Object.keys(registry[k] || {}).length > 0).length > 1;
              return (
                <div key={kind}>
                  {showKind && (
                    <div style={{ padding: "4px 4px 2px", fontSize: 10, color: t.fgSubtle, letterSpacing: 0.3, textTransform: "uppercase" }}>
                      {tr(`facet.${kind}`)}
                    </div>
                  )}
                  {entries.map(([code, ent]) => {
                    const ids = Object.keys(ent.datasets || {});
                    const childKeys = ids.map((id) => `${kind}:${code}/${id}`);
                    const nSel = childKeys.filter((k) => selectedSources.includes(k)).length;
                    const all = ids.length > 0 && nSel === ids.length;
                    const partial = nSel > 0 && !all;
                    const expanded = !!srcOpen[`${kind}:${code}`];
                    return (
                      <div key={code}>
                        {/* parent institution — checkbox selects/clears all child collections */}
                        <div style={{
                          display: "flex", alignItems: "center", gap: 4, padding: "2px 4px",
                          background: all || partial ? t.accentSoft : "transparent",
                        }}>
                          <span onClick={() => setSrcOpen((o) => ({ ...o, [`${kind}:${code}`]: !o[`${kind}:${code}`] }))}
                            style={{ cursor: "pointer", display: "flex", color: t.fgSubtle }}>
                            <Icon name={expanded ? "caretD" : "caretR"} size={9} />
                          </span>
                          <span onClick={() => onToggleSource(`${kind}:${code}`)} style={{
                            display: "flex", alignItems: "center", gap: 6, flex: 1, cursor: "pointer", minWidth: 0,
                          }}>
                            {checkbox(all, partial)}
                            <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle, flexShrink: 0 }}>{code}</span>
                            <span style={{ flex: 1, fontSize: 11, fontWeight: 600, color: all || partial ? t.fg : t.fgMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={ent.name}>{ent.name}</span>
                            <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{ids.length}</span>
                          </span>
                        </div>
                        {/* child collections (scroll long lists, e.g. GBIF) */}
                        {expanded && (
                          <div style={{ maxHeight: ids.length > 12 ? 280 : undefined, overflowY: ids.length > 12 ? "auto" : undefined }}>
                          {ids.map((id) => {
                          const ck = `${kind}:${code}/${id}`;
                          const active = selectedSources.includes(ck);
                          const ds = ent.datasets[id];
                          return (
                            <label key={id} onClick={() => onToggleSource(ck)} style={{
                              display: "flex", alignItems: "center", gap: 6, padding: "2px 4px 2px 26px",
                              cursor: "pointer", background: active ? t.accentSoft : "transparent",
                            }}>
                              {checkbox(active)}
                              {ds.code && <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle, flexShrink: 0 }}>{ds.code}</span>}
                              <span style={{ flex: 1, fontSize: 11, color: active ? t.fg : t.fgMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={ds.name}>{ds.name}</span>
                            </label>
                          );
                          })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Collector — searchable typeahead over /api/collectors */}
      <div style={{ borderBottom: `1px solid ${t.borderSoft}` }}>
        {sectionHead("collector", tr("facet.collector"), selectedCollectors.length)}
        {open.collector && (
          <CollectorSelect selected={selectedCollectors} onToggle={onToggleCollector} />
        )}
      </div>

      {/* Record number — numeric range (e.g. 100–200) */}
      <div style={{ borderBottom: `1px solid ${t.borderSoft}` }}>
        {sectionHead("record_number", tr("facet.record_number"), recordActive ? 1 : 0)}
        {open.record_number && (
          <RecordRange from={filters.record_number_from} to={filters.record_number_to} onChange={onRecordRange} />
        )}
      </div>

      {/* Completeness — the platform's core filter */}
      <div style={{ borderBottom: `1px solid ${t.borderSoft}` }}>
        {sectionHead("completeness", tr("facet.completeness"), FLAGS.filter((f) => filters[f]).length)}
        {open.completeness && (
          <div style={{ padding: "0 6px 6px" }}>
            {FLAGS.map((flag) => {
              const active = filters[flag];
              const n = comp ? (comp as any)[flag] : undefined;
              return (
                <label key={flag} onClick={() => onToggleFlag(flag)} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "3px 4px",
                  cursor: "pointer", background: active ? t.accentSoft : "transparent",
                }}>
                  {checkbox(active)}
                  <span style={{ flex: 1, fontSize: 11, color: active ? t.fg : t.fgMuted }}>{tr(`facet.${flag}`)}</span>
                  {n != null && <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{n.toLocaleString()}</span>}
                </label>
              );
            })}
          </div>
        )}
      </div>

      {/* Standard facets */}
      {SECTIONS.map((key) => {
        const values = facets?.[key] || [];
        return (
          <div key={key} style={{ borderBottom: `1px solid ${t.borderSoft}` }}>
            {sectionHead(key, tr(`facet.${key}`), filters[key].length)}
            {open[key] && (
              <div style={{ padding: "0 6px 6px", maxHeight: 240, overflow: "auto" }}>
                {values.length === 0 && <div style={{ padding: "2px 6px", color: t.fgSubtle, fontSize: 10 }}>—</div>}
                {values.map((o) => {
                  const active = filters[key].includes(o.value);
                  return (
                    <label key={o.value} onClick={() => onToggle(key, o.value)} style={{
                      display: "flex", alignItems: "center", gap: 6, padding: "2px 4px",
                      cursor: "pointer", background: active ? t.accentSoft : "transparent",
                    }}>
                      {checkbox(active)}
                      <span style={{
                        flex: 1, fontSize: 11, color: active ? t.fg : t.fgMuted,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }} title={o.value}>{o.value}</span>
                      <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{o.count.toLocaleString()}</span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Two numeric inputs (from – to) for the record_number range; debounced so typing
// doesn't fire a request per keystroke. Empty/invalid -> undefined (open-ended).
function RecordRange({ from, to, onChange }: {
  from?: number; to?: number; onChange: (from?: number, to?: number) => void;
}) {
  const [lo, setLo] = useState(from?.toString() ?? "");
  const [hi, setHi] = useState(to?.toString() ?? "");
  // reflect external changes (e.g. Clear) into the inputs
  useEffect(() => { setLo(from?.toString() ?? ""); }, [from]);
  useEffect(() => { setHi(to?.toString() ?? ""); }, [to]);
  useEffect(() => {
    const h = setTimeout(() => {
      const num = (s: string) => {
        const n = parseInt(s, 10);
        return s.trim() !== "" && Number.isFinite(n) ? n : undefined;
      };
      onChange(num(lo), num(hi));
    }, 400);
    return () => clearTimeout(h);
  }, [lo, hi]);

  const inp: React.CSSProperties = {
    width: 64, boxSizing: "border-box", padding: "3px 5px", fontFamily: t.mono, fontSize: 11,
    border: `1px solid ${t.border}`, background: t.panelAlt, outline: "none",
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 10px 8px" }}>
      <input type="number" inputMode="numeric" value={lo} placeholder="100"
        onChange={(e) => setLo(e.target.value)} style={inp} />
      <span style={{ color: t.fgSubtle }}>–</span>
      <input type="number" inputMode="numeric" value={hi} placeholder="200"
        onChange={(e) => setHi(e.target.value)} style={inp} />
    </div>
  );
}
