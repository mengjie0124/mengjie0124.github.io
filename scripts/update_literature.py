#!/usr/bin/env python3
"""Fetch public DOI metadata, filter by topic, and render static daily archives.

Python 3.11+, standard library only. No API key or language model required.
Dates in reports are discovery dates, not a claim of publication that day.
"""
import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "papers" / "catalog.json"
POLICY_VERSION = "journal-whitelist-v1"
JOURNALS = [
    "Nature", "Science", "Proceedings of the National Academy of Sciences",
    "Remote Sensing of Environment", "ISPRS Journal of Photogrammetry and Remote Sensing",
    "IEEE Transactions on Geoscience and Remote Sensing", "Earth System Science Data",
    "Limnology and Oceanography", "Limnology and Oceanography: Methods", "Optics Express",
    "Geophysical Research Letters", "Journal of Geophysical Research: Oceans",
    "IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing",
    "Journal of Geophysical Research: Biogeosciences", "Frontiers in Marine Science",
]


def journal_key(name):
    return re.sub(r"[^a-z0-9]", "", plain(name).lower().replace("&", "and"))


def allowed_journal(name, doi="", publisher=""):
    if doi.lower().startswith("10.3390/") or "mdpi" in publisher.lower():
        return False
    return journal_key(name) in {journal_key(j) for j in JOURNALS}


def apply_policy(state):
    removed = {doi for doi, p in state["records"].items()
               if doi.lower().startswith("10.3390/") or (p["kind"] != "Dataset" and (p["kind"] != "Paper" or not allowed_journal(p["venue"], doi)))}
    for doi in removed:
        del state["records"][doi]
    for entry in state["days"].values():
        entry["items"] = [doi for doi in entry["items"] if doi in state["records"]]
    if state.get("policy_version") != POLICY_VERSION:
        state["last_success"] = None
        state["policy_version"] = POLICY_VERSION
    return len(removed)
TOPICS = {
    "validation": "CDOM / DOC algorithm assessment",
    "optics": "IOPs & optical water types",
    "datasets": "European in-situ CDOM / DOC datasets",
    "plumes": "Floods, river plumes & carbon exchange",
}
QUERIES = [
    "CDOM retrieval algorithm validation coastal ocean",
    "dissolved organic carbon ocean colour algorithm assessment",
    "inherent optical properties optical water types marine",
    "CDOM DOC in situ dataset European coastal seas",
    "Adriatic Sea river discharge flood carbon",
    "river plume flood dissolved organic carbon exchange",
]
DATA_QUERIES = [
    '(CDOM OR "coloured dissolved organic matter" OR "colored dissolved organic matter") AND (Europe OR Adriatic OR Mediterranean OR Baltic OR "North Sea" OR "Black Sea")',
    '("dissolved organic carbon" OR DOC) AND (Adriatic OR Mediterranean OR Baltic OR "North Sea")',
    '("inherent optical properties" OR "optical water types") AND (marine OR coastal OR sea)',
]


def plain(value):
    return html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def contains(text, terms):
    return any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text) for t in terms)


def classify(title, description="", dataset=False):
    title_text = title.lower()
    if contains(title_text, ["inland", "lake", "lakes", "reservoir", "reservoirs"]) and not contains(title_text, ["coastal", "ocean", "marine", "sea", "seas", "estuary", "estuarine"]):
        return []
    text = (title + " " + description).lower()
    marine = contains(text, ["ocean", "marine", "coastal", "sea", "seas", "estuary", "estuarine", "plume", "plumes", "mediterranean", "adriatic", "baltic"])
    if not marine:
        return []
    organic = contains(text, ["cdom", "doc", "dissolved organic carbon", "coloured dissolved organic matter", "colored dissolved organic matter", "chromophoric dissolved organic matter"])
    algorithm = contains(text, ["algorithm", "algorithms", "retrieval", "inversion", "validation", "assessment", "validate", "evaluating", "evaluation", "intercomparison"])
    optics = contains(text, ["iop", "iops", "inherent optical properties", "absorption", "backscattering"])
    types = contains(text, ["water type", "water types", "optical classification", "distribution", "variability", "optically complex"])
    europe = contains(text, ["europe", "european", "adriatic", "mediterranean", "baltic", "north sea", "black sea", "aegean", "tyrrhenian", "iberian", "celtic sea", "bay of biscay", "english channel", "po river"])
    measurements = dataset or contains(text, ["dataset", "datasets", "data set", "in situ", "in-situ", "field measurements", "observations", "data collection"])
    river = contains(text, ["river", "rivers", "plume", "plumes", "flood", "floods", "flooding", "discharge", "runoff"])
    carbon = organic or contains(text, ["carbon", "co2", "pco2", "carbon dioxide", "carbon exchange", "carbon flux"])
    tags = []
    title_organic = contains(title_text, ["cdom", "doc", "dissolved organic carbon", "coloured dissolved organic matter", "colored dissolved organic matter", "chromophoric dissolved organic matter"])
    title_optics = contains(title_text, ["iop", "iops", "inherent optical properties", "absorption", "backscattering", "bio-optical", "ocean colour", "ocean color"])
    title_river = contains(title_text, ["river", "rivers", "plume", "plumes", "flood", "floods", "flooding", "discharge", "runoff"])
    title_carbon = contains(title_text, ["carbon", "co2", "pco2", "carbon dioxide"]) or title_organic
    if organic and algorithm and (title_organic or title_optics):
        tags.append("validation")
    if optics and types and title_optics:
        tags.append("optics")
    if title_organic and europe and measurements:
        tags.append("datasets")
    if river and (carbon or contains(text, ["adriatic"])) and (title_river or title_carbon):
        tags.append("plumes")
    return tags


