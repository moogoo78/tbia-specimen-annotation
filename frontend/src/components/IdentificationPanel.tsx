// Identifications: a person's determination of the specimen (DwC Identification).
//
// Deliberately separate from the annotation form above it. That form fills a
// gap with what the *label says* (and can be seeded by AI); this records what
// someone *determines the specimen to be* — a name, who named it, when, and on
// what authority. Those terms belong together, so one submission is one row
// (`identifications`), not one row per field. There is no AI path in here.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import type { Identification, IdentificationTerms, OccurrenceDetail } from "../api/types";
import { useAuth } from "../auth";
import { Button, StatusPill, WorkPanel, fieldGrid } from "./ui";
import { LICENSES, LICENSE_LABELS, LICENSE_URIS, SHOW_LICENSE_UI, asLicense, licenseLabel } from "../licenses";
import type { License } from "../licenses";
import { contributorLabel, isAnonymous } from "../contributors";
import { TaicolCombobox } from "./TaicolCombobox";
import type { TaicolTaxon } from "../api/types";

export const TAXON_RANK_OPTIONS = [
  "kingdom", "phylum", "class", "order", "family",
  "genus", "species", "subspecies", "variety", "form",
];
// DwC identificationQualifier's usual values; free text is still accepted.
const QUALIFIER_OPTIONS = ["cf.", "aff.", "?", "sp.", "nr."];

type Draft = Omit<IdentificationTerms, "date_identified"> & { y: string; mo: string; d: string };

function emptyDraft(name: string, orcid: string | null | undefined): Draft {
  const now = new Date();
  return {
    scientific_name: "", taxon_rank: "species", identification_qualifier: "",
    verbatim_identification: "",
    // "Me, today" is the common case; both stay editable for recording a
    // determination slip someone else wrote.
    identified_by: name, identified_by_id: orcid ? `https://orcid.org/${orcid}` : "",
    y: String(now.getFullYear()), mo: String(now.getMonth() + 1), d: String(now.getDate()),
    identification_references: "", identification_remarks: "",
    scientific_name_id: null, name_according_to: null,
  };
}

/** Year / month / day -> partial ISO 8601 (YYYY, YYYY-MM or YYYY-MM-DD).
 *  A part is only kept if the coarser one is there, matching what the API accepts. */
function isoDate(y: string, mo: string, d: string): string {
  y = y.trim(); mo = mo.trim(); d = d.trim();
  if (!y) return "";
  let out = y.padStart(4, "0");
  if (!mo) return out;
  out += "-" + mo.padStart(2, "0");
  if (!d) return out;
  return out + "-" + d.padStart(2, "0");
}

/** "Chilodontia cf. laevis" style display: the qualifier sits before the
 *  epithet it qualifies, or after a bare genus ("Begonia sp."). */
export function determinationName(i: Pick<IdentificationTerms, "scientific_name" | "identification_qualifier">): string {
  const q = i.identification_qualifier?.trim();
  if (!q) return i.scientific_name;
  const parts = i.scientific_name.split(/\s+/);
  if (parts.length < 2 || q === "sp.") return `${i.scientific_name} ${q}`;
  return [parts[0], q, ...parts.slice(1)].join(" ");
}

/** Recording a determination takes the identifier flag, beside whatever role
 *  the user has; admins always may (backend workflow.can_identify). */
export function canIdentify(user: { role: string; is_identifier?: boolean } | null | undefined): boolean {
  return !!user && (!!user.is_identifier || user.role === "admin");
}

