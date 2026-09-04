import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { useAuth } from "../auth";
import { STORY_TOPICS } from "../pages/Story";
import { ANALYTICS_ENABLED, revokeConsent, useConsent } from "../analytics";

/** The dropped-down panel. Above Leaflet's controls (MapView uses 1000) so a
 *  menu opened over the map is not painted behind it, below the cookie banner
 *  at 2000, which outranks everything by design. */
const panel: React.CSSProperties = {
  position: "absolute", top: "100%", minWidth: 172, zIndex: 1500,
  background: t.panel, border: `1px solid ${t.border}`, borderTop: "none",
  boxShadow: "0 8px 20px rgba(0,0,0,0.09)", padding: "4px 0",
};

const item: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "7px 14px",
  fontSize: 12, textDecoration: "none", color: t.fgMuted, whiteSpace: "nowrap",
};

/** Escape closes the menu and hands focus back to the button that opened it —
 *  otherwise the keyboard is left nowhere. */
function useEscape(open: boolean, close: () => void, trigger: React.RefObject<HTMLButtonElement | null>) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      close();
      trigger.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close, trigger]);
}

export function AppHeader() {
  const { t: tr, i18n } = useTranslation();
  const { user } = useAuth();
  const loc = useLocation();
  const consent = useConsent();
  // Only worth showing once there's a choice to change — while the banner is up
  // it would just duplicate it.
  const showCookieLink = ANALYTICS_ENABLED && consent !== "unset";

  // One menu at a time, so the state is here rather than in each menu: with a
  // flag per menu, two panels can sit open at once and moving between them
  // costs two clicks.
  const [open, setOpen] = useState<string | null>(null);

  // Closing on navigation is the one rule that covers every way a menu can be
  // left behind — a link inside it, a link outside it, and the back button.
  useEffect(() => setOpen(null), [loc.pathname]);

  // A press anywhere outside the open menu dismisses it. On pointerdown rather
  // than click, so it lands before another trigger's click and that trigger
  // still opens; a press inside the panel is the item doing its own work.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const el = e.target as Element | null;
      if (!el?.closest(`[data-menu="${open}"]`)) setOpen(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // The landing page is one decision (see pages/Landing.tsx): three records,
  // one action each. A row of destinations above it is precisely the choice
  // that page exists to remove, so the tabs are dropped there and the escape
  // hatches at the foot of the page carry the traffic instead.
  //
  // What stays is what is not a destination. The language toggle is how half
  // this site's visitors can read the front door at all, and sign-in is how a
  // returning contributor gets back to their work — neither competes with the
  // decision, and a public landing page cannot assume, as the mockup this came
  // from did, an English-speaking user who is already logged in.
  const minimal = loc.pathname === "/";

  const toggleLang = () => {
    const next = i18n.language === "zh" ? "en" : "zh";
    i18n.changeLanguage(next);
    localStorage.setItem("tbia_lang", next);
  };

  const isActive = (to: string, also: string[] = []) =>
    loc.pathname === to
    || (to !== "/" && loc.pathname.startsWith(to))
    || also.some((path) => loc.pathname.startsWith(path));

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: "0 14px", fontSize: 12, display: "flex", alignItems: "center", gap: 4,
    textDecoration: "none", color: active ? t.fg : t.fgMuted,
    fontWeight: active ? 600 : 400, fontFamily: t.sans,
    borderBottom: active ? `2px solid ${t.fg}` : "2px solid transparent", marginBottom: -1,
  });

  const tab = (to: string, label: string, also: string[] = []) => (
    <Link to={to} style={tabStyle(isActive(to, also))}>{label}</Link>
  );

  const group = (id: string, label: string, links: { to: string; label: string; also?: string[] }[]) => (
    <NavMenu
      id={id} label={label} links={links}
      open={open === id} onOpen={setOpen}
      active={links.some((l) => isActive(l.to, l.also))}
    />
  );

  return (
    <div data-app-header="" style={{
      borderBottom: `1px solid ${t.border}`, background: t.panel, fontFamily: t.sans,
      display: "flex", alignItems: "stretch", height: 38, flexShrink: 0,
    }}>
      {/* The rule separates the brand from the tabs; with no tabs it is a
          divider to nothing, so it goes with them. */}
      <Link to="/" style={{
        display: "flex", alignItems: "center", gap: 8, padding: "0 12px",
        borderRight: minimal ? "none" : `1px solid ${t.borderSoft}`,
        textDecoration: "none", color: t.fg,
      }}>
        <div style={{
          width: 18, height: 18, background: t.fg, color: t.bg, display: "flex",
          alignItems: "center", justifyContent: "center", fontSize: 11, fontFamily: t.mono, fontWeight: 700,
        }}>I</div>
        <span style={{ fontSize: 12, fontWeight: 600 }}>{tr("app.short")}</span>
      </Link>

      {/* Two entry points stay flat, the indexes and the taking-part pages sit
          one click down, and the guide stays reachable without opening anything
          — it is what you look for once you are already stuck. There is no Home
          tab: the wordmark to its left already goes there. */}
      {!minimal && (
        <div style={{ display: "flex", alignItems: "stretch" }}>
          {tab("/browse", tr("nav.browse"))}
          {tab("/explore", tr("nav.explore"))}
          {group("data", tr("nav.data"), [
            { to: "/species", label: tr("nav.species") },
            { to: "/institutions", label: tr("nav.institutions") },
            { to: "/collectors", label: tr("nav.collectors") },
            // The chronology is a topic of the story, so /history lights this one.
            { to: "/story", label: tr("nav.story"), also: STORY_TOPICS.map((topic) => topic.path) },
          ])}
          {/* The two halves of "contribution", named apart: what everybody has
              done, and what you have. */}
          {group("take-part", tr("nav.participate"), [
            { to: "/contributors", label: tr("nav.volunteers") },
            { to: "/me", label: tr("nav.myContributions"), also: ["/dashboard"] },
          ])}
          {tab("/guide", tr("nav.guide"))}
        </div>
      )}

      <div style={{ flex: 1 }} />

      {showCookieLink && (
        <button onClick={revokeConsent} title={tr("consent.manageTitle")} style={{
          display: "flex", alignItems: "center", padding: "0 10px", background: "transparent",
          border: "none", borderLeft: `1px solid ${t.borderSoft}`, color: t.fgSubtle, cursor: "pointer",
          fontSize: 11, fontFamily: t.sans,
        }}>
          {tr("consent.manage")}
        </button>
      )}

      <button onClick={toggleLang} title="language" style={{
        display: "flex", alignItems: "center", gap: 5, padding: "0 10px", background: "transparent",
        border: "none", borderLeft: `1px solid ${t.borderSoft}`, color: t.fgMuted, cursor: "pointer",
        fontSize: 11, fontFamily: t.sans,
      }}>
        <Icon name="globe" size={13} />{i18n.language === "zh" ? "中文" : "EN"}
      </button>

      <div style={{
        display: "flex", alignItems: "stretch", borderLeft: `1px solid ${t.borderSoft}`,
      }}>
        {user ? (
          <UserMenu open={open === "user"} onOpen={setOpen} />
        ) : (
          <Link to="/login" style={{
            display: "flex", alignItems: "center", gap: 5, padding: "0 12px",
            fontSize: 11, color: t.accent, textDecoration: "none",
          }}>
            <Icon name="user" size={13} />{tr("nav.login")}
          </Link>
        )}
      </div>
    </div>
  );
}