def request_json(base, params):
    url = base + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MengjieZhao-LiteratureFeed/1.0 (public DOI metadata)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def crossref_record(item):
    title = plain((item.get("title") or [""])[0])
    tags = classify(title, plain(item.get("abstract")))
    venue = plain((item.get("container-title") or [""])[0])
    if not title or not tags or item.get("type") != "journal-article" or not allowed_journal(venue, item.get("DOI", ""), item.get("publisher", "")):
        return None
    parts = (item.get("published", {}).get("date-parts") or [[]])[0]
    return {"doi": item["DOI"].lower(), "title": title, "published": "-".join(str(p).zfill(2) if i else str(p) for i, p in enumerate(parts)),
            "venue": venue, "source": "Crossref", "kind": "Paper", "topics": tags}


def datacite_record(item):
    a = item["attributes"]
    title = plain((a.get("titles") or [{}])[0].get("title"))
    description = " ".join(plain(d.get("description")) for d in a.get("descriptions", []))
    tags = classify(title, description, dataset=True)
    if not title or not tags:
        return None
    publisher = a.get("publisher", "DataCite")
    if isinstance(publisher, dict):
        publisher = publisher.get("name", "DataCite")
    if a["doi"].lower().startswith("10.3390/") or "mdpi" in publisher.lower():
        return None
    return {"doi": a["doi"].lower(), "title": title, "published": str(a.get("publicationYear") or ""),
            "venue": plain(publisher), "source": "DataCite", "kind": "Dataset", "topics": tags}


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def shell(title, body):
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + ' · Mengjie Zhao</title><link rel="stylesheet" href="../styles.css"><link rel="stylesheet" href="../background.css"><link rel="stylesheet" href="papers.css"></head><body><header><a class="name" href="../index.html">Mengjie Zhao</a><nav><a href="../index.html">Profile</a><a href="index.html">Daily Literature</a></nav></header><main class="literature-page">' + body + '</main><footer>Public DOI metadata · Crossref &amp; DataCite · Europe/Rome</footer></body></html>'


def render(state):
    esc = html.escape
    days = sorted(state["days"], reverse=True)
    cards = []
    for day in days:
        entry = state["days"][day]
        warning = '<p class="feed-warning">Some sources were unavailable; this report is incomplete.</p>' if entry["errors"] else ""
        count = len(entry["items"])
        cards.append(f'<a class="card date-card" href="{day}.html"><h3>{day}</h3><p>Run: {esc(entry["run_at"])}</p><p>{count} newly discovered records</p>{warning}</a>')
        records = []
        for doi in entry["items"]:
            p = state["records"][doi]
            url = "https://doi.org/" + urllib.parse.quote(doi, safe="/")
            labels = "".join(f'<span>{esc(TOPICS[t])}</span>' for t in p["topics"])
            records.append(f'<article class="card paper"><p class="paper-meta">{esc(p["kind"])} · {esc(p["source"])} · Published: {esc(p["published"] or "not supplied")}</p><h3><a href="{esc(url, quote=True)}" target="_blank" rel="noreferrer">{esc(p["title"])}</a></h3><p>{esc(p["venue"])}</p><div class="tags">{labels}</div><p class="match-note">Matched metadata topics: {esc("; ".join(TOPICS[t] for t in p["topics"]))}. Automated selection; not a full-text assessment.</p></article>')
        empty = '<p class="card empty">No new matching records were found in the checked sources.</p>' if not records and not entry["errors"] else '<p class="card empty">No records to display. Source errors prevent confirming a zero-result day.</p>'
        body = f'<a href="index.html">← All dates</a><h1>Literature discovered on {day}</h1><p>Run: {esc(entry["run_at"])} · {count} new records</p>{warning}<div class="paper-list">' + ("".join(records) or empty) + '</div>'
        atomic_write(ROOT / "papers" / f"{day}.html", shell(day, body))
    status = "" if days else '<p class="card empty">The first literature search has not run yet. Daily reports will appear after the updater completes successfully.</p>'
    policy = '<details class="feed-note"><summary>Journal selection · MDPI excluded</summary><p>Journal papers are restricted to the list below. Preprints and conference papers are excluded. Original research datasets are kept separately and are not subject to the journal list.</p><ul>' + ''.join(f'<li>{esc(j)}</li>' for j in JOURNALS) + '</ul></details>'
    body = '<h1>Daily Literature</h1><p class="intro">Ocean-colour algorithms, coastal optics, European in-situ datasets, and flood-driven river-plume carbon cycling.</p><div class="tags">' + "".join(f'<span>{esc(t)}</span>' for t in TOPICS.values()) + '</div>' + policy + '<p class="feed-note">Dates indicate when records were discovered, not publication dates. New DOI metadata and dataset updates are checked daily; older publications can appear when newly indexed. Duplicate DOIs are omitted across days. This is an automated metadata search, not an exhaustive review or a claim that dataset contents have been validated.</p><h2>Dates</h2><div class="date-grid">' + "".join(cards) + '</div>' + status
    atomic_write(ROOT / "papers" / "index.html", shell("Daily Literature", body))


