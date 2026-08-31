import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { GroupTag, TypeTag } from "../components/ui";
import { emptyFilters, type Filters, type OccurrenceRow } from "../api/types";
import { exploreUrl } from "./exploreUrl";

// Landing — the "just do it" entry screen.
//
// The hub that used to live here (browse by group, by organization, the
// contribution loop, the top of the board) moved to /browse as `Browse.tsx`;
// nothing was dropped, and the "browse everything" link below is the way back
// to it. What replaced it is a single decision: three records that each need
// one concrete thing, drawn fresh on every visit.
//
// One card per *gap*, not three from a mixed pool. The three completeness flags
// AND together in `build_where`, so "any gap" is not expressible as one filter
// anyway — and drawing per gap is the better page regardless: every card can
// name the one action it wants, which is the whole point of the screen. Each
// draw also asks for `has_media`, because all three tasks are done by reading
// the specimen's own image.
const GAPS = [
  { key: "identification", flags: { missing_identification: true } },
  { key: "coordinates", flags: { missing_coordinates: true } },
  { key: "date", flags: { missing_date: true } },
] as const;

// The queue draws from two herbaria rather than all 945 datasets: HAST and the
// NMNS vascular-plant collection, 405,009 records between them, every one a
// pressed sheet whose determination slip and locality label are legible in the
// image we already have. That is what makes the three tasks *doable* from the
// card — an unidentified insect drawer photo or a GBIF row with no sheet is a
// dead end for a first-time visitor, and offering one is how the page loses
// them. The whole store stays a click away through the figures in the
// introduction below, each of which opens the records it counts.
//
// Pinned by tbia_dataset_id, and deliberately nothing else: resolving these
// from registry.json by institution + dataset code would quietly pull in the
// fungi, because NMNS gives two of its datasets the same code `TNM` — 維管束學門
// and 真菌學門. Ids rather than codes is the whole point, so ids are all this
// holds. They are curated institution ids, which registry.json pins and an ETL
// refresh does not churn (only the GBIF aggregator ids turn over).
const DATASET_IDS = [
  "d691141ff8980195c477f429c",  // BRMAS — HAST, 中央研究院生物多樣性中心植物標本館
  "d674d7dc7c3bd2c006cefad1d",  // NMNS  — TNM 維管束學門
];

type Gap = (typeof GAPS)[number]["key"];

/** One drawn record plus the gap it was drawn for — the card names that gap's
 *  task, so a record with several gaps still asks for exactly one thing. */
interface Draw {
  gap: Gap;
  /** How many records share this task, i.e. the pool the row came from. */
  pool: number;
  row: OccurrenceRow | null;
}

const filtersFor = (gap: (typeof GAPS)[number]): Filters => ({
  ...emptyFilters(),
  has_media: true,
  tbia_dataset_id: [...DATASET_IDS],
  ...gap.flags,
});

export function Landing() {
  const { t: tr } = useTranslation();
  const [hover, setHover] = useState<string | null>(null);

  // One query over all three draws: one loading state, and one refetch behind
  // "draw three others". The endpoint is uncached on both ends (the server
  // leaves it `private, no-store`), so a refetch is genuinely a new sample.
  const draw = useQuery({
    queryKey: ["landing-queue"],
    queryFn: async (): Promise<Draw[]> =>
      Promise.all(
        GAPS.map(async (gap) => {
          const res = await api.queue(filtersFor(gap), 1);
          return { gap: gap.key, pool: res.total, row: res.items[0] ?? null };
        }),
      ),
    // A draw is a moment, not a fact about the store — never serve a stale one.
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });

  const draws = (draw.data ?? []).filter((d) => d.row);

  return (
    <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
      {/* Top-aligned rather than centred in the viewport. Centring left ~130px
          of dead space above the eyebrow, which pushed the introduction below
          the fold on a laptop screen — and an introduction nobody scrolls to is
          one we did not write. This lets its top edge show. */}
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        padding: "44px 24px 36px", gap: 26,
      }}>
        <div style={{ textAlign: "center", maxWidth: 560 }}>
          <div style={{
            fontSize: 11, fontFamily: t.mono, color: t.fgSubtle, letterSpacing: 1.2,
            textTransform: "uppercase", marginBottom: 10,
          }}>
            {tr("landing.eyebrow")}
          </div>
          {/* Counted from what was actually drawn, so an empty gap pool cannot
              leave the headline promising a card that is not on screen. Before
              the draw lands it states the intent, which is what arrives. */}
          <h1 style={{ fontSize: 30, fontWeight: 500, margin: "0 0 8px", letterSpacing: -0.6, lineHeight: 1.15 }}>
            {tr("landing.headline", { n: draw.data ? draws.length : GAPS.length })}
          </h1>
          <p style={{ fontSize: 13, color: t.fgMuted, margin: 0, lineHeight: 1.6 }}>
            {tr("landing.blurb")}
          </p>
        </div>

        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 268px))",
          gap: 14, justifyContent: "center", width: "100%", maxWidth: 852,
        }}>
          {draws.map((d) => (
            <QueueCard key={d.row!.id} draw={d} hover={hover === d.row!.id}
              onHover={(on) => setHover(on ? d.row!.id : null)} />
          ))}
          {draw.isLoading && GAPS.map((g) => <CardSkeleton key={g.key} />)}
          {!draw.isLoading && draws.length === 0 && (
            <div style={{ gridColumn: "1 / -1", textAlign: "center", fontSize: 12, color: t.fgSubtle }}>
              {draw.isError ? tr("landing.drawFailed") : tr("landing.drawEmpty")}
            </div>
          )}
        </div>

        {/* The escape hatches, deliberately quiet — including the one back to
            the old landing page, which is now /browse. */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 11, flexWrap: "wrap", justifyContent: "center" }}>
          <button onClick={() => draw.refetch()} disabled={draw.isFetching} style={{
            display: "inline-flex", alignItems: "center", gap: 5, border: `1px solid ${t.border}`,
            background: t.panel, padding: "5px 10px", fontFamily: t.sans, fontSize: 11,
            color: t.fgMuted, cursor: draw.isFetching ? "default" : "pointer",
            opacity: draw.isFetching ? 0.6 : 1,
          }}>
            <Icon name="refresh" size={11} />{tr("landing.drawAgain")}
          </button>
          {/* The navbar is hidden on this route, and it was the only way to the
              guide. It belongs first among the links regardless: "how do I
              actually do this?" is the question the three cards provoke and
              cannot answer themselves. Reuses nav.guide rather than adding a
              second key for the same word. */}
          <Link to="/guide" style={{ color: t.fgSubtle, fontSize: 11 }}>{tr("nav.guide")}</Link>
          <Link to="/story" style={{ color: t.fgSubtle, fontSize: 11 }}>{tr("landing.readStories")}</Link>
          <Link to="/browse" style={{ color: t.fgSubtle, fontSize: 11 }}>{tr("landing.browseAll")}</Link>
        </div>
      </div>

      <Intro />
    </div>
  );
}

