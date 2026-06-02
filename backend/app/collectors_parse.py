"""Parse the occurrence ``recorded_by`` field into a single collector (zh, en).

This is the *single source of truth* for collector-name parsing, shared by:
  * ``app.seed_collectors`` (populates the SQLite collector tables), and
  * ``scripts/extract_recorded_by_people.py`` (CSV export / inspection).

``recorded_by`` mixes collectors of several shapes, e.g.::

    Pi-Fong Lu (呂碧鳳)              English (Chinese)
    范義彬 Y. B. Fan                 Chinese English
    陶錫珍（Hsi-Jen Tao）            Chinese（English）  (fullwidth parens)
    Knapp, R.                        western "Last, First"
    Zhi-Jiang Zhang (張志江), Wen-Qi Liu (劉文奇)   two people
    吳士緯和張維君 S. Wu & W. C. Chang             two people (和 / &)
    陳邦傑等 / Chen et al.            "{name}等" -> drop the 等
    亞洲蔬菜研究發展中心             organization (excluded)

Rules: keep only people (drop orgs / unknown markers); when several collectors
are listed, keep the FIRST one; return ``(name_zh, name_en)``.
"""

from __future__ import annotations

import re

CJK = re.compile(r"[㐀-鿿豈-﫿]")
# Tokens that mark an entry as an organization / non-person rather than a collector.
ORG_KW = (
    # zh
    "中心", "研究", "學會", "協會", "公司", "大學", "學系", "學門", "博物館",
    "試驗所", "研究所", "標本館", "林管處", "管理處", "委員會", "公園", "農場",
    "林場", "水族館", "植物園", "動物園", "保護區", "實驗室", "工作室", "基金會",
    "政府", "公所", "大隊", "中隊", "小組", "團隊", "計畫", "課", "股份",
    "組", "級", "隊", "社", "班", "號", "船",
    # en
    "Center", "Centre", "University", "Museum", "Institute", "Society", "Survey",
    "Community", "Garden", "Herbarium", "Laborator", "Project", "Team", "Bureau",
    "Expedition", "Department", "College", "Association", "Company", "Foundation",
    "School", "Network", "Program", "Office", "Inc.", "Ltd", "Dept", "Univ.",
    "Division", "Station", "Council", "Agency", "Commission",
)
# Phrases that mean "no recorded collector".
UNKNOWN_KW = ("unknown", "採集者不明", "不明", "anonymous", "s.n.", "no collector", "佚名")

# split helpers
PERSON_SEP = re.compile(r"\s*(?:&|、|和(?![一-龥])|與|及| and )\s*")
INITIALS = re.compile(r"^[A-Z]\.?(?:\s*[A-Z]\.?)*$")
ETAL = re.compile(r"\.{2,}.*$|\bet\.?\s*al\.?.*$", re.I)


def has_cjk(s: str) -> bool:
    return bool(CJK.search(s))


def split_top_level(s: str) -> list[str]:
    """Split on commas/semicolons/& that are NOT inside parentheses."""
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in "（(":
            depth += 1
            cur += ch
        elif ch in "）)":
            depth = max(0, depth - 1)
            cur += ch
        elif depth == 0 and ch in ",，;；、&":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def first_segment(s: str) -> str:
    """The first person's raw segment, handling western 'Last, First'."""
    s = re.sub(r"\s+and\s+", ",", s, flags=re.I)  # " A and B " -> two people
    parts = split_top_level(s)
    if len(parts) == 2 and not has_cjk(s) and INITIALS.match(parts[1]):
        # "Knapp, R." -> "R. Knapp"
        return f"{parts[1]} {parts[0]}"
    seg = parts[0] if parts else s
    # "EN (中文) EN (中文)" / "EN (中文). EN (中文)" -> split after a closing
    # paren when a new Latin-led name follows (space- or period-joined people).
    return re.split(r"(?<=[)）])[.\s]+(?=[A-Za-z（(])", seg)[0]


def outer_paren(seg: str) -> tuple[int, int] | None:
    """Indices of the first *outermost* balanced paren group, or None.

    Outermost (not innermost) so radical-decomposition notation embedded in a
    Chinese name -- e.g. ``廖國(女英)`` (=廖國嫈), ``吳(糸秀)容`` (=吳綉容) -- stays
    attached to the name instead of being mistaken for the romanization.
    """
    start, depth = -1, 0
    for i, ch in enumerate(seg):
        if ch in "（(":
            if depth == 0:
                start = i
            depth += 1
        elif ch in "）)" and depth:
            depth -= 1
            if depth == 0:
                return start, i
    return None


def parse_person(seg: str) -> tuple[str, str]:
    """Return (zh, en) for a single-person segment."""
    seg = re.sub(r"[（(]\s*[?？]\s*[)）]", "", seg)  # drop "(?)" uncertainty marks
    seg = ETAL.sub("", seg).strip(" -·,，")
    zh = en = ""
    span = outer_paren(seg)
    if span:
        i, j = span
        inner = seg[i + 1:j].strip()
        outer = (seg[:i] + " " + seg[j + 1:]).strip()
        if has_cjk(outer) and not has_cjk(inner):
            zh, en = outer, inner
        elif has_cjk(inner) and not has_cjk(outer):
            zh, en = inner, outer
        elif has_cjk(outer) and has_cjk(inner):
            zh = seg.strip()  # pure-CJK name carrying a decomposition paren
        else:  # both latin -> "G. F. Kuo (G. F. Kuo)"
            en = outer or inner
    elif has_cjk(seg):
        run = re.search(r"[㐀-鿿豈-﫿・·\s和與及、]+", seg)
        zh = (run.group(0).strip() if run else "")
        en = re.sub(r"[㐀-鿿豈-﫿（）()、]", " ", seg)
    else:
        en = seg

    # collapse to the first listed person inside each script block
    if zh:
        zh = PERSON_SEP.split(zh)[0].strip(" ·、-")
        zh = re.sub(r"\s*等(人|採集?)?\s*$", "", zh)  # "{name}等" -> "{name}"
    if en:
        en = re.sub(r"\s+", " ", PERSON_SEP.split(en)[0]).strip(" .,-·")
    return zh, en


def is_person(raw: str, zh: str, en: str) -> bool:
    if not zh and not en:
        return False
    low = raw.lower()
    if any(k.lower() in low for k in UNKNOWN_KW):
        return False
    if any(k in raw for k in ORG_KW):
        return False
    return True


def parse_collector(raw: str) -> tuple[str, str] | None:
    """Parse a raw ``recorded_by`` value to ``(name_zh, name_en)`` of the first
    collector, or ``None`` if it is an organization / unknown / empty."""
    if not raw or not raw.strip():
        return None
    zh, en = parse_person(first_segment(raw))
    if not is_person(raw, zh, en):
        return None
    return zh, en
