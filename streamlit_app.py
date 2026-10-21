"""
Sports Psych Director Scout — Streamlit tester app

What it does:
- Searches the web (DuckDuckGo) for comments from sports directors and club
  leaders about psychology and performance in sport.
- Fetches the top pages and extracts their text.
- If you paste an OpenAI API key in the sidebar, it sends that page text to the
  model with the agent's rules and returns only verified, attributable quotes.
- Without a key it still shows you the raw sources it found, so you can test
  the search side for free.

The key is only used in your session. It is never saved by this app.
Testers should use their OWN key, or the app owner can add one in Streamlit
Cloud under Settings > Secrets as OPENAI_API_KEY (never commit a key to GitHub).
"""

import json
import re

import requests
import streamlit as st
from bs4 import BeautifulSoup

# ---------------------------------------------------------------- agent rules

SYSTEM_PROMPT = """You are Sports Psych Director Scout, a research agent.

MISSION
Find comments in the source text provided about psychology and performance in
sport, made by sports directors and leaders of clubs, and return only verified,
attributable quotes that appear IN the source text provided.

WHO COUNTS - include only
- Sporting director, technical director, director of football
- Director of performance, head of performance, high-performance director
- Club CEO, president, owner, general manager
- League, federation or players' association directors for mental health/performance

EXCLUDE players, head coaches/managers, sport psychologists, academics,
journalists and fans, unless a leader above is quoted (then label second-hand).

TOPICS - mental health, mindset, confidence, pressure, fear, psychological
safety, resilience, culture and values, character/psychology in recruitment,
sleep and recovery, mental skills training, hiring psychologists, wellbeing
as performance infrastructure.

RULES
- Only quote words that appear verbatim in the source text provided.
- Never invent a quote, name, role, date or URL.
- Do not repeat anything in the ALREADY COLLECTED list provided.
- If nothing in the text qualifies, say so. Do not fill the gap with weaker
  material (coaches, players, fans).

OUTPUT - reply with a JSON list only, no commentary, in this shape:
[{"speaker": "", "role": "", "club": "", "date": "", "quote": "",
  "url": "", "label": "DIRECT", "theme": ""}]
Use an empty list [] if nothing qualifies."""

SEEN = [
    "James Bunce - AS Monaco - Everyone looks at sport from the neck down",
    "Chris Markham - Huddersfield Town - sports psychology shaped everything / England penalties",
    "Rasmus Ankersen - Brentford - sleep better, perform better",
    "Chris Haslam / Michael Caulfield - Brentford - mindset, safety, fear is the biggest thing",
    "FC Nordsjaelland - psychology embraced like tactical, physical, technical",
    "Chris O'Loughlin - Union Saint-Gilloise - culture, values, character scouting",
    "Dan Ashworth - Brighton - psychology drastically under-resourced / culture and confidence",
    "William Parham - NBPA - players perform better / health and wellness is sacred",
    "Dave Brailsford - British Cycling - aggregation of marginal gains",
    "Adam Beard - Fremantle Dockers - integrated performance including psychology",
    "Ryan Poles - Chicago Bears - mental skills blind spot",
    "John Lynch - San Francisco 49ers - mental health is a real thing / full-time clinician",
    "Roger Goodell - NFL - stigma that mental health is a weakness, it's not",
    "Kevin Cheveldayoff - Winnipeg Jets - doctors for mental health / team building",
    "Adam Silver - NBA - pervasive feelings of loneliness and melancholy",
    "Jeanie Buss - LA Lakers - don't shy away from players with mental health issues",
    "Ralf Rangnick - Red Bull - identity brought everyone together",
    "Glen Driscoll - Celtic/Liverpool - productivity paranoia / psychology consultants",
]

ROLE_WORDS = [
    "sporting director",
    "technical director",
    "director of performance",
    "head of performance",
    "general manager",
    "club CEO",
    "club owner",
]
TOPIC_WORDS = [
    "sports psychology",
    "mental health",
    "mental performance",
    "mindset psychology",
    "psychological safety",
]

# ------------------------------------------------------------------- helpers


def web_search(query, max_results=6):
    """Search DuckDuckGo. Returns a list of {title, url, snippet} dicts."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": h.get("title", ""), "url": h.get("href", ""), "snippet": h.get("body", "")}
            for h in hits
            if h.get("href")
        ]
    except Exception as exc:  # search is best-effort; surface the problem plainly
        st.warning(f"Search failed for '{query}': {exc}")
        return []


def fetch_text(url, limit=6000):
    """Fetch a page and return readable text, truncated."""
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (SportsPsychDirectorScout/1.0)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
        return text[:limit]
    except Exception:
        return ""


def extract_quotes(api_key, model, sources_text):
    """Ask the model to extract qualifying quotes. Returns a list of dicts."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    user_msg = (
        "ALREADY COLLECTED (do not repeat):\n- "
        + "\n- ".join(SEEN)
        + "\n\nSOURCE TEXT:\n"
        + sources_text
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    raw = resp.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        st.error("The model did not return clean JSON. Raw reply:")
        st.code(raw)
        return []


