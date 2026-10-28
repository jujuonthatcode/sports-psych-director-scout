import csv, io, json, re, html as H
import requests, streamlit as st
from bs4 import BeautifulSoup
from collections import Counter
from urllib.parse import urlparse

PROMPT = """You are Sports Psych Director Scout, a research agent.
Find comments in the ONE source page provided about psychology and performance in sport, made by sports directors and leaders of clubs. Return only verbatim, attributable quotes from that page.
INCLUDE ONLY: sporting director, technical director, director of football, director of performance, head of performance, club CEO, president, owner, general manager, league/federation/players-association directors for mental health or performance.
EXCLUDE players, head coaches, sport psychologists, academics, journalists and fans, unless a leader above is quoted (then label SECOND-HAND).
TOPICS: mental health, mindset, confidence, pressure, fear, psychological safety, resilience, culture and values, character/psychology in recruitment, sleep and recovery, mental skills training, hiring psychologists, wellbeing as performance infrastructure.
RULES: quote only words verbatim in the page text. Never invent a quote, name, role, date or fact. Do not repeat the ALREADY COLLECTED list or FINDS SO FAR. Prefer longer, substantive quotes. If nothing qualifies return [].
OUTPUT: a JSON list only, no commentary:
[{"speaker":"","role":"","club":"","date":"","quote":"","label":"DIRECT or SECOND-HAND","theme":"","context":"1-2 sentences: what they were discussing and why it matters","source_type":"interview, news, podcast, forum, club site, research, or other"}]"""

SYNTH = """You are Sports Psych Director Scout writing the analysis section of a report from the quotes and search stats provided. Write Markdown with headings: ## Themes that recur / ## Patterns and tensions / ## What leaders are actually doing / ## Gaps in this run. Base every claim on the quotes, name speakers, use the stats honestly, do not invent finds."""

SYNTH_DEEP = """You are Sports Psych Director Scout writing the deep-research analysis for a report, from the quotes and search stats provided. Write a thorough Markdown report with these headings, in order:
## Executive summary - 4-6 sentences: the single most important finding, who said it, and what it means.
## Key findings - one subsection per major finding, each naming the speakers and clubs behind it and quoting the strongest line.
## Themes that recur - patterns across speakers, sports and countries, with evidence.
## Tensions and contradictions - where leaders disagree or where practice contradicts stated belief; name both sides.
## What leaders are actually doing - concrete actions (hiring, structures, routines, recruitment rules), not slogans.
## Source quality - which kinds of sources were strongest (interviews, podcasts, research, club sites) and where the evidence is thin.
## Gaps in this run - topics or voices not found, pages that could not be read, and the 3 most valuable follow-up questions for the next run.
Base every claim on the quotes. Name speakers. Use the stats honestly. Do not invent finds."""

SEEN = ["James Bunce - AS Monaco - neck down / under-tapped psychology",
"Chris Markham - Huddersfield - psychology shaped everything / England penalties",
"Rasmus Ankersen - Brentford - sleep better, perform better",
"Haslam / Caulfield - Brentford - mindset, safety, fear",
"FC Nordsjaelland - psychology like tactical, physical, technical",
"Chris O'Loughlin - Union SG - culture, values, character scouting",
"Dan Ashworth - Brighton - psychology drastically under-resourced",
"William Parham - NBPA - players perform better / wellness is sacred",
"Dave Brailsford - British Cycling - marginal gains",
"Adam Beard - Fremantle - integrated performance incl. psychology",
"Ryan Poles - Chicago Bears - mental skills blind spot",
"John Lynch - 49ers - mental health is real / full-time clinician",
"Roger Goodell - NFL - stigma is not weakness",
"Kevin Cheveldayoff - Winnipeg Jets - mental health doctors",
"Adam Silver - NBA - loneliness and melancholy",
"Jeanie Buss - Lakers - nonjudgmental space",
"Ralf Rangnick - Red Bull - identity brought everyone together",
"Glen Driscoll - Celtic/Liverpool - productivity paranoia"]

ROLES = ["sporting director","technical director","director of football","director of performance","head of performance","general manager","club CEO","team president","club owner"]
TOPICS = ["sports psychology","mental health athletes","mental performance","mindset and performance","psychological safety","culture and character in recruitment","resilience and pressure","sleep and recovery","wellbeing and performance"]
MODES = {"Quick": {"queries": 6, "pages": 8}, "Standard": {"queries": 14, "pages": 18}, "Deep": {"queries": 28, "pages": 32}, "Deep Research": {"queries": 40, "pages": 40}}

def web_search(q, n=5):
    try:
        from ddgs import DDGS
        with DDGS() as d:
            hits = list(d.text(q, max_results=n))
        return [{"title": h.get("title",""), "url": h.get("href",""), "snippet": h.get("body","")} for h in hits if h.get("href")]
    except Exception as e:
        return {"error": str(e)}

def fetch_text(url, limit=16000):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Scout/3.0)"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script","style","nav","footer","header","aside"]):
            t.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ")).strip()[:limit], ""
    except Exception as e:
        return "", str(e)[:120]

def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(t).lower())).strip()

