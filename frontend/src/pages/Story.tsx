import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon, type IconName } from "../design/Icon";
import { api } from "../api/client";

// The narrative layer of the platform: topics that read the collection as a
// story rather than as a result set. The survey-history chronology is the first
// of them and lives on its own route (/history) — this page is the index that
// frames it as one topic among the ones still to be written.
//
// Adding a topic is one entry here plus its own route; `Meta` is optional and
// renders whatever live number that topic can honestly show.
type Topic = {
  key: string;              // i18n prefix under `story.topics`
  path: string;
  icon: IconName;
  Meta?: () => JSX.Element | null;
};

export const STORY_TOPICS: Topic[] = [
  { key: "history", path: "/history", icon: "rows", Meta: HistoryMeta },
  { key: "begonia", path: "/story/begonia", icon: "pin", Meta: BegoniaMeta },
];

export function Story() {
  const { t: tr } = useTranslation();
  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{tr("story.title")}</h2>
      <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "6px 0 0", maxWidth: 760 }}>
        {tr("story.blurb")}
      </p>

      <div style={{ display: "grid", gap: 10, maxWidth: 760, margin: "16px 0 0" }}>
        {STORY_TOPICS.map((topic, i) => (
          <TopicCard key={topic.key} topic={topic} n={i + 1} />
        ))}
      </div>

      <p style={{ fontSize: 11, color: t.fgSubtle, margin: "14px 0 0", maxWidth: 760 }}>
        {tr("story.more")}
      </p>
    </div>
  );
}

function TopicCard({ topic, n }: { topic: Topic; n: number }) {
  const { t: tr } = useTranslation();
  const { Meta } = topic;
  return (
    <Link to={topic.path} style={{
      display: "flex", gap: 12, padding: 14, textDecoration: "none",
      background: t.panel, border: `1px solid ${t.border}`, color: t.fg,
    }}>
      <span style={{
        flexShrink: 0, width: 26, height: 26, display: "flex", alignItems: "center",
        justifyContent: "center", background: t.panelAlt, border: `1px solid ${t.borderSoft}`,
        color: t.fgMuted,
      }}><Icon name={topic.icon} size={14} /></span>

      <span style={{ minWidth: 0 }}>
        <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle }}>
            {String(n).padStart(2, "0")}
          </span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>
            {tr(`story.topics.${topic.key}.title`)}
          </span>
          <span style={{ color: t.accent, fontSize: 11 }}>→</span>
        </span>
        <span style={{ display: "block", fontSize: 12, color: t.fgMuted, lineHeight: 1.7, marginTop: 4 }}>
          {tr(`story.topics.${topic.key}.blurb`)}
        </span>
        {Meta && <Meta />}
      </span>
    </Link>
  );
}

// The curation's own shape, from /api/stories — the index endpoint runs no
// occurrence query, so the card costs nothing the page would not already pay.
function BegoniaMeta() {
  const { t: tr } = useTranslation();
  const stories = useQuery({ queryKey: ["stories"], queryFn: () => api.stories() });
  const s = stories.data?.find((x) => x.key === "begonia");
  if (!s) return null;
  return (
    <span style={{ display: "block", fontFamily: t.mono, fontSize: 11, color: t.fgSubtle, marginTop: 6 }}>
      {tr("story.topics.begonia.meta", { trips: s.n_trips, regions: s.n_regions, species: s.n_species })}
    </span>
  );
}

// The chronology's own numbers, from the queries /history already caches — so
// opening the index warms the page it links to instead of costing an extra
// round trip.
function HistoryMeta() {
  const { t: tr } = useTranslation();
  const events = useQuery({ queryKey: ["sampling-events"], queryFn: () => api.samplingEvents() });
  const counts = useQuery({ queryKey: ["sampling-event-counts"], queryFn: () => api.samplingEventCounts() });

  const rows = events.data;
  if (!rows?.length) return null;
  const withRecords = counts.data
    ? Object.values(counts.data).filter((n) => n > 0).length
    : null;

  return (
    <span style={{ display: "block", fontFamily: t.mono, fontSize: 11, color: t.fgSubtle, marginTop: 6 }}>
      {tr("story.topics.history.meta", {
        n: rows.length,
        from: rows[0].year_start,
        to: Math.max(...rows.map((e) => e.year_end)),
      })}
      {withRecords != null && ` · ${tr("story.topics.history.linked", { n: withRecords })}`}
    </span>
  );
}
