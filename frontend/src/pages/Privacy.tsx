import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon, type IconName } from "../design/Icon";

// What this platform collects and what it does with it.
//
// The cookie is the smallest part and was the only part anyone was ever told
// about. The parts that matter are further up: signing in stores an ORCID iD
// and name, annotations are public the moment they are submitted, and the copy
// returned to the collection carries the contributor's ORCID name *whether or
// not* they opted in to being named on the site — because a CC-BY attribution
// has to be checkable against a real iD. That last one was documented only in
// CLAUDE.md and one sentence of a settings hint, which is not where a
// contributor would look before deciding to contribute.
//
// Prose lives in i18n (`privacy.*`) like the guide's. Every claim is checkable
// against the code — `api/auth.py`, `models.public_name`, `api/export.py`,
// `analytics.ts` — so if one of those changes, change the copy with it.
export function Privacy() {
  const { t: tr } = useTranslation();

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "24px 24px 48px" }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px" }}>{tr("privacy.title")}</h2>
        <p style={{ fontSize: 13, color: t.fgMuted, lineHeight: 1.7, margin: "0 0 24px" }}>
          {tr("privacy.lead")}
        </p>

        <Section icon="user" title={tr("privacy.signinTitle")} items={[
          tr("privacy.signin1"), tr("privacy.signin2"), tr("privacy.signin3"),
        ]} />

        <Section icon="spark" title={tr("privacy.annotationTitle")} items={[
          tr("privacy.annotation1"), tr("privacy.annotation2"),
          tr("privacy.annotation3"), tr("privacy.annotation4"),
        ]} />

        <Section icon="rows" title={tr("privacy.nameTitle")} items={[
          tr("privacy.name1"), tr("privacy.name2"), tr("privacy.name3"),
        ]} />

        {/* Called out rather than listed: it is the one consequence a
            contributor cannot undo by changing a setting later, so it should
            not read like the fourth bullet of a policy. */}
        <div style={{
          border: `1px solid ${t.warn}`, background: t.panel, padding: "12px 14px", margin: "0 0 24px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, margin: "0 0 8px" }}>
            <Icon name="alert" size={14} />
            <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>{tr("privacy.exportTitle")}</h3>
          </div>
          <Bullets items={[tr("privacy.export1"), tr("privacy.export2"), tr("privacy.export3")]} />
        </div>

        <Section icon="globe" title={tr("privacy.cookieTitle")} items={[
          tr("privacy.cookie1"), tr("privacy.cookie2"), tr("privacy.cookie3"),
        ]} />

        <Section icon="img" title={tr("privacy.storageTitle")} items={[tr("privacy.storage1")]} />

        <Section icon="grid" title={tr("privacy.openTitle")} items={[tr("privacy.open1")]} />

        <div style={{
          display: "flex", alignItems: "center", gap: 14, marginTop: 8,
          paddingTop: 14, borderTop: `1px solid ${t.borderSoft}`, fontSize: 11, flexWrap: "wrap",
        }}>
          <span style={{ color: t.fgSubtle }}>{tr("privacy.updated")}</span>
          <div style={{ flex: 1 }} />
          <Link to="/guide" style={{ color: t.fgSubtle }}>{tr("nav.guide")}</Link>
          <Link to="/me" style={{ color: t.fgSubtle }}>{tr("nav.myContributions")}</Link>
        </div>
      </div>
    </div>
  );
}

function Section({ icon, title, items }: { icon: IconName; title: string; items: string[] }) {
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 7, margin: "0 0 8px" }}>
        <Icon name={icon} size={14} />
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>{title}</h3>
      </div>
      <div style={{ margin: "0 0 24px" }}><Bullets items={items} /></div>
    </>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: t.fg, lineHeight: 1.75 }}>
      {items.map((text, i) => <li key={i} style={{ marginBottom: 5 }}>{text}</li>)}
    </ul>
  );
}