/** A tab that opens a list of tabs. Click, never hover: a hover menu opens on
 *  the way past with a mouse and cannot be opened at all by touch. */
function NavMenu({ id, label, links, open, onOpen, active }: {
  id: string;
  label: string;
  links: { to: string; label: string; also?: string[] }[];
  open: boolean;
  onOpen: (id: string | null) => void;
  active: boolean;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  useEscape(open, () => onOpen(null), trigger);

  return (
    <div data-menu={id} style={{ position: "relative", display: "flex" }}>
      <button
        ref={trigger} onClick={() => onOpen(open ? null : id)}
        aria-haspopup="menu" aria-expanded={open}
        style={{
          padding: "0 12px", fontSize: 12, display: "flex", alignItems: "center", gap: 4,
          background: "transparent", border: "none", cursor: "pointer", fontFamily: t.sans,
          color: active || open ? t.fg : t.fgMuted, fontWeight: active ? 600 : 400,
          borderBottom: active ? `2px solid ${t.fg}` : "2px solid transparent", marginBottom: -1,
        }}
      >
        {label}<Icon name="caretD" size={11} />
      </button>
      {open && (
        <div role="menu" style={{ ...panel, left: 0 }}>
          {links.map((l) => (
            <Link key={l.to} to={l.to} role="menuitem" style={item}>{l.label}</Link>
          ))}
        </div>
      )}
    </div>
  );
}

/** Signed in, identity collapses to the avatar: the name, the role and sign-out
 *  are all still there, they just stop spending header width on every page. */
function UserMenu({ open, onOpen }: { open: boolean; onOpen: (id: string | null) => void }) {
  const { t: tr } = useTranslation();
  const { user, logout } = useAuth();
  const trigger = useRef<HTMLButtonElement>(null);
  useEscape(open, () => onOpen(null), trigger);
  if (!user) return null;

  const initials = user.display_name.split(" ").map((s) => s[0]).join("").slice(0, 2);

  return (
    <div data-menu="user" style={{ position: "relative", display: "flex" }}>
      <button
        ref={trigger} onClick={() => onOpen(open ? null : "user")}
        aria-haspopup="menu" aria-expanded={open} title={user.display_name}
        style={{
          display: "flex", alignItems: "center", gap: 5, padding: "0 12px",
          background: "transparent", border: "none", cursor: "pointer", fontFamily: t.sans,
          color: t.fgMuted,
        }}
      >
        <div style={{
          width: 22, height: 22, borderRadius: 11, background: "oklch(0.72 0.04 50)",
          color: "#fff", fontSize: 10, fontWeight: 600, display: "flex",
          alignItems: "center", justifyContent: "center", fontFamily: t.mono,
        }}>{initials}</div>
        <Icon name="caretD" size={11} />
      </button>
      {open && (
        <div role="menu" style={{ ...panel, right: 0 }}>
          <div style={{ padding: "7px 14px", borderBottom: `1px solid ${t.borderSoft}`, marginBottom: 4 }}>
            <div style={{ fontSize: 12, color: t.fg, whiteSpace: "nowrap" }}>{user.display_name}</div>
            <div style={{ fontSize: 9, color: t.fgSubtle, fontFamily: t.mono, textTransform: "uppercase" }}>{user.role}</div>
          </div>
          <Link to="/me" role="menuitem" style={item}>{tr("nav.myContributions")}</Link>
          <button
            onClick={() => { onOpen(null); logout(); }} role="menuitem"
            style={{ ...item, width: "100%", background: "transparent", border: "none", cursor: "pointer", fontFamily: t.sans }}
          >
            {tr("nav.logout")}
          </button>
        </div>
      )}
    </div>
  );
}
