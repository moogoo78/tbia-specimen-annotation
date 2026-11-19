// Browse TaiCOL's classification and pick a name from it — the other way into
// the identification's name field, beside typing. Answered from the loaded
// TaiCOL release (backend app/seed_taicol.py); one level is fetched per expand,
// so opening the tree costs a few dozen rows, never the 96k.
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { TaicolNode } from "../api/types";

export function TaicolTree({ onPick, openPath, selectedId }: {
  onPick: (n: TaicolNode) => void;
  /** Ancestors to open on arrival (the picked name's path), root first. */
  openPath: string[];
  selectedId?: string | null;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(openPath));
  const toggle = (id: string) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  return (
    <div role="tree" style={{ fontSize: 12 }}>
      <Level parent={undefined} depth={0} open={open} onToggle={toggle} onPick={onPick} selectedId={selectedId} />
    </div>
  );
}

function Level({ parent, depth, open, onToggle, onPick, selectedId }: {
  parent: string | undefined; depth: number; open: Set<string>;
  onToggle: (id: string) => void; onPick: (n: TaicolNode) => void; selectedId?: string | null;
}) {
  const { t: tr } = useTranslation();
  const q = useQuery({
    queryKey: ["taicol-tree", parent ?? "root"],
    queryFn: () => api.taicolTree(parent),
    staleTime: Infinity,
  });
  if (q.isLoading) {
    return <div style={{ padding: `3px 0 3px ${depth * 14 + 22}px`, color: t.fgSubtle, fontSize: 11 }}>…</div>;
  }
  if (q.isError) {
    return <div style={{ padding: "6px 8px", color: t.warn, fontSize: 11 }}>{tr("ident.treeDown")}</div>;
  }
  return (
    <>
      {(q.data ?? []).map((n) => (
        <Node key={n.taxon_id} n={n} depth={depth} open={open} onToggle={onToggle} onPick={onPick} selectedId={selectedId} />
      ))}
    </>
  );
}

function Node({ n, depth, open, onToggle, onPick, selectedId }: {
  n: TaicolNode; depth: number; open: Set<string>;
  onToggle: (id: string) => void; onPick: (n: TaicolNode) => void; selectedId?: string | null;
}) {
  const { t: tr } = useTranslation();
  const isOpen = open.has(n.taxon_id);
  const selected = selectedId === n.taxon_id;
  const row = useRef<HTMLDivElement>(null);
  // Bring the picked name into view once its ancestors have opened.
  useEffect(() => {
    if (selected) row.current?.scrollIntoView({ block: "center" });
  }, [selected]);
  return (
    <div role="treeitem" aria-expanded={n.n_children ? isOpen : undefined} aria-selected={selected}>
      <div ref={row} style={{
        display: "flex", alignItems: "center", gap: 4, padding: `2px 8px 2px ${depth * 14 + 4}px`,
        background: selected ? t.accentSoft : "transparent",
      }}>
        <button onClick={() => n.n_children && onToggle(n.taxon_id)} aria-label={isOpen ? "collapse" : "expand"}
          style={{
            width: 16, height: 16, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
            border: "none", background: "transparent", padding: 0, color: t.fgSubtle,
            cursor: n.n_children ? "pointer" : "default", visibility: n.n_children ? "visible" : "hidden",
          }}>
          <Icon name={isOpen ? "caretD" : "caretR"} size={9} />
        </button>
        {/* The name picks; the caret expands. Two targets, so browsing past a
            genus never picks it by accident. */}
        <button onClick={() => onPick(n)} title={tr("ident.treePick")} style={{
          flex: 1, minWidth: 0, display: "flex", alignItems: "baseline", gap: 6, textAlign: "left",
          border: "none", background: "transparent", padding: "1px 0", cursor: "pointer", fontFamily: t.sans,
          fontSize: 12, color: t.fg,
        }}>
          <span style={{ whiteSpace: "nowrap" }}>
            {n.name_parts.map((p, k) => p.italic ? <i key={k}>{p.text}</i> : <span key={k}>{p.text}</span>)}
          </span>
          {n.common_names[0] && (
            <span style={{ fontSize: 11, color: t.fgMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {n.common_names[0]}
            </span>
          )}
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, whiteSpace: "nowrap" }}>
            {n.rank}{n.n_species > 0 && n.rank !== "species" ? ` · ${n.n_species.toLocaleString()}` : ""}
          </span>
        </button>
      </div>
      {isOpen && <Level parent={n.taxon_id} depth={depth + 1} open={open} onToggle={onToggle} onPick={onPick} selectedId={selectedId} />}
    </div>
  );
}