def update():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        assert "validation" in classify("CDOM retrieval algorithm validation in coastal waters")
        assert "datasets" in classify("In-situ DOC dataset in the Adriatic Sea", dataset=True)
        assert "optics" in classify("Inherent optical properties across marine optical water types")
        assert "plumes" in classify("Flood events and carbon exchange in river plumes")
        assert not classify("CDOM retrieval validation in inland lakes")
        assert not classify("CDOM and DOC in inland waters in China", "Comparison with coastal marine validation")
        assert not classify("Occurrence Download", "Marine DOC carbon river validation Europe")
        assert not classify("The Atlantis Narrative", "Adriatic marine river carbon DOC validation")
        assert allowed_journal("Limnology and Oceanography: Methods")
        assert allowed_journal("Journal of Geophysical Research: Oceans")
        assert not allowed_journal("Remote Sensing", "10.3390/rs123")
        assert not allowed_journal("Nature", "10.3390/fake", "MDPI")
        assert not allowed_journal("An unrelated journal")
        print("Topic filters passed")
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {"records": {}, "days": {}, "last_success": None}
    removed = apply_policy(state)
    print(f"Journal policy: removed {removed} non-matching archive records", flush=True)
    if args.render_only:
        render(state)
        atomic_write(STATE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        return
    now = dt.datetime.now(ZoneInfo("Europe/Rome"))
    day = now.date().isoformat()
    # First run checks recent paper metadata plus dataset discovery of all ages.
    since = state.get("last_success") or (now.date() - dt.timedelta(days=730)).isoformat()
    since = (dt.date.fromisoformat(since[:10]) - dt.timedelta(days=1)).isoformat()
    found, errors = {}, []
    for query in QUERIES:
        print(f"Searching Crossref: {query}", flush=True)
        try:
            data = request_json("https://api.crossref.org/works", {"query": query, "rows": 100, "filter": f"from-index-date:{since},until-index-date:{day}", "sort": "relevance"})
            for item in data["message"]["items"]:
                record = crossref_record(item)
                if record:
                    found[record["doi"]] = record
        except Exception as e:
            errors.append(f"Crossref: {type(e).__name__}")
        time.sleep(1.1)
    for query in DATA_QUERIES:
        print("Searching DataCite datasets", flush=True)
        try:
            suffix = f' AND updated:[{since} TO {day}]' if state.get("last_success") else ""
            data = request_json("https://api.datacite.org/dois", {"query": f"({query}) AND types.resourceTypeGeneral:Dataset" + suffix, "page[size]": 50, "sort": "-updated"})
            for item in data["data"]:
                record = datacite_record(item)
                if record:
                    found.setdefault(record["doi"], record)
        except Exception as e:
            errors.append(f"DataCite: {type(e).__name__}")
        time.sleep(1.1)
    if len(errors) == len(QUERIES) + len(DATA_QUERIES):
        raise RuntimeError("All literature sources failed; existing reports were preserved")
    entry = state["days"].setdefault(day, {"items": [], "run_at": "", "errors": []})
    existing_titles = {re.sub(r"\W+", "", r["title"].lower()) for r in state["records"].values()}
    candidates = []
    for record in sorted(found.values(), key=lambda r: (len(r["topics"]), r["published"]), reverse=True):
        title_key = re.sub(r"\W+", "", record["title"].lower())
        if record["doi"] not in state["records"] and title_key not in existing_titles:
            candidates.append(record)
            existing_titles.add(title_key)
        if len(candidates) >= 40:
            break
    for record in candidates:
        state["records"][record["doi"]] = record
        entry["items"].append(record["doi"])
    entry.update(run_at=now.strftime("%Y-%m-%d %H:%M %Z"), errors=errors)
    if not errors:
        state["last_success"] = day
    render(state)
    atomic_write(STATE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(f"{day}: {len(candidates)} new records; {len(errors)} source errors")


if __name__ == "__main__":
    update()
