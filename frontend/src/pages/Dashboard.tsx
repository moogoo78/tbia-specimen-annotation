import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { useAuth } from "../auth";
import { Button, Spinner, StatusPill } from "../components/ui";
import { LICENSES, LICENSE_LABELS, asLicense, licenseLabel } from "../licenses";
import type { License } from "../licenses";

const STATUSES = ["submitted", "accepted", "rejected", "merged", "draft"];

export function Dashboard() {
  const { t: tr } = useTranslation();
  const { user } = useAuth();
  const [scope, setScope] = useState<"all" | "mine">("all");

  const anns = useQuery({
    queryKey: ["annotations", scope],
    queryFn: () => api.listAnnotations(scope === "mine" ? { mine: "true", limit: "500" } : { limit: "500" }),
    enabled: !!user,
  });
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: () => api.datasets(40) });

  if (!user) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: t.fgMuted }}>
        <Link to="/login" style={{ color: t.accent }}>{tr("annotate.loginToAnnotate")} →</Link>
      </div>
    );
  }

  const items = anns.data?.items ?? [];
  const byStatus = STATUSES.map((s) => ({ status: s, count: items.filter((a) => a.status === s).length }));
  const isReviewer = user.role === "reviewer" || user.role === "admin";

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 12px" }}>{tr("dash.title")}</h2>

      <RankingOptIn />
      <DefaultLicense />
      {user.role === "admin" && <TranscribeRoutePolicy />}

      {/* status summary */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {byStatus.map((s) => (
          <div key={s.status} style={{ background: t.panel, border: `1px solid ${t.border}`, padding: "8px 14px", minWidth: 110 }}>
            <div style={{ fontSize: 22, fontWeight: 600, fontFamily: t.mono }}>{s.count}</div>
            <StatusPill status={s.status} />
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16 }}>
        {/* annotation list */}
        <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}` }}>
            <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", color: t.fgMuted, letterSpacing: 0.3 }}>{tr("detail.annotations")}</span>
            <div style={{ flex: 1 }} />
            <Button small primary={scope === "all"} onClick={() => setScope("all")}>{tr("dash.all")}</Button>
            <Button small primary={scope === "mine"} onClick={() => setScope("mine")}>{tr("dash.mine")}</Button>
          </div>
          {anns.isLoading ? <Spinner /> : (
            <div style={{ maxHeight: 460, overflow: "auto" }}>
              {items.length === 0 && <div style={{ padding: 16, color: t.fgSubtle, fontSize: 12 }}>—</div>}
              {items.map((a) => (
                <Link key={a.id} to={`/record/${a.occurrence_id}`} style={{
                  display: "block", padding: "6px 10px", borderBottom: `1px solid ${t.borderSoft}`,
                  textDecoration: "none", color: t.fg,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                    <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted }}>{a.field}</span>
                    {a.source === "ai" && <Icon name="spark" size={10} />}
                    <span style={{ flex: 1 }} />
                    <StatusPill status={a.status} />
                  </div>
                  <div style={{ fontSize: 11, marginTop: 1 }}>
                    <span style={{ color: t.fgSubtle, textDecoration: "line-through" }}>{a.original_value || "∅"}</span>
                    {" → "}<span style={{ fontWeight: 600 }}>{a.proposed_value}</span>
                  </div>
                  <div style={{ fontSize: 10, color: t.fgSubtle, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {a.contributor_name} · {licenseLabel(a.license)} · {a.dataset_name}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* institutions + export */}
        <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
          <div style={{ padding: "6px 10px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`, fontSize: 11, fontWeight: 600, textTransform: "uppercase", color: t.fgMuted, letterSpacing: 0.3 }}>
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
      </div>
    </div>
  );
}

// Opt in to being named on the public /contributors board. Off by default, so
// this lives at the top of the Dashboard rather than buried in a settings page —
// otherwise nobody would ever find it and the board stays all-pseudonyms.
function RankingOptIn() {
  const { t: tr } = useTranslation();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me(), retry: false });
  const toggle = useMutation({
    mutationFn: (v: boolean) => api.updateMe({ show_in_ranking: v }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["volunteers"] });
    },
  });
  const on = !!me.data?.show_in_ranking;

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px", marginBottom: 14,
      background: t.panel, border: `1px solid ${t.border}`, maxWidth: 620,
    }}>
      <input type="checkbox" id="show-in-ranking" checked={on} disabled={me.isLoading || toggle.isPending}
        onChange={(e) => toggle.mutate(e.target.checked)} style={{ marginTop: 2, cursor: "pointer" }} />
      <label htmlFor="show-in-ranking" style={{ cursor: "pointer", flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 600 }}>{tr("vol.optInLabel")}</div>
        <div style={{ fontSize: 11, color: t.fgMuted, marginTop: 2, lineHeight: 1.5 }}>{tr("vol.optInHint")}</div>
      </label>
      <Link to="/contributors" style={{ fontSize: 11, color: t.accent, textDecoration: "none", flexShrink: 0 }}>
        {tr("vol.viewAll")}
      </Link>
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
function DefaultLicense() {
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
function TranscribeRoutePolicy() {
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
