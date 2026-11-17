import { useEffect, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { TaxonNode } from "../api/types";

/** A taxon filter value is "Kingdom/rank/Name" (or a bare kingdom) — see
 *  backend app/taxa.py. It names itself, so a chip needs no lookup. */
export function taxonLabel(key: string): { rank: string; name: string } {
  const parts = key.split("/");
  return parts.length >= 3
    ? { rank: parts[1], name: parts.slice(2).join("/") }
    : { rank: "kingdom", name: key };
}

const italic = (rank: string) => rank === "genus" || rank === "species";

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

/** Taxon picker: a search box over every rank, and the tree beneath it.
 *  Typing replaces the tree with matches; clearing the box brings it back.
 *  Counts are store-wide (the tree is for choosing; the result total reports
 *  the intersection with the other filters). */
export function TaxonSelect({ selected, onToggle }: {
  selected: string[];
  onToggle: (key: string) => void;
}) {
  const { t: tr } = useTranslation();
  const [raw, setRaw] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const h = setTimeout(() => setQ(raw.trim()), 200);
    return () => clearTimeout(h);
  }, [raw]);

  const results = useQuery({
    queryKey: ["taxa-search", q],
    queryFn: () => api.taxonSearch(q),
    enabled: q !== "",
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
  const sel = new Set(selected);

  return (
    <div style={{ padding: "2px 6px 6px" }}>
      {selected.map((key) => {
        const { rank, name } = taxonLabel(key);
        return (
          <label key={key} onClick={() => onToggle(key)} style={rowStyle(true)}>
            {box(true)}
            <span style={labelStyle(true)} title={key}>
              <RankTag rank={rank} />
              <span style={{ fontStyle: italic(rank) ? "italic" : "normal" }}>{name}</span>
            </span>
            <Icon name="x" size={9} />
          </label>
        );
      })}

      <div style={{ position: "relative", margin: "4px 0 2px" }}>
        <span style={{ position: "absolute", left: 6, top: 5, color: t.fgSubtle }}>
          <Icon name="search" size={11} />
        </span>
        <input value={raw} onChange={(e) => setRaw(e.target.value)}
          placeholder={tr("taxon.search")} aria-label={tr("taxon.search")}
          style={{
            width: "100%", boxSizing: "border-box", padding: "4px 6px 4px 22px",
            fontFamily: t.sans, fontSize: 11, border: `1px solid ${t.border}`,
            background: t.panelAlt, outline: "none",
          }} />
      </div>

      <div style={{ maxHeight: 320, overflow: "auto" }} data-taxon-list>
        {q !== "" ? (
          (results.data ?? []).length === 0 ? (
            <div style={{ padding: "3px 6px", color: t.fgSubtle, fontSize: 10 }}>
              {results.isFetching ? "…" : tr("taxon.none")}
            </div>
          ) : (
            (results.data ?? []).map((n) => (
              <TaxonRow key={n.key} node={n} depth={0} active={sel.has(n.key)} onToggle={onToggle}
                // Ancestors tell same-named taxa apart: Arenaria the sandwort
                // (Caryophyllaceae) from Arenaria the turnstone (Scolopacidae).
                context={(n.lineage ?? []).slice(0, 2).join(" · ")} />
            ))
          )
        ) : (
          <Level parent={undefined} depth={0} selected={sel} onToggle={onToggle} />
        )}
      </div>
    </div>
  );
}

/** One level of the tree, fetched when its parent is first opened. */
function Level({ parent, depth, selected, onToggle }: {
  parent?: string; depth: number; selected: Set<string>; onToggle: (key: string) => void;
}) {
  const { t: tr } = useTranslation();
  const level = useQuery({
    queryKey: ["taxa-children", parent ?? ""],
    queryFn: () => api.taxonChildren(parent),
    staleTime: 10 * 60_000,
  });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!level.data) {
    return <div style={{ padding: `2px ${6 + depth * 12}px`, color: t.fgSubtle, fontSize: 10 }}>…</div>;
  }
  return (
    <>
      {level.data.items.map((n) => (
        <div key={n.key}>
          <TaxonRow node={n} depth={depth} active={selected.has(n.key)} onToggle={onToggle}
            expanded={!!open[n.key]}
            onExpand={n.has_children ? () => setOpen((o) => ({ ...o, [n.key]: !o[n.key] })) : undefined} />
          {open[n.key] && <Level parent={n.key} depth={depth + 1} selected={selected} onToggle={onToggle} />}
        </div>
      ))}
      {/* Records under the parent with nothing at this rank — a family-level
          identification under its family, say. Counted so the children's sum
          is not a mystery; not selectable, since there is nothing to name. */}
      {level.data.n_unplaced > 0 && (
        <div style={{
          display: "flex", gap: 6, padding: `1px 4px 1px ${4 + depth * 12 + 14}px`,
          fontSize: 10, color: t.fgSubtle,
        }} title={tr("taxon.unplacedHint")}>
          <span style={{ flex: 1, fontStyle: "italic" }}>{tr("taxon.unplaced")}</span>
          <span style={{ fontFamily: t.mono }}>{level.data.n_unplaced.toLocaleString()}</span>
        </div>
      )}
    </>
  );
}

function TaxonRow({ node, depth, active, onToggle, expanded, onExpand, context }: {
  node: TaxonNode; depth: number; active: boolean; onToggle: (key: string) => void;
  expanded?: boolean; onExpand?: () => void; context?: string;
}) {
  return (
    <div style={{ ...rowStyle(active), paddingLeft: 4 + depth * 12 }} data-taxon={node.key}>
      <span onClick={onExpand} style={{
        width: 10, display: "flex", color: t.fgSubtle, cursor: onExpand ? "pointer" : "default",
        visibility: onExpand ? "visible" : "hidden",
      }} data-expand>
        <Icon name={expanded ? "caretD" : "caretR"} size={9} />
      </span>
      <label onClick={() => onToggle(node.key)} style={{
        display: "flex", alignItems: "center", gap: 6, flex: 1, minWidth: 0, cursor: "pointer",
      }}>
        {box(active)}
        <span style={labelStyle(active)} title={[node.name, node.name_c, context].filter(Boolean).join(" · ")}>
          {context !== undefined && <RankTag rank={node.rank} />}
          <span style={{ fontStyle: italic(node.rank) ? "italic" : "normal" }}>{node.name}</span>
          {node.name_c && <span style={{ color: t.fgSubtle, marginLeft: 4 }}>{node.name_c}</span>}
          {context && <span style={{ color: t.fgSubtle, marginLeft: 4, fontSize: 10 }}>{context}</span>}
        </span>
        <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{node.n.toLocaleString()}</span>
      </label>
    </div>
  );
}

function RankTag({ rank }: { rank: string }) {
  const { t: tr } = useTranslation();
  return (
    <span style={{
      fontSize: 9, color: t.fgSubtle, border: `1px solid ${t.borderSoft}`, padding: "0 3px",
      marginRight: 4, fontStyle: "normal",
    }}>{tr(`taxon.rank.${rank}`)}</span>
  );
}

const rowStyle = (active: boolean): React.CSSProperties => ({
  display: "flex", alignItems: "center", gap: 4, padding: "2px 4px",
  background: active ? t.accentSoft : "transparent",
});

const labelStyle = (active: boolean): React.CSSProperties => ({
  flex: 1, fontSize: 11, color: active ? t.fg : t.fgMuted,
  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
});
