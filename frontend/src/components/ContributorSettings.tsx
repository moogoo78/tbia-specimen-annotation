// The standing choices and role-gated controls that used to sit on the
// dashboard. They moved out of a page and into a module when /dashboard became
// /me (個人貢獻): a settings card is not the property of whichever page happened
// to hold it first, and the personal page should not have to import from
// another page to show them.

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { useAuth } from "../auth";
import { Button, Spinner } from "../components/ui";
import { LICENSES, LICENSE_LABELS, asLicense } from "../licenses";
import type { License } from "../licenses";

// Opt in to being named wherever the site says who contributed — the
// /contributors board, the annotation list below, each record's history and
// queue line (backend: models.public_name). Off by default, so this lives at the
// top of the Dashboard rather than buried in a settings page — otherwise nobody
// would ever find it and every contribution stays pseudonymous.
export function RankingOptIn() {
  const { t: tr } = useTranslation();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me(), retry: false });
  const toggle = useMutation({
    mutationFn: (v: boolean) => api.updateMe({ show_in_ranking: v }),
    onSuccess: invalidateNamed,
  });
  // The name to be published under. `null` draft = "whatever the server has",
  // so the field fills itself in once /me answers and re-syncs after a save
  // without an effect watching the query.
  const [draft, setDraft] = useState<string | null>(null);
  const saveName = useMutation({
    mutationFn: (v: string) => api.updateMe({ public_display_name: v }),
    onSuccess: () => { setDraft(null); invalidateNamed(); },
  });
  const on = !!me.data?.show_in_ranking;
  const saved = me.data?.public_display_name ?? "";
  const value = draft ?? saved;
  const dirty = value.trim() !== saved;

  function invalidateNamed() {
    qc.invalidateQueries({ queryKey: ["me"] });
    qc.invalidateQueries({ queryKey: ["volunteers"] });
    // Bylines carry the name, so the lists that print them are stale too.
    qc.invalidateQueries({ queryKey: ["annotations"] });
  }

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px", marginBottom: 14,
      background: t.panel, border: `1px solid ${t.border}`, maxWidth: 620,
    }}>
      <input type="checkbox" id="show-in-ranking" checked={on} disabled={me.isLoading || toggle.isPending}
        onChange={(e) => toggle.mutate(e.target.checked)} style={{ marginTop: 2, cursor: "pointer" }} />
      {/* The name field is a sibling of the label, never inside it: a click on
          an input nested in a <label> activates the label's control, so typing
          your name there would toggle the opt-in off. */}
      <div style={{ flex: 1 }}>
        <label htmlFor="show-in-ranking" style={{ cursor: "pointer", display: "block" }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>{tr("vol.optInLabel")}</div>
          <div style={{ fontSize: 11, color: t.fgMuted, marginTop: 2, lineHeight: 1.5 }}>{tr("vol.optInHint")}</div>
        </label>
        {/* Two questions, asked in order: whether to be named, then as what. The
            second only means anything once the first is yes, so it appears with
            it — and the placeholder shows what leaving it blank will publish. */}
        {on && (
          <div style={{ marginTop: 8 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <label htmlFor="public-name" style={{ fontSize: 11, color: t.fgMuted }}>{tr("vol.nameLabel")}</label>
              <input
                id="public-name"
                value={value}
                maxLength={60}
                placeholder={me.data?.display_name ?? ""}
                disabled={saveName.isPending}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && dirty) saveName.mutate(value.trim()); }}
                style={{
                  flex: 1, maxWidth: 260, fontSize: 12, padding: "3px 6px",
                  background: t.bg, color: t.fg, border: `1px solid ${t.border}`,
                  fontFamily: t.sans,
                }}
              />
              <Button small disabled={!dirty || saveName.isPending}
                onClick={() => saveName.mutate(value.trim())}>
                {tr("vol.nameSave")}
              </Button>
            </div>
            <div style={{ fontSize: 11, color: t.fgSubtle, marginTop: 4, lineHeight: 1.5 }}>{tr("vol.nameHint")}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// The licence new annotations start on. A *default*, not a policy: it seeds the
// picker on the record page and nothing more, so changing it here leaves every
// annotation already contributed exactly as it was — relicensing those is done
// per annotation, on the record, by whoever wrote them.
//
// It sits beside the ranking opt-in for the same reason: a standing choice about
// how your own contributions are published belongs somewhere you can find it,
// not re-asked on every record.
export function DefaultLicense() {
  const { t: tr } = useTranslation();
  const qc = useQueryClient();
  const { refreshUser } = useAuth();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me(), retry: false });
  const set = useMutation({
    mutationFn: (v: License) => api.updateMe({ default_license: v }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      // The record page reads this off the auth context, not this query.
      refreshUser();
    },
  });
  const current = asLicense(me.data?.default_license);

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px", marginBottom: 14,
      background: t.panel, border: `1px solid ${t.border}`, maxWidth: 620,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 600 }}>{tr("annotate.licenseDefaultLabel")}</div>
        <div style={{ fontSize: 11, color: t.fgMuted, marginTop: 2, lineHeight: 1.5 }}>
          {tr("annotate.licenseDefaultHint")}
        </div>
      </div>
      <select value={current} disabled={me.isLoading || set.isPending}
        onChange={(e) => set.mutate(e.target.value as License)}
        style={{
          fontSize: 12, fontFamily: t.sans, padding: "4px 6px", background: t.panelAlt,
          border: `1px solid ${t.border}`, cursor: "pointer", flexShrink: 0,
        }}>
        {LICENSES.map((l) => <option key={l} value={l}>{LICENSE_LABELS[l]}</option>)}
      </select>
    </div>
  );
}

