import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { emptyFilters, type Filters } from "../api/types";
import { FacetPanel } from "../components/FacetPanel";
import type { CollectorRef } from "../components/CollectorSelect";
import { TableView, GridView, SplitList } from "../components/Results";
import { MapView } from "../components/MapView";
import { RecordDetailView } from "./RecordDetail";
import { Spinner } from "../components/ui";

type View = "table" | "grid" | "map" | "split";
type ArrayKey = "bio_group" | "kingdom_c" | "county" | "taxon_rank" | "basis_of_record" | "type_status" | "dataset_name";
type FlagKey = "missing_coordinates" | "missing_date" | "missing_identification" | "has_media";

const PAGE = 100;

export function Explore() {
  const { t: tr } = useTranslation();
  const [filters, setFilters] = useState<Filters>(emptyFilters());
  const [qInput, setQInput] = useState("");
  const [view, setView] = useState<View>("table");
  const [sort, setSort] = useState("completeness_score");
  const [offset, setOffset] = useState(0);
  const [activeId, setActiveId] = useState<string | undefined>();
  // Source selection is stored at child granularity: "institutions:BRMAS/<datasetId>".
  // A parent (institution) checkbox simply selects/clears all of its children.
  const [sources, setSources] = useState<string[]>([]);
  // Selected collectors kept as {id,label} so chips can show names; ids feed the filter.
  const [collectors, setCollectors] = useState<CollectorRef[]>([]);

  const registry = useQuery({ queryKey: ["registry"], queryFn: () => api.registry(), staleTime: Infinity });

  // Expand selected child sources into their dataset ids; map collectors to ids.
  const effFilters = useMemo<Filters>(() => {
    const ids = new Set<string>();
    for (const key of sources) {
      const id = key.split("/")[1];
      if (id) ids.add(id);
    }
    return { ...filters, tbia_dataset_id: [...ids], collector_id: collectors.map((c) => c.id) };
  }, [filters, sources, collectors]);

  // Filters handed over via navigation (a collector from a record/row, or source
  // datasets from the institutions page): apply once per navigation, then consume.
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const st = location.state as { collector?: CollectorRef; sources?: string[] } | null;
    if (!st) return;
    if (st.collector) {
      const c = st.collector;
      setCollectors((cs) => cs.some((x) => x.id === c.id) ? cs : [...cs, c]);
    }
    if (st.sources?.length) {
      setSources((s) => Array.from(new Set([...s, ...st.sources!])));
    }
    if (st.collector || st.sources?.length) {
      setOffset(0);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.key]);

  // Debounce the free-text box into the filter set.
  useEffect(() => {
    const h = setTimeout(() => {
      setFilters((f) => ({ ...f, q: qInput || undefined }));
      setOffset(0);
    }, 350);
    return () => clearTimeout(h);
  }, [qInput]);

  const order = sort === "scientific_name" || sort === "catalog_number" ? "asc" : "asc";
  const search = useQuery({
    queryKey: ["search", effFilters, sort, offset, view === "map"],
    queryFn: () => api.search(effFilters, sort, order, view === "map" ? 500 : PAGE, offset),
    placeholderData: keepPreviousData,
  });
  const facets = useQuery({ queryKey: ["facets", effFilters], queryFn: () => api.facets(effFilters) });

  const toggle = (key: ArrayKey, value: string) => {
    setFilters((f) => {
      const cur = f[key];
      return { ...f, [key]: cur.includes(value) ? cur.filter((x) => x !== value) : [...cur, value] };
    });
    setOffset(0);
  };
  const toggleFlag = (flag: FlagKey) => { setFilters((f) => ({ ...f, [flag]: !f[flag] })); setOffset(0); };
  const toggleSource = (key: string) => {
    setSources((s) => {
      if (key.includes("/")) {  // child collection — toggle the one dataset
        return s.includes(key) ? s.filter((x) => x !== key) : [...s, key];
      }
      // parent institution "kind:code" — select all children, or clear them if all selected
      const [kind, code] = key.split(":") as ["institutions" | "aggregators", string];
      const ids = Object.keys(registry.data?.[kind]?.[code]?.datasets || {});
      const childKeys = ids.map((id) => `${key}/${id}`);
      const all = childKeys.length > 0 && childKeys.every((k) => s.includes(k));
      const rest = s.filter((k) => !childKeys.includes(k));
      return all ? rest : [...rest, ...childKeys];
    });
    setOffset(0);
  };
  const setRecordRange = (from?: number, to?: number) => {
    setFilters((f) => ({ ...f, record_number_from: from, record_number_to: to }));
    setOffset(0);
  };
  const toggleCollector = (c: CollectorRef) => {
    setCollectors((cs) => cs.some((x) => x.id === c.id) ? cs.filter((x) => x.id !== c.id) : [...cs, c]);
    setOffset(0);
  };
  const clear = () => { setFilters(emptyFilters()); setQInput(""); setSources([]); setCollectors([]); setOffset(0); };

  const total = search.data?.total ?? 0;
  const rows = search.data?.items ?? [];

  // Clicking a row in any list view opens it in the split pane.
  const openRecord = (id: string) => { setActiveId(id); setView("split"); };
  // In split view, fall back to the first row when nothing is (or no longer) selected.
  const activeRowId = activeId && rows.some((r) => r.id === activeId) ? activeId : rows[0]?.id;

  const pager = (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 10px", borderTop: `1px solid ${t.border}`, background: t.panelAlt, fontSize: 11 }}>
      <span style={{ color: t.fgMuted, fontFamily: t.mono }}>
        {total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} {tr("search.of")} {total.toLocaleString()}
      </span>
      <div style={{ flex: 1 }} />
      <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} style={pgBtn(offset === 0)}><Icon name="back" size={10} /></button>
      <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} style={pgBtn(offset + PAGE >= total)}><Icon name="caretR" size={10} /></button>
    </div>
  );

  const chips = useMemo(() => {
    const out: { label: string; onRemove: () => void }[] = [];
    if (filters.q) out.push({ label: `"${filters.q}"`, onRemove: () => setQInput("") });
    // group selected child sources by institution: collapse to one chip when fully selected.
    const byEntry = new Map<string, string[]>();
    sources.forEach((key) => {
      const entryKey = key.split("/")[0];  // "kind:code"
      byEntry.set(entryKey, [...(byEntry.get(entryKey) || []), key]);
    });
    byEntry.forEach((keys, entryKey) => {
      const [kind, code] = entryKey.split(":") as ["institutions" | "aggregators", string];
      const ent = registry.data?.[kind]?.[code];
      const ids = Object.keys(ent?.datasets || {});
      if (ent && keys.length === ids.length) {
        out.push({ label: ent.name, onRemove: () => toggleSource(entryKey) });
      } else {
        keys.forEach((k) => {
          const ds = ent?.datasets[k.split("/")[1]];
          out.push({ label: ds?.code || ds?.name || k, onRemove: () => toggleSource(k) });
        });
      }
    });
    collectors.forEach((c) => out.push({ label: c.label, onRemove: () => toggleCollector(c) }));
    if (filters.record_number_from != null || filters.record_number_to != null) {
      out.push({
        label: `# ${filters.record_number_from ?? ""}–${filters.record_number_to ?? ""}`,
        onRemove: () => setRecordRange(undefined, undefined),
      });
    }
    (["missing_identification", "missing_coordinates", "missing_date", "has_media"] as FlagKey[])
      .forEach((f) => filters[f] && out.push({ label: tr(`facet.${f}`), onRemove: () => toggleFlag(f) }));
    (["bio_group", "kingdom_c", "county", "taxon_rank", "type_status", "dataset_name"] as ArrayKey[])
      .forEach((k) => filters[k].forEach((v) => out.push({ label: v, onRemove: () => toggle(k, v) })));
    return out;
  }, [filters, sources, collectors, registry.data]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* query bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: t.panel, borderBottom: `1px solid ${t.border}` }}>
        <div style={{ position: "relative", flex: 1, maxWidth: 460 }}>
          <span style={{ position: "absolute", left: 8, top: 6, color: t.fgSubtle }}><Icon name="search" size={12} /></span>
          <input value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder={tr("search.placeholder")} style={{
            width: "100%", boxSizing: "border-box", padding: "5px 6px 5px 26px", fontFamily: t.sans,
            fontSize: 12, border: `1px solid ${t.border}`, background: t.panelAlt, outline: "none",
          }} />
        </div>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgMuted }}>
          <b style={{ color: t.fg }}>{total.toLocaleString()}</b> {tr("search.results")}
        </span>
        <div style={{ display: "flex", border: `1px solid ${t.border}` }}>
          {(["table", "grid", "split", "map"] as View[]).map((v) => (
            <button key={v} onClick={() => { setView(v); if (v === "map") setOffset(0); }} title={tr(`view.${v}`)} style={{
              padding: "0 8px", height: 26, border: "none",
              background: view === v ? t.accentSoft : "transparent",
              color: view === v ? t.accent : t.fgMuted, cursor: "pointer",
            }}><Icon name={v === "table" ? "rows" : v === "grid" ? "grid" : v === "split" ? "split" : "map"} size={13} /></button>
          ))}
        </div>
        <select value={sort} onChange={(e) => setSort(e.target.value)} style={{
          border: `1px solid ${t.border}`, background: t.panel, fontSize: 11, padding: "3px 4px", fontFamily: t.sans,
        }}>
          <option value="completeness_score">↑ {tr("col.completeness")}</option>
          <option value="std_date">{tr("col.date")}</option>
          <option value="scientific_name">{tr("col.sciname")}</option>
          <option value="catalog_number">{tr("col.catalog")}</option>
        </select>
      </div>

      {/* active chips */}
      {chips.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "4px 8px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`, alignItems: "center" }}>
          <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono, marginRight: 2 }}>WHERE</span>
          {chips.map((c, i) => (
            <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "1px 2px 1px 6px", background: t.panel, border: `1px solid ${t.border}`, fontSize: 11, maxWidth: 240 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.label}</span>
              <button onClick={c.onRemove} style={{ border: "none", background: "none", padding: "2px 4px", cursor: "pointer", color: t.fgSubtle, display: "flex" }}><Icon name="x" size={9} /></button>
            </span>
          ))}
        </div>
      )}

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <FacetPanel facets={facets.data} filters={filters} onToggle={toggle} onToggleFlag={toggleFlag} onClear={clear}
          registry={registry.data} selectedSources={sources} onToggleSource={toggleSource}
          selectedCollectors={collectors} onToggleCollector={toggleCollector}
          onRecordRange={setRecordRange} />

        {view === "split" ? (
          /* split-pane: dense list column + record detail (design variation B) */
          <>
            <div style={{ width: 380, flexShrink: 0, borderRight: `1px solid ${t.border}`, background: t.panel, display: "flex", flexDirection: "column", minHeight: 0 }}>
              {search.isLoading && !search.data
                ? <Spinner />
                : <SplitList rows={rows} activeId={activeRowId} onSelect={setActiveId} />}
              {pager}
            </div>
            {activeRowId
              ? <RecordDetailView key={activeRowId} id={activeRowId} embedded />
              : <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: t.fgSubtle, fontSize: 12, background: t.panelAlt }}>{tr("search.results")}: 0</div>}
          </>
        ) : (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
            {search.isLoading && !search.data ? <Spinner /> :
              view === "table" ? <TableView rows={rows} activeId={activeId} onSelect={openRecord} /> :
              view === "grid" ? <GridView rows={rows} activeId={activeId} onSelect={openRecord} /> :
              <MapView rows={rows} />}

            {view !== "map" && pager}
          </div>
        )}
      </div>
    </div>
  );
}

const pgBtn = (disabled: boolean): React.CSSProperties => ({
  border: `1px solid ${t.border}`, background: t.panel, padding: "2px 8px",
  cursor: disabled ? "not-allowed" : "pointer", color: disabled ? t.fgSubtle : t.fg, display: "flex",
});
