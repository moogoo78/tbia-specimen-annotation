import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t, toneFor } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { emptyFilters, type Dataset, type SourceKind } from "../api/types";

// Landing page: introduces the platform, then offers two card grids that drill
// into Explore pre-faceted — by biological group (生物類群) or by holding
// organization (組織單位). Both navigate to /explore carrying filter state that
// Explore consumes once on arrival.
export function Home() {
  const { t: tr } = useTranslation();
  const nav = useNavigate();

  // Unfiltered counts for the cards (has_media off so totals reflect everything).
  const base = useMemo(() => ({ ...emptyFilters(), has_media: false }), []);
  const facets = useQuery({ queryKey: ["home-facets"], queryFn: () => api.facets(base) });
  const registry = useQuery({ queryKey: ["registry"], queryFn: () => api.registry(), staleTime: Infinity });
  const datasets = useQuery({ queryKey: ["datasets", 1000], queryFn: () => api.datasets(1000) });

  const statsById = useMemo(() => {
    const m = new Map<string, Dataset>();
    for (const d of datasets.data ?? []) if (d.tbia_dataset_id) m.set(d.tbia_dataset_id, d);
    return m;
  }, [datasets.data]);

  const groups = facets.data?.bio_group ?? [];

  const orgs = useMemo(() => {
    if (!registry.data) return [];
    const kinds: SourceKind[] = ["institutions", "aggregators"];
    const out: { kind: SourceKind; code: string; name: string; ids: string[]; records: number }[] = [];
    for (const kind of kinds) {
      for (const [code, ent] of Object.entries(registry.data[kind] || {})) {
        const ids = Object.keys(ent.datasets || {});
        let records = 0;
        for (const id of ids) records += statsById.get(id)?.n_records ?? 0;
        out.push({ kind, code, name: ent.name, ids, records });
      }
    }
    return out.sort((a, b) => b.records - a.records);
  }, [registry.data, statsById]);

  const byGroup = (value: string) => nav("/explore", { state: { bio_group: [value] } });
  const byOrg = (o: { kind: SourceKind; code: string; ids: string[] }) =>
    nav("/explore", { state: { sources: o.ids.map((id) => `${o.kind}:${o.code}/${id}`) } });

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      {/* hero */}
      <div style={{ background: t.panel, borderBottom: `1px solid ${t.border}`, padding: "40px 24px 34px" }}>
        <div style={{ maxWidth: 860, margin: "0 auto" }}>
          <div style={{ fontFamily: t.mono, fontSize: 11, color: t.fgSubtle, letterSpacing: 0.4, textTransform: "uppercase", marginBottom: 10 }}>
            TBIA · {tr("home.tagline")}
          </div>
          <h1 style={{ fontSize: 26, fontWeight: 700, margin: "0 0 12px", lineHeight: 1.25 }}>{tr("app.title")}</h1>
          <p style={{ fontSize: 14, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 20px", maxWidth: 680 }}>{tr("home.blurb")}</p>
          <button onClick={() => nav("/explore")} style={{
            display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 16px",
            background: t.fg, color: t.bg, border: "none", cursor: "pointer",
            fontFamily: t.sans, fontSize: 13, fontWeight: 600,
          }}>
            <Icon name="search" size={13} />{tr("home.startExploring")}<Icon name="caretR" size={11} />
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 24px 40px" }}>
        {/* 生物類群 */}
        <Section title={tr("home.browseByGroup")} icon="grid" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10, marginBottom: 30 }}>
          {groups.map((g) => (
            <button key={g.value} onClick={() => byGroup(g.value)} style={cardStyle}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: toneFor(g.value), flexShrink: 0 }} />
              <span style={{ flex: 1, textAlign: "left", fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.value}</span>
              <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgSubtle }}>{g.count.toLocaleString()}</span>
            </button>
          ))}
          {groups.length === 0 && <Placeholder loading={facets.isLoading} />}
        </div>

        {/* 組織單位 (institutions) */}
        <Section title={tr("home.browseByOrg")} icon="rows" />
        <OrgGrid orgs={orgs.filter((o) => o.kind === "institutions")} onOrg={byOrg} loading={registry.isLoading} tr={tr} />

        {/* 整合平台 (aggregators, e.g. GBIF) */}
        {orgs.some((o) => o.kind === "aggregators") && (
          <div style={{ marginTop: 30 }}>
            <Section title={tr("facet.aggregators")} icon="rows" />
            <OrgGrid orgs={orgs.filter((o) => o.kind === "aggregators")} onOrg={byOrg} loading={registry.isLoading} tr={tr} />
          </div>
        )}
      </div>
    </div>
  );
}

type Org = { kind: SourceKind; code: string; name: string; ids: string[]; records: number };

function OrgGrid({ orgs, onOrg, loading, tr }: {
  orgs: Org[]; onOrg: (o: Org) => void; loading: boolean; tr: (k: string) => string;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
      {orgs.map((o) => (
        <button key={`${o.kind}:${o.code}`} onClick={() => onOrg(o)} style={cardStyle}>
          <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgSubtle, flexShrink: 0 }}>{o.code}</span>
          <span style={{ flex: 1, textAlign: "left", fontSize: 12, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={o.name}>{o.name}</span>
          <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle, flexShrink: 0 }}>
            {o.records > 0 ? `${o.records.toLocaleString()} ${tr("home.records")}` : `${o.ids.length} ${tr("home.datasets")}`}
          </span>
        </button>
      ))}
      {orgs.length === 0 && <Placeholder loading={loading} />}
    </div>
  );
}

function Section({ title, icon }: { title: string; icon: "grid" | "rows" }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 7, margin: "0 0 12px" }}>
      <Icon name={icon} size={14} />
      <h2 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>{title}</h2>
    </div>
  );
}

function Placeholder({ loading }: { loading: boolean }) {
  return <div style={{ gridColumn: "1 / -1", fontSize: 12, color: t.fgSubtle, padding: "8px 0" }}>{loading ? "…" : "—"}</div>;
}

const cardStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "10px 12px",
  background: t.panel, border: `1px solid ${t.border}`, cursor: "pointer",
  fontFamily: t.sans, color: t.fg,
};
