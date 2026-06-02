import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { Dataset, RegistryEntry, SourceKind } from "../api/types";
import { Spinner } from "../components/ui";

// Collection institutions / aggregators from registry.json, each with its
// datasets and completeness stats (from /api/datasets). Clicking drills into
// Explore filtered to that source.
export function Institutions() {
  const { t: tr } = useTranslation();
  const registry = useQuery({ queryKey: ["registry"], queryFn: () => api.registry(), staleTime: Infinity });
  const datasets = useQuery({ queryKey: ["datasets", 1000], queryFn: () => api.datasets(1000) });

  // tbia_dataset_id -> stats
  const statsById = useMemo(() => {
    const m = new Map<string, Dataset>();
    for (const d of datasets.data ?? []) if (d.tbia_dataset_id) m.set(d.tbia_dataset_id, d);
    return m;
  }, [datasets.data]);

  if (registry.isLoading || datasets.isLoading || !registry.data) return <Spinner />;

  const groups: SourceKind[] = ["institutions", "aggregators"];
  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 12px" }}>{tr("inst.title")}</h2>
      {groups.map((kind) => {
        const entries = Object.entries(registry.data![kind] || {});
        if (entries.length === 0) return null;
        return (
          <div key={kind} style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 10, color: t.fgSubtle, letterSpacing: 0.3, textTransform: "uppercase", margin: "0 0 6px" }}>
              {tr(`facet.${kind}`)}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(440px, 1fr))", gap: 10 }}>
              {entries.map(([code, ent]) => (
                <OrgCard key={code} kind={kind} code={code} ent={ent}
                  statsById={statsById} defaultOpen={kind === "institutions"} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Bar({ pct, width = "100%" }: { pct: number; width?: number | string }) {
  return (
    <div style={{ width, height: 6, background: t.panelAlt, border: `1px solid ${t.borderSoft}`, flexShrink: 0 }}>
      <div style={{ width: `${pct}%`, height: "100%", background: t.ok }} />
    </div>
  );
}

function OrgCard({ kind, code, ent, statsById, defaultOpen }: {
  kind: SourceKind; code: string; ent: RegistryEntry;
  statsById: Map<string, Dataset>; defaultOpen: boolean;
}) {
  const { t: tr } = useTranslation();
  const nav = useNavigate();
  const [open, setOpen] = useState(defaultOpen);

  const ids = Object.keys(ent.datasets || {});
  let total = 0, weighted = 0;
  for (const id of ids) {
    const s = statsById.get(id);
    if (s) { total += s.n_records; weighted += (s.avg_completeness || 0) * s.n_records; }
  }
  const pct = total ? Math.round((weighted / total) * 100) : 0;

  // Drill into Explore filtered to one or more source datasets ("kind:code/id").
  const drill = (childKeys: string[]) => nav("/", { state: { sources: childKeys } });
  const allKeys = ids.map((id) => `${kind}:${code}/${id}`);

  return (
    <div style={{ background: t.panel, border: `1px solid ${t.border}`, display: "flex", flexDirection: "column" }}>
      {/* header */}
      <div onClick={() => setOpen((o) => !o)} style={{
        display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", cursor: "pointer",
        background: t.panelAlt, borderBottom: open ? `1px solid ${t.borderSoft}` : "none",
      }}>
        <Icon name={open ? "caretD" : "caretR"} size={11} />
        <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgSubtle, flexShrink: 0 }}>{code}</span>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={ent.name}>{ent.name}</span>
        <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{ids.length} {tr("inst.datasets")}</span>
      </div>

      {/* totals strip */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderBottom: open ? `1px solid ${t.borderSoft}` : "none" }}>
        <Bar pct={pct} />
        <span style={{ fontSize: 10, fontFamily: t.mono, color: t.fgMuted, width: 130, textAlign: "right", flexShrink: 0 }}>
          {pct}% · {total.toLocaleString()} {tr("inst.records")}
        </span>
        <button onClick={(e) => { e.stopPropagation(); drill(allKeys); }} title={tr("inst.viewAll")} style={{
          border: `1px solid ${t.border}`, background: t.panel, color: t.accent, cursor: "pointer",
          padding: "2px 6px", display: "flex", alignItems: "center", gap: 3, fontSize: 10,
        }}>
          <Icon name="rows" size={11} /><Icon name="caretR" size={9} />
        </button>
      </div>

      {/* dataset rows */}
      {open && (
        <div style={{ maxHeight: ids.length > 14 ? 320 : undefined, overflow: ids.length > 14 ? "auto" : undefined }}>
          {ids.map((id) => {
            const ds = ent.datasets[id];
            const s = statsById.get(id);
            const dpct = s ? Math.round((s.avg_completeness || 0) * 100) : 0;
            return (
              <div key={id} onClick={() => drill([`${kind}:${code}/${id}`])} title={tr("inst.viewAll")} style={{
                display: "flex", alignItems: "center", gap: 8, padding: "5px 10px",
                borderBottom: `1px solid ${t.borderSoft}`, cursor: "pointer",
              }}>
                {ds.code && <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle, flexShrink: 0 }}>{ds.code}</span>}
                <span style={{ flex: 1, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: t.accent }} title={ds.name}>{ds.name}</span>
                <Bar pct={dpct} width={70} />
                <span style={{ fontSize: 10, fontFamily: t.mono, color: t.fgMuted, width: 110, textAlign: "right", flexShrink: 0 }}>
                  {s ? `${dpct}% · ${s.n_records.toLocaleString()}` : "—"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