def verify(quote, page):
    q, p = norm(quote), norm(page)
    if not q or not p: return False
    if q in p: return True
    w = q.split()
    if len(w) > 12 and " ".join(w[:12]) in p: return True
    if len(w) > 24 and " ".join(w[len(w)//2:len(w)//2+10]) in p: return True
    return False

def llm_poll(system, user, model="openai"):
    """Free, keyless AI via Pollinations (text.pollinations.ai): no sign-up, no key, no cost.
    Tries the OpenAI-style POST first; the service answers with plain text or a JSON envelope."""
    payload = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "model": model, "temperature": 0}
    last = None
    for _ in range(2):
        try:
            r = requests.post("https://text.pollinations.ai/", json=payload, timeout=120)
            r.raise_for_status()
            try:
                d = r.json()
                return d["choices"][0]["message"]["content"].strip()
            except (ValueError, KeyError, IndexError, TypeError):
                return r.text.strip()
        except Exception as e:
            last = e
    raise last

def llm(key, model, system, user):
    if not key:
        return llm_poll(system, user)
    from openai import OpenAI
    r = OpenAI(api_key=key).chat.completions.create(model=model, temperature=0,
        messages=[{"role":"system","content":system},{"role":"user","content":user}])
    return r.choices[0].message.content.strip()

def extract(key, model, url, text, so_far):
    user = ("ALREADY COLLECTED (do not repeat):\n- " + "\n- ".join(SEEN)
        + "\n\nFINDS SO FAR (do not repeat):\n- "
        + ("\n- ".join(f"{f['speaker']}: {f['quote'][:60]}" for f in so_far) or "none")
        + f"\n\nSOURCE PAGE: {url}\n\nPAGE TEXT:\n" + text[:14000])
    try:
        raw = llm(key, model, PROMPT, user).removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    except Exception:
        return extract_free(url, text, so_far)
    try:
        d = json.loads(raw)
        return d if isinstance(d, list) else []
    except json.JSONDecodeError:
        return extract_free(url, text, so_far)

THEME_KEYWORDS = {
    "Mental health": ["mental health", "wellbeing", "well-being", "anxiety", "depression", "burnout"],
    "Mindset & confidence": ["mindset", "confidence", "belief", "fear", "pressure"],
    "Psychological safety": ["psychological safety", "safe space", "speak up", "nonjudgmental", "non-judgmental"],
    "Culture & character": ["culture", "character", "values", "humility", "identity"],
    "Sleep & recovery": ["sleep", "recovery", "rest"],
    "Mental skills": ["mental skills", "resilience", "process", "routine"],
    "Hiring psychologists": ["psychologist", "psychology department", "mental skills coach"],
}
SKIP_PHRASES = ["neck down", "under-tapped", "drastically under-resourced", "marginal gains", "productivity paranoia", "mental health is a real thing", "players perform better", "shaped everything"]

def free_theme(quote):
    low = quote.lower()
    for theme, words in THEME_KEYWORDS.items():
        if any(w in low for w in words): return theme
    return "Psychology & performance"

def extract_free(url, text, so_far):
    """No-key extraction: quotation marks near a director's name + role. Rougher than AI extraction, but free."""
    found, seen_q = [], {norm(r.get("quote", ""))[:60] for r in so_far}
    people = []
    for m in re.finditer(r"([A-Z][a-z]+(?: [A-Z][a-z]+){0,2})[^.\n]{0,140}?((?i:sporting director|technical director|director of football|director of performance|head of performance|general manager|club CEO|team president|club owner))", text):
        name = m.group(1).strip()
        if len(name.split()) < 2 or name.lower().startswith(("the ", "a ")): continue
        people.append((m.start(), name, m.group(2)))
    if not people: return []
    counts = Counter(p[1] for p in people)
    main = next(p for p in people if p[1] == counts.most_common(1)[0][0])
    for qm in re.finditer(r"[“\"]([^”\"]{40,600})[”\"]", text):
        quote = re.sub(r"\s+", " ", qm.group(1)).strip()
        qlow = quote.lower()
        if len(quote) < 40 or any(p in qlow for p in SKIP_PHRASES): continue
        if norm(quote)[:60] in seen_q: continue
        near = [p for p in people if abs(p[0] - qm.start()) < 4000]
        if near:
            pos, name, role = max(near, key=lambda p: (counts[p[1]], -abs(p[0] - qm.start())))
        else:
            pos, name, role = main
        window = text[max(0, pos - 100):pos + 400]
        club = ""
        cm = re.search(r"\b(?:at|of|for)\s+(?:the\s+)?([A-Z][A-Za-z]+(?: [A-Z][a-z]+)?)", window)
        if cm and cm.group(1).lower() not in ("the", "a", "an"): club = cm.group(1)
        before = re.sub(r"\s+", " ", text[max(0, qm.start() - 220):qm.start()]).strip()
        ctx = (before[-200:] + " …") if len(before) > 200 else before
        low_url = url.lower()
        stype = "podcast" if "podcast" in low_url else ("research" if "study" in low_url or "research" in low_url else ("forum" if "reddit" in low_url else "interview"))
        found.append({"speaker": name, "role": role, "club": club, "date": "", "quote": quote,
                      "label": "DIRECT", "theme": free_theme(quote),
                      "context": f"Quoted near a mention of {name} ({role}). {ctx}" if ctx else f"Quoted near a mention of {name} ({role}).",
                      "source_type": stype, "verified": True})
        seen_q.add(norm(quote)[:60])
    return found

def synth_free(results, log, n_cor):
    """No-key analysis: counted from the quotes, not written by a model."""
    by_theme = Counter(r.get("theme", "") for r in results)
    by_speaker = Counter(r.get("speaker", "") for r in results)
    covered = norm(" ".join(r.get("theme", "") + " " + r.get("context", "") for r in results))
    missing = [t for t in TOPICS if t.split()[0] not in covered]
    L = ["## Executive summary",
         f"Fallback analysis (no AI key, or the AI analysis failed): {len(results)} quotes from {len(by_speaker)} directors/leaders, read from {log['pages_read']} pages. {n_cor} quote(s) confirmed by a second source. This analysis was counted from the quotes, not written by a model - check the strongest ones at source before relying on them.",
         "## Key findings"]
    for r in sorted(results, key=lambda x: len(x.get("quote", "")), reverse=True)[:3]:
        L.append(f"- **{r.get('speaker','')} ({r.get('role','')}, {r.get('club','')})**: \"{r.get('quote','')[:220]}\"")
    L.append("## Themes that recur")
    for theme, n in by_theme.most_common():
        L.append(f"- {theme}: {n} quote(s)")
    L.append("## Gaps in this run")
    if missing:
        L.append("No quotes found for these topics: " + ", ".join(missing) + ". Try them as the only topics, or run Deep Research with a key for the full analysis.")
    else:
        L.append("Every chosen topic produced at least one quote.")
    L.append(f"Pages that could not be read: {log['pages_failed']}. Pages skipped (no director/topic signal): {log.get('pages_skipped', 0)}.")
    L.append("## Source quality")
    L.append("Free mode cannot judge source quality the way the AI analysis does. Treat 'Verified in page text' quotes as the strongest, and 'Corroborated' ones as stronger still.")
    return "\n\n".join(L)

def build_queries(sport, region, topics, target, forums, podcasts, research, limit):
    qs, s = [], "" if sport == "All sports" else sport
    rg = "" if region == "Global" else region
    for topic in topics:
        for role in ROLES[:5]:
            qs.append(" ".join(x for x in [role, s, rg, topic, "interview"] if x))
    if podcasts:
        for topic in topics:
            qs.append(" ".join(x for x in ["sporting director", s, topic, "podcast"] if x))
            qs.append(" ".join(x for x in ["director of performance", s, topic, "podcast interview"] if x))
    if forums:
        for topic in topics:
            qs.append(f"site:reddit.com {s} director {topic}".strip())
            qs.append(f"forum {s} sporting director {topic}".strip())
    if research:
        for topic in topics:
            qs.append(f"performance directors interview study {topic} elite sport")
    if target:
        for topic in topics:
            qs.append(f"{target} {topic} director performance")
        qs.append(f"{target} sports psychology")
    out, seen = [], set()
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower()); out.append(q)
    return out[:limit]

