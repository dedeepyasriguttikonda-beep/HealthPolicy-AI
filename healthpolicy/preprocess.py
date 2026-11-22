"""Clean Firecrawl markdown and split each page into structured policy records."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict

from dateutil import parser as dateparser

from .collector import RawPage

BOILERPLATE = re.compile(
    r"(cookie|accessibility|privacy policy|terms of use|skip to (main )?content|subscribe|"
    r"follow us|share this|back to top|site footer|all rights reserved|copyright ©|last updated on)",
    re.I,
)
IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}\b",
    r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*,? \d{4}\b",
    r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\b",
]
GENERIC_HEADINGS = {"latest updates", "news", "press releases", "whats new", "what's new", "notices",
                    "circulars", "announcements", "recent news", "related links", "more", "menu"}


@dataclass
class PolicyRecord:
    item_id: str
    source_id: str
    source_name: str
    url: str
    category: str
    region: str
    authority: str
    title: str
    published: str | None
    text: str
    link: str | None
    content_hash: str
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w%$.\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sha(text: str, n: int = 16) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def extract_date(text: str) -> str | None:
    for pat in DATE_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            try:
                return dateparser.parse(m.group(0), dayfirst="/" in m.group(0) or "." in m.group(0)).date().isoformat()
            except (ValueError, OverflowError):
                continue
    return None


def clean_markdown(md: str) -> str:
    md = IMG.sub("", md)
    lines = []
    for line in md.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if s.startswith(">"):  # banner / callout quotes are not policy content
            continue
        if BOILERPLATE.search(s) and len(s) < 160:
            continue
        if re.fullmatch(r"[-*_|=\s]{3,}", s):
            continue
        lines.append(line.rstrip())
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _first_link(text: str) -> str | None:
    for _, href in MD_LINK.findall(text):
        if href and href != "#" and not href.startswith("javascript"):
            return href
    return None


def _plain(text: str) -> str:
    text = MD_LINK.sub(lambda m: m.group(1) if m.group(1).lower() not in {"read more", "more", "click here"} else "", text)
    text = re.sub(r"[*_`#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _segments_by_heading(md: str):
    blocks, cur_title, cur = [], None, []
    for line in md.splitlines():
        h = re.match(r"^#{2,4}\s+(.*)", line)
        if h:
            if cur_title is not None:
                blocks.append((cur_title, "\n".join(cur)))
            cur_title, cur = h.group(1).strip(), []
        elif cur_title is not None:
            cur.append(line)
    if cur_title is not None:
        blocks.append((cur_title, "\n".join(cur)))
    return [(t, b) for t, b in blocks if _plain(t).lower() not in GENERIC_HEADINGS and (_plain(b) or len(t) > 30)]


def _segments_by_links(md: str):
    """Listing pages (common on .gov.in sites): each '- [Title](url) date' line is one notice."""
    segs = []
    for line in md.splitlines():
        s = line.strip().lstrip("-*0123456789. ").strip()
        m = MD_LINK.search(s)
        if m and len(m.group(1)) >= 25:
            rest = _plain(MD_LINK.sub("", s))
            segs.append((m.group(1), f"{line}\n{rest}"))
    return segs


def to_records(page: RawPage) -> list[PolicyRecord]:
    if page.status != "ok" or not page.markdown.strip():
        return []
    md = clean_markdown(page.markdown)
    segs = _segments_by_heading(md) or _segments_by_links(md)
    if not segs:  # single-document page (e.g. one guidance page)
        segs = [(page.title, md)]
    records, seen = [], set()
    for title, body in segs:
        title_p = _plain(title)
        published = extract_date(body) or extract_date(title)
        # date is stored as a field; drop a leading "Published: <date>" label from the body text
        body_p = re.sub(r"^(published|posted|issued|date|updated)\s*(on)?\s*:?\s*", "", _plain(body), flags=re.I)
        for pat in DATE_PATTERNS:
            body_p = re.sub(r"^" + pat + r"\s*[|:-]?\s*", "", body_p, flags=re.I)
        if len(title_p) < 8:
            continue
        item_id = sha(f"{page.source_id}|{normalize(title_p)}")
        if item_id in seen:
            continue
        seen.add(item_id)
        records.append(PolicyRecord(
            item_id=item_id,
            source_id=page.source_id,
            source_name=page.source_name,
            url=page.url,
            category=page.category,
            region=page.region,
            authority=page.authority,
            title=title_p,
            published=published,
            text=body_p[:6000],
            link=_first_link(body),
            content_hash=sha(normalize(f"{title_p} {published or ''} {body_p}"), 40),
            fetched_at=page.fetched_at,
        ))
    return records
