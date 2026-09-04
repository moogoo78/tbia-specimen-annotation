import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { api } from "../api/client";
import { useAuth } from "../auth";
import { Spinner, StatusPill } from "../components/ui";
import { ContributionList, Pager } from "../components/Contributions";
import { AdminSection, DefaultLicense, RankingOptIn } from "../components/ContributorSettings";

const PAGE = 50;
// Draft last: it is the one status that is not a contribution yet.
const STATUSES = ["submitted", "accepted", "merged", "rejected", "draft"];

// 個人貢獻 — everything about *your own* participation, and nothing about
// anyone else's.
//
// This page and /contributors are one decision made twice: what a person did is
// private-by-default and theirs to manage, what the platform did is public and
// belongs to everybody. The old /dashboard was both at once — your name opt-in
// and your default licence sat above a list of everyone's annotations and a
// table of every institution — so neither question had a page that answered it.
// The public half moved to /contributors; what is left here is yours.
//
// Two things separate it from its public twin at /contributors/:id: drafts are
// here, because they are private working state, and the counts are yours alone.
export function MyContributions() {
  const { t: tr } = useTranslation();
  const { user } = useAuth();
  const [status, setStatus] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const page = useQuery({
    queryKey: ["my-annotations", status, offset],
    queryFn: () => api.myAnnotations({ status: status ?? undefined, limit: PAGE, offset }),
    enabled: !!user,
  });

  if (!user) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: t.fgMuted }}>
        <Link to="/login" style={{ color: t.accent }}>{tr("annotate.loginToAnnotate")} →</Link>
      </div>
    );
  }

  const summary = page.data?.summary ?? {};
  const items = page.data?.items ?? [];
  // A filter change must also reset the page, or picking "accepted" lands you
  // on the third page of a two-page list.
  const pick = (s: string | null) => { setStatus(s); setOffset(0); };

  const tab = (label: string, value: string | null, count: number | undefined) => {
    const on = status === value;
    return (
      <button key={value ?? "all"} onClick={() => pick(value)} style={{
        display: "flex", alignItems: "center", gap: 6, padding: "5px 10px",
        fontFamily: t.sans, cursor: "pointer",
        border: `1px solid ${on ? t.accent : t.border}`,
        background: on ? t.accentSoft : t.panel,
        color: on ? t.fg : t.fgMuted, fontWeight: on ? 600 : 400,
      }}>
        <span style={{ fontSize: 11 }}>{label}</span>
        <span style={{ fontSize: 13, fontFamily: t.mono, fontWeight: 600, color: t.fg }}>
          {(count ?? 0).toLocaleString()}
        </span>
      </button>
    );
  };

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{tr("mine.title")}</h2>
        <div style={{ flex: 1 }} />
        <Link to="/contributors" style={{ fontSize: 11, color: t.accent, textDecoration: "none" }}>
          {tr("mine.viewPublic")} →
        </Link>
      </div>
      <p style={{ fontSize: 11, color: t.fgMuted, margin: "6px 0 14px", maxWidth: 620, lineHeight: 1.6 }}>
        {tr("mine.blurb")}
      </p>

      {/* The standing choices about how your work is published. They live with
          your work rather than in a settings page nobody opens. */}
      <RankingOptIn />
      <DefaultLicense />

      {/* Counts over everything of yours, not over this page. */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {tab(tr("mine.filterAll"), null, summary.total)}
        {STATUSES.filter((s) => summary[s]).map((s) => tab(tr(`status.${s}`), s, summary[s]))}
      </div>

      <div style={{ background: t.panel, border: `1px solid ${t.border}`, maxWidth: 720 }}>
        {page.isLoading ? <Spinner /> : (
          <ContributionList items={items} empty={tr("mine.empty")} />
        )}
        {!page.isLoading && items.length === 0 && status && (
          <div style={{ padding: "0 16px 12px", fontSize: 11, color: t.fgSubtle }}>
            <StatusPill status={status} />
          </div>
        )}
        <Pager total={page.data?.total ?? 0} limit={PAGE} offset={offset} onOffset={setOffset} />
      </div>

      {/* Neither personal nor public: a role's controls. Absent for everyone
          who does not hold the role. */}
      <div style={{ maxWidth: 720 }}>
        <AdminSection role={user.role} />
      </div>
    </div>
  );
}
