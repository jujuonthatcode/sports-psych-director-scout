
import csv
import io
import re
import json
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from ddgs import DDGS

# PAGE CONFIGURATION
st.set_page_config(
    page_title="Sports Psych Director Scout",
    page_icon="🧠",
    layout="wide"
)

# MUSE-INSPIRED DARK DESIGN
st.markdown("""
<style>
.stApp {
    background: #0b1020;
    color: #eef4ff;
}
.block-container {
    padding-top: 2rem;
    max-width: 1250px;
}
h1, h2, h3 {
    color: #f4f8ff !important;
}
.eyebrow {
    color: #31d8e9;
    letter-spacing: 3px;
    font-weight: 700;
    font-size: 12px;
}
.panel {
    background: #131e36;
    border: 1px solid #2b3c59;
    border-radius: 16px;
    padding: 18px;
    margin: 8px 0 18px;
}
.subtle {
    color: #a9b8d2;
    font-size: 13px;
}
div[data-testid="stMetric"] {
    background: #182745;
    border: 1px solid #30486e;
    padding: 16px;
    border-radius: 14px;
}
a {
    color: #42dbe9 !important;
}
</style>
""", unsafe_allow_html=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# SEARCH ONLINE
def search_web(query, limit):
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=limit))


# INSPECT ARTICLES AND AUTHORS
@st.cache_data(ttl=3600, show_spinner=False)
def inspect_page(url):
    data = {
        "author": "Not identified",
        "author_profile": "",
        "author_bio": "",
        "publication": urlparse(url).netloc,
        "published": "Not identified",
        "page_text": "",
        "status": "Unavailable"
    }

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=12
        )
        response.raise_for_status()

        if "text/html" not in response.headers.get(
            "Content-Type", "text/html"
        ):
            data["status"] = "Not an HTML page"
            return data

        soup = BeautifulSoup(
            response.text[:1500000],
            "html.parser"
        )

        def meta(*names):
            for name in names:
                tag = (
                    soup.find("meta", attrs={"name": name})
                    or soup.find(
                        "meta",
                        attrs={"property": name}
                    )
                )
                if tag and tag.get("content"):
                    return tag["content"].strip()
            return ""

        data["author"] = (
            meta(
                "author",
                "article:author",
                "parsely-author"
            )
            or "Not identified"
        )

        data["published"] = (
            meta(
                "article:published_time",
                "datePublished",
                "date",
                "pubdate"
            )
            or "Not identified"
        )

        data["publication"] = (
            meta("og:site_name")
            or data["publication"]
        )

        # LOOK FOR STRUCTURED AUTHOR INFORMATION
        for node in soup.find_all(
            "script",
            type="application/ld+json"
        ):
            try:
                obj = json.loads(
                    node.string or node.get_text()
                )

                items = obj if isinstance(obj, list) else [obj]

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    if "@graph" in item:
                        items.extend(
                            x for x in item["@graph"]
                            if isinstance(x, dict)
                        )

                    author = item.get("author")

                    if isinstance(author, list):
                        author = author[0] if author else None

                    if isinstance(author, dict):
                        data["author"] = (
                            author.get("name")
                            or data["author"]
                        )
                        data["author_profile"] = (
                            author.get("url") or ""
                        )
                        data["author_bio"] = (
                            author.get("description") or ""
                        )

                    elif isinstance(author, str):
                        data["author"] = author

                    data["published"] = (
                        item.get("datePublished")
                        or data["published"]
                    )

            except Exception:
                pass

        # EXTRACT ARTICLE TEXT
        for tag in soup([
            "script", "style", "nav",
            "footer", "header"
        ]):
            tag.decompose()

        main = (
            soup.find("article")
            or soup.find("main")
            or soup.body
            or soup
        )

        data["page_text"] = " ".join(
            main.stripped_strings
        )[:18000]

        data["status"] = "Read"

    except Exception as exc:
        data["status"] = (
            f"Could not read: {type(exc).__name__}"
        )

    return data