export function IdentificationPanel({ record, autoOpen, onAutoOpened }: {
  record: OccurrenceDetail;
  /** Scroll to the form and focus it (Explore's preview "Add identification"). */
  autoOpen?: boolean; onAutoOpened?: () => void;
}) {
  const { t: tr } = useTranslation();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => emptyDraft(user?.display_name ?? "", user?.orcid));
  const [receipt, setReceipt] = useState<"draft" | "submitted" | null>(null);
  const [license, setLicense] = useState<License>(() => asLicense(user?.default_license));
  const touchedLicense = useRef(false);
  const profileLicense = asLicense(user?.default_license);
  useEffect(() => { if (!touchedLicense.current) setLicense(profileLicense); }, [profileLicense]);
  // `user` can arrive after first paint; prefill identifiedBy once it does,
  // unless the contributor has already typed something there.
  useEffect(() => {
    if (!user) return;
    setDraft((s) => s.identified_by || s.identified_by_id ? s : {
      ...s, identified_by: user.display_name,
      identified_by_id: user.orcid ? `https://orcid.org/${user.orcid}` : "",
    });
  }, [user]);

  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!autoOpen) return;
    setReceipt(null);
    // After the form has rendered, so the scroll lands on its full height.
    requestAnimationFrame(() => {
      // The work column's top, so its tabs stay in view above the form.
      (rootRef.current?.parentElement ?? rootRef.current)?.scrollIntoView({ behavior: "smooth", block: "start" });
      rootRef.current?.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
    });
    onAutoOpened?.();
  }, [autoOpen, onAutoOpened]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["detail", record.id] });
  const set = (k: keyof Draft, v: string) => { setReceipt(null); setDraft((s) => ({ ...s, [k]: v })); };
  // The TaiCOL record behind the name, when it was picked rather than typed.
  // Its two DwC terms ride in the draft; the rest is only shown under the field.
  const [picked, setPicked] = useState<TaicolTaxon | null>(null);
  const pick = (tx: TaicolTaxon | null) => {
    setPicked(tx);
    setDraft((s) => ({
      ...s,
      scientific_name: tx ? tx.scientific_name : s.scientific_name,
      taxon_rank: tx?.taxon_rank ?? s.taxon_rank,
      scientific_name_id: tx?.scientific_name_id ?? null,
      // Picked: TaiCOL's citation, fixed. Unpicked: clear it only if it was
      // TaiCOL's — a citation the contributor typed themselves stays theirs.
      name_according_to: tx?.scientific_name_id ? tx.name_according_to
        : s.scientific_name_id ? null : s.name_according_to,
    }));
  };
  const reset = () => { setPicked(null); setDraft(emptyDraft(user?.display_name ?? "", user?.orcid)); };

  const createMut = useMutation({
    mutationFn: (status: "draft" | "submitted") => {
      const { y, mo, d, identified_by_id: _ignored, ...terms } = draft;
      // identifiedByID is not asked for: it is the signed-in contributor's
      // ORCID iD, sent only while "Identified by" still names them. Recording
      // someone else's determination must not carry *our* iD as theirs.
      const mine = user && (terms.identified_by ?? "").trim() === user.display_name.trim();
      return api.createIdentification(String(record.id), {
        ...terms, date_identified: isoDate(y, mo, d), status,
        identified_by_id: mine && user.orcid ? `https://orcid.org/${user.orcid}` : null,
        ...(SHOW_LICENSE_UI ? { license } : {}),
      });
    },
    onSuccess: (_res, status) => {
      setReceipt(status);
      reset();
      refresh();
      qc.invalidateQueries({ queryKey: ["myIdentifications"] });
    },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      api.updateIdentification(id, body),
    onSuccess: refresh,
  });

  const isReviewer = user?.role === "reviewer" || user?.role === "admin";
  const idents = record.identifications ?? [];
  // nameAccordingTo: TaiCOL's when the name was picked (locked), else the
  // contributor must name a source before submitting. A draft can wait.
  const fromTaicol = !!draft.scientific_name_id;
  const hasAccording = fromTaicol || (draft.name_according_to ?? "").trim() !== "";
  const canDraft = draft.scientific_name.trim() !== "" && !createMut.isPending;
  const canSubmit = canDraft && hasAccording;

  return (
    <div ref={rootRef}>
    <WorkPanel data-ident-panel>

        {receipt && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 8px", background: t.accentSoft, border: `1px solid ${t.border}`, fontSize: 11 }}>
            <Icon name="check" size={12} />
            <span>{tr(receipt === "draft" ? "ident.draftSaved" : "ident.submitted")}</span>
            <div style={{ flex: 1 }} />
            <Link to="/me" style={{ color: t.accent, textDecoration: "none", whiteSpace: "nowrap" }}>{tr("annotate.seeMine")} →</Link>
          </div>
        )}

        {!user ? (
          <div style={{ fontSize: 12 }}>
            <Link to="/login" style={{ color: t.accent }}>{tr("ident.loginToIdentify")} →</Link>
          </div>
        ) : !canIdentify(user) ? (
          <div data-ident-locked style={{
            display: "flex", gap: 8, alignItems: "flex-start", padding: "8px 10px", fontSize: 12, lineHeight: 1.5,
            background: t.panelAlt, border: `1px solid ${t.borderSoft}`, color: t.fgMuted,
          }}>
            <Icon name="user" size={12} />
            <div>
              <div style={{ fontWeight: 600, color: t.fg }}>{tr("ident.needsIdentifier")}</div>
              <div style={{ fontSize: 11 }}>{tr("ident.needsIdentifierHint")}</div>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {createMut.isError && (
              <div style={{ padding: "6px 8px", border: `1px solid ${t.danger}`, fontSize: 11, color: t.danger }}>
                {tr("annotate.submitFailed")} — {(createMut.error as Error).message}
              </div>
            )}
            <div style={fieldGrid}>
            <Row label={tr("ident.scientificName")} term="scientificName" required style={{ gridColumn: "1 / -1" }}>
              <TaicolCombobox value={draft.scientific_name} onText={(v) => set("scientific_name", v)}
                picked={picked} onPick={pick} inputStyle={inputStyle} />
            </Row>
            <Row label={tr("ident.nameAccordingTo")} term="nameAccordingTo" required={!fromTaicol}
              style={{ gridColumn: "1 / -1" }}>
              <input value={draft.name_according_to ?? ""} readOnly={fromTaicol} aria-readonly={fromTaicol}
                onChange={(e) => set("name_according_to", e.target.value)}
                placeholder={tr("ident.nameAccordingToHint")}
                style={fromTaicol
                  ? { ...inputStyle, color: t.fgMuted, background: t.borderSoft, cursor: "not-allowed", fontSize: 11 }
                  : inputStyle} />
              <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 3, lineHeight: 1.5 }}>
                {fromTaicol ? tr("ident.nameAccordingToLocked") : tr("ident.nameAccordingToNeeded")}
              </div>
            </Row>
            <div style={{ display: "flex", gap: 6, minWidth: 0 }}>
              <Row label={tr("ident.qualifier")} term="identificationQualifier" style={{ width: 96, flexShrink: 0, minWidth: 0 }}>
                <input list="ident-qualifiers" value={draft.identification_qualifier ?? ""}
                  onChange={(e) => set("identification_qualifier", e.target.value)} placeholder="—" style={inputStyle} />
                <datalist id="ident-qualifiers">{QUALIFIER_OPTIONS.map((q) => <option key={q} value={q} />)}</datalist>
              </Row>
              <Row label={tr("ident.taxonRank")} term="taxonRank" style={{ flex: 1, minWidth: 0 }}>
                <select value={draft.taxon_rank ?? ""} onChange={(e) => set("taxon_rank", e.target.value)} style={inputStyle}>
                  <option value="">—</option>
                  {[...TAXON_RANK_OPTIONS, ...(draft.taxon_rank && !TAXON_RANK_OPTIONS.includes(draft.taxon_rank) ? [draft.taxon_rank] : [])]
                    .map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </Row>
            </div>
            <Row label={tr("ident.identifiedBy")} term="identifiedBy">
              <input value={draft.identified_by ?? ""} onChange={(e) => set("identified_by", e.target.value)} style={inputStyle} />
            </Row>
            <Row label={tr("ident.dateIdentified")} term="dateIdentified">
              <div style={{ display: "flex", gap: 4 }}>
                <input inputMode="numeric" value={draft.y} onChange={(e) => set("y", e.target.value)} placeholder="YYYY" style={{ ...inputStyle, width: 64 }} />
                <select value={draft.mo} onChange={(e) => set("mo", e.target.value)} style={{ ...inputStyle, width: 60 }}>
                  <option value="">MM</option>
                  {Array.from({ length: 12 }, (_, i) => String(i + 1)).map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <input inputMode="numeric" value={draft.d} onChange={(e) => set("d", e.target.value)} placeholder="DD" style={{ ...inputStyle, width: 52 }} />
              </div>
            </Row>
            <Row label={tr("ident.references")} term="identificationReferences">
              <input value={draft.identification_references ?? ""} onChange={(e) => set("identification_references", e.target.value)}
                placeholder={tr("ident.referencesHint")} style={inputStyle} />
            </Row>
            <Row label={tr("ident.remarks")} term="identificationRemarks" style={{ gridColumn: "1 / -1" }}>
              <textarea value={draft.identification_remarks ?? ""} onChange={(e) => set("identification_remarks", e.target.value)}
                style={{ ...inputStyle, height: 56, resize: "vertical" }} />
            </Row>
            </div>

            {SHOW_LICENSE_UI && (
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: t.fgMuted }}>{tr("annotate.license")}</span>
                <select value={license} onChange={(e) => { touchedLicense.current = true; setLicense(e.target.value as License); }}
                  style={{ ...inputStyle, width: "auto", flex: 1 }}>
                  {LICENSES.map((l) => <option key={l} value={l}>{LICENSE_LABELS[l]}</option>)}
                </select>
                <a href={LICENSE_URIS[license]} target="_blank" rel="noreferrer noopener"
                  style={{ fontSize: 10, color: t.accent, whiteSpace: "nowrap" }}>{tr("annotate.licenseDeed")}</a>
              </div>
            )}

            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Button primary small disabled={!canSubmit} onClick={() => createMut.mutate("submitted")}>{tr("ident.submit")}</Button>
              <Button small disabled={!canDraft} onClick={() => createMut.mutate("draft")}>{tr("annotate.saveDraft")}</Button>
              <div style={{ flex: 1 }} />
              {/* Always-open form, so nothing to close: this resets it to the
                  prefilled "me, today" state instead. */}
              <Button small onClick={() => { setReceipt(null); reset(); }}>{tr("ident.clear")}</Button>
            </div>
          </div>
        )}

        {idents.length > 0 && (
          <div style={{ borderTop: `1px solid ${t.borderSoft}`, paddingTop: 8 }}>
            <div style={{ fontSize: 10, color: t.fgSubtle, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.3 }}>{tr("ident.history")}</div>
            {idents.map((i) => (
              <IdentificationCard key={i.id} i={i} isReviewer={isReviewer} userId={user?.id}
                onUpdate={(body) => updateMut.mutate({ id: i.id, body })} />
            ))}
          </div>
        )}
    </WorkPanel>
    </div>
  );
}

