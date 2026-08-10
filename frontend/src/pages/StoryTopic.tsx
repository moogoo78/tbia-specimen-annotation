import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { api } from "../api/client";
import type { Story, StoryRegion, StorySpecies, StoryTrip } from "../api/types";
import { Spinner } from "../components/ui";
import { Citation } from "../components/Citation";

// A curated story, rendered from `GET /api/stories/{key}`: the transcription as
// written, with every number in it answered live by the occurrence store.
//
// Two kinds of link leave this page, and both are queries rather than claims:
// a trip opens Explore filtered to the subject collector within the trip's
// dates, and a species opens a name search. A trip that yielded nothing we hold
// shows a plain count with no link, the same rule /history follows.
export function StoryTopic() {
  const { key = "" } = useParams();
  const { t: tr } = useTranslation();
  const story = useQuery({ queryKey: ["story", key], queryFn: () => api.story(key) });

  if (story.isLoading) return <Spinner />;
  if (story.isError || !story.data) {
    return <div style={{ padding: 20, fontSize: 12, color: t.fgSubtle }}>{tr("storyDetail.missing")}</div>;
  }
  const s = story.data;
  const subject = s.subject.collector;

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <Link to="/story" style={{ fontSize: 11, color: t.fgMuted, textDecoration: "none" }}>
        ← {tr("story.title")}
      </Link>

      <h2 style={{ fontSize: 18, fontWeight: 600, margin: "4px 0 0" }}>
        {tr(`story.topics.${s.key}.title`)}
      </h2>
      <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.7, margin: "6px 0 0", maxWidth: 760 }}>
        {tr(`story.topics.${s.key}.blurb`)}
      </p>

      {/* Who the story is about — their career page is the derived counterpart. */}
      <p style={{ fontSize: 12, margin: "8px 0 0" }}>
        <span style={{ color: t.fgSubtle }}>{tr("storyDetail.subject")}: </span>
        {subject ? (
          <Link to={`/collectors/${subject.id}`} style={{ color: t.accent, textDecoration: "none" }}>
            {subject.label}
          </Link>
        ) : (
          <span>{s.subject.name} {s.subject.name_en}</span>
        )}
      </p>

      {s.source.citation && (
        <p style={{ fontSize: 11, color: t.fgSubtle, margin: "6px 0 0", maxWidth: 760, lineHeight: 1.6 }}>
          {tr("hist.source")}: <Citation text={s.source.citation} />
        </p>
      )}

      <Summary story={s} />

      {s.regions.map((r) => <Region key={r.key} region={r} story={s} />)}
    </div>
  );
}

// What the store can say about the story as a whole. The last tile is the point
// of the platform showing up inside the narrative: specimens filed under the
// bare genus are identification gaps waiting on someone.
function Summary({ story }: { story: Story }) {
  const { t: tr } = useTranslation();
  const c = story.subject.collector;
  const { focus, totals } = story;
  const genus = focus.genus ?? "";

  const tiles: { label: string; value: string; to?: object }[] = [
    { label: tr("storyDetail.tripsTile"), value: `${totals.trips} / ${totals.regions}` },
    {
      label: tr("storyDetail.tripRecordsTile"),
      value: totals.trip_records.toLocaleString(),
      to: c ? { collectors: [{ id: c.id, label: c.label }], flags: { has_media: false } } : undefined,
    },
    {
      label: tr("storyDetail.focusTile", { genus }),
      value: focus.records.toLocaleString(),
      to: c ? { collectors: [{ id: c.id, label: c.label }], q: genus, flags: { has_media: false } } : undefined,
    },
    {
      label: tr("storyDetail.genusOnlyTile", { genus }),
      value: focus.genus_only.toLocaleString(),
      to: c ? {
        collectors: [{ id: c.id, label: c.label }], q: genus,
        flags: { missing_identification: true, has_media: false },
      } : undefined,
    },
    { label: tr("storyDetail.speciesTile"), value: `${totals.species_present} / ${totals.species}` },
  ];

  return (
    <div style={{
      display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
      gap: 8, margin: "14px 0 6px", maxWidth: 900,
    }}>
      {tiles.map((tile) => {
        const body = (
          <>
            <div style={{ fontFamily: t.mono, fontSize: 17, fontWeight: 600 }}>{tile.value}</div>
            <div style={{ fontSize: 11, color: t.fgMuted, marginTop: 2, lineHeight: 1.4 }}>{tile.label}</div>
          </>
        );
        const style = {
          display: "block", padding: "10px 12px", background: t.panel,
          border: `1px solid ${t.border}`, textDecoration: "none", color: t.fg,
        } as const;
        return tile.to
          ? <Link key={tile.label} to="/explore" state={tile.to} style={style}>{body}</Link>
          : <div key={tile.label} style={style}>{body}</div>;
      })}
    </div>
  );
}

