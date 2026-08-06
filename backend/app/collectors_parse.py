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
#
# These are matched as substrings of the segment being kept, so every Chinese
# token must be at least two characters: single characters collide with names.
# 郭立園, 曾彥學, 熊科 and 蔡政學 are all people in this data, which rules out
# 園 / 學 / 科 on their own — and is why 改良場 is listed rather than 場.
ORG_KW = (
    # zh — institutions
    "中心", "研究", "學會", "協會", "公司", "大學", "大学", "學系", "學門", "博物館",
    "試驗所", "研究所", "標本館", "林管處", "管理處", "委員會", "公園", "農場",
    "林場", "水族館", "植物園", "動物園", "保護區", "實驗室", "工作室", "基金會",
    "政府", "公所", "大隊", "中隊", "小組", "團隊", "計畫", "課", "股份",
    "組", "級", "隊", "社", "班", "號", "船",
    # zh — the ones this export actually carries: agricultural stations, seed
    # banks, overseas technical missions, bird societies, district offices.
    "改良場", "繁殖場", "試驗場", "漁場", "農技團", "工作站", "引種站", "通訊站",
    "種原庫", "農部", "植物部", "試所", "植物所", "科學所", "資訊所", "文哲所",
    "生醫所", "分所", "派出所", "檢所", "警所", "鳥會", "建設局", "農業局",
    "消防局", "動保處", "醫院", "集團", "企業", "銀行", "分行", "園區", "鳥店",
    "農專", "師院", "學院", "海產",
    # zh — collectives and roles standing in for a name ("the park staff")
    "人員", "同仁", "官兵", "駐軍", "志工", "義工", "獵人", "工人", "學生",
    "警衛", "技師", "小孩", "學者", "老板", "老闆",
    # en
    "Center", "Centre", "University", "Museum", "Institute", "Society", "Survey",
    "Community", "Garden", "Herbarium", "Laborator", "Project", "Team", "Bureau",
    "Expedition", "Department", "College", "Association", "Company", "Foundation",
    "School", "Network", "Program", "Office", "Inc.", "Ltd", "Dept", "Univ.", " Co.",
    "Division", "Station", "Council", "Agency", "Commission",
)
# Collectives that stand in for a name — "Owston Jap. Collectors", "Native
# collector", "commercial fishermen". Matched case-insensitively against the
# segment (the export shouts as often as not), so a real collector listed
# *before* one of these survives: "F.B. Steiner, Commercial fisherman".
CREW_KW = ("collector", "fisherman", "fishermen")

# Phrases that mean "no recorded collector". Compared case-insensitively.
UNKNOWN_KW = ("unknown", "採集者不明", "不明", "anonymous", "anon.", "s.n.", "no collector",
              "佚名", "illegible", "捐贈", "代購", "贈", "not stated",
              "ukn", "ign.", "unspecified")

# A field label that leaked into the value: "Collector(s): Alex H. T. Yu". The
# long forms may drop the colon ("Collector Unknown"); the abbreviations must
# keep their punctuation, or "Legrand" would lose its first three letters.
LABEL = re.compile(
    # latin: the colon is required. Without it, "COLLECTORS FOR N. KURODA" would
    # be stripped down to a person named "FOR N. KURODA"; the label-less forms
    # ("Collector Unknown") are unusable anyway and get caught downstream.
    r"^\s*(?:collector\(s\)|collectors?|collected\s+by|recorded\s+by)\s*[:：]\s*"
    # chinese: no space to rely on, so the colon carries it
    r"|^\s*(?:採集者|採集人|記錄者)\s*[:：]\s*"
    # abbreviations: punctuation required, or Legrand loses its first letters
    r"|^\s*(?:leg|coll|det)\s*[.:：]\s*",
    re.I,
)

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