# EXTRACT RELEVANT PASSAGES
def extract_evidence(text, keywords):
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    matches = [
        sentence.strip()
        for sentence in sentences
        if 45 <= len(sentence) <= 450
        and any(
            word.lower() in sentence.lower()
            for word in keywords
        )
    ]

    return matches[:3]


# DASHBOARD HEADER
st.markdown(
    '<div class="eyebrow">'
    'AI RESEARCH AGENT · SPORT PSYCHOLOGY'
    '</div>',
    unsafe_allow_html=True
)

st.title("🧠 Sports Psych Director Scout")

st.caption(
    "Discover what sports directors and club leaders "
    "say about psychology and performance, "
    "with sources and author attribution."
)

st.markdown(
    "**01 Configure　　"
    "02 Search · Read　　"
    "03 Evidence · Analysis · Downloads**"
)


# SIDEBAR CONTROLS
with st.sidebar:
    st.header("Research Settings")

    query = st.text_input(
        "Search topic",
        "sports directors mental performance"
    )

    keywords = st.text_input(
        "Evidence keywords",
        "psychology, mental, mindset, "
        "performance, confidence, pressure"
    )

    max_results = st.slider(
        "Search results",
        3, 20, 8
    )

    read_pages = st.checkbox(
        "Read public article pages",
        value=True
    )

    st.caption(
        "Research public sources only. "
        "Verify quotations against originals."
    )

    run = st.button(
        "🔎 Run Research",
        type="primary",
        use_container_width=True
    )


# STORE RESULTS
if "records" not in st.session_state:
    st.session_state.records = []

if "last_query" not in st.session_state:
    st.session_state.last_query = ""


# RUN RESEARCH
if run:
    try:
        with st.spinner(
            "Searching and reviewing sources..."
        ):
            hits = search_web(query, max_results)
            records = []

            for hit in hits:
                url = (
                    hit.get("href")
                    or hit.get("url")
                    or ""
                )

                if not url.startswith("http"):
                    continue

                if read_pages:
                    info = inspect_page(url)
                else:
                    info = {
                        "author": "Not identified",
                        "author_profile": "",
                        "author_bio": "",
                        "publication": urlparse(url).netloc,
                        "published": "Not identified",
                        "page_text": "",
                        "status": "Not read"
                    }

                records.append({
                    "title": hit.get(
                        "title", "Untitled"
                    ),
                    "url": url,
                    "snippet": hit.get("body", ""),
                    "query": query,
                    **info
                })

            st.session_state.records = records
            st.session_state.last_query = query

    except Exception as exc:
        st.error(f"Search failed: {exc}")


records = st.session_state.records

terms = [
    x.strip()
    for x in keywords.split(",")
    if x.strip()
]

read = [
    r for r in records
    if r["status"] == "Read"
]

evidence = [
    (r, sentence)
    for r in read
    for sentence in extract_evidence(
        r["page_text"], terms
    )
]

verified_quotes = 0


# DASHBOARD TABS
tabs = st.tabs([
    "📊 Overview",
    "💬 Evidence",
    "🧩 Themes & Gaps",
    "👤 Writers & Sources",
    "🔎 Search Log",
    "⬇️ Downloads",
    "📗 Guide & Scoring"
    "🌐 Social Media"

])


