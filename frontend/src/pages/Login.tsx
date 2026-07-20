import { useState } from "react";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { useAuth } from "../auth";

// ORCID brand mark (green circle + "iD"), inlined so it works offline.
function OrcidMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 256 256" aria-hidden="true">
      <circle cx="128" cy="128" r="128" fill="#A6CE39" />
      <g fill="#fff">
        <path d="M86 186h-20V79h20v107z" />
        <path d="M108 79h41c39 0 56 28 56 54 0 28-22 53-56 53h-41V79zm20 89h19c27 0 33-20 33-35 0-24-15-36-34-36h-18v71z" />
        <circle cx="76" cy="55" r="13" />
      </g>
    </svg>
  );
}

export function Login() {
  const { t: tr } = useTranslation();
  const { startOrcidLogin } = useAuth();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const signIn = async () => {
    setError("");
    setBusy(true);
    try {
      await startOrcidLogin(); // redirects away on success
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setBusy(false);
    }
  };

  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: t.bg }}>
      <div style={{ width: 340, background: t.panel, border: `1px solid ${t.border}`, padding: 24 }}>
        <h2 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 600 }}>{tr("login.title")}</h2>
        <p style={{ margin: "0 0 20px", fontSize: 12, color: t.fgMuted, lineHeight: 1.5 }}>
          {tr("login.orcidBlurb")}
        </p>

        <button
          onClick={signIn}
          disabled={busy}
          style={{
            width: "100%", boxSizing: "border-box", display: "flex", alignItems: "center",
            justifyContent: "center", gap: 8, padding: "9px 12px", fontSize: 13, fontWeight: 500,
            cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
            border: `1px solid ${t.border}`, background: t.panelAlt, color: t.fg,
          }}
        >
          <OrcidMark />
          {busy ? tr("login.orcidRedirecting") : tr("login.orcidSignIn")}
        </button>

        {error && <div style={{ color: t.danger, fontSize: 11, marginTop: 12 }}>{error}</div>}

        <div style={{ marginTop: 18, paddingTop: 14, borderTop: `1px solid ${t.borderSoft}`, fontSize: 11, color: t.fgSubtle, lineHeight: 1.6 }}>
          {tr("login.orcidHelp")}{" "}
          <a href="https://orcid.org/register" target="_blank" rel="noreferrer" style={{ color: t.accent }}>
            orcid.org/register
          </a>
        </div>
      </div>
    </div>
  );
}