def to_markdown(results, sport, topic):
    lines = [f"# Sports Psych Director Scout — run: {sport} / {topic}\n"]
    if not results:
        lines.append("No new verified director quotes found in this run.\n")
    for i, r in enumerate(results, 1):
        lines.append(f"## {i}. {r.get('speaker', '')} — {r.get('role', '')}, {r.get('club', '')}")
        if r.get("date"):
            lines.append(f"- Date: {r['date']}")
        lines.append(f"> \"{r.get('quote', '')}\"")
        lines.append(f"- Source: {r.get('url', '')}")
        lines.append(f"- Label: {r.get('label', '')} | Theme: {r.get('theme', '')}\n")
    return "\n".join(lines)


# ----------------------------------------------------------------------- UI

st.set_page_config(page_title="Sports Psych Director Scout", page_icon="🧠", layout="wide")
st.title("🧠 Sports Psych Director Scout")
st.write(
    "Finds **verified comments from sports directors and club leaders** "
    "(sporting directors, GMs, owners, performance directors) about "
    "**psychology and performance** in sport."
)

with st.sidebar:
    st.header("Your OpenAI key (optional)")
    api_key = st.text_input(
        "OpenAI API key",
        type="password",
        value=st.secrets.get("OPENAI_API_KEY", "") if "OPENAI_API_KEY" in st.secrets else "",
        help="Needed for quote extraction. Use your own key — it is not saved. "
        "Without a key you still get the raw sources the search found.",
    )
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"], index=0)
    st.divider()
    st.caption(
        "Rules are built in: director-level voices only, verbatim quotes only, "
        "nothing already in the seen list, and gaps reported honestly."
    )

col1, col2, col3 = st.columns(3)
with col1:
    sport = st.selectbox(
        "Sport",
        ["Football / soccer", "NBA (basketball)", "NFL (American football)",
         "MLB (baseball)", "NHL (ice hockey)", "Rugby", "AFL (Australian rules)",
         "Cycling", "All sports"],
    )
with col2:
    topic = st.selectbox("Topic focus", TOPIC_WORDS + ["culture and character in recruitment", "sleep and recovery"])
with col3:
    max_pages = st.slider("Pages to read per run", 3, 12, 6)

extra = st.text_input("Optional: a club, league or person's name to target", "")

if st.button("🔎 Run the agent", type="primary"):
    queries = []
    base_sport = "" if sport == "All sports" else sport
    for role in ROLE_WORDS[:4]:
        q = f"{role} {base_sport} {topic} interview".strip()
        if extra:
            q = f"{extra} {q}"
        queries.append(q)

    with st.spinner("Searching..."):
        found, seen_urls = [], set()
        for q in queries:
            for hit in web_search(q, max_results=5):
                if hit["url"] not in seen_urls:
                    seen_urls.add(hit["url"])
                    found.append(hit)
        found = found[: max_pages * 2]

    if not found:
        st.error("The search returned nothing. Try a broader sport/topic, or try again in a minute.")
        st.stop()

    st.subheader(f"Sources found ({len(found)})")
    for h in found:
        st.markdown(f"- [{h['title'] or h['url']}]({h['url']})")

    with st.spinner("Reading the top pages..."):
        chunks = []
        for h in found[:max_pages]:
            text = fetch_text(h["url"])
            if text:
                chunks.append(f"\n\n=== SOURCE: {h['url']} ===\n{text}")
        sources_text = "".join(chunks)[:60000]

    if not api_key:
        st.info(
            "No API key given, so here is the search side only. Paste an OpenAI key "
            "in the sidebar and run again to extract verified quotes from these pages."
        )
        st.stop()

    with st.spinner("Extracting verified director quotes..."):
        results = extract_quotes(api_key, model, sources_text)

    st.subheader(f"New verified quotes: {len(results)}")
    if not results:
        st.warning(
            "Nothing in those pages qualified — that is a valid result. "
            "Try another sport, topic, or a named club/person."
        )
    for r in results:
        with st.container(border=True):
            st.markdown(f"**{r.get('speaker', '')}** — {r.get('role', '')}, {r.get('club', '')}")
            st.markdown(f"> {r.get('quote', '')}")
            st.caption(f"{r.get('label', '')} · {r.get('theme', '')} · {r.get('date', '')}")
            if r.get("url"):
                st.markdown(f"[Open the original source]({r['url']})")

    report = to_markdown(results, sport, topic)
    st.download_button(
        "⬇️ Download this run as Markdown",
        data=report,
        file_name="sports-psych-director-scout-run.md",
        mime="text/markdown",
    )

st.divider()
with st.expander("Already collected — the agent will not repeat these"):
    for item in SEEN:
        st.markdown(f"- {item}")
with st.expander("How to test this agent (scoring)"):
    st.markdown(
        "1. **Attribution** — every quote names a real director/leader, role and club.\n"
        "2. **Verbatim** — open 2 source links; the quoted words must actually be there.\n"
        "3. **No fabrication** — no quote, date or URL you cannot find at the source.\n"
        "4. **De-duplication** — nothing already in the list above.\n"
        "5. **Role discipline** — no players/coaches passed off as directors.\n"
        "6. **Gap honesty** — empty areas reported as gaps, not filled with weaker material.\n"
        "7. **Usefulness** — would a researcher keep at least half of these finds?"
    )