# TAB 1: OVERVIEW
with tabs[0]:
    st.subheader("Research Overview")

    a, b, c, d = st.columns(4)

    a.metric(
        "Sources Found",
        len(records)
    )

    b.metric(
        "Pages Read",
        len(read)
    )

    c.metric(
        "Relevant Passages",
        len(evidence)
    )

    d.metric(
        "Verified Speaker Quotes",
        verified_quotes
    )

    st.markdown("#### Research Pipeline")

    columns = st.columns(4)

    steps = [
        (
            "Search",
            "Discover relevant public pages"
        ),
        (
            "Read & Extract",
            "Find passages and article bylines"
        ),
        (
            "Verify",
            "Confirm original wording and speakers"
        ),
        (
            "Analyse",
            "Identify themes and research gaps"
        )
    ]

    for column, (title, description) in zip(
        columns, steps
    ):
        with column:
            st.markdown(
                f'<div class="panel">'
                f'<b>{title}</b>'
                f'<p class="subtle">{description}</p>'
                f'</div>',
                unsafe_allow_html=True
            )

    if not records:
        st.info(
            "Use the sidebar to run your first search."
        )


# TAB 2: EVIDENCE
with tabs[1]:
    st.subheader("Evidence From Articles")

    st.caption(
        "These passages match your keywords. "
        "They are not automatically verified "
        "quotes from named sports directors."
    )

    for record, sentence in evidence:
        with st.container(border=True):

            st.markdown(
                f'**{record["title"]}**'
            )

            st.write(sentence)

            st.caption(
                f'Written by: {record["author"]} '
                f'· {record["publication"]}'
            )

            st.link_button(
                "Open Original Source",
                record["url"]
            )

    if not evidence:
        st.info(
            "No matching passages yet. "
            "Run a search or change your keywords."
        )


# TAB 3: THEMES AND GAPS
with tabs[2]:
    st.subheader("Themes & Research Gaps")

    themes = {
        "Mental Health": [
            "mental health",
            "wellbeing",
            "well-being"
        ],
        "Confidence": [
            "confidence",
            "self-belief"
        ],
        "Pressure": [
            "pressure",
            "stress",
            "anxiety"
        ],
        "Culture": [
            "culture",
            "leadership",
            "team"
        ],
        "Performance": [
            "performance",
            "performance psychology"
        ],
        "Recovery": [
            "recovery",
            "sleep",
            "rest"
        ]
    }

    for theme, words in themes.items():

        count = sum(
            any(
                word in sentence.lower()
                for word in words
            )
            for _, sentence in evidence
        )

        st.progress(
            min(
                count / max(len(evidence), 1),
                1
            ),
            text=f"{theme}: {count} matching passages"
        )

    st.info(
        "These are keyword counts, "
        "not AI-generated conclusions."
    )


# TAB 4: WRITERS AND SOURCES
with tabs[3]:
    st.subheader("Writers & Sources")

    st.caption(
        "Discover who wrote an article, "
        "where it was published, and "
        "which people were quoted."
    )

    for record in records:

        with st.expander(record["title"]):

            st.write(
                "**Written by:**",
                record["author"]
            )

            st.write(
                "**Publication:**",
                record["publication"]
            )

            st.write(
                "**Published:**",
                record["published"]
            )

            st.write(
                "**About the Writer:**",
                record["author_bio"]
                or "Biography not available"
            )

            profile = record["author_profile"]

            if profile.startswith("http"):
                st.link_button(
                    "View Author Profile",
                    profile
                )

            st.write(
                "**Sports Director / Person Quoted:** "
                "Not yet verified"
            )

            st.write(
                "**Source Status:**",
                record["status"]
            )

            st.link_button(
                "Read Full Article",
                record["url"]
            )

    if not records:
        st.info(
            "Run research to discover "
            "writers and sources."
        )


# TAB 5: SEARCH LOG
with tabs[4]:
    st.subheader("Search Log")

    st.write(
        "**Latest Search:**",
        st.session_state.last_query
        or "No search yet"
    )

    for record in records:
        st.write(
            f'{record["status"]} — '
            f'{record["title"]}'
        )

        st.write(record["url"])


