import { t, toneFor } from "../design/tokens";
import { Icon } from "../design/Icon";
import { useTranslation } from "react-i18next";

export function GroupTag({ group }: { group?: string | null }) {
  if (!group) return <span style={{ color: t.fgSubtle }}>—</span>;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, fontWeight: 600,
      color: "#fff", background: toneFor(group), padding: "1px 5px", borderRadius: 2,
    }}>{group}</span>
  );
}

const STATUS_TONE: Record<string, string> = {
  draft: t.fgMuted, submitted: t.warn, accepted: t.ok, rejected: t.danger, merged: t.accent,
};

export function StatusPill({ status }: { status: string }) {
  const { t: tr } = useTranslation();
  const c = STATUS_TONE[status] || t.fgMuted;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, color: t.fg }}>
      <span style={{ width: 6, height: 6, borderRadius: 3, background: c }} />
      {tr(`status.${status}`)}
    </span>
  );
}

// Four dots: identification / coordinates / date / media.
export function CompletenessDots({ row, size = 7 }: {
  row: { has_identification: boolean; has_coordinates: boolean; has_date: boolean; has_media: boolean };
  size?: number;
}) {
  const flags: [boolean, string][] = [
    [row.has_identification, t.ok],
    [row.has_coordinates, t.accent],
    [row.has_date, t.warn],
    [row.has_media, "oklch(0.6 0.08 320)"],
  ];
  return (
    <span style={{ display: "inline-flex", gap: 3, alignItems: "center" }}>
      {flags.map(([on, c], i) => (
        <span key={i} title={["id", "geo", "date", "media"][i]} style={{
          width: size, height: size, borderRadius: 1,
          background: on ? c : "transparent",
          border: `1px solid ${on ? c : t.border}`,
        }} />
      ))}
    </span>
  );
}

export function Button({ children, onClick, primary, danger, small, disabled, title }: {
  children: React.ReactNode; onClick?: () => void; primary?: boolean; danger?: boolean;
  small?: boolean; disabled?: boolean; title?: string;
}) {
  return (
    <button onClick={onClick} disabled={disabled} title={title} style={{
      border: primary ? "none" : `1px solid ${t.border}`,
      background: disabled ? t.panelAlt : primary ? t.fg : t.panel,
      color: disabled ? t.fgSubtle : danger ? t.danger : primary ? t.bg : t.fg,
      padding: small ? "2px 8px" : "4px 12px", fontSize: small ? 11 : 12,
      fontFamily: t.sans, cursor: disabled ? "not-allowed" : "pointer", borderRadius: 2,
      fontWeight: primary ? 600 : 400, display: "inline-flex", alignItems: "center", gap: 5,
    }}>{children}</button>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div style={{ padding: 24, color: t.fgSubtle, fontSize: 12, display: "flex", gap: 8, alignItems: "center" }}>
      <Icon name="cog" size={14} />{label || "Loading…"}
    </div>
  );
}
