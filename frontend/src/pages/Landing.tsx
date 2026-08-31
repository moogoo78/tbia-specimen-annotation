import { useState } from "react";
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
// them. The whole store is still one click away under 進入完整佇列.
//
// Pinned by tbia_dataset_id, not resolved from registry.json by institution +
// dataset code, because NMNS gives two datasets the same code `TNM` — 維管束學門
// and 真菌學門 — so a code lookup would quietly pull in the fungi as well. These
// are curated institution ids, which registry.json pins and an ETL refresh does
// not churn (only the GBIF aggregator ids turn over).
const SOURCES = [
  { kind: "institutions", code: "BRMAS", id: "d691141ff8980195c477f429c" },  // HAST
  { kind: "institutions", code: "NMNS", id: "d674d7dc7c3bd2c006cefad1d" },   // TNM 維管束學門
] as const;

const DATASET_IDS = SOURCES.map((s) => s.id);
/** The same two, in the "kind:CODE/datasetId" form links into Explore carry. */
const SOURCE_KEYS = SOURCES.map((s) => `${s.kind}:${s.code}/${s.id}`);

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
      <div style={{
        flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", padding: "48px 24px 40px", gap: 28,
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
          <Link to="/story" style={{ color: t.fgSubtle, fontSize: 11 }}>{tr("landing.readStories")}</Link>
          {/* Carries the same two sources as the cards, so "the whole queue" is
              the pool they were drawn from rather than a wider one the visitor
              never asked for. Serialised as sources, which Explore expands back
              into dataset ids on arrival — writing both would let them drift. */}
          <Link to={exploreUrl({
            sources: [...SOURCE_KEYS],
            flags: { missing_identification: true, has_media: true },
          })} style={{ color: t.fgSubtle, fontSize: 11 }}>{tr("landing.runQueue")}</Link>
          <Link to="/browse" style={{ color: t.fgSubtle, fontSize: 11 }}>{tr("landing.browseAll")}</Link>
        </div>
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
