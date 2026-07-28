import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { ANALYTICS_ENABLED, setConsent, useConsent } from "../analytics";

/**
 * Opt-in banner for the Google Analytics cookie. Renders only when a
 * measurement ID was compiled in *and* the visitor hasn't chosen yet, so local
 * dev never sees it. Declining is persisted too — we ask once, not every visit.
 *
 * Portalled to <body> deliberately: #root carries `zoom: 1.15` (see index.html),
 * which rescales the lengths of `position: fixed` descendants and would make a
 * full-width bar overflow the viewport horizontally.
 */
export function CookieConsent() {
  const { t: tr } = useTranslation();
  const consent = useConsent();

  if (!ANALYTICS_ENABLED || consent !== "unset") return null;

  return createPortal(
    <div
      role="dialog"
      aria-live="polite"
      aria-label={tr("consent.title")}
      style={{
        position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 2000,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexWrap: "wrap", gap: 16,
        padding: "12px 20px",
        background: t.panel, borderTop: `1px solid ${t.border}`,
        boxShadow: "0 -2px 12px rgba(0,0,0,0.06)",
        fontFamily: t.sans, color: t.fg,
      }}
    >
      <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: t.fgMuted, maxWidth: 760 }}>
        {tr("consent.text")}
      </p>
      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
        <BannerButton onClick={() => setConsent("denied")}>{tr("consent.decline")}</BannerButton>
        <BannerButton primary onClick={() => setConsent("granted")}>{tr("consent.accept")}</BannerButton>
      </div>
    </div>,
    document.body,
  );
}

// Local copy of the Button styling: ui.tsx's Button is sized for the zoomed #root
// tree, and this banner renders outside it.
function BannerButton({ children, onClick, primary }: {
  children: React.ReactNode; onClick: () => void; primary?: boolean;
}) {
  return (
    <button onClick={onClick} style={{
      border: primary ? "none" : `1px solid ${t.border}`,
      background: primary ? t.fg : t.panel,
      color: primary ? t.bg : t.fg,
      padding: "6px 16px", fontSize: 13, fontFamily: t.sans,
      fontWeight: primary ? 600 : 400,
      cursor: "pointer", borderRadius: 2, whiteSpace: "nowrap",
    }}>{children}</button>
  );
}