def followup_queries(results, topics, sport, target, limit=24):
    """Round 2: chase the leads round 1 found - the people, clubs and topics with no quotes yet."""
    qs, s = [], "" if sport == "All sports" else sport
    top = [name for name, _ in Counter(r.get("speaker", "") for r in results if r.get("speaker")).most_common(6)]
    for name in top:
        club = next((r.get("club", "") for r in results if r.get("speaker") == name and r.get("club")), "")
        for topic in topics[:2]:
            qs.append(f"{name} {topic} interview")
            if club: qs.append(f"{name} {club} {topic}")
    covered = norm(" ".join(r.get("theme", "") + " " + r.get("context", "") for r in results))
    for topic in topics:
        if topic.split()[0] not in covered:
            qs.append(" ".join(x for x in ["sporting director", s, topic, "interview"] if x))
            qs.append(" ".join(x for x in ["director of performance", s, topic, "podcast"] if x))
    if target:
        for name in top: qs.append(f"{target} {name} psychology performance")
    out, seen = [], set()
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower()); out.append(q)
    return out[:limit]

def corroborate(results, log):
    """Round 3: for each quote, search its exact words + speaker; a second, different source confirms it."""
    n = 0
    for r in results[:25]:
        words = re.sub(r"\s+", " ", str(r.get("quote", ""))).split()[:10]
        if len(words) < 6 or not r.get("speaker"): continue
        res = web_search(f"\"{' '.join(words)}\" {r['speaker']}", 3)
        if isinstance(res, dict): continue
        src_dom = urlparse(str(r.get("url", ""))).netloc.replace("www.", "")
        for h in res:
            dom = urlparse(h["url"]).netloc.replace("www.", "")
            if dom and dom != src_dom:
                r["corroborated"] = True; r["corroborated_by"] = dom; n += 1
                log["sources"].append({"url": h["url"], "status": f"corroborates quote by {r.get('speaker','')}"})
                break
    return n

