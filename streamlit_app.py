import csv, io, json, re, html as H
import requests, streamlit as st
from bs4 import BeautifulSoup

PROMPT = """You are Sports Psych Director Scout, a research agent.
Find comments in the ONE source page provided about psychology and performance in sport, made by sports directors and leaders of clubs. Return only verbatim, attributable quotes from that page.
INCLUDE ONLY: sporting director, technical director, director of football, director of performance, head of performance, club CEO, president, owner, general manager, league/federation/players-association directors for mental health or performance.
EXCLUDE players, head coaches, sport psychologists, academics, journalists and fans, unless a leader above is quoted (then label SECOND-HAND).
TOPICS: mental health, mindset, confidence, pressure, fear, psychological safety, resilience, culture and values, character/psychology in recruitment, sleep and recovery, mental skills training, hiring psychologists, wellbeing as performance infrastructure.
RULES: quote only words verbatim in the page text. Never invent a quote, name, role, date or fact. Do not repeat the ALREADY COLLECTED list or FINDS SO FAR. Prefer longer, substantive quotes. If nothing qualifies return [].
OUTPUT: a JSON list only, no commentary:
[{"speaker":"","role":"","club":"","date":"","quote":"","label":"DIRECT or SECOND-HAND","theme":"","context":"1-2 sentences: what they were discussing and why it matters","source_type":"interview, news, podcast, forum, club site, research, or other"}]"""

SYNTH = """You are Sports Psych Director Scout writing the analysis section of a report from the quotes and search stats provided. Write Markdown with headings: ## Themes that recur / ## Patterns and tensions / ## What leaders are actually doing / ## Gaps in this run. Base every claim on the quotes, name speakers, use the stats honestly, do not invent finds."""

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
MODES = {"Quick": {"queries": 6, "pages": 8}, "Standard": {"queries": 14, "pages": 18}, "Deep": {"queries": 28, "pages": 32}}

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

def llm(key, model, system, user):
    from openai import OpenAI
    r = OpenAI(api_key=key).chat.completions.create(model=model, temperature=0,
        messages=[{"role":"system","content":system},{"role":"user","content":user}])
    return r.choices[0].message.content.strip()

def extract(key, model, url, text, so_far):
    user = ("ALREADY COLLECTED (do not repeat):\n- " + "\n- ".join(SEEN)
        + "\n\nFINDS SO FAR (do not repeat):\n- "
        + ("\n- ".join(f"{f['speaker']}: {f['quote'][:60]}" for f in so_far) or "none")
        + f"\n\nSOURCE PAGE: {url}\n\nPAGE TEXT:\n" + text[:14000])
    raw = llm(key, model, PROMPT, user).removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(raw)
        return d if isinstance(d, list) else []
    except json.JSONDecodeError:
        return []

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

def score_hit(h, topics):
    t = (h["title"] + " " + h["snippet"]).lower()
    return sum(2 for r in ROLES if r in t) + sum(1 for x in topics if x.split()[0] in t) + (2 if "interview" in t or "podcast" in t else 0)

def to_csv(results):
    b = io.StringIO(); w = csv.writer(b)
    w.writerow(["speaker","role","club","date","quote","url","label","theme","context","source_type","verified_in_page_text"])
    for r in results:
        w.writerow([r.get(k,"") for k in ["speaker","role","club","date","quote","url","label","theme","context","source_type","verified"]])
    return b.getvalue()

def to_md(results, synthesis, sport, topics, log):
    L = [f"# Sports Psych Director Scout - detailed run", f"Sport: {sport} | Topics: {', '.join(topics)}",
         f"Queries: {len(log['queries'])} | Pages read: {log['pages_read']} | Failed: {log['pages_failed']} | Quotes: {len(results)}\n"]
    for i, r in enumerate(results, 1):
        L.append(f"## {i}. {r.get('speaker','')} - {r.get('role','')}, {r.get('club','')}")
        if r.get("date"): L.append(f"- Date: {r['date']}")
        L.append(f"> \"{r.get('quote','')}\"")
        L.append(f"- Context: {r.get('context','')}")
        L.append(f"- Source: {r.get('url','')} ({r.get('source_type','')})")
        L.append(f"- Label: {r.get('label','')} | Theme: {r.get('theme','')} | Verified in page text: {r.get('verified','')}\n")
    if synthesis: L.append(synthesis)
    L.append("\n## Search log")
    for q in log["queries"]: L.append(f"- {q}")
    L.append("\n## Sources")
    for s in log["sources"]: L.append(f"- {s['url']} - {s['status']}")
    return "\n".join(L)


st.set_page_config(
    page_title="Sports Psych Director Scout",
    layout="wide"
)

st.title("Sports Psych Director Scout")
st.write("Research sports psychology and athletic performance.")

query = st.text_input(
    "What would you like to research?",
    "sports directors mental performance"
)

if st.button("Search"):
    with st.spinner("Searching the web..."):
        results = web_search(query, n=5)

    if isinstance(results, dict):
        st.error(results.get("error", "Search failed."))
    elif not results:
        st.warning("No results found.")
    else:
        for result in results:
            st.subheader(result.get("title", "Untitled"))
            st.write(result.get("snippet", ""))
            st.write(result.get("url", ""))

