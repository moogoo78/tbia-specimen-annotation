import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { useAuth } from "../auth";

export function AppHeader() {
  const { t: tr, i18n } = useTranslation();
  const { user, logout } = useAuth();
  const loc = useLocation();

  const toggleLang = () => {
    const next = i18n.language === "zh" ? "en" : "zh";
    i18n.changeLanguage(next);
    localStorage.setItem("tbia_lang", next);
  };

  const tab = (to: string, label: string) => {
    const active = loc.pathname === to || (to !== "/" && loc.pathname.startsWith(to));
    return (
      <Link to={to} style={{
        padding: "0 14px", fontSize: 12, display: "flex", alignItems: "center",
        textDecoration: "none", color: active ? t.fg : t.fgMuted,
        fontWeight: active ? 600 : 400,
        borderBottom: active ? `2px solid ${t.fg}` : "2px solid transparent", marginBottom: -1,
      }}>{label}</Link>
    );
  };

  return (
    <div style={{
      borderBottom: `1px solid ${t.border}`, background: t.panel, fontFamily: t.sans,
      display: "flex", alignItems: "stretch", height: 38, flexShrink: 0,
    }}>
      <Link to="/" style={{
        display: "flex", alignItems: "center", gap: 8, padding: "0 12px",
        borderRight: `1px solid ${t.borderSoft}`, textDecoration: "none", color: t.fg,
      }}>
        <div style={{
          width: 18, height: 18, background: t.fg, color: t.bg, display: "flex",
          alignItems: "center", justifyContent: "center", fontSize: 11, fontFamily: t.mono, fontWeight: 700,
        }}>T</div>
        <span style={{ fontSize: 12, fontWeight: 600 }}>{tr("app.short")}</span>
      </Link>

      <div style={{ display: "flex", alignItems: "stretch" }}>
        {tab("/", tr("nav.explore"))}
        {tab("/institutions", tr("nav.institutions"))}
        {tab("/dashboard", tr("nav.dashboard"))}
      </div>

      <div style={{ flex: 1 }} />

      <button onClick={toggleLang} title="language" style={{
        display: "flex", alignItems: "center", gap: 5, padding: "0 10px", background: "transparent",
        border: "none", borderLeft: `1px solid ${t.borderSoft}`, color: t.fgMuted, cursor: "pointer",
        fontSize: 11, fontFamily: t.sans,
      }}>
        <Icon name="globe" size={13} />{i18n.language === "zh" ? "中文" : "EN"}
      </button>

      <div style={{
        display: "flex", alignItems: "center", gap: 8, padding: "0 12px",
        borderLeft: `1px solid ${t.borderSoft}`,
      }}>
        {user ? (
          <>
            <div style={{
              width: 22, height: 22, borderRadius: 11, background: "oklch(0.72 0.04 50)",
              color: "#fff", fontSize: 10, fontWeight: 600, display: "flex",
              alignItems: "center", justifyContent: "center", fontFamily: t.mono,
            }}>{user.display_name.split(" ").map((s) => s[0]).join("").slice(0, 2)}</div>
            <span style={{ fontSize: 11, color: t.fgMuted }}>{user.display_name}</span>
            <span style={{ fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, textTransform: "uppercase" }}>{user.role}</span>
            <button onClick={logout} style={{ border: "none", background: "none", color: t.fgSubtle, fontSize: 11, cursor: "pointer", textDecoration: "underline" }}>
              {tr("nav.logout")}
            </button>
          </>
        ) : (
          <Link to="/login" style={{ fontSize: 11, color: t.accent, textDecoration: "none", display: "flex", gap: 5, alignItems: "center" }}>
            <Icon name="user" size={13} />{tr("nav.login")}
          </Link>
        )}
      </div>
    </div>
  );
}