// The system-wide AI transcription route, set by an admin for everyone. It used
// to be a switch inside each record's AI panel, which only admins saw and which
// only changed their own next click — so it read as a personal preference when
// what it decides is what the platform does with a contributor's click and who
// pays for it. It lives here instead: one setting, one place, stated as applying
// to all users. The server enforces the same value (`policy.transcribe_route`),
// so this is the decision itself rather than a view of it.
export function TranscribeRoutePolicy() {
  const { t: tr } = useTranslation();
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["transcribe-config"], queryFn: () => api.transcribeConfig() });
  const save = useMutation({
    mutationFn: (route: "queue" | "now") => api.setTranscribeConfig(route),
    // Write the answer straight into the cache the record panel reads, so the
    // AI card is not still offering the old route behind its 10-minute
    // staleTime — the point of the setting is that it takes effect now.
    onSuccess: (next) => qc.setQueryData(["transcribe-config"], next),
  });
  const route = cfg.data?.route ?? "queue";
  const busy = cfg.isLoading || save.isPending;

  return (
    <div style={{
      padding: "8px 10px", marginBottom: 14,
      background: t.panel, border: `1px solid ${t.border}`, maxWidth: 620,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon name="spark" size={12} />
        <div style={{ fontSize: 12, fontWeight: 600, flex: 1 }}>{tr("dash.aiRouteTitle")}</div>
        {(["queue", "now"] as const).map((r) => (
          <Button key={r} small primary={route === r} disabled={busy}
            onClick={() => route !== r && save.mutate(r)}>
            {tr(r === "now" ? "annotate.routeNow" : "annotate.routeQueue")}
          </Button>
        ))}
      </div>
      <div style={{ fontSize: 11, color: t.fgMuted, marginTop: 4, lineHeight: 1.5 }}>
        {tr("dash.aiRouteHint")}
      </div>
      {route === "now" && !save.isPending && (
        <div style={{ fontSize: 11, color: t.warn, marginTop: 4, display: "flex", alignItems: "center", gap: 4 }}>
          <Icon name="alert" size={11} />{tr("dash.aiRouteNowWarn")}
        </div>
      )}
      {save.isPending && <div style={{ fontSize: 11, color: t.fgSubtle, marginTop: 4 }}>{tr("dash.aiRouteSaving")}</div>}
      {save.isError && (
        <div style={{ fontSize: 11, color: t.danger, marginTop: 4 }}>{(save.error as Error).message}</div>
      )}
    </div>
  );
}

function InstitutionRow({ d, isReviewer }: { d: import("../api/types").Dataset; isReviewer: boolean }) {
  const { t: tr } = useTranslation();
  const [result, setResult] = useState<number | null>(null);
  const exportMut = useMutation({
    mutationFn: () => api.exportProvider(d.dataset_name),
    onSuccess: (res) => setResult(res.count),
  });
  const pct = Math.round((d.avg_completeness || 0) * 100);
  return (
    <div style={{ padding: "6px 10px", borderBottom: `1px solid ${t.borderSoft}` }}>
      <div style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={d.dataset_name}>{d.dataset_name}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
        <div style={{ flex: 1, height: 6, background: t.panelAlt, border: `1px solid ${t.borderSoft}` }}>
          <div style={{ width: `${pct}%`, height: "100%", background: t.ok }} />
        </div>
        <span style={{ fontSize: 10, fontFamily: t.mono, color: t.fgMuted, width: 64, textAlign: "right" }}>{pct}% · {d.n_records.toLocaleString()}</span>
        {isReviewer && (
          <Button small onClick={() => exportMut.mutate()} disabled={exportMut.isPending} title={tr("dash.export")}>
            <Icon name="down" size={11} />
          </Button>
        )}
      </div>
      {result != null && <div style={{ fontSize: 10, color: t.accent, marginTop: 2 }}>{result} {tr("dash.exported")}</div>}
    </div>
  );
}


/** Per-dataset completeness, with the reviewer's provider-export button beside
 *  each row. Neither personal nor public: the numbers are open data, but the
 *  control that acts on them is a reviewer's, so the whole panel lives in the
 *  personal page's 管理 section and renders for nobody else.
 */
export function InstitutionPanel({ isReviewer }: { isReviewer: boolean }) {
  const { t: tr } = useTranslation();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: () => api.datasets(40) });
  return (
    <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
      <div style={{
        padding: "6px 10px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`,
        fontSize: 11, fontWeight: 600, textTransform: "uppercase", color: t.fgMuted, letterSpacing: 0.3,
      }}>
        {tr("dash.byInstitution")}
      </div>
      {datasets.isLoading ? <Spinner /> : (
        <div style={{ maxHeight: 460, overflow: "auto" }}>
          {datasets.data?.map((d) => (
            <InstitutionRow key={d.dataset_name} d={d} isReviewer={isReviewer} />
          ))}
        </div>
      )}
    </div>
  );
}

/** The 管理 block: everything on this page that belongs to a role rather than
 *  to the person. Renders nothing for a plain contributor, so the personal page
 *  stays personal for the people it is mostly for. */
export function AdminSection({ role }: { role: string }) {
  const { t: tr } = useTranslation();
  const isReviewer = role === "reviewer" || role === "admin";
  if (!isReviewer) return null;
  return (
    <div style={{ marginTop: 20 }}>
      <h3 style={{
        fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3,
        color: t.fgMuted, margin: "0 0 8px",
      }}>
        {tr("dash.adminTitle")}
      </h3>
      {role === "admin" && <TranscribeRoutePolicy />}
      <InstitutionPanel isReviewer={isReviewer} />
    </div>
  );
}