# TAB 6: DOWNLOADS
with tabs[5]:
    st.subheader("Download Research")

    if records:

        output = io.StringIO()

        fields = [
            "title",
            "url",
            "author",
            "author_profile",
            "author_bio",
            "publication",
            "published",
            "status",
            "snippet",
            "query"
        ]

        writer = csv.DictWriter(
            output,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(records)

        st.download_button(
            "Download Research CSV",
            output.getvalue().encode("utf-8-sig"),
            file_name="sports_psych_sources.csv",
            mime="text/csv"
        )

        report = (
            "# Sports Psych Director Scout\n\n"
            f'Query: {st.session_state.last_query}\n\n'
        )

        for record in records:
            report += (
                f'## {record["title"]}\n'
                f'- URL: {record["url"]}\n'
                f'- Author: {record["author"]}\n'
                f'- Publication: {record["publication"]}\n'
                f'- Date: {record["published"]}\n'
                f'- Status: {record["status"]}\n\n'
            )

        st.download_button(
            "Download Research Report",
            report,
            file_name="sports_psych_report.md"
        )

    else:
        st.info(
            "Run research before downloading."
        )


# TAB 7: GUIDE
with tabs[6]:
    st.subheader("Guide & Scoring")

    st.markdown("""
    ### How the Research Agent Works

    **1. Search**

    Finds publicly available articles and discussions
    about sports psychology and performance.

    **2. Read**

    Opens accessible pages and extracts relevant text.

    **3. Identify Writers**

    Attempts to identify article authors, publication
    information, dates, and available author profiles.

    **4. Review Evidence**

    Finds passages containing your research keywords.

    **5. Analyse Themes**

    Counts matching references to topics such as
    mental health, confidence, pressure, and recovery.

    **6. Export Research**

    Saves collected sources as downloadable reports.

    ### Research Accuracy

    - Article authors are separate from interviewees.
    - Quotations require original-source verification.
    - Missing information is marked as unavailable.
    - Theme counts do not establish scientific conclusions.
    - Public sources must be used responsibly.
    """)


# SOCIAL MEDIA RESEARCH TAB

with tabs[8]:
    st.subheader("Social Media Listening")

    st.caption(
        "Discover public sports conversations on X "
        "and indexed LinkedIn posts."
    )

    social_topic = st.text_input(
        "Sports discussion topic",
        value="athlete mental health OR mental performance",
        key="social_topic"
    )

    platforms = st.multiselect(
        "Platforms",
        ["X (Twitter)", "LinkedIn"],
        default=["X (Twitter)", "LinkedIn"]
    )

    audiences = st.multiselect(
        "People to research",
        [
            "All public discussions",
            "Directors and club leaders",
            "Coaches",
            "Athletes",
            "Parents and fans"
        ],
        default=["All public discussions"]
    )

    use_x_api = st.checkbox(
        "Use official X API (may incur charges)",
        value=False
    )

    if st.button("Search Social Media"):

        if not social_topic.strip():
            st.warning("Enter a search topic.")

        elif not platforms or not audiences:
            st.warning("Select a platform and audience.")

        else:
            social_results = []
            errors = []

            search_topic = social_topic.strip()

            if "All public discussions" not in audiences:

                role_queries = {
                    "Directors and club leaders":
                        '"sports director" OR "club director"',
                    "Coaches": "coach OR coaching",
                    "Athletes": "athlete OR player",
                    "Parents and fans": "parent OR fan"
                }

                roles = [
                    role_queries[a]
                    for a in audiences
                    if a in role_queries
                ]

                if roles:
                    search_topic += (
                        " (" + " OR ".join(roles) + ")"
                    )

            # DISCOVER INDEXED PUBLIC LINKS

            domains = {
                "X (Twitter)": "x.com",
                "LinkedIn": "linkedin.com/posts"
            }

            with st.spinner("Searching public sources..."):

                for platform in platforms:

                    domain = domains[platform]

                    try:
                        with DDGS() as searcher:
                            hits = list(
                                searcher.text(
                                    f"site:{domain} {search_topic}",
                                    max_results=10
                                )
                            )

                        for hit in hits:

                            url = (
                                hit.get("href")
                                or hit.get("url")
                                or ""
                            )

                            if not url.startswith("http"):
                                continue

                            social_results.append({
                                "platform": platform,
                                "type": "Indexed search preview",
                                "author": "Not verified",
                                "role": "Not verified",
                                "title": hit.get(
                                    "title", "Public discussion"
                                ),
                                "text": hit.get("body", ""),
                                "url": url
                            })

                    except Exception as error:
                        errors.append(
                            f"{platform}: {error}"
                        )

            # OPTIONAL OFFICIAL X API

            if "X (Twitter)" in platforms and use_x_api:

                try:
                    token = st.secrets.get(
                        "X_BEARER_TOKEN", ""
                    )
                except Exception:
                    token = ""

                if not token:
                    st.warning(
                        "Add X_BEARER_TOKEN to "
                        "Streamlit Secrets first."
                    )

                else:
                    try:
                        response = requests.get(
                            "https://api.x.com/2/tweets/search/recent",
                            headers={
                                "Authorization": f"Bearer {token}"
                            },
                            params={
                                "query":
                                    f"({social_topic}) lang:en "
                                    "-is:retweet",
                                "max_results": 25,
                                "tweet.fields":
                                    "author_id,created_at",
                                "expansions": "author_id",
                                "user.fields":
                                    "name,username,description"
                            },
                            timeout=20
                        )

                        response.raise_for_status()

                        payload = response.json()

                        users = {
                            user["id"]: user
                            for user in payload.get(
                                "includes", {}
                            ).get("users", [])
                        }

                        for post in payload.get("data", []):

                            author = users.get(
                                post.get("author_id"), {}
                            )

                            username = author.get(
                                "username", ""
                            )

                            link = (
                                f"https://x.com/{username}/"
                                f"status/{post['id']}"
                                if username else
                                f"https://x.com/i/web/status/"
                                f"{post['id']}"
                            )

                            social_results.append({
                                "platform": "X (Twitter)",
                                "type": "X API post or reply",
                                "author": author.get(
                                    "name", "Not identified"
                                ),
                                "role": "Not independently verified",
                                "title": "Public X discussion",
                                "text": post.get("text", ""),
                                "url": link,
                                "bio": author.get(
                                    "description", ""
                                ),
                                "date": post.get(
                                    "created_at", ""
                                )
                            })

                    except Exception as error:
                        errors.append(f"X API: {error}")

            # REMOVE DUPLICATES

            unique = {}

            for result in social_results:
                unique[result["url"]] = result

            st.session_state["social_results"] = list(
                unique.values()
            )

            st.session_state["social_errors"] = errors

    # DISPLAY RESULTS

    for error in st.session_state.get(
        "social_errors", []
    ):
        st.warning(error)

    results = st.session_state.get(
        "social_results", []
    )

    st.metric("Social Sources Found", len(results))

    for result in results:

        with st.container(border=True):

            st.markdown(
                f"**{result['platform']} — "
                f"{result['type']}**"
            )

            st.write(result["title"])
            st.write(result["text"])

            st.write(
                "**Writer:**", result["author"]
            )

            st.write(
                "**Professional Role:**", result["role"]
            )

            if result.get("bio"):
                st.write(
                    "**About the Writer:**",
                    result["bio"]
                )

            if result.get("date"):
                st.write(
                    "**Posted:**", result["date"]
                )

            st.link_button(
                "View Original Source",
                result["url"]
            )

    if not results:
        st.info(
            "Run a social search to discover "
            "posts and discussions."
        )

    else:
        import io
        import csv

        output = io.StringIO()

        fields = [
            "platform", "type", "author",
            "role", "title", "text",
            "url", "bio", "date"
        ]

        writer = csv.DictWriter(
            output,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(results)

        st.download_button(
            "Download Social Research CSV",
            output.getvalue().encode("utf-8-sig"),
            file_name="social_research.csv",
            mime="text/csv"
        )