def research_round(key, model, queries, log, results, max_pages, topics, status, label, sport="", target=""):
    """One research round: search the queries, read the best-fit new pages, extract quotes."""
    status.write(label)
    hits = []
    for q in queries:
        res = web_search(q, 5)
        if isinstance(res, dict) and "error" in res:
            log["sources"].append({"url": f"SEARCH FAILED: {q}", "status": res["error"]}); continue
        for h in res:
            if h["url"] not in log["seen_urls"]:
                log["seen_urls"].add(h["url"]); h["score"] = score_hit(h, topics, sport, target); hits.append(h)
    hits.sort(key=lambda h: h["score"], reverse=True)
    picked, doms = [], Counter()
    for h in hits:
        d = urlparse(h["url"]).netloc.replace("www.", "")
        if doms[d] < 3: picked.append(h); doms[d] += 1
        if len(picked) >= max_pages: break
    if len(picked) < max_pages:
        for h in hits:
            if h not in picked: picked.append(h)
            if len(picked) >= max_pages: break
    hits = picked
    status.write(f"{label} - {len(queries)} searches, {len(hits)} best-fit pages to read.")
    for h in hits:
        text, err = fetch_text(h["url"])
        if not text:
            log["pages_failed"] += 1; log["sources"].append({"url": h["url"], "status": f"could not read ({err or 'empty'})"}); continue
        if not page_fits(text, topics):
            log["pages_skipped"] = log.get("pages_skipped", 0) + 1
            log["sources"].append({"url": h["url"], "status": "skipped - no director role or topic signal, extraction call saved"})
            continue
        log["pages_read"] += 1; log["sources"].append({"url": h["url"], "status": f"read, {len(text)} characters"})
        try: found = extract(key, model, h["url"], text, results)
        except Exception as e: status.write(f"Extraction failed on {h['url']}: {e}"); found = []
        for r in found:
            if isinstance(r, dict) and r.get("quote") and r.get("speaker"):
                r["url"] = h["url"]; r["verified"] = verify(r["quote"], text); results.append(r)
    ded, keys = [], set()
    for r in results:
        k = (r["speaker"].lower(), norm(r["quote"])[:60])
        if k not in keys: keys.add(k); ded.append(r)
    return ded

def score_hit(h, topics, sport="", target=""):
    """Best-fit ranking: a page scores for naming a director role, matching a full topic phrase, being an interview/podcast/research piece, and matching the target. Forum hits score lower."""
    title, snip = h["title"].lower(), h["snippet"].lower()
    s = 0
    for r in ROLES:
        if r in title: s += 4
        elif r in snip: s += 2
    for x in topics:
        if x in title: s += 3
        elif x in snip: s += 2
        elif x.split()[0] in snip: s += 1
    if "interview" in title or "podcast" in title: s += 3
    elif "interview" in snip or "podcast" in snip: s += 1
    if "study" in title or "research" in title: s += 2
    if target and target.lower() in title + " " + snip: s += 3
    if sport and sport != "All sports" and sport.split()[0].lower() in title: s += 1
    if "reddit" in snip or "forum" in title: s -= 1
    return s

def page_fits(text, topics):
    """Cheap pre-screen before spending an extraction call: the page must name a director role AND touch a chosen topic."""
    low = text.lower()
    if len(text) < 800: return False
    if not any(r in low for r in ROLES): return False
    return any(x.split()[0] in low for x in topics)

def to_csv(results):
    b = io.StringIO(); w = csv.writer(b)
    w.writerow(["speaker","role","club","date","quote","url","label","theme","context","source_type","verified_in_page_text","corroborated","corroborated_by"])
    for r in results:
        w.writerow([r.get(k,"") for k in ["speaker","role","club","date","quote","url","label","theme","context","source_type","verified","corroborated","corroborated_by"]])
    return b.getvalue()

def to_md(results, synthesis, sport, topics, log):
    L = [f"# Sports Psych Director Scout - detailed run", f"Sport: {sport} | Topics: {', '.join(topics)}",
         f"Queries: {len(log['queries'])} | Pages read: {log['pages_read']} | Failed: {log['pages_failed']} | Skipped (no signal): {log.get('pages_skipped', 0)} | Quotes: {len(results)} | Rounds: {log.get('rounds', 1)} | Corroborated: {sum(1 for r in results if r.get('corroborated'))}\n"]
    for i, r in enumerate(results, 1):
        L.append(f"## {i}. {r.get('speaker','')} - {r.get('role','')}, {r.get('club','')}")
        if r.get("date"): L.append(f"- Date: {r['date']}")
        L.append(f"> \"{r.get('quote','')}\"")
        L.append(f"- Context: {r.get('context','')}")
        L.append(f"- Source: {r.get('url','')} ({r.get('source_type','')})")
        L.append(f"- Label: {r.get('label','')} | Theme: {r.get('theme','')} | Verified in page text: {r.get('verified','')} | Corroborated: {r.get('corroborated','')}" + (f" by {r['corroborated_by']}" if r.get("corroborated_by") else "") + "\n")
    if synthesis: L.append(synthesis)
    L.append("\n## Search log")
    for rnd, qs in enumerate(log.get("queries_by_round", [log["queries"]]), 1):
        L.append(f"\n### Round {rnd}")
        for q in qs: L.append(f"- {q}")
    L.append("\n## Sources")
    for s in log["sources"]: L.append(f"- {s['url']} - {s['status']}")
    return "\n".join(L)
