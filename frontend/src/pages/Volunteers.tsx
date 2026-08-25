import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api, getToken } from "../api/client";
import type { VolunteerRange } from "../api/types";
import { Spinner } from "../components/ui";
import { contributorLabel } from "../contributors";

// Public leaderboard. Ranked on accepted work, with submitted and distinct
// records alongside so the table shows each volunteer's real shape. Names are
// opt-in (users.show_in_ranking) — everyone else is "Unnamed contributor #<id>" —
// and a volunteer who set a public name is listed under that, not their ORCID one.
export function Volunteers() {
  const { t: tr } = useTranslation();
  const [range, setRange] = useState<VolunteerRange>("all");
  const board = useQuery({
    queryKey: ["volunteers", range],
    queryFn: () => api.volunteers(range, 100),
  });
  // Only to highlight your own row / nudge you to opt in; the board itself is public.
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me(), enabled: !!getToken(), retry: false });

  const items = board.data?.items ?? [];
  const mine = items.find((v) => v.user_id === me.data?.id);

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "0 0 12px" }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{tr("vol.title")}</h2>
        <div style={{ flex: 1 }} />
        {(["all", "month"] as VolunteerRange[]).map((r) => (
          <button key={r} onClick={() => setRange(r)} style={{
            padding: "3px 10px", fontSize: 11, fontFamily: t.sans, cursor: "pointer",
            border: `1px solid ${range === r ? t.accent : t.border}`,
            background: range === r ? t.accentSoft : t.panel,
            color: range === r ? t.fg : t.fgMuted, fontWeight: range === r ? 600 : 400,
          }}>
            {tr(r === "all" ? "vol.rangeAll" : "vol.rangeMonth")}
          </button>
        ))}
      </div>

      <p style={{ fontSize: 11, color: t.fgMuted, margin: "0 0 12px", maxWidth: 620, lineHeight: 1.6 }}>
        {tr("vol.blurb")}
      </p>

      {/* Your own standing — only when signed in and you haven't opted in yet. */}
      {mine?.anonymous && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", marginBottom: 10,
          background: t.accentSoft, border: `1px solid ${t.border}`, fontSize: 11, color: t.fgMuted,
        }}>
          <Icon name="user" size={12} />
          <span>{tr("vol.youAreAnonymous")}</span>
        </div>
      )}

      {board.isLoading ? <Spinner /> : items.length === 0 ? (
        <div style={{ padding: 20, fontSize: 12, color: t.fgSubtle }}>{tr("vol.empty")}</div>
      ) : (
        <div style={{ background: t.panel, border: `1px solid ${t.border}`, maxWidth: 720 }}>
          <Row header />
          {items.map((v) => (
            <Row key={v.user_id} v={v} isMe={v.user_id === me.data?.id} />
          ))}
        </div>
      )}
    </div>
  );
}

const cells: React.CSSProperties[] = [
  { width: 40, textAlign: "right", fontFamily: t.mono, color: t.fgSubtle, flexShrink: 0 },
  { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  { width: 80, textAlign: "right", fontFamily: t.mono, flexShrink: 0 },
  { width: 80, textAlign: "right", fontFamily: t.mono, flexShrink: 0 },
  { width: 80, textAlign: "right", fontFamily: t.mono, flexShrink: 0 },
];

function Row({ v, header, isMe }: {
  v?: import("../api/types").Volunteer; header?: boolean; isMe?: boolean;
}) {
  const { t: tr } = useTranslation();
  const base: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 10, padding: "6px 10px",
    borderBottom: `1px solid ${t.borderSoft}`, fontSize: 12,
  };
  if (header) {
    return (
      <div style={{
        ...base, background: t.panelAlt, fontSize: 10, fontWeight: 600,
        textTransform: "uppercase", letterSpacing: 0.3, color: t.fgMuted,
      }}>
        <span style={cells[0]}>{tr("vol.rank")}</span>
        <span style={cells[1]}>{tr("vol.volunteer")}</span>
        <span style={cells[2]}>{tr("vol.accepted")}</span>
        <span style={cells[3]}>{tr("vol.submitted")}</span>
        <span style={cells[4]}>{tr("vol.records")}</span>
      </div>
    );
  }
  if (!v) return null;
  return (
    <div style={{ ...base, background: isMe ? t.accentSoft : "transparent" }}>
      <span style={cells[0]}>{v.rank}</span>
      <span style={{ ...cells[1], color: v.anonymous ? t.fgSubtle : t.fg, fontStyle: v.anonymous ? "italic" : "normal" }}
        title={v.anonymous ? tr("vol.anonymousHint") : undefined}>
        {contributorLabel(tr, v.name, v.user_id)}
      </span>
      <span style={{ ...cells[2], fontWeight: 600, color: t.ok }}>{v.n_accepted.toLocaleString()}</span>
      <span style={{ ...cells[3], color: t.fgMuted }}>{v.n_submitted.toLocaleString()}</span>
      <span style={{ ...cells[4], color: t.fgMuted }}>{v.n_records.toLocaleString()}</span>
    </div>
  );
}
