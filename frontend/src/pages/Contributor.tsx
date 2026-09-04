import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { api } from "../api/client";
import { Spinner } from "../components/ui";
import { ContributionList, ContributionStats, Pager } from "../components/Contributions";
import { contributorLabel, isAnonymous } from "../contributors";

const PAGE = 50;

// One contributor's work in public — what a byline in a record's annotation
// history and a row on the ranking board open into.
//
// It publishes nothing new. Every annotation listed here is already on its own
// record page, and /api/volunteers already carries the counts; this only puts
// them in one place, which is what turns a number on a leaderboard into
// something a person can actually look at. A contributor who has not opted in to
// being named appears as "Unnamed contributor #<id>", with no name and no ORCID
// iD — the same rule every other surface applies (models.public_name).
export function Contributor() {
  const { t: tr } = useTranslation();
  const { id } = useParams();
  const uid = Number(id);
  const [offset, setOffset] = useState(0);

  const profile = useQuery({
    queryKey: ["contributor", uid],
    queryFn: () => api.contributor(uid),
    enabled: Number.isFinite(uid),
    retry: false,
  });
  const page = useQuery({
    queryKey: ["contributor-annotations", uid, offset],
    queryFn: () => api.contributorAnnotations(uid, { limit: PAGE, offset }),
    enabled: Number.isFinite(uid) && profile.isSuccess,
  });

  if (profile.isLoading) return <Spinner />;
  if (profile.isError || !profile.data) {
    return <div style={{ padding: 20, color: t.fgSubtle, fontSize: 12 }}>{tr("prof.notFound")}</div>;
  }

  const p = profile.data;
  const anon = isAnonymous(p.name);
  const items = page.data?.items ?? [];

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h2 style={{
          fontSize: 18, fontWeight: 600, margin: 0,
          color: anon ? t.fgMuted : t.fg, fontStyle: anon ? "italic" : "normal",
        }} title={anon ? tr("vol.anonymousHint") : undefined}>
          {contributorLabel(tr, p.name, p.user_id)}
        </h2>
        <div style={{ flex: 1 }} />
        {/* Only ever present when the name is: the iD is an identity, so it
            travels with the name or not at all. */}
        {p.orcid && (
          <a href={`https://orcid.org/${p.orcid}`} target="_blank" rel="noreferrer"
            style={{ fontSize: 11, fontFamily: t.mono, color: t.accent, textDecoration: "none" }}>
            {tr("prof.orcid")} {p.orcid}
          </a>
        )}
      </div>

      {anon && (
        <div style={{ fontSize: 11, color: t.fgSubtle, marginTop: 4, maxWidth: 620, lineHeight: 1.6 }}>
          {tr("prof.anonymousBlurb")}
        </div>
      )}

      <ContributionStats profile={p} />

      <div style={{ background: t.panel, border: `1px solid ${t.border}`, maxWidth: 720 }}>
        <div style={{
          padding: "6px 10px", background: t.panelAlt, borderBottom: `1px solid ${t.borderSoft}`,
          fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3, color: t.fgMuted,
        }}>
          {tr("prof.contributions")}
        </div>
        {/* Grouped by specimen, and with no byline: every row here belongs to
            the one contributor this page is about. */}
        {page.isLoading ? <Spinner />
          : <ContributionList items={items} empty={tr("vol.empty")} />}
        <Pager total={page.data?.total ?? 0} limit={PAGE} offset={offset} onOffset={setOffset} />
      </div>
    </div>
  );
}