# "NAME_institution" — some providers glue the collector's affiliation onto the
# name. Underscore anywhere, a spaced dash, or a bare dash before Chinese: a
# bare dash between Latin letters is a hyphenated given name (Wen-Liang), not a
# separator.
NAME_TAG = re.compile(
    r"^(?P<name>[^_]+?)\s*(?:_|\s[-－—]\s|[-－—](?=[㐀-鿿豈-﫿]))\s*(?P<tag>.+)$"
)
# A first segment that is only a country/region is a provenance note, not a
# collector — "印度，國際熱帶半乾旱作物研究所" lists where, then who.
PLACE_ONLY = {
    "印度", "美國", "中國", "日本", "韓國", "泰國", "越南", "菲律賓", "馬來西亞",
    "澳洲", "英國", "法國", "德國", "俄國", "巴西", "台灣", "臺灣", "香港",
    "china", "taiwan", "japan", "india", "korea", "thailand", "vietnam",
    "usa", "u.s.a.", "america", "australia",
}


def strip_org_tag(seg: str) -> str:
    """``張玉珍_林試所 Y. C. Chang`` -> ``張玉珍 Y. C. Chang``.

    Drops the affiliation while keeping the romanization that may follow it. A
    Chinese institution is one whitespace chunk, so only that chunk goes; a
    Latin one ("National Museum of Natural Science") is several words with no
    reliable end, so the whole tail goes.

    An organization that merely contains a dash is left intact here and still
    reads as an organization to :func:`is_person` afterwards.
    """
    m = NAME_TAG.match(seg)
    if not m:
        return seg
    chunks = m.group("tag").split()
    kept = []
    for i, chunk in enumerate(chunks):
        if any(k in chunk for k in ORG_KW):
            if not has_cjk(chunk):
                kept = []                           # latin affiliation: drop the tail
                break
            continue                                # chinese: drop just this chunk
        kept.append(chunk)
    if len(kept) == len(chunks):
        return seg                                  # nothing looked like an org
    return re.sub(r"\s+", " ", f"{m.group('name')} {' '.join(kept)}").strip(" -_·")


# Square brackets only. Parentheses carry the romanization and the radical
# decompositions, and are parsed structurally further down.
BRACKETED = re.compile(r"^[\[［]\s*(?P<inner>.+?)\s*[\]］]$")
HAS_LETTER = re.compile(r"[A-Za-z㐀-鿿豈-﫿]")


def unwrap_brackets(seg: str) -> str:
    """``[Swinhoe]`` -> ``Swinhoe``.

    A whole value in brackets is an editorial note, and the ones that wrap a
    name would otherwise become a separate collector from the same person
    recorded without them.
    """
    m = BRACKETED.match(seg.strip())
    return m.group("inner") if m else seg


def is_person(raw: str, seg: str, zh: str, en: str) -> bool:
    """Whether the parsed name is a person.

    The two tests have deliberately different scope. An *organization* later in
    the list says nothing about the first collector, so it is judged on ``seg``
    alone. An *unknown marker* — ``s.n.``, ``illegible`` — says the value is not
    a usable attribution at all, so it still disqualifies the whole ``raw``:
    scoping it to the segment would turn ``Lu,S.-Y. s.n. [2009-05-18]`` into a
    collector named "Lu".
    """
    if not zh and not en:
        return False
    if not HAS_LETTER.search(f"{zh}{en}"):
        return False                      # punctuation left over from "[...]"
    if any(k in seg.lower() for k in CREW_KW):
        return False
    if f"{zh}{en}".strip().lower() in PLACE_ONLY:
        return False
    if any(k.lower() in raw.lower() for k in UNKNOWN_KW):
        return False
    if any(k in seg for k in ORG_KW):
        return False
    return True


def parse_collector(raw: str) -> tuple[str, str] | None:
    """Parse a raw ``recorded_by`` value to ``(name_zh, name_en)`` of the first
    collector, or ``None`` if it is an organization / unknown / empty.

    The organization test applies to the first segment only. Testing the whole
    raw value would discard the named collector in ``F.B. Steiner, Commercial
    fisherman`` or ``Huang, Chien-I; illegible`` along with the part that is
    genuinely unusable.
    """
    if not raw or not raw.strip():
        return None
    raw = LABEL.sub("", raw)
    seg = unwrap_brackets(strip_org_tag(first_segment(raw)))
    zh, en = parse_person(seg)
    if not is_person(raw, seg, zh, en):
        return None
    return zh, en
