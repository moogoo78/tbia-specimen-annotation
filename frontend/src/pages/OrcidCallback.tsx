import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { consumeOrcidState, useAuth } from "../auth";

/** Landing route for ORCID's redirect: reads ?code&state, verifies state,
 *  exchanges the code for our JWT, then sends the user home. */
export function OrcidCallback() {
  const { t: tr } = useTranslation();
  const { finishOrcidLogin } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [error, setError] = useState("");
  const ran = useRef(false); // StrictMode mounts effects twice; exchange once

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const code = params.get("code");
    const denied = params.get("error"); // e.g. user clicked "Deny"
    (async () => {
      try {
        if (denied) throw new Error(params.get("error_description") || denied);
        consumeOrcidState(params.get("state"));
        if (!code) throw new Error("Missing authorization code");
        await finishOrcidLogin(code);
        nav("/", { replace: true });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Sign-in failed");
      }
    })();
  }, [params, finishOrcidLogin, nav]);

  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: t.bg }}>
      <div style={{ width: 340, textAlign: "center", fontSize: 13, color: t.fgMuted }}>
        {error ? (
          <>
            <div style={{ color: t.danger, marginBottom: 12 }}>{error}</div>
            <button
              onClick={() => nav("/login", { replace: true })}
              style={{ padding: "7px 14px", fontSize: 12, cursor: "pointer", border: `1px solid ${t.border}`, background: t.panelAlt, color: t.fg }}
            >
              {tr("login.orcidRetry")}
            </button>
          </>
        ) : (
          tr("login.orcidCompleting")
        )}
      </div>
    </div>
  );
}
