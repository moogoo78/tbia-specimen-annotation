import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { t } from "../design/tokens";
import { api } from "../api/client";
import type { OccurrenceRow } from "../api/types";
import { CompletenessDots, GroupTag } from "./ui";

// Collector name as a link: resolves the raw recorded_by to a collector on click
// (lazily, to avoid one request per row) and filters Explore to its records.
// stopPropagation so it doesn't also open the row's record.
function CollectorLink({ value }: { value: string | null }) {
  const nav = useNavigate();
  if (!value) return <span style={{ color: t.fgSubtle }}>—</span>;
  const onClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const c = await api.resolveCollector(value);
      if (c) nav("/", { state: { collector: { id: c.id, label: c.label } } });
    } catch { /* unmapped (org/unknown) — no-op */ }
  };
  return (
    <span onClick={onClick} title={value}
      style={{ color: t.accent, cursor: "pointer" }}>{value}</span>
  );
}

export function TableView({ rows, activeId, onSelect }: {
  rows: OccurrenceRow[]; activeId?: string; onSelect?: (id: string) => void;
}) {
  const { t: tr } = useTranslation();
  const nav = useNavigate();
  const go = (id: string) => (onSelect ? onSelect(id) : nav(`/record/${id}`));

  const cols: [string, number][] = [
    [tr("col.completeness"), 60], [tr("col.group"), 70], [tr("col.catalog"), 110],
    [tr("col.record_number"), 90],
    [tr("col.sciname"), 220], [tr("col.common"), 110], [tr("col.county"), 80],
    [tr("col.locality"), 200], [tr("col.date"), 90], [tr("detail.collector"), 150],
    [tr("col.institution"), 200],
  ];
  return (
    <div style={{ flex: 1, overflow: "auto", background: t.panel }}>
      <table style={{ borderCollapse: "separate", borderSpacing: 0, width: "100%", fontSize: 11, tableLayout: "fixed" }}>
        <colgroup>{cols.map((c, i) => <col key={i} style={{ width: c[1] }} />)}</colgroup>
        <thead>
          <tr>
            {cols.map((c, i) => (
              <th key={i} style={{
                position: "sticky", top: 0, zIndex: 1, background: t.panelAlt,
                borderBottom: `1px solid ${t.border}`, borderRight: `1px solid ${t.borderSoft}`,
                padding: "5px 6px", textAlign: "left", fontSize: 10, fontWeight: 600,
                color: t.fgMuted, letterSpacing: 0.3, textTransform: "uppercase",
              }}>{c[0]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, idx) => (
            <tr key={r.id} onClick={() => go(r.id)} style={{
              background: r.id === activeId ? t.accentSoft : idx % 2 ? t.panelAlt : t.panel,
              cursor: "pointer", height: t.row,
            }}>
              <Cell><CompletenessDots row={r} /></Cell>
              <Cell><GroupTag group={r.bio_group} /></Cell>
              <Cell mono>{r.catalog_number || "—"}</Cell>
              <Cell mono>{r.record_number || "—"}</Cell>
              <Cell><i>{r.scientific_name || "—"}</i> <span style={{ color: t.fgMuted, fontSize: 10 }}>{r.name_author}</span></Cell>
              <Cell muted>{r.common_name_c || "—"}</Cell>
              <Cell>{r.county || "—"}</Cell>
              <Cell muted>{r.locality || "—"}</Cell>
              <Cell mono>{r.std_date || "—"}</Cell>
              <Cell><CollectorLink value={r.recorded_by} /></Cell>
              <Cell muted>{r.dataset_name || "—"}</Cell>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Dense list column for the split-pane view (design variation B).
export function SplitList({ rows, activeId, onSelect }: {
  rows: OccurrenceRow[]; activeId?: string; onSelect: (id: string) => void;
}) {
  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      {rows.map((r) => {
        const is = r.id === activeId;
        return (
          <div key={r.id} onClick={() => onSelect(r.id)} style={{
            display: "flex", gap: 8, padding: "6px 8px",
            borderBottom: `1px solid ${t.borderSoft}`,
            borderLeft: `3px solid ${is ? t.accent : "transparent"}`,
            background: is ? t.accentSoft : "transparent", cursor: "pointer",
          }}>
            {/* thumbnail or striped placeholder */}
            <div style={{
              width: 40, height: 40, flexShrink: 0, position: "relative", overflow: "hidden",
              background: `repeating-linear-gradient(45deg, ${t.panelAlt} 0 6px, ${t.borderSoft} 6px 7px)`,
              border: `1px solid ${t.borderSoft}`,
            }}>
              {r.thumbnail && (
                <img src={r.thumbnail} alt="" loading="lazy"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
              )}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 1 }}>
                <GroupTag group={r.bio_group} />
                {r.type_status && <span style={{ fontSize: 9, fontWeight: 700, color: t.danger, letterSpacing: 0.3, fontFamily: t.mono }}>{r.type_status.toUpperCase()}</span>}
                <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted, marginLeft: "auto", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 110 }}>{r.catalog_number || "—"}</span>
              </div>
              <div style={{ fontSize: 12, lineHeight: 1.2, marginBottom: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                <i style={{ fontWeight: 500 }}>{r.scientific_name || "—"}</i>
                <span style={{ color: t.fgSubtle, fontSize: 10 }}> {r.name_author}</span>
              </div>
              <div style={{ display: "flex", gap: 6, fontSize: 10, color: t.fgMuted, alignItems: "center", overflow: "hidden" }}>
                <span style={{ fontFamily: t.mono }}>{r.std_date || "—"}</span>
                <span>·</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{r.locality || r.county || "—"}</span>
                <CompletenessDots row={r} size={6} />
              </div>
              {r.recorded_by && (
                <div style={{ fontSize: 10, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <CollectorLink value={r.recorded_by} />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Cell({ children, mono, muted }: { children: React.ReactNode; mono?: boolean; muted?: boolean }) {
  return (
    <td style={{
      padding: "0 6px", borderBottom: `1px solid ${t.borderSoft}`, borderRight: `1px solid ${t.borderSoft}`,
      fontSize: 11, verticalAlign: "middle", overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis",
      fontFamily: mono ? t.mono : undefined, color: muted ? t.fgMuted : undefined,
    }}>{children}</td>
  );
}

export function GridView({ rows, activeId, onSelect }: {
  rows: OccurrenceRow[]; activeId?: string; onSelect?: (id: string) => void;
}) {
  const nav = useNavigate();
  const go = (id: string) => (onSelect ? onSelect(id) : nav(`/record/${id}`));
  return (
    <div style={{ flex: 1, overflow: "auto", padding: 10, background: t.bg }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 8 }}>
        {rows.map((r) => (
          <div key={r.id} onClick={() => go(r.id)} style={{
            background: t.panel, border: `1px solid ${r.id === activeId ? t.accent : t.border}`,
            cursor: "pointer", display: "flex", flexDirection: "column", minWidth: 0,
          }}>
            <div style={{
              aspectRatio: "4/3", position: "relative",
              background: `repeating-linear-gradient(45deg, ${t.panelAlt} 0 8px, ${t.borderSoft} 8px 9px)`,
              borderBottom: `1px solid ${t.borderSoft}`, display: "flex", alignItems: "center", justifyContent: "center",
              overflow: "hidden",
            }}>
              {/* placeholder label, sits behind the image (visible if there is none or it fails) */}
              <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle }}>{r.bio_group || "—"}</span>
              {r.thumbnail && (
                <img
                  src={r.thumbnail}
                  alt={r.scientific_name || r.catalog_number || ""}
                  loading="lazy"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  style={{
                    position: "absolute", inset: 0, width: "100%", height: "100%",
                    objectFit: "cover", background: t.panel,
                  }}
                />
              )}
              <div style={{ position: "absolute", top: 4, left: 4 }}><GroupTag group={r.bio_group} /></div>
              <div style={{ position: "absolute", bottom: 4, right: 4 }}><CompletenessDots row={r} /></div>
            </div>
            <div style={{ padding: "4px 6px 5px", minWidth: 0 }}>
              <div style={{ fontFamily: t.mono, fontSize: 9, color: t.fgMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.catalog_number || "—"}</div>
              <div style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><i>{r.scientific_name || "—"}</i></div>
              <div style={{ fontSize: 10, color: t.fgMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.common_name_c || r.family || "—"}</div>
              <div style={{ fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.std_date || "—"} · {r.county || "—"}</div>
              {r.recorded_by && (
                <div style={{ fontSize: 10, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <CollectorLink value={r.recorded_by} />
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
