// Scientific-name combobox backed by TaiCOL (backend/app/taicol.py).
//
// It is a text field first: typing a name by hand always works, and is the
// fallback whenever TaiCOL is slow or down. The dropdown only *offers* names;
// picking one is what attaches a scientificNameID + nameAccordingTo to the
// identification. Editing the text after a pick drops that link — the id
// described the picked name, not whatever the field says now.
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { api } from "../api/client";
import type { TaicolSuggestion, TaicolTaxon } from "../api/types";

export function TaicolCombobox({ value, onText, picked, onPick, inputStyle }: {
  value: string;
  onText: (v: string) => void;
  picked: TaicolTaxon | null;
  onPick: (t: TaicolTaxon | null) => void;
  inputStyle: React.CSSProperties;
}) {
  const { t: tr, i18n } = useTranslation();
  const listId = useId();
  const [items, setItems] = useState<TaicolSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [state, setState] = useState<"idle" | "loading" | "down">("idle");
  const [resolving, setResolving] = useState(false);
  const typed = useRef(false);  // only search on the person's typing, not on a pick filling the field
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!typed.current) return;
    const q = value.trim();
    if (q.length < 2) { setItems([]); setOpen(false); return; }
    let live = true;
    setState("loading");
    const h = setTimeout(() => {
      api.taicolSuggest(q, i18n.language.startsWith("zh") ? "zh-hant" : "en-us")
        .then((rows) => { if (!live) return; setItems(rows); setActive(0); setOpen(true); setState("idle"); })
        .catch(() => { if (!live) return; setItems([]); setOpen(false); setState("down"); });
    }, 250);
    return () => { live = false; clearTimeout(h); };
  }, [value, i18n.language]);

  // Close on a press outside, as a native select would.
  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  const choose = async (s: TaicolSuggestion) => {
    setOpen(false);
    typed.current = false;
    onText(s.name);
    setResolving(true);
    try {
      onPick(await api.taicolTaxon(s.taxon_id));
    } catch {
      onPick(null);       // the name stays; it just carries no TaiCOL id
      setState("down");
    } finally {
      setResolving(false);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!open || items.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % items.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + items.length) % items.length); }
    else if (e.key === "Enter") { e.preventDefault(); choose(items[active]); }
    else if (e.key === "Escape") { setOpen(false); }
  };

  return (
    <div ref={wrap} style={{ position: "relative" }}>
      <input
        role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={open && items[active] ? `${listId}-${active}` : undefined}
        value={value}
        onChange={(e) => {
          typed.current = true;
          onText(e.target.value);
          if (picked && e.target.value.trim() !== picked.scientific_name) onPick(null);
        }}
        onFocus={() => { if (items.length) setOpen(true); }}
        onKeyDown={onKey}
        placeholder={tr("ident.namePlaceholder")}
        // Latin names read italic; a Chinese query does not.
        style={{ ...inputStyle, fontStyle: value && !/[\u3400-\u9fff]/.test(value) ? "italic" : "normal" }}
      />

      {open && (
        <ul id={listId} role="listbox" style={{
          position: "absolute", zIndex: 20, top: "100%", left: 0, right: 0, margin: 0, padding: 0,
          listStyle: "none", maxHeight: 280, overflowY: "auto", background: t.panel,
          border: `1px solid ${t.border}`, borderTop: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
        }}>
          {items.length === 0 && (
            <li style={{ padding: "6px 8px", fontSize: 11, color: t.fgSubtle }}>{tr("ident.taicolNone")}</li>
          )}
          {items.map((s, i) => (
            <li key={s.taxon_id} id={`${listId}-${i}`} role="option" aria-selected={i === active}
              onPointerDown={(e) => { e.preventDefault(); choose(s); }}
              onMouseEnter={() => setActive(i)}
              style={{
                padding: "5px 8px", cursor: "pointer", fontSize: 12, display: "flex", gap: 8, alignItems: "baseline",
                background: i === active ? t.accentSoft : "transparent",
              }}>
              <span>{s.name_parts.map((p, k) => p.italic ? <i key={k}>{p.text}</i> : <span key={k}>{p.text}</span>)}</span>
              <span style={{ fontSize: 11, color: t.fgMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                {s.common_names.join("、")}
              </span>
              <span style={{ fontFamily: t.mono, fontSize: 9, color: t.fgSubtle }}>{s.taxon_id}</span>
            </li>
          ))}
          <li style={{ padding: "3px 8px", fontSize: 9, color: t.fgSubtle, borderTop: `1px solid ${t.borderSoft}` }}>
            {tr("ident.taicolSource")}
          </li>
        </ul>
      )}

      {/* What the pick attached — or why nothing is attached. */}
      <div style={{ fontSize: 10, marginTop: 3, minHeight: 14, lineHeight: 1.5 }}>
        {resolving ? (
          <span style={{ color: t.fgSubtle }}>{tr("ident.taicolResolving")}</span>
        ) : picked ? (
          <span style={{ color: t.ok, display: "inline-flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
            <span>✓ TaiCOL</span>
            <span style={{ color: t.fgMuted }}>
              <i>{picked.scientific_name}</i> {picked.name_author}
              {picked.common_name_c ? ` · ${picked.common_name_c}` : ""}
              {picked.version ? ` · ${tr("ident.taicolVersion", { v: picked.version })}` : ""}
            </span>
            {picked.scientific_name_id && (
              <a href={picked.taxon_uri} target="_blank" rel="noreferrer noopener" style={{ color: t.accent }}>taicol.tw ↗</a>
            )}
            <button onClick={() => onPick(null)} title={tr("ident.taicolUnlink")} style={{
              border: "none", background: "transparent", color: t.fgSubtle, cursor: "pointer", padding: 0, fontSize: 10,
            }}>× {tr("ident.taicolUnlink")}</button>
          </span>
        ) : state === "down" ? (
          <span style={{ color: t.warn }}>{tr("ident.taicolDown")}</span>
        ) : value.trim() ? (
          <span style={{ color: t.fgSubtle }}>{tr("ident.taicolUnpicked")}</span>
        ) : (
          <span style={{ color: t.fgSubtle }}>{tr("ident.taicolHint")}</span>
        )}
      </div>
    </div>
  );
}
