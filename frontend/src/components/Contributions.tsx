// One contribution, and one strip of totals — shared by the two pages that show
// a person's work (`/contributors/:id` in public, `/me` in private) so the two
// cannot drift apart. Same reasoning as `contributors.ts` being one function for
// every surface that names somebody.

import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { StatusPill } from "./ui";
import { licenseLabel } from "../licenses";
import { contributorLabel, isAnonymous } from "../contributors";
import type { Contribution } from "../api/types";

/** One annotation, as a row under its record's heading.
 *
 *  It does not name the specimen: the heading above it does, which is the whole
 *  point of grouping. `byline` is off on a single contributor's page — every row
 *  there has the same one — and on for a mixed feed, where it is the point.
 */
function Row({ c, byline }: { c: Contribution; byline?: boolean }) {
  const { t: tr } = useTranslation();
  return (
    <div style={{ padding: "5px 10px 5px 16px", borderBottom: `1px solid ${t.borderSoft}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
        <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted }}>{c.field}</span>
        {c.source !== "manual" && <Icon name="spark" size={10} />}
        <span style={{ flex: 1 }} />
        <StatusPill status={c.status} />
      </div>
      <div style={{ fontSize: 11, marginTop: 1, wordBreak: "break-word" }}>
        <span style={{ color: t.fgSubtle, textDecoration: "line-through" }}>{c.original_value || "∅"}</span>
        {" → "}<span style={{ fontWeight: 600 }}>{c.proposed_value}</span>
      </div>
      <div style={{
        fontSize: 10, color: t.fgSubtle, marginTop: 2,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {byline && (
          <>
            <Link to={`/contributors/${c.contributor_id}`} style={{
              color: t.fgSubtle, textDecoration: "none",
              fontStyle: isAnonymous(c.contributor_name) ? "italic" : "normal",
            }} title={isAnonymous(c.contributor_name) ? tr("vol.anonymousHint") : undefined}>
              {contributorLabel(tr, c.contributor_name, c.contributor_id)}
            </Link>
            {" · "}
          </>
        )}
        {new Date(c.modified).toLocaleDateString()} · {licenseLabel(c.license)}
        {c.dataset_name ? ` · ${c.dataset_name}` : ""}
      </div>
      {c.note && (
        <div style={{
          fontSize: 10, color: t.fgMuted, marginTop: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{c.note}</div>
      )}
    </div>
  );
}

/** Contributions grouped under the specimen each one improved.
 *
 *  The single rendering of "a list of contributions", used by the personal page,
 *  a contributor's public page and the platform's activity feed — so the three
 *  cannot drift into three different ideas of what a contribution looks like.
 */
export function ContributionList({ items, byline, empty }: {
  items: Contribution[];
  /** Name each row's contributor. On for a feed of many, off for one person's. */
  byline?: boolean;
  empty?: string;
}) {
  if (items.length === 0) {
    return <div style={{ padding: 16, fontSize: 12, color: t.fgSubtle }}>{empty ?? "—"}</div>;
  }
  return (
    <>
      {groupByRecord(items).map((g) => (
        <div key={g.id}>
          <RecordHeading rows={g.rows} />
          {g.rows.map((c) => <Row key={c.id} c={c} byline={byline} />)}
        </div>
      ))}
    </>
  );
}

/** Submitted / accepted / records, in the board's own vocabulary so a profile
 *  and the row it was opened from read as the same three numbers. */
export function ContributionStats({ profile }: {
  profile: { n_submitted: number; n_accepted: number; n_records: number; first?: string | null };
}) {
  const { t: tr } = useTranslation();
  return (
    <div style={{ display: "flex", gap: 18, flexWrap: "wrap", margin: "8px 0 14px", fontSize: 11, color: t.fgMuted }}>
      <Stat n={profile.n_accepted} label={tr("vol.accepted")} tone={t.ok} />
      <Stat n={profile.n_submitted} label={tr("vol.submitted")} />
      <Stat n={profile.n_records} label={tr("vol.records")} />
      {profile.first && (
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, fontFamily: t.mono, color: t.fg }}>
            {new Date(profile.first).getFullYear()}
          </div>
          <div>{tr("prof.since")}</div>
        </div>
      )}
    </div>
  );
}

function Stat({ n, label, tone }: { n: number; label: string; tone?: string }) {
  return (
    <div>
      <div style={{ fontSize: 18, fontWeight: 600, fontFamily: t.mono, color: tone || t.fg }}>
        {n.toLocaleString()}
      </div>
      <div>{label}</div>
    </div>
  );
}

/** Offset paging shared by both lists. Renders nothing while everything fits on
 *  one page, so a short list is not framed by dead controls. */
export function Pager({ total, limit, offset, onOffset }: {
  total: number; limit: number; offset: number; onOffset: (n: number) => void;
}) {
  const { t: tr } = useTranslation();
  if (total <= limit) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  const btn = (label: string, to_: number, disabled: boolean) => (
    <button disabled={disabled} onClick={() => onOffset(to_)} style={{
      padding: "2px 8px", fontSize: 11, fontFamily: t.sans,
      border: `1px solid ${t.border}`, background: disabled ? t.panelAlt : t.panel,
      color: disabled ? t.fgSubtle : t.fg, cursor: disabled ? "default" : "pointer",
    }}>{label}</button>
  );
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
      borderTop: `1px solid ${t.borderSoft}`, fontSize: 11, color: t.fgMuted,
    }}>
      <span style={{ fontFamily: t.mono }}>{from}–{to} / {total.toLocaleString()}</span>
      <div style={{ flex: 1 }} />
      {btn(tr("sp.prev"), Math.max(0, offset - limit), offset === 0)}
      {btn(tr("sp.next"), offset + limit, to >= total)}
    </div>
  );
}

/** Annotations bucketed by the specimen they improved, in the order the records
 *  first appear — so a server ordering of "most recently touched first" is
 *  preserved by the record, not scrambled into alphabetical order.
 *
 *  A record is what a person actually worked on: someone fixing a date, a
 *  locality and a coordinate on one sheet did one piece of work, and a flat
 *  list prints it as three unrelated lines. */
export function groupByRecord<T extends Contribution>(items: T[]): { id: string; rows: T[] }[] {
  const order: string[] = [];
  const by = new Map<string, T[]>();
  for (const c of items) {
    const rows = by.get(c.occurrence_id);
    if (rows) rows.push(c);
    else { by.set(c.occurrence_id, [c]); order.push(c.occurrence_id); }
  }
  return order.map((id) => ({ id, rows: by.get(id)! }));
}

/** The specimen heading over one such group, and the way into the record.
 *
 *  It is the only link in the group: the rows beneath carry their own controls
 *  and bylines, and nesting an <a> inside an <a> is invalid HTML — which is
 *  what the flat dashboard list had to do to be clickable at all. */
export function RecordHeading({ rows }: { rows: Contribution[] }) {
  const { t: tr } = useTranslation();
  const first = rows[0];
  const named = !!first.scientific_name;
  return (
    <Link to={`/record/${first.occurrence_id}`} style={{
      display: "flex", alignItems: "baseline", gap: 8, padding: "6px 10px",
      background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`,
      textDecoration: "none", color: t.fg,
    }}>
      <span style={{
        minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        fontSize: 12, fontStyle: named ? "italic" : "normal", color: named ? t.fg : t.fgMuted,
      }}>
        {first.scientific_name || first.catalog_number || first.occurrence_id}
      </span>
      {named && first.catalog_number && (
        <span style={{ fontFamily: t.mono, fontSize: 10, color: t.fgSubtle }}>{first.catalog_number}</span>
      )}
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: 10, color: t.fgSubtle, whiteSpace: "nowrap" }}>
        {tr("dash.nFields", { count: rows.length })}
      </span>
    </Link>
  );
}