// What the page is, under what it asks you to do.
//
// The queue answers "what should I do"; until now nothing on `/` answered "what
// is this and why does it matter" — which the hub that used to live here did,
// and which a public front door needs, since this is the page that gets crawled,
// indexed and unfurled into chat. The shape follows DiSSCover's landing page
// (disscover.dissco.eu), the initiative this platform's own TDWG abstract names
// as its reference: the scale first, then the ask. The prose is condensed from
// `tdwg-2026-abstract.md`, so the site and the abstract say the same thing.
function Intro() {
  const { t: tr } = useTranslation();

  // The same query Browse runs, deliberately under the same key so moving
  // between / and /browse pays for this rollup once. It scans ~2M rows, but the
  // route is in cache.STATIC_ROUTES and edge-cached for an hour.
  const base = useMemo(() => ({ ...emptyFilters(), has_media: false }), []);
  const facets = useQuery({ queryKey: ["home-facets"], queryFn: () => api.facets(base) });
  const c = facets.data?.completeness;

  // Every figure links to the records behind it. `has_media: false` is stated on
  // each one because exploreUrl() starts from emptyFilters(), whose has_media is
  // true — without it the landing page would quote a number Explore then fails
  // to reproduce.
  const stats: { n?: number; label: string; to: string }[] = [
    { n: c?.total, label: "statRecords", to: exploreUrl({ flags: { has_media: false } }) },
    { n: c?.missing_identification, label: "statNoId", to: exploreUrl({ flags: { missing_identification: true, has_media: false } }) },
    { n: c?.missing_coordinates, label: "statNoGeo", to: exploreUrl({ flags: { missing_coordinates: true, has_media: false } }) },
    { n: c?.missing_date, label: "statNoDate", to: exploreUrl({ flags: { missing_date: true, has_media: false } }) },
  ];

  return (
    <div style={{ background: t.panel, borderTop: `1px solid ${t.border}`, padding: "30px 24px 40px" }}>
      <div style={{ maxWidth: 860, margin: "0 auto" }}>
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 12, marginBottom: 28,
        }}>
          {stats.map((s) => (
            <Link key={s.label} to={s.to} style={{
              display: "flex", flexDirection: "column", gap: 3, textDecoration: "none",
              color: "inherit", padding: "8px 10px", background: t.panelAlt,
              border: `1px solid ${t.borderSoft}`,
            }}>
              <span style={{ fontFamily: t.mono, fontSize: 19, fontWeight: 600, letterSpacing: -0.3 }}>
                {s.n == null ? "—" : s.n.toLocaleString()}
              </span>
              <span style={{ fontSize: 11, color: t.fgSubtle, lineHeight: 1.4 }}>
                {tr(`landing.intro.${s.label}`)}
              </span>
            </Link>
          ))}
        </div>

        <h2 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 10px" }}>{tr("landing.intro.title")}</h2>
        <p style={{ fontSize: 13, color: t.fgMuted, lineHeight: 1.75, margin: "0 0 12px" }}>
          {tr("landing.intro.p1")}
        </p>
        <p style={{ fontSize: 13, color: t.fgMuted, lineHeight: 1.75, margin: "0 0 14px" }}>
          {tr("landing.intro.p2")}
        </p>
        <Link to="/guide" style={{ fontSize: 12, color: t.accent, textDecoration: "none" }}>
          {tr("home.viewGuide")} →
        </Link>
      </div>
    </div>
  );
}

