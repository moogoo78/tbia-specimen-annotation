import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { useAuth } from "../auth";
import { Button, Spinner, StatusPill } from "../components/ui";

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
                    {a.contributor_name} · {a.dataset_name}
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