function Region({ region, story }: { region: StoryRegion; story: Story }) {
  const { t: tr } = useTranslation();
  const n = region.trips.reduce((a, x) => a + x.n_records, 0);
  return (
    <section style={{ marginTop: 22, maxWidth: 900 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, borderBottom: `1px solid ${t.border}`, paddingBottom: 5 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>{region.name}</h3>
        <span style={{ fontSize: 11, color: t.fgSubtle }}>{region.name_en}</span>
        <div style={{ flex: 1 }} />
        {n > 0 && (
          <span style={{ fontFamily: t.mono, fontSize: 11, color: t.fgSubtle }}>
            {tr("storyDetail.records", { n: n.toLocaleString() })}
          </span>
        )}
      </div>

      {region.summary && (
        <p style={{ fontSize: 12, color: t.fgMuted, lineHeight: 1.8, margin: "8px 0 0" }}>{region.summary}</p>
      )}

      {region.trips.map((trip) => <Trip key={trip.seq} trip={trip} story={story} />)}

      {region.species.length > 0 && <SpeciesList region={region} />}
    </section>
  );
}

function Trip({ trip, story }: { trip: StoryTrip; story: Story }) {
  const { t: tr } = useTranslation();
  const c = story.subject.collector;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "132px 1fr", gap: 12, marginTop: 12 }}>
      <div>
        <div style={{ fontFamily: t.mono, fontSize: 12, fontWeight: 600 }}>{trip.verbatim_date}</div>
        {/* The source dates some visits only to the month; the query still runs
            over the whole month, so say which kind of date this is. */}
        {trip.precision === "month" && (
          <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 2 }}>{tr("storyDetail.monthOnly")}</div>
        )}
        {c && trip.n_records > 0 ? (
          <Link
            to="/explore"
            state={{
              collectors: [{ id: c.id, label: c.label }],
              dates: { from: trip.date_start, to: trip.date_end },
              flags: { has_media: false },
            }}
            title={tr("storyDetail.tripHint", { who: c.label, from: trip.date_start, to: trip.date_end })}
            style={{ display: "inline-block", marginTop: 5, fontSize: 11, color: t.accent, textDecoration: "none" }}
          >
            {tr("storyDetail.specimens", { n: trip.n_records.toLocaleString() })} →
          </Link>
        ) : (
          <div style={{ marginTop: 5, fontSize: 11, color: t.fgSubtle }} title={tr("storyDetail.noneHint")}>
            {tr("storyDetail.specimens", { n: 0 })}
          </div>
        )}
      </div>

      <div style={{ minWidth: 0 }}>
        <p style={{ fontSize: 12, lineHeight: 1.8, margin: 0 }}>{trip.narrative}</p>
        {trip.party && trip.party.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
            {trip.party.map((m) => (
              <span key={m.name} style={{
                fontSize: 11, color: t.fgMuted, background: t.panelAlt,
                border: `1px solid ${t.borderSoft}`, padding: "1px 6px",
              }}>{m.name}{m.name_en ? ` ${m.name_en}` : ""}</span>
            ))}
          </div>
        )}
        {trip.notes?.map((note, i) => (
          <p key={i} style={{ fontSize: 11.5, color: t.fgMuted, lineHeight: 1.8, margin: "6px 0 0", paddingLeft: 10, borderLeft: `2px solid ${t.borderSoft}` }}>
            {note.date && <span style={{ fontFamily: t.mono, color: t.fgSubtle, marginRight: 6 }}>{note.date}</span>}
            {note.text}
          </p>
        ))}
      </div>
    </div>
  );
}

function SpeciesList({ region }: { region: StoryRegion }) {
  const { t: tr } = useTranslation();
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: t.fgMuted }}>
        {region.species_heading || tr("storyDetail.species")}
      </div>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))",
        gap: "2px 14px", marginTop: 6,
      }}>
        {region.species.map((sp, i) => <Species key={sp.name || `${region.key}-${i}`} sp={sp} n={i + 1} />)}
      </div>
    </div>
  );
}

// A described species links to a name search only when the store holds it. It
// mostly does not: these were described from Vietnam, Borneo and Luzon, and
// TBIA is a Taiwanese aggregation — the absence is the honest answer.
function Species({ sp, n }: { sp: StorySpecies; n: number }) {
  const { t: tr } = useTranslation();
  const label = (
    <>
      <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle, marginRight: 6 }}>
        {String(n).padStart(2, "0")}
      </span>
      {sp.name && <i>{sp.name}</i>}
      {sp.authorship && <span style={{ color: t.fgSubtle }}> {sp.authorship}</span>}
      {sp.name_zh && <span style={{ marginLeft: 6 }}>{sp.name_zh}</span>}
      {sp.origin && <span style={{ color: t.fgSubtle }}> ({sp.origin})</span>}
    </>
  );
  const style = { fontSize: 11.5, lineHeight: 1.9, display: "block" } as const;
  if (!sp.name || sp.n_records === 0) {
    return <span style={{ ...style, color: t.fgMuted }} title={tr("storyDetail.speciesAbsent")}>{label}</span>;
  }
  return (
    <Link to="/explore" state={{ q: sp.name, flags: { has_media: false } }}
      style={{ ...style, color: t.fg, textDecoration: "none" }}>
      {label}
      <span style={{ color: t.accent, marginLeft: 6 }}>{sp.n_records} →</span>
    </Link>
  );
}
