import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t, toneFor } from "../design/tokens";
import { Icon, type IconName } from "../design/Icon";
import { api } from "../api/client";
import { useAuth } from "../auth";
import { emptyFilters, type Dataset, type SourceKind } from "../api/types";
import { exploreUrl } from "./exploreUrl";

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

  const byGroup = (value: string) => nav(exploreUrl({ bio_group: [value] }));
  const byOrg = (o: { kind: SourceKind; code: string; ids: string[] }) =>
    nav(exploreUrl({ sources: o.ids.map((id) => `${o.kind}:${o.code}/${id}`) }));

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
        {/* 開始使用 — the contribution loop, before the browse grids */}
        <GetStarted />

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

        {/* 貢獻者排行 — top 5, linking to the full board */}
        <TopVolunteers />

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

// The four steps of the contribution loop, each one a real link into the app
// rather than a description of one. Step 1 flips to "done" once you're signed
// in, so a returning contributor sees where they already are. The long-form
// version of all four lives on /guide.
function GetStarted() {
  const { t: tr } = useTranslation();
  const { user } = useAuth();
  const nav = useNavigate();

  const steps: { n: number; icon: IconName; key: string; go: () => void }[] = [
    { n: 1, icon: "user", key: "step1", go: () => nav(user ? "/guide#step-1" : "/login") },
    // The manual's own highest-value combination: identifiable from the photo.
    { n: 2, icon: "search", key: "step2", go: () => nav(exploreUrl({ flags: { missing_identification: true, has_media: true } })) },
    { n: 3, icon: "spark", key: "step3", go: () => nav("/guide#step-3") },
    { n: 4, icon: "check", key: "step4", go: () => nav("/dashboard") },
  ];

  return (
    <div style={{ marginBottom: 30 }}>
      <Section title={tr("home.getStarted")} icon="check" />
      <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "-6px 0 12px", maxWidth: 680 }}>
        {tr("home.getStartedBlurb")}
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
        {steps.map((s) => {
          const done = s.n === 1 && !!user;
          return (
            <button key={s.n} onClick={s.go} style={{
              ...cardStyle, flexDirection: "column", alignItems: "stretch", gap: 6, padding: 12,
            }}>
              <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{
                  flexShrink: 0, width: 18, height: 18, display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontFamily: t.mono, color: done ? "#fff" : t.fgMuted,
                  background: done ? t.ok : t.panelAlt, border: `1px solid ${done ? t.ok : t.border}`,
                }}>{done ? <Icon name="check" size={10} stroke={2} /> : s.n}</span>
                <Icon name={s.icon} size={13} />
                <span style={{ flex: 1, textAlign: "left", fontSize: 13, fontWeight: 600 }}>{tr(`guide.${s.key}Title`)}</span>
                <Icon name="caretR" size={11} />
              </span>
              <span style={{ textAlign: "left", fontSize: 11, color: t.fgMuted, lineHeight: 1.6 }}>
                {done ? tr("guide.step1Done") : tr(`guide.${s.key}What`)}
              </span>
            </button>
          );
        })}
      </div>
      <div style={{ marginTop: 8, textAlign: "right" }}>
        <Link to="/guide" style={{ fontSize: 11, color: t.accent, textDecoration: "none" }}>
          {tr("home.viewGuide")} →
        </Link>
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

// Compact top-5 from the public ranking. Same endpoint as /contributors, limit 5.
function TopVolunteers() {
  const { t: tr } = useTranslation();
  const board = useQuery({ queryKey: ["volunteers", "all", 5], queryFn: () => api.volunteers("all", 5) });
  const items = board.data?.items ?? [];
  if (!board.isLoading && items.length === 0) return null;
  return (
    <div style={{ marginTop: 30 }}>
      <Section title={tr("vol.homeTitle")} icon="rows" />
      <div style={{ background: t.panel, border: `1px solid ${t.border}`, maxWidth: 520 }}>
        {items.map((v) => (
          <div key={v.user_id} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "6px 10px",
            borderBottom: `1px solid ${t.borderSoft}`, fontSize: 12,
          }}>
            <span style={{ width: 20, textAlign: "right", fontFamily: t.mono, fontSize: 11, color: t.fgSubtle }}>{v.rank}</span>
            <span style={{
              flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              color: v.anonymous ? t.fgSubtle : t.fg, fontStyle: v.anonymous ? "italic" : "normal",
            }}>
              {v.anonymous ? `${tr("vol.anonymous")} #${v.user_id}` : v.name}
            </span>
            <span style={{ fontFamily: t.mono, fontSize: 11, fontWeight: 600, color: t.ok }}>{v.n_accepted.toLocaleString()}</span>
            <span style={{ fontSize: 10, color: t.fgSubtle }}>{tr("vol.accepted")}</span>
          </div>
        ))}
        <Link to="/contributors" style={{
          display: "block", padding: "6px 10px", fontSize: 11, color: t.accent, textDecoration: "none",
        }}>
          {tr("vol.viewAll")} →
        </Link>
      </div>
    </div>
  );
}

function Section({ title, icon }: { title: string; icon: IconName }) {
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