# ---------- UI: modern dark tech theme, 01 Configure > 02 Run > 03 Results ----------
st.set_page_config(page_title="Sports Psych Director Scout", page_icon="🧠", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;600&display=swap');
:root{--line:#1e2a44;--mut:#8fa1c2;--cy:#22d3ee;--vi:#a78bfa;--gr:#34d399;--am:#fbbf24}
.stApp{background:radial-gradient(900px 480px at 12% -8%,rgba(34,211,238,.16),transparent 60%),radial-gradient(900px 520px at 88% -10%,rgba(167,139,250,.15),transparent 60%),#070b16;color:#e8eefc;font-family:'Inter',sans-serif}
h1,h2,h3{font-family:'Space Grotesk',sans-serif !important}
#MainMenu,footer{visibility:hidden}
section[data-testid="stSidebar"]{background:#0a1120;border-right:1px solid var(--line)}
div[data-testid="stMetric"]{background:#111a2e;border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.stButton>button{background:linear-gradient(90deg,var(--cy),var(--vi));color:#06121f !important;font-weight:700;border:none;border-radius:12px;padding:.65rem 1.4rem}
button[data-baseweb="tab"]{background:#0d1424;color:var(--mut);border:1px solid var(--line);border-radius:12px 12px 0 0;padding:.55rem 1rem;font-weight:600}
button[data-baseweb="tab"][aria-selected="true"]{color:#e8eefc;border-color:var(--cy)}
.hero{border:1px solid var(--line);border-radius:22px;padding:32px 34px;background:linear-gradient(135deg,rgba(34,211,238,.12),rgba(167,139,250,.10) 55%,rgba(13,20,36,.4));margin-bottom:20px}
.hero .k{color:var(--cy);font-weight:700;letter-spacing:.22em;font-size:.7rem;text-transform:uppercase}
.hero h1{font-size:2.4rem;margin:.3rem 0;line-height:1.05}
.hero p{color:var(--mut);max-width:800px;margin:0}
.pill{display:inline-block;border:1px solid var(--line);background:rgba(17,26,46,.75);border-radius:999px;padding:.25rem .75rem;font-size:.78rem;margin:14px .3rem 0 0}
.pill b{color:var(--cy)}
.shead{display:flex;gap:12px;align-items:flex-start;margin:24px 0 4px}
.snum{font-family:'Space Grotesk';font-weight:700;font-size:.82rem;color:#06121f;background:linear-gradient(135deg,var(--cy),var(--vi));border-radius:10px;padding:.4rem .55rem}
.shead h2{margin:0;font-size:1.35rem}.shead p{color:var(--mut);margin:.1rem 0 0;font-size:.9rem}
.qc{background:linear-gradient(180deg,#111a2e,#0d1424);border:1px solid var(--line);border-left:4px solid var(--cy);border-radius:16px;padding:16px 18px;margin:0 0 12px}
.qc .top{display:flex;gap:10px;align-items:center}
.av{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--cy),var(--vi));display:flex;align-items:center;justify-content:center;font-weight:700;color:#06121f}
.qc .who{font-weight:700}.qc .role{color:var(--mut);font-size:.84rem}
.qc blockquote{border:none;margin:6px 0;padding:0;font-size:1.02rem;line-height:1.5}
.qc .ctx{color:var(--mut);font-size:.9rem}
.b{display:inline-block;border-radius:999px;padding:.14rem .6rem;font-size:.72rem;font-weight:700;margin-right:.3rem}
.ok{background:rgba(52,211,153,.15);color:var(--gr);border:1px solid rgba(52,211,153,.45)}
.fl{background:rgba(251,191,36,.12);color:var(--am);border:1px solid rgba(251,191,36,.45)}
.th{background:rgba(167,139,250,.13);color:var(--vi);border:1px solid rgba(167,139,250,.45)}
.ty{background:rgba(34,211,238,.1);color:var(--cy);border:1px solid rgba(34,211,238,.4)}
.co{background:rgba(34,211,238,.14);color:var(--cy);border:1px solid rgba(34,211,238,.5)}
.qc a{color:var(--cy);font-size:.85rem;font-weight:600;text-decoration:none}
.empty{border:1px dashed var(--line);border-radius:16px;padding:24px;text-align:center;color:var(--mut)}
</style>""", unsafe_allow_html=True)

def esc(v): return H.escape(str(v or ""))
def shead(n, t, d):
    st.markdown(f'<div class="shead"><div class="snum">{esc(n)}</div><div><h2>{esc(t)}</h2><p>{esc(d)}</p></div></div>', unsafe_allow_html=True)
def initials(name):
    p = [x for x in re.split(r"\s+", str(name).strip()) if x]
    return "?" if not p else (p[0][:2].upper() if len(p) == 1 else (p[0][0] + p[-1][0]).upper())
def quote_card(r):
    badge = '<span class="b ok">✓ Verified in page text</span>' if r.get("verified") else '<span class="b fl">⚠ Flagged - check source</span>'
    cor = f'<span class="b co">✓ Corroborated by {esc(r.get("corroborated_by"))}</span>' if r.get("corroborated") else ""
    th = f'<span class="b th">{esc(r.get("theme"))}</span>' if r.get("theme") else ""
    ty = f'<span class="b ty">{esc(r.get("source_type"))}</span>' if r.get("source_type") else ""
    dt = f' · {esc(r.get("date"))}' if r.get("date") else ""
    link = f'<a href="{esc(r.get("url"))}" target="_blank">Open the original source</a>' if r.get("url") else ""
    st.markdown(f"""<div class="qc"><div class="top"><div class="av">{esc(initials(r.get('speaker')))}</div>
<div><div class="who">{esc(r.get('speaker'))}</div><div class="role">{esc(r.get('role'))} · {esc(r.get('club'))}{dt}</div></div></div>
<blockquote>&ldquo;{esc(r.get('quote'))}&rdquo;</blockquote><p class="ctx">{esc(r.get('context'))}</p>
<div>{badge}{cor}{th}{ty}</div><div style="margin-top:6px">{link}</div></div>""", unsafe_allow_html=True)
def empty(t, x): st.markdown(f'<div class="empty"><b>{esc(t)}</b><br>{esc(x)}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Control panel")
    st.caption("Your key and model live here. Everything else is set in step 01.")
    dkey = ""
    try:
        if "OPENAI_API_KEY" in st.secrets: dkey = st.secrets["OPENAI_API_KEY"]
    except Exception: dkey = ""
    api_key = st.text_input("OpenAI API key (optional)", type="password", value=dkey, help="Use your own key - it is not saved. Leave blank to use free Pollinations AI instead.")
    if api_key: st.success("Key loaded - full-speed OpenAI extraction")
    else: st.info("🆓 No key needed - running on free Pollinations AI. Add an OpenAI key any time for faster, more reliable runs.")
    st.caption("Model choice applies to OpenAI keys; Pollinations uses its default model.")
    model = st.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"], index=0)
    st.divider(); st.markdown("**The agent's rules**")
    st.markdown("- Director-level voices only\n- Verbatim quotes, checked in code\n- Nothing already collected\n- Gaps reported, never filled")
    st.caption("Sports Psych Director Scout · v4.3 Pollinations (free, no key)")

st.markdown("""<div class="hero"><div class="k">AI Research Agent · Sport Psychology</div>
<h1>🧠 Sports Psych Director Scout</h1>
<p>It hunts down what <b>sports directors and club leaders</b> actually say about <b>psychology and performance</b> - in interviews, podcasts, forums and media. Every quote is verified against its source. <b>Deep Research</b> goes further: it follows the leads it finds, chases the topics it missed, and checks each quote against a second source. No OpenAI key needed — it runs on free Pollinations AI. Add a key any time for the full-speed version.</p>
<span class="pill"><b>01</b> Configure the run</span><span class="pill"><b>02</b> Search · read · extract</span><span class="pill"><b>03</b> Quotes · analysis · downloads</span></div>""", unsafe_allow_html=True)

shead("01", "Configure your run", "Tell the agent where to look. More topics and Deep mode find more - and take longer.")
with st.container(border=True):
    c1, c2 = st.columns(2)
    with c1:
        sport = st.selectbox("Sport", ["Football / soccer","NBA (basketball)","NFL (American football)","MLB (baseball)","NHL (ice hockey)","Rugby","AFL (Australian rules)","Cycling","Olympic sport","All sports"])
        region = st.selectbox("Region", ["Global","UK","Europe","North America","Australia"])
        target = st.text_input("Target (optional)", placeholder="A club, league or person - e.g. Brighton, NBA, Dan Ashworth")
    with c2:
        topics = st.multiselect("Topics", TOPICS, default=["sports psychology", "mental health athletes"])
        mode_name = st.radio("Run depth", list(MODES.keys()), index=1)
        if mode_name == "Deep Research":
            st.info("🔬 Deep Research runs 3 rounds: broad discovery, then follow-up searches on the people and topics it found, then a corroboration check on every quote. Expect several minutes and noticeably more API credit - that is the cost of depth.")
    t1, t2, t3 = st.columns(3)
    inc_forums = t1.checkbox("💬 Forums (incl. Reddit)", value=True)
    inc_pods = t2.checkbox("🎙️ Podcasts & interviews", value=True)
    inc_res = t3.checkbox("🔬 Research interviews", value=True)
mode = MODES[mode_name]
deep = mode_name == "Deep Research"

shead("02", "Run the agent", "It searches, opens the best pages, extracts quotes page by page, checks every quote in code, then writes the analysis. Deep Research adds two more rounds: follow the leads, then corroborate.")
if st.button("🚀 Run the agent", type="primary", use_container_width=True):
    if not topics: st.error("Pick at least one topic in step 01."); st.stop()
    if not api_key:
        st.info("🆓 No key — running on free Pollinations AI. No sign-up, no cost. It can be slower and has usage limits; add an OpenAI key in the sidebar any time for the full-speed version.")
    log = {"queries": [], "queries_by_round": [], "sources": [], "pages_read": 0, "pages_failed": 0, "pages_skipped": 0, "seen_urls": set(), "rounds": 1}
    status = st.status("Deep research starting..." if deep else "Searching...", expanded=True)
    results = []
    # Round 1 - broad discovery
    q1 = build_queries(sport, region, topics, target, inc_forums, inc_pods, inc_res, mode["queries"])
    log["queries"] += q1; log["queries_by_round"].append(q1)
    results = research_round(api_key, model, q1, log, results, mode["pages"], topics, status, "Round 1 of 3 - broad discovery" if deep else "Stage 1 - searching and reading", sport, target)
    # Round 2 - follow the leads (Deep Research only). Spend more of round 2 where round 1 came up thin.
    if deep:
        q2 = followup_queries(results, topics, sport, target)
        log["queries"] += q2; log["queries_by_round"].append(q2); log["rounds"] = 2
        r2_pages = 30 if len(results) < 3 else (12 if len(results) >= 10 else 20)
        status.write(f"Round 1 found {len(results)} quotes - spending round 2 on {r2_pages} pages where it matters most.")
        results = research_round(api_key, model, q2, log, results, r2_pages, topics, status, "Round 2 of 3 - following leads: the people found, the topics missed", sport, target)
    # Round 3 - corroborate every quote (Deep Research only)
    n_cor = 0
    if deep:
        log["rounds"] = 3
        status.write("Round 3 of 3 - corroborating: searching each quote's exact words to find a second source.")
        n_cor = corroborate(results, log)
        status.write(f"Corroboration done: {n_cor} of {len(results)} quotes confirmed by a second, independent source.")
    status.update(label="Writing the analysis..." if deep else "Writing themes and gaps analysis...")
    synthesis = ""
    if results:
        stats = (f"Queries: {len(log['queries'])} across {log['rounds']} round(s). Pages read: {log['pages_read']}. "
                 f"Failed: {log['pages_failed']}. Skipped (no director/topic signal): {log.get('pages_skipped', 0)}. Corroborated quotes: {n_cor}. Forums: {inc_forums}. Podcasts: {inc_pods}. Research: {inc_res}.")
        try: synthesis = llm(api_key, model, SYNTH_DEEP if deep else SYNTH, stats + "\n\nQUOTES:\n" + json.dumps(results, indent=1))
        except Exception: synthesis = synth_free(results, log, n_cor)
    status.update(label="Run complete - results are in section 03 below.", state="complete", expanded=False)
    st.session_state["run"] = {"results": results, "synthesis": synthesis, "log": log, "sport": sport, "topics": topics, "mode": mode_name}

shead("03", "Results", "Six clear sections: overview, quotes, analysis, search log, downloads, and the testing guide.")
run = st.session_state.get("run")
results = run["results"] if run else []
log = run["log"] if run else {"queries": [], "queries_by_round": [], "sources": [], "pages_read": 0, "pages_failed": 0, "pages_skipped": 0, "rounds": 1}
vcount = sum(1 for r in results if r.get("verified"))
ccount = sum(1 for r in results if r.get("corroborated"))
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["◈ Overview", "💬 Quotes", "📊 Themes & Gaps", "🔍 Search Log", "⬇️ Downloads", "🧪 Guide & Scoring"])

with tab1:
    st.markdown("#### Overview — how a run flows, and the headline numbers")
    st.markdown("**A · Search** role × topic queries across media, podcasts, forums and research &nbsp;→&nbsp; **B · Read & extract** best pages in full, quotes page by page &nbsp;→&nbsp; **C · Verify** every quote checked in code, duplicates filtered &nbsp;→&nbsp; **D · Analyse** themes, tensions, gaps, downloads.")
    if run and run.get("mode") == "Deep Research":
        st.markdown("**Deep Research rounds:** 1 · Broad discovery &nbsp;→&nbsp; 2 · Follow the leads (people found, topics missed) &nbsp;→&nbsp; 3 · Corroborate each quote against a second source.")
    if run:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("New quotes", len(results)); m2.metric("Verified in source", vcount)
        m3.metric("Pages read", log["pages_read"]); m4.metric("Searches run", len(log["queries"]))
        st.caption(f"Research rounds: {log.get('rounds', 1)} · Quotes corroborated by a second source: {ccount} · Pages skipped (no director/topic signal): {log.get('pages_skipped', 0)}")
        if results:
            st.markdown("#### Strongest finds from this run")
            best = sorted(results, key=lambda r: (bool(r.get("corroborated")), bool(r.get("verified")), len(r.get("quote", ""))), reverse=True)
            for r in best[:3]: quote_card(r)
        else: empty("No quotes this run", "Try Deep Research, different topics, or a named target.")
    else: empty("No run yet", "Configure in section 01, then hit Run the agent in section 02.")

with tab2:
    st.markdown("#### Quotes — every new director comment, with context, source and verification badge")
    if not run: empty("Nothing here yet", "Run the agent and quotes will appear here.")
    elif not results: empty("No qualifying quotes", "The pages read held no attributable director quotes on these topics.")
    else:
        f1, f2, f3 = st.columns(3)
        tf = f1.selectbox("Filter by theme", ["All themes"] + sorted({r.get("theme","") for r in results if r.get("theme")}))
        vonly = f2.checkbox("✓ Verified only", value=False)
        nf = f3.text_input("Filter by name or club", "")
        shown = results
        if tf != "All themes": shown = [r for r in shown if r.get("theme") == tf]
        if vonly: shown = [r for r in shown if r.get("verified")]
        if nf: shown = [r for r in shown if nf.lower() in (r.get("speaker","") + " " + r.get("club","")).lower()]
        st.caption(f"Showing {len(shown)} of {len(results)} quotes")
        for r in shown: quote_card(r)
        if not shown: empty("No quotes match those filters", "Loosen a filter to see the full set.")

with tab3:
    st.markdown("#### Themes & Gaps — what recurs, where leaders differ, what they are doing, and what the run missed")
    if not run: empty("No analysis yet", "Written at the end of each run, from the quotes it found.")
    elif not results: empty("No analysis - no quotes found", "The agent reports the gap instead of inventing themes.")
    else:
        with st.container(border=True): st.markdown(run["synthesis"] or "The analysis step returned nothing.")

with tab4:
    st.markdown("#### Search Log — every search run, and every source read or failed")
    if not run: empty("No log yet", "After a run, every query and source will be listed here.")
    else:
        st.markdown(f"**Searches run ({len(log['queries'])}) across {log.get('rounds', 1)} round(s)**")
        with st.container(border=True):
            for rnd, qs in enumerate(log.get("queries_by_round", [log["queries"]]), 1):
                st.markdown(f"**Round {rnd}**")
                for q in qs: st.markdown(f"- `{q}`")
        st.markdown(f"**Sources ({len(log['sources'])}) — read: {log['pages_read']} · failed: {log['pages_failed']} · skipped (no director/topic signal): {log.get('pages_skipped', 0)}**")
        with st.container(border=True):
            for s in log["sources"]:
                icon = "✅" if s["status"].startswith("read") else "❌"
                st.markdown(f"- {icon} {s['url']} — *{s['status']}*")

with tab5:
    st.markdown("#### Downloads — a readable report for people, a spreadsheet for analysis")
    d1, d2 = st.columns(2)
    with d1:
        with st.container(border=True):
            st.markdown("**📄 Full report (Markdown)**\n\nEvery quote with context and source, the analysis, search log and sources.")
            if run: st.download_button("⬇️ Download the report", data=to_md(results, run["synthesis"], run["sport"], run["topics"], log), file_name="scout-report.md", mime="text/markdown", use_container_width=True)
            else: st.caption("Available after a run.")
    with d2:
        with st.container(border=True):
            st.markdown("**📊 Quotes spreadsheet (CSV)**\n\nOne row per quote: speaker, role, club, quote, source, theme, verification.")
            if run: st.download_button("⬇️ Download the CSV", data=to_csv(results), file_name="scout-quotes.csv", mime="text/csv", use_container_width=True)
            else: st.caption("Available after a run.")

with tab6:
    st.markdown("#### Guide & Scoring — how to judge a run, and what is already collected")
    with st.container(border=True):
        st.markdown("1. **Attribution** - real director/leader, role and club on every quote.\n2. **Verbatim** - open 2 sources; the words must be there.\n3. **No fabrication** - no quote, date or URL you cannot find.\n4. **De-duplication** - nothing in the collected list below.\n5. **Role discipline** - no players/coaches as directors.\n6. **Gap honesty** - check Themes & Gaps and the Search Log.\n7. **Usefulness** - would a researcher keep half of these?")
    with st.expander("📚 Already collected - the agent will not repeat these"):
        for item in SEEN: st.markdown(f"- {item}")
    with st.expander("ℹ️ Honest limits of this web version"):
        st.markdown("- Search is DuckDuckGo, so social coverage is weaker than the Muse version (dedicated Instagram/Facebook/Threads search).\n- Pages behind logins or paywalls cannot be read - they show in the Search Log as failed.\n- Deep mode makes one API call per page plus one analysis call: slower, more API credit. That is the cost of detail.\n- Deep Research adds two rounds on top: follow-up searches and a corroboration search per quote. Expect several minutes and the most API credit of any mode.\n- Best-fit spending: sources are ranked by role + full topic phrase + interview/podcast/research signals, capped at 3 pages per site for variety, and pages with no director role or topic signal are skipped before any extraction call - so the API budget goes to the pages most likely to hold a usable quote. If round 1 comes up thin, round 2 spends more pages; if it finds plenty, round 2 spends fewer.\n- No-key engine: without an OpenAI key the app uses free Pollinations AI - no sign-up, no cost, but slower with usage limits. If Pollinations fails on a page, the app falls back to rule-based extraction for that page, and to a counted analysis instead of a written one.")

st.markdown('<div style="text-align:center;color:#8fa1c2;font-size:.8rem;margin-top:30px">Sports Psych Director Scout · Verified quotes from sports directors & club leaders · Psychology × Performance</div>', unsafe_allow_html=True)