function QueueCard({ draw, hover, onHover }: {
  draw: Draw; hover: boolean; onHover: (on: boolean) => void;
}) {
  const { t: tr } = useTranslation();
  const r = draw.row!;
  return (
    <Link to={`/record/${r.id}`}
      onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}
      style={{
        display: "flex", flexDirection: "column", textDecoration: "none", color: "inherit",
        background: t.panel, border: `1px solid ${hover ? t.accent : t.border}`,
        boxShadow: hover ? "0 4px 16px rgba(0,0,0,.10)" : "0 1px 2px rgba(0,0,0,.04)",
        transform: hover ? "translateY(-2px)" : "none", transition: "all .14s",
      }}>
      <div style={{
        aspectRatio: "4 / 3", position: "relative", overflow: "hidden",
        borderBottom: `1px solid ${t.borderSoft}`,
        background: `repeating-linear-gradient(45deg, ${t.panelAlt} 0 8px, ${t.borderSoft} 8px 9px)`,
      }}>
        {r.thumbnail && (
          <img src={r.thumbnail} alt="" loading="lazy"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
        )}
        {/* Guarded rather than passed straight through: GroupTag's empty state
            is an em dash, which reads as a value in a table cell but as a stray
            mark floating on a photo. Absent here means no badge. */}
        <div style={{ position: "absolute", top: 6, left: 6, display: "flex", gap: 4, alignItems: "center" }}>
          {r.bio_group && <GroupTag group={r.bio_group} />}
          <TypeTag value={r.type_status} filled />
        </div>
      </div>

      <div style={{ padding: "10px 12px 12px", display: "flex", flexDirection: "column", gap: 5, flex: 1 }}>
        {/* Who holds it, above its number — the two together are the specimen's
            provenance, and the card asks a stranger to work on a real object in
            a real cabinet. The code is a chip because it is short and scannable;
            the name runs to 15 CJK characters, so it takes the rest of the row
            and truncates, with the full string on hover. */}
        <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
          {r.institution_code && (
            <span style={{
              flexShrink: 0, fontFamily: t.mono, fontSize: 9, fontWeight: 700, letterSpacing: 0.3,
              color: t.fgMuted, background: t.panelAlt, border: `1px solid ${t.borderSoft}`,
              padding: "1px 4px", borderRadius: 2,
            }}>{r.institution_code}</span>
          )}
          {r.institution_name && (
            <span title={r.institution_name} style={{
              flex: 1, minWidth: 0, fontSize: 10, color: t.fgSubtle,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{r.institution_name}</span>
          )}
        </div>
        <div style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {r.catalog_number || "—"}
        </div>
        <div style={{ fontSize: 15, lineHeight: 1.2 }}>
          {/* The identification queue draws rows that have no name yet — say so
              rather than printing an em dash where a binomial goes. */}
          {r.scientific_name ? (
            <>
              <i style={{ fontWeight: 500 }}>{r.scientific_name}</i>
              {r.name_author && <span style={{ color: t.fgMuted, fontSize: 11 }}> {r.name_author}</span>}
            </>
          ) : (
            <span style={{ color: t.fgSubtle, fontStyle: "italic" }}>{tr("landing.unnamed")}</span>
          )}
        </div>
        <div style={{ fontSize: 11, color: t.fgMuted, lineHeight: 1.35 }}>
          {[r.locality, r.county].filter(Boolean).join(", ") || "—"}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{
          display: "flex", alignItems: "center", gap: 6, marginTop: 6, paddingTop: 8,
          borderTop: `1px solid ${t.borderSoft}`,
          fontSize: 11, fontWeight: 600, color: hover ? t.accent : t.fgMuted,
        }}>
          <span>{tr(`landing.task.${draw.gap}`)}</span>
          <span style={{ marginLeft: "auto", fontFamily: t.mono, fontWeight: 400, color: t.fgSubtle }}
            title={tr("landing.poolTitle")}>
            {tr("landing.waiting", { n: draw.pool.toLocaleString() })}
          </span>
          <Icon name="caretR" size={11} />
        </div>
      </div>
    </Link>
  );
}

function CardSkeleton() {
  return (
    <div style={{ background: t.panel, border: `1px solid ${t.border}` }}>
      <div style={{
        aspectRatio: "4 / 3", borderBottom: `1px solid ${t.borderSoft}`,
        background: `repeating-linear-gradient(45deg, ${t.panelAlt} 0 8px, ${t.borderSoft} 8px 9px)`,
      }} />
      <div style={{ padding: "10px 12px 12px", height: 96 }} />
    </div>
  );
}