/** One determination, written the way a det. slip reads it. */
export function IdentificationCard({ i, isReviewer, userId, onUpdate }: {
  i: Identification; isReviewer?: boolean; userId?: number;
  onUpdate?: (body: Record<string, unknown>) => void;
}) {
  const { t: tr } = useTranslation();
  const det = [i.identified_by, i.date_identified].filter(Boolean).join(", ");
  return (
    <div style={{ padding: "5px 0", borderBottom: `1px solid ${t.borderSoft}`, fontSize: 11, opacity: i.status === "rejected" ? 0.6 : 1 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <i style={{ fontWeight: 600, fontSize: 12 }}>{determinationName(i)}</i>
        {i.taxon_rank && <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted }}>{i.taxon_rank}</span>}
        <span style={{ flex: 1 }} />
        <StatusPill status={i.status} />
      </div>
      {det && (
        <div style={{ color: t.fgMuted, marginTop: 1 }}>
          det. {i.identified_by_id && /^https?:\/\//.test(i.identified_by_id)
            ? <a href={i.identified_by_id} target="_blank" rel="noreferrer noopener" style={{ color: t.fgMuted }}>{det}</a>
            : det}
        </div>
      )}
      {i.scientific_name_id && (
        <div style={{ color: t.fgSubtle, fontSize: 10 }}>
          <a href={i.scientific_name_id} target="_blank" rel="noreferrer noopener" style={{ color: t.accent }}>TaiCOL ↗</a>
          {i.name_according_to && <span title="nameAccordingTo"> · {i.name_according_to.replace(/^TaiCOL \(Catalogue of Life in Taiwan\), /, "")}</span>}
        </div>
      )}
      {i.identification_references && (
        <div style={{ color: t.fgSubtle, fontSize: 10 }}>{tr("ident.references")}: {i.identification_references}</div>
      )}
      {i.identification_remarks && <div style={{ color: t.fgMuted, fontSize: 10 }}>{i.identification_remarks}</div>}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
        <span style={{ fontSize: 10, color: t.fgSubtle }}>— </span>
        <Link to={`/contributors/${i.contributor_id}`}
          style={{ fontSize: 10, color: t.fgSubtle, textDecoration: "none", fontStyle: isAnonymous(i.contributor_name) ? "italic" : "normal" }}
          title={isAnonymous(i.contributor_name) ? tr("vol.anonymousHint") : undefined}>
          {contributorLabel(tr, i.contributor_name, i.contributor_id)}
        </Link>
        <span style={{ fontSize: 10, color: t.fgSubtle }}>·</span>
        {SHOW_LICENSE_UI && userId === i.contributor_id && onUpdate ? (
          <select value={asLicense(i.license)} title={tr("annotate.licenseChange")}
            onChange={(e) => onUpdate({ license: e.target.value })}
            style={{ fontSize: 10, fontFamily: t.mono, color: t.fgMuted, padding: "1px 2px", background: t.panelAlt, border: `1px solid ${t.borderSoft}`, cursor: "pointer" }}>
            {LICENSES.map((l) => <option key={l} value={l}>{LICENSE_LABELS[l]}</option>)}
          </select>
        ) : (
          <span style={{ fontSize: 10, color: t.fgSubtle, fontFamily: t.mono }}>{licenseLabel(i.license)}</span>
        )}
        {onUpdate && userId === i.contributor_id && i.status === "draft" && (
          <span style={{ marginLeft: "auto" }}>
            <Button small primary onClick={() => onUpdate({ status: "submitted" })}>{tr("ident.submit")}</Button>
          </span>
        )}
        {onUpdate && isReviewer && i.status === "submitted" && (
          <span style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
            <Button small onClick={() => onUpdate({ status: "accepted" })}>{tr("annotate.accept")}</Button>
            <Button small danger onClick={() => onUpdate({ status: "rejected" })}>{tr("annotate.reject")}</Button>
          </span>
        )}
        {onUpdate && isReviewer && i.status === "accepted" && (
          <span style={{ marginLeft: "auto" }}>
            <Button small onClick={() => onUpdate({ status: "merged" })}>{tr("annotate.merge")}</Button>
          </span>
        )}
      </div>
    </div>
  );
}

function Row({ label, term, required, style, children }: {
  label: string; term: string; required?: boolean; style?: React.CSSProperties; children: React.ReactNode;
}) {
  return (
    <div style={{ minWidth: 0, ...style }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 3, minWidth: 0 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: t.fgMuted, whiteSpace: "nowrap" }}>
          {label}{required && <span style={{ color: t.danger }}> *</span>}
        </span>
        <span title={term} style={{ fontSize: 9, fontFamily: t.mono, color: t.fgSubtle, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{term}</span>
      </div>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", padding: "5px 7px", fontSize: 12,
  border: `1px solid ${t.border}`, background: t.panelAlt, outline: "none", fontFamily: t.sans,
};
