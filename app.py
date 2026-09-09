from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import requests
import streamlit as st

REFRESH_SECONDS = 30
TIMEZONES = {
    "Eastern Time": "America/New_York",
    "Central Time": "America/Chicago",
}
DEFAULT_TIMEZONE = "Eastern Time"

SPORTS = {
    "🏈 Football": [],
    "⚽ Men's Soccer": [],
    "⚽ Women's Soccer": [],
    "🏀 Men's Basketball": [],
    "🏀 Women's Basketball": [],
    "🏐 Women's Volleyball": [],
    "⚾ Baseball": [],
    "🥎 Softball": [],
}

DEFAULT_FAVORITES = {"Kentucky": "96", "Auburn": "2", "West Florida": "2908"}
TEAM_IDS = {
    "Kentucky": "96", "Auburn": "2", "West Florida": "2908", "Alabama": "333",
    "Georgia": "61", "Florida": "57", "Florida State": "52", "Miami": "2390",
    "LSU": "99", "Tennessee": "2633", "Clemson": "228", "Ohio State": "194",
    "Michigan": "130", "Notre Dame": "87",
}

st.set_page_config(
    page_title="College Sports Live",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.game-card { border:1px solid rgba(128,128,128,.35); border-radius:14px; padding:15px 18px; margin:8px 0; }
.score { font-size:30px; font-weight:800; float:right; }
.team { font-size:18px; font-weight:700; margin:8px 0; min-height:38px; }
.meta { color:#9ca3af; font-size:13px; }
</style>
""", unsafe_allow_html=True)


def today_in_timezone(timezone_name):
    return datetime.now(ZoneInfo(timezone_name)).date()


def _normalize_team_name(name):
    return " ".join(str(name or "").lower().replace("&", "and").replace(".", "").split())


@st.cache_data(ttl=86400)
def get_ncaa_schools_index():
    """Return normalized school-name -> official NCAA logo slug mappings."""
    url = "https://ncaa-api.henrygd.me/schools-index"
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        payload = payload.get("schools") or payload.get("data") or payload.get("items") or []
    if not isinstance(payload, list):
        return {}

    index = {}
    for school in payload:
        if not isinstance(school, dict):
            continue
        # ncaa-api currently returns: slug, name, long
        slug = school.get("slug") or school.get("team_seo") or school.get("seo")
        if not slug:
            continue
        names = [
            school.get("name"), school.get("long"), school.get("long_name"),
            school.get("school"), school.get("school_name"), school.get("short_name"),
            school.get("team_name"), school.get("displayName"), school.get("team_seo"),
            school.get("slug"),
        ]
        nested = school.get("names")
        if isinstance(nested, dict):
            names.extend(nested.get(k) for k in ("full", "short", "seo"))
        for name in names:
            key = _normalize_team_name(name)
            if key:
                index[key] = str(slug)
    return index


# Common NCAA naming differences that otherwise prevent a school-index match.
NCAA_LOGO_ALIASES = {
    "miami (fl)": "miami-fl",
    "miami fl": "miami-fl",
    "miami hurricanes": "miami-fl",
    "ole miss": "ole-miss",
    "mississippi": "ole-miss",
    "uconn": "connecticut",
    "connecticut huskies": "connecticut",
    "pitt": "pittsburgh",
    "pittsburgh panthers": "pittsburgh",
    "nc state": "north-carolina-state",
    "north carolina state": "north-carolina-state",
    "utsa": "utsa",
    "ucf": "ucf",
    "uwf": "west-florida",
}

def _slugify_logo_name(name):
    import re, unicodedata
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

@st.cache_data(ttl=86400, show_spinner=False)
def _logo_data_uri(url):
    """Fetch an NCAA SVG once on the server and embed it in the page.

    Embedding the cached SVG avoids the browser firing dozens of simultaneous
    requests at the public NCAA logo endpoint, which can cause lower cards to
    lose their logos when the endpoint rate-limits those requests.
    """
    if not url:
        return ""
    candidates = [url]
    if "?dark=true" in url:
        candidates.append(url.split("?", 1)[0])
    for candidate in candidates:
        try:
            r = requests.get(candidate, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            content = r.content
            if not content:
                continue
            encoded = base64.b64encode(content).decode("ascii")
            return f"data:image/svg+xml;base64,{encoded}"
        except Exception:
            continue
    return ""


def _ncaa_logo_url(team_names, team=None, school_index=None):
    """Build an NCAA logo URL using the exact school-index slug, then safe fallbacks."""
    team = team if isinstance(team, dict) else {}
    team_names = team_names if isinstance(team_names, dict) else {}
    candidates = [
        team_names.get("seo"), team_names.get("team_seo"), team_names.get("slug"),
        team.get("team_seo"), team.get("seo"), team.get("slug"),
        team_names.get("full"), team_names.get("short"), team.get("name"), team.get("displayName"),
    ]
    if school_index:
        for candidate in candidates:
            key = _normalize_team_name(candidate)
            if key in school_index:
                return f"https://ncaa-api.henrygd.me/logo/{school_index[key]}.svg?dark=true"
            alias = NCAA_LOGO_ALIASES.get(key)
            if alias:
                return f"https://ncaa-api.henrygd.me/logo/{alias}.svg?dark=true"
    for candidate in candidates:
        if candidate:
            alias = NCAA_LOGO_ALIASES.get(_normalize_team_name(candidate))
            slug = alias or _slugify_logo_name(candidate)
            if slug:
                return f"https://ncaa-api.henrygd.me/logo/{slug}.svg?dark=true"
    return ""


RANKING_CONFIGS = {
    "🏈 Football (AP Top 25)": ("football", "fbs", "associated-press"),
    "🏀 Men's Basketball (AP Top 25)": ("basketball-men", "d1", "associated-press"),
    "🏀 Women's Basketball (AP Top 25)": ("basketball-women", "d1", "associated-press"),
    "🏐 Women's Volleyball (AVCA)": ("volleyball-women", "d1", "avca-rankings"),
}


@st.cache_data(ttl=900)
def get_ncaa_rankings(sport_slug, division, poll_slug):
    url = f"https://ncaa-api.henrygd.me/rankings/{sport_slug}/{division}/{poll_slug}"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


def _extract_ranking_rows(payload):
    """Normalize NCAA ranking tables, including the current uppercase column names."""
    if not payload:
        return []
    candidates = []
    if isinstance(payload, dict):
        value = payload.get("data")
        if isinstance(value, list):
            candidates = value
        else:
            for key in ("rankings", "teams", "rows", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    candidates.extend(value)
    elif isinstance(payload, list):
        candidates = payload

    rows = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        team = item.get("team") if isinstance(item.get("team"), dict) else {}
        def pick(*keys):
            for key in keys:
                if key in item and item[key] not in (None, ""):
                    return item[key]
                upper = str(key).upper()
                if upper in item and item[upper] not in (None, ""):
                    return item[upper]
        name = pick("teamName", "school", "name") or team.get("name") or team.get("fullName") or team.get("displayName")
        rank = pick("rank", "ranking", "position")
        record = pick("record", "overallRecord", "winsLosses")
        points = pick("points", "votes", "totalPoints")
        previous = pick("previousRank", "lastWeek", "previous", "previous ranking")
        if name is not None and rank is not None:
            rows.append({"Rank": rank, "Team": name, "Record": record or "", "Points/Votes": points or "", "Previous": previous or ""})

    seen = set()
    unique = []
    for row in rows:
        key = (str(row["Rank"]), str(row["Team"]))
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique[:50]


def get_inline_ranking_maps():
    result = {}
    configs = {
        "🏈 Football": RANKING_CONFIGS["🏈 Football (AP Top 25)"],
        "🏀 Men's Basketball": RANKING_CONFIGS["🏀 Men's Basketball (AP Top 25)"],
        "🏀 Women's Basketball": RANKING_CONFIGS["🏀 Women's Basketball (AP Top 25)"],
        "🏐 Women's Volleyball": RANKING_CONFIGS["🏐 Women's Volleyball (AVCA)"],
    }
    for sport_name, (sport_slug, division, poll_slug) in configs.items():
        try:
            rows = _extract_ranking_rows(get_ncaa_rankings(sport_slug, division, poll_slug))
            result[sport_name] = {_normalize_team_name(r["Team"]): str(r["Rank"]).strip().lstrip("#") for r in rows}
        except Exception:
            result[sport_name] = {}
    return result


@st.cache_data(ttl=15)
def get_ncaa_game_detail(game_id):
    """Fetch NCAA game-center data on demand (used for volleyball set scores)."""
    if not game_id or str(game_id).startswith("ncaa-"):
        return None
    url = f"https://ncaa-api.henrygd.me/game/{game_id}"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15)
def get_ncaa_boxscore(game_id):
    """Fetch the NCAA boxscore as a fallback for set/period scoring."""
    if not game_id or str(game_id).startswith("ncaa-"):
        return None
    url = f"https://ncaa-api.henrygd.me/game/{game_id}/boxscore"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _first_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str) and not value.strip().isdigit():
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_volleyball_set_scores(payload, away_id="", home_id=""):
    """Best-effort parser for NCAA game-center set/period scoring structures."""
    if not payload:
        return []

    # Most NCAA game-center variants expose period/line/set scores somewhere in
    # a list. We inspect several naming variants because the upstream GraphQL
    # schema has changed between API releases.
    candidate_keys = {
        "sets", "setsscores", "setscores", "periods", "periodscores",
        "linescores", "linescore", "linescores", "periodscores",
    }

    def key_norm(k):
        return str(k).lower().replace("_", "").replace("-", "")

    # First try to find a single list whose rows contain both teams' values.
    for obj in _walk_json(payload):
        for key, value in obj.items():
            if key_norm(key) not in candidate_keys or not isinstance(value, list) or not value:
                continue
            rows = []
            for idx, row in enumerate(value):
                if not isinstance(row, dict):
                    continue
                label = row.get("name") or row.get("label") or row.get("period") or row.get("set") or row.get("number") or idx + 1
                away = row.get("awayScore", row.get("away_score"))
                home = row.get("homeScore", row.get("home_score"))
                if away is None or home is None:
                    scores = row.get("scores") or row.get("score")
                    if isinstance(scores, dict):
                        away = scores.get("away", scores.get(str(away_id)))
                        home = scores.get("home", scores.get(str(home_id)))
                if away is not None and home is not None:
                    a, h = _first_number(away), _first_number(home)
                    if a is not None and h is not None:
                        rows.append({"Set": str(label), "Away": a, "Home": h})
            if rows:
                return rows

    # Fallback: locate team objects that contain an array of set/period scores.
    team_rows = []
    for obj in _walk_json(payload):
        if not isinstance(obj, dict):
            continue
        team = obj.get("team") if isinstance(obj.get("team"), dict) else None
        team_name = ""
        team_key = ""
        if team:
            team_name = team.get("name") or team.get("nameShort") or team.get("displayName") or ""
            team_key = str(team.get("id") or "")
        elif obj.get("teamId") is not None:
            team_key = str(obj.get("teamId"))
            team_name = str(obj.get("teamName") or "")
        for key, value in obj.items():
            if key_norm(key) not in candidate_keys or not isinstance(value, list):
                continue
            vals = []
            for row in value:
                if isinstance(row, dict):
                    raw = row.get("score", row.get("points", row.get("value")))
                    n = _first_number(raw)
                    if n is not None:
                        vals.append(n)
                else:
                    n = _first_number(row)
                    if n is not None:
                        vals.append(n)
            if vals:
                team_rows.append((team_key, team_name, vals))

    if len(team_rows) >= 2:
        # Prefer rows matching the scoreboard's team IDs when available.
        away_row = next((r for r in team_rows if r[0] == str(away_id)), None)
        home_row = next((r for r in team_rows if r[0] == str(home_id)), None)
        chosen = [away_row, home_row] if away_row and home_row else team_rows[:2]
        a_vals, h_vals = chosen[0][2], chosen[1][2]
        rows = []
        for i in range(min(len(a_vals), len(h_vals))):
            rows.append({"Set": str(i + 1), "Away": a_vals[i], "Home": h_vals[i]})
        if rows:
            return rows

    return []


def get_ncaa_scoreboard(sport_slug, division, sport_name, timezone_name, target_date=None):
    """Fetch a dated NCAA scoreboard and normalize it to our app format."""
    local_date = target_date or today_in_timezone(timezone_name)
    date_path = local_date.strftime("%Y/%m/%d")
    url = f"https://ncaa-api.henrygd.me/scoreboard/{sport_slug}/{division}/{date_path}"

    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()

    raw_games = payload.get("games", []) if isinstance(payload, dict) else []
    events = []
    try:
        school_index = get_ncaa_schools_index()
    except Exception:
        school_index = {}

    for item in raw_games:
        game = item.get("game", item) if isinstance(item, dict) else {}
        if not isinstance(game, dict):
            continue

        away = game.get("away", {}) or {}
        home = game.get("home", {}) or {}
        away_names = away.get("names", {}) or {}
        home_names = home.get("names", {}) or {}

        away_name = away_names.get("full") or away_names.get("short") or away.get("name") or "Away"
        home_name = home_names.get("full") or home_names.get("short") or home.get("name") or "Home"
        away_logo = _ncaa_logo_url(away_names, away, school_index)
        home_logo = _ncaa_logo_url(home_names, home, school_index)
        game_id = str(game.get("gameID") or game.get("gameId") or f"ncaa-{away_name}-{home_name}")

        # Prefer NCAA's epoch timestamp; otherwise combine startDate + startTime.
        event_dt = None
        epoch = game.get("startTimeEpoch")
        if epoch not in (None, ""):
            try:
                value = float(epoch)
                if value > 100000000000:
                    value /= 1000
                event_dt = datetime.fromtimestamp(value, tz=ZoneInfo("UTC")).astimezone(ZoneInfo(timezone_name))
            except (TypeError, ValueError, OverflowError):
                event_dt = None

        if event_dt is None:
            start_date = game.get("startDate") or local_date.isoformat()
            start_time = game.get("startTime") or ""
            if isinstance(start_date, str) and isinstance(start_time, str) and start_time.strip():
                import re
                raw_time = start_time.strip()
                # The NCAA football feed can return a UTC calendar date in
                # startDate while startTime is explicitly labeled ET. For a
                # date-scoped request, the requested local date is the source
                # of truth in this fallback case. Otherwise a Thursday night
                # game can arrive as Friday in UTC and get filtered out.
                explicit_eastern = bool(re.search(r"\b(?:ET|EST|EDT)\b", raw_time, re.I))
                if explicit_eastern and target_date is not None:
                    start_date = local_date.isoformat()
                text = raw_time.replace(" ET", "").replace(" EST", "").replace(" EDT", "")
                match = re.match(r"^(\d{1,2}:\d{2})\s*(AM|PM)?", text, re.I)
                if match:
                    clock = match.group(1)
                    ampm = match.group(2) or ""
                    try:
                        naive = datetime.strptime(
                            f"{start_date[:10]} {clock} {ampm}".strip(),
                            "%Y-%m-%d %I:%M %p" if ampm else "%Y-%m-%d %H:%M",
                        )
                        # NCAA startTime is presented in Eastern Time in the old-format feed.
                        event_dt = naive.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(ZoneInfo(timezone_name))
                    except ValueError:
                        pass

        state_raw = str(game.get("gameState", game.get("status", "P"))).upper()
        state = "in" if state_raw in ("I", "LIVE", "IN") else ("post" if state_raw in ("F", "FINAL", "POST") else "pre")

        def safe_score(team):
            try:
                return int(team.get("score", 0) or 0)
            except (TypeError, ValueError):
                return 0

        away_score = safe_score(away)
        home_score = safe_score(home)

        # Normalize NCAA's response into the same shape the existing renderer uses.
        events.append({
            "id": game_id,
            "date": event_dt.isoformat() if event_dt else None,
            "status": {
                "type": {
                    "state": state,
                    "shortDetail": game.get("finalMessage") or game.get("startTime") or "",
                    "detail": game.get("finalMessage") or game.get("startTime") or "",
                },
                "displayClock": game.get("contestClock", ""),
                "period": game.get("currentPeriod", ""),
            },
            "competitions": [{
                "competitors": [
                    {"homeAway": "away", "team": {"id": str(away.get("id", "")), "displayName": away_name, "logo": away_logo, "conferences": away.get("conferences", [])}, "score": str(away_score)},
                    {"homeAway": "home", "team": {"id": str(home.get("id", "")), "displayName": home_name, "logo": home_logo, "conferences": home.get("conferences", [])}, "score": str(home_score)},
                ],
                "broadcasts": ([{"names": [game.get("network")]}] if game.get("network") else []),
                "_venue": game.get("venue") or game.get("venueName") or game.get("location") or "",
            }],
            "_sport_name": sport_name,
            "_sport": sport_slug,
            "_league": sport_slug,
            "_division": "NCAA D-I" if division == "d1" else division.upper(),
        })

    return {
        "events": events,
        "_diagnostic": {
            "source": "NCAA API",
            "url": url,
            "sport": sport_slug,
            "division": division,
            "raw_game_count": len(raw_games),
            "parsed_event_count": len(events),
            "sample_games": [
                {
                    "away": ((x.get("game", x) or {}).get("away", {}) or {}).get("names", {}) if isinstance(x, dict) else {},
                    "home": ((x.get("game", x) or {}).get("home", {}) or {}).get("names", {}) if isinstance(x, dict) else {},
                    "startTime": ((x.get("game", x) or {}).get("startTime") if isinstance(x, dict) else None),
                    "startDate": ((x.get("game", x) or {}).get("startDate") if isinstance(x, dict) else None),
                    "gameState": ((x.get("game", x) or {}).get("gameState") if isinstance(x, dict) else None),
                } for x in raw_games[:5]
            ],
        },
    }


# NCAA is now the primary source for every supported college sport.
NCAA_SPORTS = {
    "🏈 Football": [("football", "fbs"), ("football", "fcs")],
    "⚽ Men's Soccer": [("soccer-men", "d1")],
    "⚽ Women's Soccer": [("soccer-women", "d1")],
    "🏀 Men's Basketball": [("basketball-men", "d1")],
    "🏀 Women's Basketball": [("basketball-women", "d1")],
    "🏐 Women's Volleyball": [("volleyball-women", "d1")],
    "⚾ Baseball": [("baseball", "d1")],
    "🥎 Softball": [("softball", "d1")],
}


@st.cache_data(ttl=20)
def get_all_scoreboards(timezone_name, target_date=None):
    combined = []
    errors = []
    diagnostics = []
    for sport_name, configs in NCAA_SPORTS.items():
        for sport_slug, division in configs:
            try:
                data = get_ncaa_scoreboard(sport_slug, division, sport_name, timezone_name, target_date)
                if data.get("_diagnostic"):
                    diagnostics.append({"sport": sport_name, **data["_diagnostic"]})
                for event in data.get("events", []):
                    event["_sport_name"] = sport_name
                    combined.append(event)
            except requests.RequestException as exc:
                errors.append(f"{sport_name} ({sport_slug}/{division}): {exc}")
            except Exception as exc:
                errors.append(f"{sport_name} ({sport_slug}/{division}): {type(exc).__name__}: {exc}")
    return {"events": combined, "errors": errors, "diagnostics": diagnostics}


def _extract_conference(team):
    """Return a team conference name/slug from NCAA scoreboard data."""
    if not isinstance(team, dict):
        return ""
    conferences = team.get("conferences") or []
    if isinstance(conferences, dict):
        conferences = [conferences]
    if isinstance(conferences, list):
        for conf in conferences:
            if isinstance(conf, dict):
                name = (conf.get("conferenceName") or conf.get("name") or
                        conf.get("conference") or conf.get("conferenceSeo") or
                        conf.get("slug"))
                if name:
                    return str(name).strip()
    for key in ("conferenceName", "conference", "conferenceSeo", "conferenceSlug"):
        if team.get(key):
            return str(team[key]).strip()
    return ""


def _pretty_conference(value):
    """Turn NCAA conference slugs into friendly labels."""
    labels = {
        "sec": "SEC", "big-ten": "Big Ten", "big-12": "Big 12",
        "acc": "ACC", "pac-12": "Pac-12", "aac": "AAC",
        "sun-belt": "Sun Belt", "conference-usa": "Conference USA",
        "mountain-west": "Mountain West", "mac": "MAC", "independent": "Independent",
        "ivy-league": "Ivy League", "big-east": "Big East",
        "atlantic-10": "Atlantic 10", "wcc": "WCC", "mvc": "Missouri Valley",
        "a-10": "Atlantic 10", "american": "AAC",
    }
    key = _normalize_team_name(value).replace(" ", "-")
    return labels.get(key, str(value).strip())




def _format_record_value(value):
    """Normalize an NCAA record object/string into a compact W-L style string."""
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        text = value.strip()
        return text
    if isinstance(value, dict):
        # Common NCAA shapes: {wins, losses}, {win, loss}, {overallRecord: ...}
        for key in ("display", "text", "record", "overallRecord", "winsLosses"):
            if value.get(key) not in (None, ""):
                return _format_record_value(value.get(key))
        wins = value.get("wins", value.get("win", value.get("w")))
        losses = value.get("losses", value.get("loss", value.get("l")))
        if wins is not None and losses is not None:
            return f"{wins}-{losses}"
    return str(value).strip()


def _extract_team_record(team):
    """Find a team's current overall record across NCAA scoreboard response variants."""
    if not isinstance(team, dict):
        return ""
    direct_keys = (
        "record", "overallRecord", "winsLosses", "recordDisplay",
        "overall_record", "overall", "teamRecord", "records",
    )
    for key in direct_keys:
        if key in team:
            record = _format_record_value(team.get(key))
            if record:
                return record
    # Some NCAA responses nest record data under a team/standings object.
    for value in team.values():
        if isinstance(value, dict):
            record = _extract_team_record(value)
            if record:
                return record
    return ""


@st.cache_data(ttl=900, show_spinner=False)
def get_ncaa_standing_records(sport_slug, division):
    """Fetch cached NCAA standings and build team-name/ID -> overall record maps."""
    url = f"https://ncaa-api.henrygd.me/standings/{sport_slug}/{division}"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()
    result = {}

    def walk(value):
        if isinstance(value, dict):
            team = value.get("team") if isinstance(value.get("team"), dict) else value
            name = ""
            if isinstance(team, dict):
                name = team.get("name") or team.get("school") or team.get("teamName") or team.get("displayName") or ""
            record = _extract_team_record(value)
            if name and record:
                result[_normalize_team_name(name)] = record
                tid = team.get("id") if isinstance(team, dict) else None
                if tid not in (None, ""):
                    result[f"id:{tid}"] = record
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return result


def get_record_maps_for_games(games):
    """Merge scoreboard records, cached standings records, and ranking records."""
    maps = {}
    sport_slugs = {
        "🏈 Football": ["football", "fbs"],
        "⚽ Men's Soccer": ["soccer-men", "d1"],
        "⚽ Women's Soccer": ["soccer-women", "d1"],
        "🏀 Men's Basketball": ["basketball-men", "d1"],
        "🏀 Women's Basketball": ["basketball-women", "d1"],
        "🏐 Women's Volleyball": ["volleyball-women", "d1"],
        "⚾ Baseball": ["baseball", "d1"],
        "🥎 Softball": ["softball", "d1"],
    }
    needed = {g.get("sport") for g in games if g.get("sport") in sport_slugs}
    for sport in needed:
        slug, division = sport_slugs[sport]
        try:
            maps[sport] = get_ncaa_standing_records(slug, division)
        except Exception:
            maps[sport] = {}
    return maps

def parse_games(data, timezone_name):
    games = []
    for event in data.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        if len(competitors) < 2:
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        def score(c):
            try:
                return int(c.get("score", 0))
            except (TypeError, ValueError):
                return 0

        hs, aws = score(home), score(away)
        status = event.get("status", {})
        type_info = status.get("type", {})
        state = type_info.get("state", "pre")

        event_dt = None
        raw_event_date = event.get("date")
        if isinstance(raw_event_date, str) and raw_event_date.strip():
            try:
                event_dt = datetime.fromisoformat(raw_event_date.replace("Z", "+00:00")).astimezone(ZoneInfo(timezone_name))
            except (TypeError, ValueError):
                pass

        games.append({
            "id": event.get("id"),
            "event_date": event_dt.date() if event_dt else None,
            "event_time": event_dt,
            "sport": event.get("_sport_name", "College Sports"),
            "division": event.get("_division", "NCAA"),
            "home": home.get("team", {}).get("displayName", "Home"),
            "away": away.get("team", {}).get("displayName", "Away"),
            "home_id": str(home.get("team", {}).get("id", "")),
            "away_id": str(away.get("team", {}).get("id", "")),
            "home_record": _extract_team_record(home.get("team", {})),
            "away_record": _extract_team_record(away.get("team", {})),
            "home_logo": home.get("team", {}).get("logo", ""),
            "away_logo": away.get("team", {}).get("logo", ""),
            "away_conference": _pretty_conference(_extract_conference(away.get("team", {}))),
            "home_conference": _pretty_conference(_extract_conference(home.get("team", {}))),
            "home_score": hs,
            "away_score": aws,
            "diff": abs(hs - aws),
            "state": state,
            "detail": type_info.get("shortDetail") or type_info.get("detail") or "",
            "clock": status.get("displayClock", ""),
            "period": status.get("period", ""),
            "broadcasts": [n for b in competition.get("broadcasts", []) for n in b.get("names", [])],
            "venue": event.get("_venue", ""),
        })
    return games


def _normalize_team_name(name):
    return " ".join(str(name or "").lower().replace("&", "and").replace(".", "").split())


# NCAA team IDs are different from ESPN team IDs, so favorite matching is
# primarily name-based now. The stored IDs remain as a fallback for any feed
# that happens to use the old IDs.
FAVORITE_NAME_ALIASES = {
    "Kentucky": {"kentucky", "kentucky wildcats"},
    "Auburn": {"auburn", "auburn tigers"},
    "West Florida": {"west florida", "west florida argos", "uwf"},
    "Alabama": {"alabama", "alabama crimson tide"},
    "Georgia": {"georgia", "georgia bulldogs"},
    "Florida": {"florida", "florida gators"},
    "Florida State": {"florida state", "florida state seminoles"},
    "Miami": {"miami", "miami hurricanes", "miami (fl)"},
    "LSU": {"lsu", "lsu tigers", "louisiana state"},
    "Tennessee": {"tennessee", "tennessee volunteers"},
    "Clemson": {"clemson", "clemson tigers"},
    "Ohio State": {"ohio state", "ohio state buckeyes"},
    "Michigan": {"michigan", "michigan wolverines"},
    "Notre Dame": {"notre dame", "notre dame fighting irish"},
}

def is_favorite(game, favorites):
    home_id = str(game.get("home_id", ""))
    away_id = str(game.get("away_id", ""))
    home_name = _normalize_team_name(game.get("home"))
    away_name = _normalize_team_name(game.get("away"))

    for favorite_name, favorite_id in favorites.items():
        aliases = {_normalize_team_name(favorite_name)} | {
            _normalize_team_name(alias) for alias in FAVORITE_NAME_ALIASES.get(favorite_name, set())
        }
        if home_id == str(favorite_id) or away_id == str(favorite_id):
            return True
        if home_name in aliases or away_name in aliases:
            return True
    return False



def _collect_watch_info(payload):
    """Extract broadcast/network names, actual stream/watch URLs, and venue separately."""
    if not payload:
        return {"broadcasts": [], "watch_urls": [], "venue": ""}
    broadcasts, watch_urls, venues = [], [], []
    broadcast_keys = {"network", "networkname", "broadcast", "broadcastname", "tv", "channel"}
    watch_keys = {"watch", "stream", "streamurl", "watchurl", "videourl", "url", "href", "link"}
    venue_keys = {"venue", "venuename", "stadium", "arenaname", "location"}

    def add_text(bucket, value):
        if isinstance(value, str) and value.strip():
            bucket.append(value.strip())

    def walk(value):
        if isinstance(value, dict):
            # Treat likely video/live objects specially so their URL is not confused with venue data.
            for k, v in value.items():
                nk = str(k).lower().replace("_", "").replace("-", "")
                if nk in broadcast_keys:
                    vals = v if isinstance(v, list) else [v]
                    for x in vals:
                        if isinstance(x, dict):
                            add_text(broadcasts, x.get("name") or x.get("title") or x.get("displayName") or x.get("network"))
                            add_text(watch_urls, x.get("url") or x.get("href") or x.get("link"))
                        else:
                            add_text(broadcasts, x)
                elif nk in watch_keys:
                    if isinstance(v, str) and v.startswith(("http://", "https://")):
                        watch_urls.append(v.strip())
                    elif isinstance(v, dict):
                        add_text(watch_urls, v.get("url") or v.get("href") or v.get("link"))
                if nk in venue_keys:
                    if isinstance(v, dict):
                        v = v.get("name") or v.get("displayName") or v.get("fullName")
                    add_text(venues, v)
                walk(v)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(payload)

    def unique(values):
        out, seen = [], set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()
            key = value.lower()
            if key not in seen:
                seen.add(key); out.append(value)
        return out

    return {
        "broadcasts": unique(broadcasts)[:6],
        "watch_urls": unique(watch_urls)[:6],
        "venue": unique(venues)[:1][0] if venues else "",
    }


@st.cache_data(ttl=30)
def get_game_watch_info(game_id):
    if not game_id or str(game_id).startswith("ncaa-"):
        return {"broadcasts": [], "watch_urls": [], "venue": ""}
    detail = get_ncaa_game_detail(game_id)
    return _collect_watch_info(detail)


def render_game(game, favorite=False, close=False, rankings=None, records=None):
    status_badge = "🔴 LIVE" if game["state"] == "in" else ("FINAL" if game["state"] == "post" else "UPCOMING")
    meta = " • ".join(x for x in [
        status_badge,
        game["division"],
        "⭐ FAVORITE" if favorite else "",
        "🔥 CLOSE" if close else "",
        game["detail"],
        f"TV: {', '.join(game['broadcasts'])}" if game["broadcasts"] else "",
    ] if x)

    away_logo_url = game.get("away_logo", "")
    home_logo_url = game.get("home_logo", "")
    away_logo = f'<img src="{_logo_data_uri(away_logo_url)}" width="36" height="36" style="vertical-align:middle;margin-right:8px;object-fit:contain;">' if away_logo_url and _logo_data_uri(away_logo_url) else ""
    home_logo = f'<img src="{_logo_data_uri(home_logo_url)}" width="36" height="36" style="vertical-align:middle;margin-right:8px;object-fit:contain;">' if home_logo_url and _logo_data_uri(home_logo_url) else ""
    ranking_map = rankings or {}
    away_rank = ranking_map.get(_normalize_team_name(game["away"]))
    home_rank = ranking_map.get(_normalize_team_name(game["home"]))
    record_map = records or {}
    away_record = game.get("away_record") or record_map.get(_normalize_team_name(game["away"])) or record_map.get(f"id:{game.get('away_id', '')}")
    home_record = game.get("home_record") or record_map.get(_normalize_team_name(game["home"])) or record_map.get(f"id:{game.get('home_id', '')}")
    away_label = ((f"#{away_rank} " if away_rank else "") + (f"({away_record}) " if away_record else ""))
    home_label = ((f"#{home_rank} " if home_rank else "") + (f"({home_record}) " if home_record else ""))

    if game["state"] in ("in", "post"):
        away_score, home_score = game["away_score"], game["home_score"]
    else:
        away_score = home_score = "—"

    clock = ""
    if game["state"] == "in":
        clock = f" • Period {game['period']} • {game['clock']}" if game["clock"] else f" • Period {game['period']}"

    start_time = ""
    if game.get("event_time") and game["state"] == "pre":
        start_time = game["event_time"].strftime("%I:%M %p %Z").lstrip("0")

    st.markdown(f"""
    <div class="game-card">
      <div class="meta">{game['sport']} • {meta}</div>
      <div class="team">{away_logo}{away_label}{game['away']}<span class="score">{away_score}</span></div>
      <div class="team">{home_logo}{home_label}{game['home']}<span class="score">{home_score}</span></div>
      <div class="meta">Score difference: {game['diff']}{clock}{(' • Start: ' + start_time) if start_time else ''}</div>
    </div>
    """, unsafe_allow_html=True)

    if game.get("venue"):
        st.caption("📍 Venue: " + game["venue"])

def _alert_key(game_id):
    return f"game_alert_{game_id}"


def _game_label(game):
    return f"{game.get('away', 'Away')} at {game.get('home', 'Home')}"


def render_alert_toggle(game, context):
    """Render one persistent alert toggle per game. Only main/upcoming cards get controls."""
    if context not in ("main", "upcoming"):
        return bool(st.session_state.get(_alert_key(game["id"]), False))
    key = _alert_key(game["id"])
    if key not in st.session_state:
        st.session_state[key] = False
    return st.checkbox("🔔 Flash alerts", key=key, help="Flash the screen when this game's score changes.")


def update_score_alerts(all_games):
    """Detect score/state changes for games the user has marked for alerts."""
    previous = st.session_state.setdefault("previous_game_snapshots", {})
    flashes = []
    current = {}
    for game in all_games:
        gid = str(game.get("id"))
        snapshot = (game.get("away_score", 0), game.get("home_score", 0), game.get("state"), game.get("period", ""), game.get("clock", ""))
        current[gid] = snapshot
        if st.session_state.get(_alert_key(gid), False):
            old = previous.get(gid)
            if old is not None and old != snapshot and (
                old[0] != snapshot[0] or old[1] != snapshot[1] or old[2] != snapshot[2]
            ):
                flashes.append(game)
    st.session_state.previous_game_snapshots = current
    return flashes


def inject_flash_css():
    st.markdown("""
    <style>
    @keyframes scoreboardFlash { 0%,100% { opacity:1; transform:scale(1); } 25% { opacity:.25; transform:scale(1.02); } 50% { opacity:1; transform:scale(1); } 75% { opacity:.25; transform:scale(1.02); } }
    .scoreboard-flash { animation: scoreboardFlash 1.0s linear infinite; border:4px solid currentColor; border-radius:18px; padding:18px; margin:12px 0 20px; font-size:22px; font-weight:900; text-align:center; }
    </style>
    """, unsafe_allow_html=True)


def get_standings_for_sport(sport_name):
    configs = {
        "🏀 Men's Basketball": ("basketball-men", "d1"),
        "🏀 Women's Basketball": ("basketball-women", "d1"),
        "🏐 Women's Volleyball": ("volleyball-women", "d1"),
        "🏈 Football": ("football", "fbs"),
        "⚾ Baseball": ("baseball", "d1"),
        "🥎 Softball": ("softball", "d1"),
        "⚽ Men's Soccer": ("soccer-men", "d1"),
        "⚽ Women's Soccer": ("soccer-women", "d1"),
    }
    config = configs.get(sport_name)
    if not config:
        return None
    try:
        r = requests.get(f"https://ncaa-api.henrygd.me/standings/{config[0]}/{config[1]}", timeout=20, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _standings_rows(payload):
    """Flatten the NCAA standings response into conference/team rows."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("data") if isinstance(payload.get("data"), list) else payload.get("standings")
    if raw is None:
        raw = payload.get("data") if isinstance(payload.get("data"), dict) else []
    rows = []
    if isinstance(raw, list):
        for block in raw:
            if not isinstance(block, dict):
                continue
            conf = block.get("conference") or block.get("title") or block.get("name") or "Conference"
            teams = block.get("standings") or block.get("teams") or block.get("rows") or []
            if isinstance(teams, list):
                for row in teams:
                    if isinstance(row, dict):
                        item = dict(row)
                        item["Conference"] = conf
                        rows.append(item)
    return rows


def render_conference_standings(selected_sport, selected_conference=""):
    payload = get_standings_for_sport(selected_sport)
    rows = _standings_rows(payload)
    if not rows:
        st.info("NCAA standings are not available for this sport right now.")
        return
    if selected_conference:
        rows = [r for r in rows if _normalize_team_name(r.get("Conference", "")) == _normalize_team_name(selected_conference)]
    if not rows:
        st.info("No standings found for that conference.")
        return
    # Preserve useful NCAA columns while avoiding huge nested payloads.
    clean = []
    for r in rows:
        clean.append({k: v for k, v in r.items() if isinstance(v, (str, int, float)) and k.lower() not in {"logo", "id"}})
    st.dataframe(clean, use_container_width=True, hide_index=True)



@st.fragment(run_every="30s")
def live_dashboard(timezone_label, selected_timezone, sport_filter, threshold, conference_filter, top25_only, date_offset, live_only, favorites_only, standings_sport, standings_conference):
    st.title("🏆 College Sports Live")
    selected_date = today_in_timezone(selected_timezone) + timedelta(days=date_offset)
    date_label = { -1: "Yesterday", 0: "Today", 1: "Tomorrow" }.get(date_offset, str(selected_date))
    st.caption(f"NCAA college scores • {date_label} • Showing times in {timezone_label}")

    try:
        data = get_all_scoreboards(selected_timezone, selected_date)
        games = parse_games(data, selected_timezone)

        # The NCAA football scoreboard can sometimes return the next slate of
        # games even when a specific date was requested. Never let those
        # future games leak into the selected date. Use the actual parsed
        # local event date as the source of truth.
        games = [g for g in games if g.get("event_date") == selected_date]
    except Exception as exc:
        st.error(f"Could not retrieve scores: {type(exc).__name__}: {exc}")
        st.stop()

    all_games_for_alerts = list(games)
    flashes = update_score_alerts(all_games_for_alerts)
    if flashes:
        inject_flash_css()
        names = " • ".join(_game_label(g) for g in flashes[:4])
        st.markdown(f'<div class="scoreboard-flash">🚨 SCORE ALERT 🚨<br>{names}</div>', unsafe_allow_html=True)

    if show_diagnostics:
        with st.expander("🛠️ Scoreboard Diagnostics", expanded=True):
            st.write({"selected_time_zone": timezone_label, "selected_date": str(selected_date), "raw_combined_event_count": len(data.get("events", [])), "parsed_game_count": len(games), "errors": data.get("errors", [])})
            for diag in data.get("diagnostics", []):
                with st.container(border=True):
                    st.markdown(f"**{diag.get('sport','Unknown sport')}**")
                    st.write({k:v for k,v in diag.items() if k not in {"sample_games"}})
                    if diag.get("sample_games"): st.json(diag["sample_games"][:10])

    selected = set(sport_filter)
    if selected:
        games = [g for g in games if g["sport"] in selected]

    ranking_maps = get_inline_ranking_maps()
    record_maps = get_record_maps_for_games(games)
    if conference_filter:
        selected_conferences = set(conference_filter)
        games = [g for g in games if g.get("away_conference") in selected_conferences or g.get("home_conference") in selected_conferences]
    if top25_only:
        games = [g for g in games if ranking_maps.get(g["sport"], {}).get(_normalize_team_name(g["away"])) or ranking_maps.get(g["sport"], {}).get(_normalize_team_name(g["home"]))]

    favorites = st.session_state.favorites
    if live_only:
        games = [g for g in games if g["state"] == "in"]
    if favorites_only:
        games = [g for g in games if is_favorite(g, favorites)]

    live_games = [g for g in games if g["state"] == "in"]
    close_games = [g for g in live_games if g["diff"] < threshold]
    favorite_games = [g for g in games if is_favorite(g, favorites)]
    live_sorted = sorted(live_games, key=lambda g: (g["diff"], g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone))))
    final_sorted = sorted([g for g in games if g["state"] == "post"], key=lambda g: g["event_time"] or datetime.min.replace(tzinfo=ZoneInfo(selected_timezone)), reverse=True)
    upcoming_today = sorted([g for g in games if g["state"] == "pre"], key=lambda g: g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone)))

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("🔴 Live", len(live_games)); c2.metric(f"🔥 Under {threshold}", len(close_games)); c3.metric("⭐ My Teams", len(favorite_games)); c4.metric("🏆 Games", len(games)); c5.metric("🔔 Alerts", sum(bool(st.session_state.get(_alert_key(g["id"]), False)) for g in all_games_for_alerts))

    st.markdown("---")
    st.subheader("⭐ My Teams")
    if favorite_games:
        for favorite_name, favorite_id in favorites.items():
            team_games = [g for g in games if is_favorite(g, {favorite_name: favorite_id})]
            st.markdown(f"### ⭐ {favorite_name}")
            if not team_games: st.caption("No games found for this date.")
            else:
                for game in sorted(team_games, key=lambda g: (g["state"] != "in", g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone)))):
                    alert = bool(st.session_state.get(_alert_key(game["id"]), False))
                    st.caption("🔔 Flash alert enabled" if alert else "")
                    render_game({**game, "_render_context":"myteams"}, favorite=True, close=(game["state"]=="in" and game["diff"]<threshold), rankings=ranking_maps.get(game["sport"], {}), records=record_maps.get(game["sport"], {}))
    else:
        st.info("Select teams in the sidebar to build your My Teams dashboard.")

    st.markdown("---")
    st.subheader("🏆 Games — Sorted by Closeness")
    for game in live_sorted + final_sorted:
        context = "main"
        render_alert_toggle(game, context)
        render_game({**game, "_render_context":context}, favorite=is_favorite(game, favorites), close=(game["state"]=="in" and game["diff"]<threshold), rankings=ranking_maps.get(game["sport"], {}), records=record_maps.get(game["sport"], {}))
    if not (live_sorted or final_sorted): st.info("No live or completed games match the current filters.")

    st.markdown("---")
    st.subheader("📅 Upcoming")
    if not upcoming_today: st.info("No upcoming games match the current filters.")
    for game in upcoming_today:
        render_alert_toggle(game, "upcoming")
        render_game({**game, "_render_context":"upcoming"}, favorite=is_favorite(game, favorites), close=False, rankings=ranking_maps.get(game["sport"], {}), records=record_maps.get(game["sport"], {}))

    st.markdown("---")
    st.subheader("📊 Conference Standings")
    st.caption("NCAA conference standings for the selected sport.")
    render_conference_standings(standings_sport, standings_conference)


# Sidebar controls
with st.sidebar:
    st.header("⚙️ Settings")
    timezone_label = st.selectbox("Time zone", list(TIMEZONES.keys()), index=list(TIMEZONES.keys()).index(DEFAULT_TIMEZONE))
    selected_timezone = TIMEZONES[timezone_label]

    date_choice = st.radio("📅 Date", ["Yesterday", "Today", "Tomorrow"], index=1)
    date_offset = {"Yesterday": -1, "Today": 0, "Tomorrow": 1}[date_choice]

    sport_filter = st.multiselect("Sports", list(SPORTS.keys()), default=list(SPORTS.keys()))
    conference_options = ["ACC","AAC","America East","Atlantic 10","ASUN","Big 12","Big East","Big Sky","Big South","Big Ten","Big West","CAA","C-USA","Horizon League","Ivy League","MAAC","MAC","MEAC","Missouri Valley","Mountain West","NEC","Ohio Valley","Pac-12","Patriot League","SEC","SoCon","Southland","Summit League","Sun Belt","SWAC","WAC","WCC","West Coast","Independent"]
    conference_filter = st.multiselect("🏟️ Conferences", conference_options, default=[])
    top25_only = st.checkbox("🏆 Top 25 teams only", value=False)
    live_only = st.checkbox("🔴 Live games only", value=False)
    favorites_only = st.checkbox("⭐ My Teams only", value=False)
    threshold = st.slider("Close-game threshold", min_value=1, max_value=20, value=7)

    st.markdown("---")
    st.subheader("⭐ Favorite Teams")
    if "favorites" not in st.session_state: st.session_state.favorites = dict(DEFAULT_FAVORITES)
    favorite_options = list(TEAM_IDS.keys())
    current_favorites = [name for name in favorite_options if name in st.session_state.favorites]
    selected_favorites = st.multiselect("My Teams", favorite_options, default=current_favorites)
    st.session_state.favorites = {name: TEAM_IDS[name] for name in selected_favorites}

    st.markdown("---")
    st.subheader("📊 Conference Tools")
    standings_sport = st.selectbox("Sport for standings", list(SPORTS.keys()), index=0)
    standings_conference = st.selectbox("Conference", ["All conferences"] + conference_options, index=0)
    if standings_conference == "All conferences": standings_conference = ""

    st.markdown("---")
    st.subheader("🔔 Score Alerts")
    st.caption("Use the 🔔 Flash alerts checkbox on a game card. Marked games flash on screen when their score changes.")
    show_diagnostics = st.checkbox("Show diagnostics", value=False)

    if st.button("🔄 Refresh now", use_container_width=True):
        st.cache_data.clear(); st.rerun()

live_dashboard(timezone_label, selected_timezone, sport_filter, threshold, conference_filter, top25_only, date_offset, live_only, favorites_only, standings_sport, standings_conference)

