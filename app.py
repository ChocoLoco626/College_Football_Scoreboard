from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
    """Return a flexible name -> NCAA school slug index for reliable logos."""
    url = "https://ncaa-api.henrygd.me/schools-index"
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        for key in ("schools", "data", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return {}
    index = {}
    for school in payload:
        if not isinstance(school, dict):
            continue
        slug = school.get("slug") or school.get("team_seo") or school.get("seo")
        if not slug:
            continue
        names = [
            school.get("name"), school.get("school"), school.get("school_name"),
            school.get("short_name"), school.get("team_name"), school.get("displayName"),
            school.get("team_seo"), school.get("slug"),
        ]
        nested = school.get("names")
        if isinstance(nested, dict):
            names.extend(nested.get(k) for k in ("full", "short", "seo"))
        for name in names:
            key = _normalize_team_name(name)
            if key:
                index[key] = str(slug)
    return index


def _ncaa_logo_url(team_names, team=None, school_index=None):
    """Build a reliable NCAA logo URL, using the scoreboard slug then schools index."""
    team = team if isinstance(team, dict) else {}
    team_names = team_names if isinstance(team_names, dict) else {}
    direct_slug = (team_names.get("seo") or team_names.get("team_seo") or
                   team_names.get("slug") or team.get("team_seo") or
                   team.get("seo") or team.get("slug"))
    slug = direct_slug
    if school_index:
        candidates = [
            team_names.get("full"), team_names.get("short"), team.get("name"),
            team.get("displayName"), team_names.get("seo"),
        ]
        for candidate in candidates:
            found = school_index.get(_normalize_team_name(candidate))
            if found:
                slug = found
                break
    return f"https://ncaa-api.henrygd.me/logo/{slug}.svg" if slug else ""


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


def get_ncaa_scoreboard(sport_slug, division, sport_name, timezone_name):
    """Fetch a dated NCAA Division I scoreboard and normalize it to our app format."""
    local_date = today_in_timezone(timezone_name)
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
                text = start_time.strip().replace(" ET", "").replace(" EST", "").replace(" EDT", "")
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
                    {"homeAway": "away", "team": {"id": str(away.get("id", "")), "displayName": away_name, "logo": away_logo}, "score": str(away_score)},
                    {"homeAway": "home", "team": {"id": str(home.get("id", "")), "displayName": home_name, "logo": home_logo}, "score": str(home_score)},
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
def get_all_scoreboards(timezone_name):
    combined = []
    errors = []
    diagnostics = []
    for sport_name, configs in NCAA_SPORTS.items():
        for sport_slug, division in configs:
            try:
                data = get_ncaa_scoreboard(sport_slug, division, sport_name, timezone_name)
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
            "home_logo": home.get("team", {}).get("logo", ""),
            "away_logo": away.get("team", {}).get("logo", ""),
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
    """Best-effort extraction of network/broadcast and venue from NCAA game-center data."""
    if not payload:
        return {"broadcasts": [], "venue": ""}
    broadcasts, venues = [], []
    broadcast_keys = {"network", "networkname", "broadcast", "broadcastname", "tv", "channel", "watch", "stream"}
    venue_keys = {"venue", "venuename", "stadium", "arenaname", "location"}
    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                nk = str(k).lower().replace("_", "").replace("-", "")
                if nk in broadcast_keys:
                    vals = v if isinstance(v, list) else [v]
                    for x in vals:
                        if isinstance(x, dict):
                            x = x.get("name") or x.get("title") or x.get("displayName") or x.get("network")
                        if isinstance(x, str) and x.strip():
                            broadcasts.append(x.strip())
                if nk in venue_keys:
                    if isinstance(v, dict):
                        v = v.get("name") or v.get("displayName") or v.get("fullName")
                    if isinstance(v, str) and v.strip():
                        venues.append(v.strip())
                walk(v)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(payload)
    def unique(values):
        out=[]; seen=set()
        for value in values:
            if value.lower() not in seen:
                seen.add(value.lower()); out.append(value)
        return out
    return {"broadcasts": unique(broadcasts)[:6], "venue": unique(venues)[:1][0] if venues else ""}


@st.cache_data(ttl=30)
def get_game_watch_info(game_id):
    if not game_id or str(game_id).startswith("ncaa-"):
        return {"broadcasts": [], "venue": ""}
    detail = get_ncaa_game_detail(game_id)
    return _collect_watch_info(detail)


def render_game(game, favorite=False, close=False):
    status_badge = "🔴 LIVE" if game["state"] == "in" else ("FINAL" if game["state"] == "post" else "UPCOMING")
    meta = " • ".join(x for x in [
        status_badge,
        game["division"],
        "⭐ FAVORITE" if favorite else "",
        "🔥 CLOSE" if close else "",
        game["detail"],
        f"TV: {', '.join(game['broadcasts'])}" if game["broadcasts"] else "",
    ] if x)

    away_logo = f'<img src="{game["away_logo"]}" width="36" style="vertical-align:middle;margin-right:8px;">' if game["away_logo"] else ""
    home_logo = f'<img src="{game["home_logo"]}" width="36" style="vertical-align:middle;margin-right:8px;">' if game["home_logo"] else ""

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
      <div class="team">{away_logo}{game['away']}<span class="score">{away_score}</span></div>
      <div class="team">{home_logo}{game['home']}<span class="score">{home_score}</span></div>
      <div class="meta">Score difference: {game['diff']}{clock}{(' • Start: ' + start_time) if start_time else ''}</div>
    </div>
    """, unsafe_allow_html=True)

    if game.get("state") in ("pre", "in", "post"):
        watch_key = f"watch_info_{game['id']}"
        if watch_key not in st.session_state:
            st.session_state[watch_key] = None
        if game.get("broadcasts") or game.get("venue"):
            parts = []
            if game.get("broadcasts"):
                parts.append("📺 " + ", ".join(game["broadcasts"]))
            if game.get("venue"):
                parts.append("📍 " + game["venue"])
            st.caption(" • ".join(parts))
        if st.button("📺 Where to watch", key=f"watch_btn_{game['id']}"):
            try:
                st.session_state[watch_key] = get_game_watch_info(game["id"])
            except Exception as exc:
                st.session_state[watch_key] = {"error": f"Could not retrieve game information: {type(exc).__name__}: {exc}"}
        info = st.session_state.get(watch_key)
        if info is not None:
            if info.get("error"):
                st.warning(info["error"])
            else:
                parts = []
                if info.get("broadcasts"):
                    parts.append("📺 Watch: " + ", ".join(info["broadcasts"]))
                if info.get("venue"):
                    parts.append("📍 Venue: " + info["venue"])
                st.info(" • ".join(parts) if parts else "The NCAA game feed does not list a broadcast or venue for this game yet.")

    if game.get("sport") == "🏐 Women's Volleyball" and game.get("state") in ("in", "post"):
        key = f"volley_sets_{game['id']}"
        if key not in st.session_state:
            st.session_state[key] = None
        button_label = "📊 Show set scores" if st.session_state[key] is None else "↻ Refresh set scores"
        if st.button(button_label, key=f"btn_{game['id']}"):
            try:
                detail = get_ncaa_game_detail(game["id"])
                set_scores = _extract_volleyball_set_scores(
                    detail, game.get("away_id", ""), game.get("home_id", "")
                )
                if not set_scores:
                    try:
                        boxscore = get_ncaa_boxscore(game["id"])
                        set_scores = _extract_volleyball_set_scores(
                            boxscore, game.get("away_id", ""), game.get("home_id", "")
                        )
                    except Exception:
                        pass
                st.session_state[key] = set_scores
                st.session_state[f"volley_sets_error_{game['id']}"] = ""
            except Exception as exc:
                st.session_state[key] = []
                st.session_state[f"volley_sets_error_{game['id']}"] = f"Could not retrieve set scores: {type(exc).__name__}: {exc}"

        if st.session_state.get(key) is not None:
            error = st.session_state.get(f"volley_sets_error_{game['id']}", "")
            if error:
                st.warning(error)
            elif st.session_state[key]:
                st.caption("Set-by-set score")
                st.dataframe(st.session_state[key], use_container_width=True, hide_index=True)
            else:
                st.info("The NCAA game feed did not provide set-by-set scores for this match yet.")


if "favorites" not in st.session_state:
    st.session_state.favorites = dict(DEFAULT_FAVORITES)

with st.sidebar:
    st.header("🏆 College Sports Controls")
    timezone_label = st.selectbox(
        "Time zone",
        list(TIMEZONES.keys()),
        index=list(TIMEZONES.keys()).index(DEFAULT_TIMEZONE),
        help="Choose the time zone used for game times and deciding which games count as today.",
    )
    selected_timezone = TIMEZONES[timezone_label]
    sport_filter = st.multiselect("Sports", list(SPORTS.keys()), default=list(SPORTS.keys()))
    threshold = st.slider("Close-game threshold", 1, 30, 10)
    show_diagnostics = st.checkbox(
        "🛠️ Diagnostics",
        value=False,
        help="Show exactly what each sports data source returned, including volleyball.",
    )
    st.divider()
    st.header("⭐ Favorite Teams")
    favorite_choices = st.multiselect("Teams", list(TEAM_IDS.keys()), default=list(DEFAULT_FAVORITES.keys()))
    st.session_state.favorites = {name: TEAM_IDS[name] for name in favorite_choices}
    st.divider()
    if st.button("🔄 Refresh now", use_container_width=True):
        get_all_scoreboards.clear()
        st.rerun()


@st.fragment(run_every=30)
def live_dashboard(timezone_label, selected_timezone, sport_filter, threshold):
    st.title("🏆 College Sports Live")
    st.caption(f"NCAA college scores • Showing times in {timezone_label}")

    try:
        data = get_all_scoreboards(selected_timezone)
        games = parse_games(data, selected_timezone)
    except Exception as exc:
        st.error(f"Could not retrieve scores: {type(exc).__name__}: {exc}")
        st.stop()

    if show_diagnostics:
        with st.expander("🛠️ Scoreboard Diagnostics", expanded=True):
            st.write({
                "selected_time_zone": timezone_label,
                "selected_local_date": str(today_in_timezone(selected_timezone)),
                "raw_combined_event_count": len(data.get("events", [])),
                "parsed_game_count": len(games),
                "errors": data.get("errors", []),
            })
            diagnostics = data.get("diagnostics", [])
            if diagnostics:
                for diag in diagnostics:
                    sport_name = diag.get("sport", "Unknown sport")
                    with st.container(border=True):
                        st.markdown(f"**{sport_name}**")
                        if diag.get("source"):
                            st.caption(f"Source: {diag['source']}")
                        if diag.get("url"):
                            st.code(diag["url"], language="text")
                        if "raw_game_count" in diag:
                            st.write({
                                "raw_games": diag.get("raw_game_count"),
                                "parsed_events": diag.get("parsed_event_count"),
                            })
                        if "merged_event_count" in diag:
                            st.write({"merged_ESPN_events": diag.get("merged_event_count")})
                        requests_info = diag.get("requests", [])
                        if requests_info:
                            st.dataframe(requests_info, use_container_width=True, hide_index=True)
                        if diag.get("sample_raw_keys"):
                            st.write("Sample raw item keys:", diag["sample_raw_keys"][:5])
                        if diag.get("sample_games"):
                            st.write("Sample games:")
                            st.json(diag["sample_games"][:10])
            else:
                st.warning("No source diagnostics were returned.")

            volleyball_games = [
                g for g in games if g.get("sport") == "🏐 Women's Volleyball"
            ]
            st.markdown("### Volleyball after parsing")
            st.write({
                "parsed_volleyball_games": len(volleyball_games),
                "volleyball_dates": sorted({str(g.get("event_date")) for g in volleyball_games}),
            })
            if volleyball_games:
                st.dataframe(
                    [
                        {
                            "away": g["away"],
                            "home": g["home"],
                            "date": str(g.get("event_date")),
                            "start": g.get("event_time").isoformat() if g.get("event_time") else None,
                            "state": g["state"],
                            "detail": g["detail"],
                        }
                        for g in volleyball_games
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    selected = set(sport_filter)
    if selected:
        games = [g for g in games if g["sport"] in selected]

    # Only show games whose event timestamp lands on today's selected-time-zone
    # calendar date. Tomorrow is fetched only as a reliability fallback.
    today = today_in_timezone(selected_timezone)
    games = [g for g in games if g.get("event_date") == today]

    favorites = st.session_state.favorites
    live_games = [g for g in games if g["state"] == "in"]
    close_games = [g for g in live_games if g["diff"] < threshold]
    favorite_games = [g for g in games if is_favorite(g, favorites)]

    live_sorted = sorted(
        [g for g in games if g["state"] == "in"],
        key=lambda g: (g["diff"], g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone))),
    )
    final_sorted = sorted(
        [g for g in games if g["state"] == "post"],
        key=lambda g: g["event_time"] or datetime.min.replace(tzinfo=ZoneInfo(selected_timezone)),
        reverse=True,
    )
    games_by_closeness = live_sorted + final_sorted

    upcoming_today = sorted(
        [g for g in games if g["state"] == "pre"],
        key=lambda g: g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone)),
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Live", len(live_games))
    c2.metric(f"🔥 Under {threshold}", len(close_games))
    c3.metric("⭐ My Teams", len(favorite_games))
    c4.metric("🏆 Today's Games", len(games))
    st.markdown("---")

    st.subheader("⭐ My Teams")
    if favorite_games:
        for favorite_name, favorite_id in favorites.items():
            team_games = [g for g in games if is_favorite(g, {favorite_name: favorite_id})]
            st.markdown(f"### ⭐ {favorite_name}")
            if not team_games:
                st.caption("No games found on today's NCAA scoreboards.")
            else:
                team_games.sort(key=lambda g: (g["state"] != "in", g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone))))
                for game in team_games:
                    render_game(game, favorite=True, close=(game["state"] == "in" and game["diff"] < threshold))
    else:
        st.info("Select teams in the sidebar to build your My Teams dashboard.")

    st.markdown("---")
    st.subheader("🏅 Rankings")
    st.caption("Current NCAA poll data. Football and basketball use AP; volleyball uses the AVCA poll.")
    ranking_choice = st.selectbox(
        "Ranking",
        list(RANKING_CONFIGS.keys()),
        key="ranking_choice",
    )
    r_sport, r_division, r_poll = RANKING_CONFIGS[ranking_choice]
    try:
        ranking_payload = get_ncaa_rankings(r_sport, r_division, r_poll)
        ranking_rows = _extract_ranking_rows(ranking_payload)
        if ranking_rows:
            st.dataframe(ranking_rows, use_container_width=True, hide_index=True)
        else:
            st.info("The NCAA ranking feed did not return ranked teams for this poll right now.")
    except requests.RequestException as exc:
        st.warning(f"Rankings are temporarily unavailable: {exc}")
    except Exception as exc:
        st.warning(f"Could not parse the NCAA rankings: {type(exc).__name__}: {exc}")

    st.markdown("---")
    st.subheader("🏆 Games — Sorted by Closeness")
    if not games_by_closeness:
        st.info("No live or completed games are currently available for the selected sports today.")
    else:
        st.caption("Live games are sorted closest first. Completed games follow.")
        for game in games_by_closeness:
            render_game(game, favorite=is_favorite(game, favorites), close=(game["state"] == "in" and game["diff"] < threshold))

    st.markdown("---")
    st.subheader("📅 Upcoming Today")
    if not upcoming_today:
        st.info("No upcoming games are currently listed by the NCAA for today in the selected sports.")
    else:
        st.caption("Upcoming games are sorted by start time and placed below the live/completed games.")
        for game in upcoming_today:
            render_game(game, favorite=is_favorite(game, favorites), close=False)


live_dashboard(timezone_label, selected_timezone, sport_filter, threshold)
