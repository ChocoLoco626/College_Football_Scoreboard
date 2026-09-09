from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import base64
import re
import json
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
from matchups import format_matchup_badges

REFRESH_SECONDS = 30
TIMEZONES = {
    "Eastern Time": "America/New_York",
    "Central Time": "America/Chicago",
}
DEFAULT_TIMEZONE = "Central Time"

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

# Sport-specific close-game defaults. A 7-point football game is close,
# while a 7-goal soccer game clearly is not. Values are score-margin points/goals.
DEFAULT_CLOSE_THRESHOLDS = {
    "🏈 Football": 7,
    "⚽ Men's Soccer": 1,
    "⚽ Women's Soccer": 1,
    "🏀 Men's Basketball": 7,
    "🏀 Women's Basketball": 7,
    "🏐 Women's Volleyball": 2,
    "⚾ Baseball": 2,
    "🥎 Softball": 2,
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
.score { font-size:30px; font-weight:800; float:right; text-align:right; }
.set-points { font-size:13px; font-weight:700; opacity:.72; }
.vb-live-set { margin-top:8px; padding:7px 9px; border:1px solid rgba(49,130,96,.35); border-radius:6px; font-size:13px; font-weight:700; }
.vb-live-team { margin-left:14px; }
.vb-set-table { margin-top:9px; border:1px solid rgba(128,128,128,.35); border-radius:5px; overflow:hidden; font-size:12px; }
.vb-set-label, .vb-set-row { display:grid; grid-template-columns:minmax(105px, 1fr) repeat(auto-fit, minmax(28px, 28px)) 32px; align-items:center; }
.vb-set-label { background:rgba(128,128,128,.12); font-weight:800; text-align:center; }
.vb-set-label span, .vb-set-row > span, .vb-set-row > b { padding:4px 3px; text-align:center; border-left:1px solid rgba(128,128,128,.22); }
.vb-set-row { border-top:1px solid rgba(128,128,128,.22); }
.vb-set-row strong { padding:4px 6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.vb-set-row b { font-size:13px; }
.team { font-size:18px; font-weight:700; margin:8px 0; min-height:38px; }
.meta { color:#9ca3af; font-size:13px; }
.update-bar { border:1px solid rgba(128,128,128,.30); border-radius:12px; padding:9px 12px; margin:8px 0 14px; font-size:13px; }
.update-good { color:#22c55e; font-weight:700; }
.update-warn { color:#eab308; font-weight:700; }
.update-bad { color:#ef4444; font-weight:700; }
.myteam-game-row { border-top:1px solid rgba(128,128,128,.18); padding-top:8px; margin-top:8px; }
.myteam-card { border:1px solid rgba(128,128,128,.30); border-radius:12px; padding:11px 13px; margin:5px 0 10px; min-height:112px; }
.myteam-name { font-size:16px; font-weight:800; margin-bottom:4px; }
.myteam-status { font-size:12px; color:#9ca3af; margin-bottom:7px; }
.myteam-score { font-size:22px; font-weight:850; line-height:1.1; }
.myteam-opponent { font-size:13px; margin-top:4px; }
.history-row { border-bottom:1px solid rgba(128,128,128,.18); padding:7px 0; font-size:13px; }
.history-time { color:#9ca3af; font-size:11px; }
.score-change { font-size:12px; font-weight:800; margin-left:8px; }
.countdown { font-weight:800; }
.compact-game-card { padding:9px 12px; margin:5px 0; }
.compact-game-card .team { font-size:16px; margin:5px 0; min-height:30px; }
.compact-game-card .score { font-size:25px; }
.compact-game-card .meta { font-size:11px; }

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


@st.cache_data(ttl=60, show_spinner=False)
def get_ncaa_game_detail(game_id):
    """Fetch NCAA game-center data on demand (used for volleyball set scores)."""
    if not game_id or str(game_id).startswith("ncaa-"):
        return None
    url = f"https://ncaa-api.henrygd.me/game/{game_id}"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=30, show_spinner=False)
def get_ncaa_volleyball_play_by_play(game_id):
    """Fetch NCAA volleyball play-by-play as a last-resort source for set points."""
    if not game_id or str(game_id).startswith("ncaa-"):
        return None
    try:
        response = requests.get(
            f"https://ncaa-api.henrygd.me/game/{game_id}/play-by-play",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def get_ncaa_boxscore(game_id):
    """Fetch the NCAA boxscore as a fallback for set/period scoring."""
    if not game_id or str(game_id).startswith("ncaa-"):
        return None
    url = f"https://ncaa-api.henrygd.me/game/{game_id}/boxscore"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=30, show_spinner=False)
def get_ncaa_volleyball_boxscore(game_id):
    """Call NCAA's volleyball-specific box-score query directly."""
    if not game_id or str(game_id).startswith("ncaa-"): return None
    try:
        hash_value="4320484382257c2a7ac3be318db2dee09a7fb74029448825c285d5dbdda365ae"
        url="https://sdataprod.ncaa.com/"
        # The NCAA GraphQL endpoint expects both the persisted-query hash and
        # the query name. The previous versions omitted queryName, which can
        # return a valid HTTP response without the volleyball team-stats data.
        params={
            "queryName":"TeamStatsVolleyball",
            "extensions":'{"persistedQuery":{"version":1,"sha256Hash":"'+hash_value+'"}}',
            "variables":json.dumps({"contestId": int(str(game_id)), "staticTestEnv": None}, separators=(",", ":")),
        }
        r=requests.get(url,params=params,timeout=10,headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.ncaa.com/"})
        r.raise_for_status(); return r.json()
    except Exception: return None


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
    # Normalize these names the same way we normalize incoming JSON keys.
    # The NCAA game-center has used both camelCase and snake_case names over
    # time (for example setScores / set_scores / periodScores).
    candidate_keys = {
        key.replace("_", "").replace("-", "").lower()
        for key in (
            "sets", "setScores", "setScore", "periods", "periodScores",
            "periodScore", "lineScores", "lineScore", "scoresBySet",
            "scoreBySet", "scoresByPeriod", "scoreByPeriod",
            "set_scores", "set_score", "period_scores", "period_score",
            "line_scores", "line_score", "scores_by_set", "score_by_set",
            "scores_by_period", "score_by_period",
        )
    }

    def parse_score_pair(value):
        """Parse a volleyball period score represented as a pair/string/list."""
        if isinstance(value, str):
            import re
            m = re.search(r"(\d+)\s*[-–:]\s*(\d+)", value)
            if m:
                return int(m.group(1)), int(m.group(2))
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            a, h = _first_number(value[0]), _first_number(value[1])
            if a is not None and h is not None:
                return a, h
        if isinstance(value, dict):
            a = value.get("away", value.get("awayScore", value.get("away_score")))
            h = value.get("home", value.get("homeScore", value.get("home_score")))
            a, h = _first_number(a), _first_number(h)
            if a is not None and h is not None:
                return a, h
        return None

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
                    pair = parse_score_pair(row)
                    if pair:
                        rows.append({"Set": str(idx + 1), "Away": pair[0], "Home": pair[1]})
                    continue
                label = row.get("name") or row.get("label") or row.get("period") or row.get("set") or row.get("number") or idx + 1
                away = row.get("awayScore", row.get("away_score"))
                home = row.get("homeScore", row.get("home_score"))
                if away is None or home is None:
                    scores = row.get("scores") or row.get("score") or row.get("setScore") or row.get("periodScore")
                    if isinstance(scores, dict):
                        away = scores.get("away", scores.get(str(away_id)))
                        home = scores.get("home", scores.get(str(home_id)))
                    else:
                        pair = parse_score_pair(scores)
                        if pair:
                            away, home = pair
                if away is not None and home is not None:
                    a, h = _first_number(away), _first_number(home)
                    if a is not None and h is not None:
                        rows.append({"Set": str(label), "Away": a, "Home": h})
            if rows:
                return rows

    # Some NCAA game-center responses put the per-set values directly on
    # each team as period1/period2/... (or set1/set2/...). Reconstruct the
    # paired rows from the away/home team objects when that shape is used.
    team_period_maps = []
    for obj in _walk_json(payload):
        if not isinstance(obj, dict):
            continue
        team = obj.get("team") if isinstance(obj.get("team"), dict) else obj
        team_id = str(team.get("id") or obj.get("teamId") or "")
        if not team_id and not (team.get("name") or team.get("displayName")):
            continue
        period_map = {}
        for key, value in obj.items():
            nk = key_norm(key)
            m = re.match(r"(?:set|period|game)0*(\d+)(?:score|points)?$", nk)
            if not m:
                continue
            n = int(m.group(1))
            score = _first_number(value)
            if score is not None and 0 <= score <= 60:
                period_map[n] = score
        if period_map:
            team_period_maps.append((team_id, period_map))

    if len(team_period_maps) >= 2:
        away_map = next((m for tid, m in team_period_maps if tid == str(away_id)), None)
        home_map = next((m for tid, m in team_period_maps if tid == str(home_id)), None)
        if away_map is None or home_map is None:
            away_map, home_map = team_period_maps[0][1], team_period_maps[1][1]
        rows = [
            {"Set": str(i), "Away": away_map[i], "Home": home_map[i]}
            for i in sorted(set(away_map) & set(home_map))
        ]
        if rows:
            return rows

    # Generic fallback: NCAA game-center responses can expose volleyball
    # periods/sets under sport-specific names. Look for any nested objects that
    # clearly represent a numbered set/period and contain two team scores.
    generic_rows = []
    for obj in _walk_json(payload):
        if not isinstance(obj, dict):
            continue
        label = obj.get("period") or obj.get("set") or obj.get("setNumber") or obj.get("periodNumber") or obj.get("periodName") or obj.get("setName")
        if label is None:
            continue
        # Avoid treating generic game-period strings like "Set 1" without scores as rows.
        score_candidates = []
        for key, value in obj.items():
            nk = key_norm(key)
            if nk in {"score", "scores", "setscore", "periodscore", "scorevalue", "points"} or "score" in nk or nk in {"away", "home"}:
                if isinstance(value, (dict, list, tuple, str)):
                    pair = parse_score_pair(value)
                    if pair:
                        score_candidates.append(pair)
        if len(score_candidates) == 1:
            a, h = score_candidates[0]
            generic_rows.append({"Set": str(label), "Away": a, "Home": h})
        elif len(score_candidates) >= 2:
            # Prefer the first pair; duplicate representations are common.
            a, h = score_candidates[0]
            generic_rows.append({"Set": str(label), "Away": a, "Home": h})
    if generic_rows:
        # Keep the first occurrence of each set label and require sensible
        # volleyball scores to avoid accidentally parsing player statistics.
        cleaned = []
        seen_labels = set()
        for row in generic_rows:
            key = row["Set"]
            if key in seen_labels:
                continue
            if 0 <= row["Away"] <= 60 and 0 <= row["Home"] <= 60:
                seen_labels.add(key)
                cleaned.append(row)
        if cleaned:
            return cleaned

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
                    pair = parse_score_pair(raw)
                    if pair:
                        # A paired score belongs to the row-level parser above;
                        # do not treat it as a single team's value here.
                        continue
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

    # Last-resort structured-team scan. Some current NCAA game-center payloads
    # put each team's line scores on its own team object.
    team_arrays = []
    score_keys = {"linescores", "linescore", "periodscores", "periodscore", "setscores", "setscore"}
    for obj in _walk_json(payload):
        if not isinstance(obj, dict): continue
        team = obj.get("team") if isinstance(obj.get("team"), dict) else obj
        tid = str(team.get("id") or obj.get("teamId") or "")
        for key, value in obj.items():
            if key_norm(key) not in score_keys or not isinstance(value, list): continue
            vals=[]
            for row in value:
                raw = row.get("score", row.get("value", row.get("points", row.get("displayValue")))) if isinstance(row, dict) else row
                if isinstance(raw,str):
                    m=re.search(r"-?\d+",raw); raw=m.group(0) if m else None
                n=_first_number(raw)
                if n is not None and 0 <= n <= 60: vals.append(n)
            if vals: team_arrays.append((tid,vals))
    if len(team_arrays)>=2:
        away_row=next((r for r in team_arrays if away_id and r[0]==str(away_id)),None)
        home_row=next((r for r in team_arrays if home_id and r[0]==str(home_id)),None)
        if away_row and home_row:
            n=min(len(away_row[1]),len(home_row[1]))
            if n: return [{"Set":str(i+1),"Away":away_row[1][i],"Home":home_row[1][i]} for i in range(n)]
    return []


def _extract_vb_scores_from_pbp(payload, away_id="", home_id=""):
    """Extract running volleyball set scores from NCAA PBP snapshots."""
    if not payload:
        return []
    def num(v):
        try:
            return None if v is None or isinstance(v, bool) else int(v)
        except (TypeError, ValueError):
            return None
    latest = {}
    for obj in _walk_json(payload):
        if not isinstance(obj, dict):
            continue
        pairs = [
            (obj.get("awayScore"), obj.get("homeScore")),
            (obj.get("visitorScore"), obj.get("homeScore")),
            (obj.get("away_score"), obj.get("home_score")),
            (obj.get("visitor_score"), obj.get("home_score")),
            (obj.get("awayPoints"), obj.get("homePoints")),
            (obj.get("away_points"), obj.get("home_points")),
        ]
        pair = None
        for a, h in pairs:
            a, h = num(a), num(h)
            if a is not None and h is not None and 0 <= a <= 60 and 0 <= h <= 60:
                pair = (a, h); break
        if pair is None and isinstance(obj.get("score"), dict):
            sc = obj["score"]
            a, h = num(sc.get("away", sc.get("visitor", sc.get(str(away_id))))), num(sc.get("home", sc.get(str(home_id))))
            if a is not None and h is not None and 0 <= a <= 60 and 0 <= h <= 60:
                pair = (a, h)
        if pair is None and isinstance(obj.get("score"), str):
            m = re.search(r"(\d+)\s*[-–:]\s*(\d+)", obj["score"])
            if m and int(m.group(1)) <= 60 and int(m.group(2)) <= 60:
                pair = (int(m.group(1)), int(m.group(2)))
        if pair is None:
            continue
        label = obj.get("periodNumber") or obj.get("period") or obj.get("setNumber") or obj.get("set") or obj.get("periodDisplay") or obj.get("setDisplay")
        m = re.search(r"(\d+)", str(label or ""))
        if m and 1 <= int(m.group(1)) <= 5:
            latest[int(m.group(1))] = pair
    return [{"Set": str(n), "Away": latest[n][0], "Home": latest[n][1]} for n in sorted(latest)]


def _extract_vb_label_value_sets(payload, away_id="", home_id=""):
    """Parse common NCAA stat-row shapes such as Set 1 -> 11 on each team."""
    if not payload: return []
    team_rows=[]
    for obj in _walk_json(payload):
        if not isinstance(obj,dict): continue
        team=obj.get("team") if isinstance(obj.get("team"),dict) else None
        tid=str((team or {}).get("id") or obj.get("teamId") or "")
        if not tid: continue
        found={}
        for child in _walk_json(obj):
            if not isinstance(child,dict): continue
            label=str(child.get("label") or child.get("name") or child.get("displayName") or child.get("statName") or child.get("description") or "")
            m=re.search(r"(?:set|period)\s*(\d+)",label,re.I)
            if not m: continue
            raw=child.get("value",child.get("score",child.get("points",child.get("displayValue",child.get("statValue")))))
            n=_first_number(raw)
            if n is not None and 0 <= n <= 60: found[int(m.group(1))]=n
        if found: team_rows.append((tid,found))
    away=next((x[1] for x in team_rows if away_id and x[0]==str(away_id)),None)
    home=next((x[1] for x in team_rows if home_id and x[0]==str(home_id)),None)
    if away is not None and home is not None:
        return [{"Set":str(i),"Away":away[i],"Home":home[i]} for i in sorted(set(away)&set(home))]
    return []


@st.cache_data(ttl=60, show_spinner=False)
def get_volleyball_set_info(game_id, away_id="", home_id=""):
    """Return volleyball set totals and per-set point scores from NCAA sources."""
    if not game_id or str(game_id).startswith("ncaa-"):
        return None

    candidate_rows = []
    try:
        payload = get_ncaa_game_detail(game_id)
        if payload:
            candidate_rows = _extract_volleyball_set_scores(payload, away_id, home_id)
    except Exception:
        pass

    if not candidate_rows:
        try:
            payload = get_ncaa_boxscore(game_id)
            if payload:
                candidate_rows = _extract_volleyball_set_scores(payload, away_id, home_id)
                if not candidate_rows:
                    candidate_rows = _extract_vb_label_value_sets(payload, away_id, home_id)
        except Exception:
            pass

    # Direct volleyball-specific NCAA GraphQL query. This avoids relying on the
    # wrapper's basketball-first hash discovery and is the most targeted source.
    if not candidate_rows:
        payload = get_ncaa_volleyball_boxscore(game_id)
        if payload:
            candidate_rows = _extract_volleyball_set_scores(payload, away_id, home_id)
            if not candidate_rows:
                candidate_rows = _extract_vb_label_value_sets(payload, away_id, home_id)

    # Last resort: reconstruct from NCAA play-by-play snapshots.
    if not candidate_rows:
        candidate_rows = _extract_vb_scores_from_pbp(
            get_ncaa_volleyball_play_by_play(game_id), away_id, home_id
        )

    if not candidate_rows:
        return None

    # Remove duplicate set labels and keep sensible volleyball scores.
    rows=[]; seen=set()
    for idx,row in enumerate(candidate_rows,1):
        try:
            a=int(row.get("Away")); h=int(row.get("Home"))
        except (TypeError,ValueError):
            continue
        label=str(row.get("Set") or idx)
        if label in seen or not (0 <= a <= 60 and 0 <= h <= 60):
            continue
        seen.add(label); rows.append({"Set":label,"Away":a,"Home":h})
    if not rows:
        return None

    def set_complete(a,h,set_number):
        target=15 if set_number>=5 else 25
        return max(a,h)>=target and abs(a-h)>=2

    completed=[]; current=None
    for idx,row in enumerate(rows,1):
        if set_complete(row["Away"],row["Home"],idx):
            completed.append(row)
        elif idx == len(rows):
            current=row

    return {
        "rows": rows,
        "away_sets": sum(r["Away"] > r["Home"] for r in completed),
        "home_sets": sum(r["Home"] > r["Away"] for r in completed),
        "away_points": [r["Away"] for r in rows],
        "home_points": [r["Home"] for r in rows],
        "current_set_number": len(completed)+1 if current else None,
        "current_set_away": current["Away"] if current else None,
        "current_set_home": current["Home"] if current else None,
    }


def _volleyball_live_tracker(game):
    """Return a clear current-set tracker with each team's live point total."""
    if game.get("sport") != "🏐 Women's Volleyball" or game.get("state") != "in":
        return ""
    set_no = game.get("volleyball_current_set")
    away = game.get("volleyball_current_away")
    home = game.get("volleyball_current_home")
    if set_no is None or away is None or home is None:
        return ""
    return (
        f'<div class="vb-live-set">🟢 <strong>LIVE — SET {set_no}</strong>'
        f'<span class="vb-live-team">{game["away"]}: <strong>{away}</strong></span>'
        f'<span class="vb-live-team">{game["home"]}: <strong>{home}</strong></span></div>'
    )


def _volleyball_score_label(game, side):
    """For volleyball, show only sets won in the main score; current points are tracked separately."""
    sets = game.get(f"{side}_score")
    if game.get("sport") != "🏐 Women's Volleyball":
        return str(sets) if sets not in (None, "") else "—"
    return str(sets) if sets not in (None, "") else "—"

def _ncaa_football_week(target_date):
    """Return the NCAA football scoreboard week containing target_date.

    NCAA's football scoreboard API is week-based (YYYY/WK), unlike the
    date-based routes used by most other sports. The first regular-season
    week can span two calendar weeks because of Labor Day weekend, so use
    the first two Thursdays of the season as the boundary.
    """
    year = target_date.year
    # NCAA football normally begins on the last Thursday of August. Week 1
    # runs through the Wednesday before the following Thursday (the long
    # Labor Day opening week); subsequent weeks are seven days each.
    aug31 = date(year, 8, 31)
    first_thursday = aug31 - timedelta(days=(aug31.weekday() - 3) % 7)
    if target_date < first_thursday:
        return 0
    second_thursday = first_thursday + timedelta(days=14)
    if target_date < second_thursday:
        return 1
    return 2 + ((target_date - second_thursday).days // 7)


def get_ncaa_scoreboard(sport_slug, division, sport_name, timezone_name, target_date=None):
    """Fetch an NCAA scoreboard and normalize it to our app format."""
    local_date = target_date or today_in_timezone(timezone_name)
    if sport_slug == "football":
        week = _ncaa_football_week(local_date)
        date_path = f"{local_date.year}/{week:02d}/all-conf"
    else:
        date_path = local_date.strftime("%Y/%m/%d")
    url = f"https://ncaa-api.henrygd.me/scoreboard/{sport_slug}/{division}/{date_path}"

    # The public NCAA API supports pagination. Some busy dates can place a
    # matchup on a later page, so fetch additional pages when the first page
    # is full. This prevents marquee games (for example Kentucky-Louisville)
    # from disappearing simply because the slate is large.
    payload = None
    raw_games = []
    page = 1
    max_pages = 5
    while page <= max_pages:
        page_url = url if page == 1 else f"{url}?page={page}"
        response = requests.get(page_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        page_payload = response.json()
        if not isinstance(page_payload, dict):
            break
        page_games = page_payload.get("games", []) or []
        if page == 1:
            payload = page_payload
        raw_games.extend(page_games)
        # NCAA returns a bounded page. If it is not full, there is no next page.
        if len(page_games) < 20:
            break
        page += 1

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

        # NCAA can expose a calendar date (startDate) separately from an
        # epoch timestamp.  The epoch is authoritative for the clock/timezone,
        # but its converted local date can be one day earlier/later than the
        # NCAA contest calendar date.  Do NOT blindly replace the date on the
        # epoch value: that can move unrelated games to the wrong day.
        # Instead, when the scoreboard request is for a specific calendar date
        # and NCAA supplied that same startDate, keep the NCAA calendar date
        # while preserving the converted clock from the epoch.
        source_start_date = game.get("startDate")
        if event_dt is not None and isinstance(source_start_date, str) and target_date is not None:
            try:
                source_day = date.fromisoformat(source_start_date[:10])
                if source_day == local_date and abs((event_dt.date() - source_day).days) == 1:
                    event_dt = event_dt.replace(year=source_day.year, month=source_day.month, day=source_day.day)
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

        # Preserve any event/tournament/championship metadata exposed by the NCAA feed.
        context_values = []
        for key in (
            "eventName", "event_name", "contestName", "contest_name", "tournamentName",
            "tournament_name", "roundName", "round_name", "championshipName",
            "championship_name", "title", "description", "notes", "seasonType",
        ):
            value = game.get(key)
            if value not in (None, "", []):
                context_values.append(str(value))
        event_context = " | ".join(dict.fromkeys(context_values))
        event_name = (
            game.get("eventName") or game.get("event_name") or game.get("contestName")
            or game.get("contest_name") or game.get("tournamentName") or game.get("tournament_name")
            or ""
        )
        tournament_name = game.get("tournamentName") or game.get("tournament_name") or ""
        round_name = game.get("roundName") or game.get("round_name") or ""

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
            "_event_name": event_name,
            "_event_context": event_context,
            "_tournament_name": tournament_name,
            "_round_name": round_name,
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
            "pages_fetched": page,
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



@st.cache_data(ttl=1800)
def get_ncaa_schedule_alt(sport_slug, division, season_year):
    """Fetch the NCAA's newer full-season schedule feed (2026+)."""
    url = f"https://ncaa-api.henrygd.me/schedule-alt/{sport_slug}/{division}/{season_year}"
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


def _walk_schedule_nodes(value):
    """Yield nested dictionaries from the flexible schedule-alt response."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_schedule_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schedule_nodes(child)


def _schedule_team_name(team):
    if not isinstance(team, dict):
        return ""
    names = team.get("names") or {}
    return (
        team.get("displayName") or team.get("nameFull") or names.get("full") or
        names.get("short") or team.get("name") or team.get("teamName") or ""
    )


def _schedule_candidates(payload):
    """Extract contest-like records without depending on one response shape."""
    seen = set()
    for node in _walk_schedule_nodes(payload):
        teams = node.get("teams")
        if isinstance(teams, list) and len(teams) >= 2:
            yield node, teams[:2]
            continue
        home = node.get("home")
        away = node.get("away")
        if isinstance(home, dict) and isinstance(away, dict):
            key = (str(node.get("contestId") or node.get("gameID") or ""), _schedule_team_name(home), _schedule_team_name(away))
            if key not in seen:
                seen.add(key)
                yield node, [away, home]


def get_schedule_fallback_events(sport_slug, division, sport_name, timezone_name, target_date):
    """Recover scheduled games missing from a date scoreboard feed.

    This is intentionally cached for 30 minutes. It is a schedule-recovery
    layer, not part of the 30-second live-score refresh loop.
    """
    payload = get_ncaa_schedule_alt(sport_slug, division, target_date.year)
    events = []
    try:
        school_index = get_ncaa_schools_index()
    except Exception:
        school_index = {}

    for node, teams in _schedule_candidates(payload):
        if len(teams) < 2:
            continue
        # NCAA contest records expose isHome; fall back to the pair ordering.
        home_team = next((t for t in teams if isinstance(t, dict) and t.get("isHome") is True), teams[-1])
        away_team = next((t for t in teams if isinstance(t, dict) and t.get("isHome") is False), teams[0])
        away_name = _schedule_team_name(away_team)
        home_name = _schedule_team_name(home_team)
        if not away_name or not home_name:
            continue

        event_dt = None
        start_time = node.get("startTime") or node.get("time") or ""
        epoch = node.get("startTimeEpoch") or node.get("startTimestamp") or node.get("timestamp")
        if epoch not in (None, ""):
            try:
                value = float(epoch)
                if value > 100000000000:
                    value /= 1000
                event_dt = datetime.fromtimestamp(value, tz=ZoneInfo("UTC")).astimezone(ZoneInfo(timezone_name))
            except (TypeError, ValueError, OverflowError):
                pass

        start_date = node.get("startDate") or node.get("date") or node.get("gameDate")
        if event_dt is not None and isinstance(start_date, str) and start_date:
            # schedule-alt may return an epoch whose local conversion crosses
            # midnight relative to NCAA's contest calendar date. Keep the
            # schedule's calendar date, but retain the real converted clock.
            try:
                source_day = date.fromisoformat(start_date[:10])
                if abs((event_dt.date() - source_day).days) == 1:
                    event_dt = event_dt.replace(year=source_day.year, month=source_day.month, day=source_day.day)
            except ValueError:
                pass

        if event_dt is None and isinstance(start_date, str) and start_date:
            try:
                # New NCAA schedule data's startTime is presented in ET.
                text = str(start_time).replace(" ET", "").replace(" EST", "").replace(" EDT", "").strip()
                import re
                m = re.search(r"(\d{1,2}:\d{2})\s*(AM|PM)?", text, re.I)
                if m:
                    clock, ampm = m.group(1), m.group(2) or ""
                    fmt = "%Y-%m-%d %I:%M %p" if ampm else "%Y-%m-%d %H:%M"
                    naive = datetime.strptime(f"{start_date[:10]} {clock} {ampm}".strip(), fmt)
                    event_dt = naive.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(ZoneInfo(timezone_name))
                    # The schedule date is the contest calendar date. If ET ->
                    # local conversion crossed midnight, preserve that date.
                    source_day = date.fromisoformat(start_date[:10])
                    if abs((event_dt.date() - source_day).days) == 1:
                        event_dt = event_dt.replace(year=source_day.year, month=source_day.month, day=source_day.day)
                else:
                    # A scheduled game with no announced kickoff (TBA) still
                    # belongs to the selected calendar date.
                    event_dt = datetime.fromisoformat(start_date[:10]).replace(tzinfo=ZoneInfo(timezone_name), hour=12, minute=0)
            except (TypeError, ValueError):
                pass

        if event_dt is None or event_dt.date() != target_date:
            continue

        game_id = str(node.get("contestId") or node.get("gameID") or node.get("id") or f"schedule-{away_name}-{home_name}-{event_dt.isoformat()}")
        away_id = str(away_team.get("id") or away_team.get("teamId") or "")
        home_id = str(home_team.get("id") or home_team.get("teamId") or "")
        away_names = away_team.get("names") or {}
        home_names = home_team.get("names") or {}
        away_logo = away_team.get("logo") or _ncaa_logo_url(away_names, away_team, school_index)
        home_logo = home_team.get("logo") or _ncaa_logo_url(home_names, home_team, school_index)
        state_raw = str(node.get("gameState") or node.get("status") or "P").upper()
        state = "in" if state_raw in ("I", "LIVE", "IN") else ("post" if state_raw in ("F", "FINAL", "POST") else "pre")
        try:
            away_score = int(away_team.get("score") or 0)
        except (TypeError, ValueError):
            away_score = 0
        try:
            home_score = int(home_team.get("score") or 0)
        except (TypeError, ValueError):
            home_score = 0

        events.append({
            "id": game_id,
            "date": event_dt.isoformat(),
            "status": {"type": {"state": state, "shortDetail": node.get("finalMessage") or (start_time if start_time else "TBA"), "detail": node.get("finalMessage") or (start_time if start_time else "TBA")}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "away", "team": {"id": away_id, "displayName": away_name, "logo": away_logo}, "score": str(away_score)},
                    {"homeAway": "home", "team": {"id": home_id, "displayName": home_name, "logo": home_logo}, "score": str(home_score)},
                ],
                "broadcasts": ([{"names": [node.get("broadcasterName")]}] if node.get("broadcasterName") else []),
                "_venue": node.get("venue") or node.get("venueName") or node.get("location") or "",
            }],
            "_event_name": node.get("contestName") or node.get("eventName") or "",
            "_event_context": node.get("roundDescription") or node.get("description") or "",
            "_tournament_name": node.get("tournamentName") or "",
            "_round_name": node.get("roundDescription") or "",
            "_sport_name": sport_name,
            "_sport": sport_slug,
            "_league": sport_slug,
            "_division": "NCAA D-I" if division == "d1" else division.upper(),
        })
    return events


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


@st.cache_data(ttl=1800, show_spinner=False)
def _get_cached_scoreboard_snapshot(timezone_name, target_date, selected_sports=()):
    """Build a relatively stable slate snapshot for the selected date.

    Upcoming and completed games live here for 30 minutes. Live score polling
    is deliberately handled by get_all_scoreboards(), which only re-requests
    NCAA feeds for games that are already live or whose scheduled start time
    has passed.
    """
    combined = []
    errors = []
    diagnostics = []
    target_date = target_date or today_in_timezone(timezone_name)
    selected_sports = tuple(selected_sports or ())
    if not selected_sports:
        return {"events": [], "errors": [], "diagnostics": [], "cached_at": datetime.now(ZoneInfo(timezone_name)).isoformat()}

    for sport_name, configs in NCAA_SPORTS.items():
        if sport_name not in selected_sports:
            continue
        for sport_slug, division in configs:
            if sport_slug == "football":
                dates_to_fetch = [target_date]
            elif timezone_name == "America/Chicago":
                dates_to_fetch = [target_date - timedelta(days=1), target_date, target_date + timedelta(days=1)]
            else:
                dates_to_fetch = [target_date]

            seen_ids = set()
            for fetch_date in dates_to_fetch:
                try:
                    data = get_ncaa_scoreboard(sport_slug, division, sport_name, timezone_name, fetch_date)
                    if data.get("_diagnostic"):
                        diagnostics.append({
                            "sport": sport_name,
                            "requested_date": str(fetch_date),
                            **data["_diagnostic"],
                        })
                    for event in data.get("events", []):
                        event["_sport_name"] = sport_name
                        event["_requested_ncaa_date"] = str(fetch_date)
                        event_id = str(event.get("id", ""))
                        if event_id and event_id in seen_ids:
                            continue
                        if event_id:
                            seen_ids.add(event_id)
                        combined.append(event)
                except requests.RequestException as exc:
                    errors.append(f"{sport_name} ({sport_slug}/{division}, {fetch_date}): {exc}")
                except Exception as exc:
                    errors.append(f"{sport_name} ({sport_slug}/{division}, {fetch_date}): {type(exc).__name__}: {exc}")

            try:
                fallback_events = get_schedule_fallback_events(
                    sport_slug, division, sport_name, timezone_name, target_date
                )
                existing = {str(e.get("id")) for e in combined if e.get("_sport_name") == sport_name}
                for event in fallback_events:
                    event_id = str(event.get("id"))
                    if event_id and event_id not in existing:
                        event["_from_schedule_fallback"] = True
                        event["_requested_ncaa_date"] = str(target_date)
                        combined.append(event)
                        existing.add(event_id)
            except Exception as exc:
                diagnostics.append({"sport": sport_name, "schedule_fallback_error": str(exc)})

    return {
        "events": combined,
        "errors": errors,
        "diagnostics": diagnostics,
        "cached_at": datetime.now(ZoneInfo(timezone_name)).isoformat(),
    }


def _event_is_live_candidate(event, now_local):
    """Return True when this event should be actively polled for score changes."""
    if not isinstance(event, dict):
        return False
    status = str(event.get("gameState") or event.get("state") or "").lower()
    if status in {"in", "live", "active"}:
        return True
    if status in {"post", "final", "completed"}:
        return False
    raw_date = event.get("date")
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            event_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(now_local.tzinfo)
            return event_dt <= now_local
        except (TypeError, ValueError):
            pass
    return False


def get_all_scoreboards(timezone_name, target_date=None, selected_sports=()):
    """Return a cached slate plus live updates only for selected active games.

    Upcoming/final games are held in a 30-minute snapshot. Every 30-second
    refresh only polls feeds for selected sports that contain a live game or
    a game whose scheduled start time has passed. If no sport is selected, no
    NCAA score requests are made.
    """
    target_date = target_date or today_in_timezone(timezone_name)
    selected_sports = tuple(s for s in (selected_sports or ()) if s in NCAA_SPORTS)
    if not selected_sports:
        return {
            "events": [], "errors": [], "diagnostics": [],
            "fetched_at": datetime.now(ZoneInfo(timezone_name)).isoformat(),
            "snapshot_cached_at": None,
        }

    snapshot = _get_cached_scoreboard_snapshot(timezone_name, target_date, selected_sports)
    combined = list(snapshot.get("events", []))
    errors = list(snapshot.get("errors", []))
    diagnostics = list(snapshot.get("diagnostics", []))
    now_local = datetime.now(ZoneInfo(timezone_name))

    for sport_name in selected_sports:
        configs = NCAA_SPORTS.get(sport_name, [])
        for sport_slug, division in configs:
            candidates = [
                event for event in combined
                if event.get("_sport_name") == sport_name
                and event.get("_division") == division
                and _event_is_live_candidate(event, now_local)
            ]
            if not candidates:
                continue

            if sport_slug == "football":
                dates_to_fetch = [target_date]
            elif timezone_name == "America/Chicago":
                dates_to_fetch = [target_date - timedelta(days=1), target_date, target_date + timedelta(days=1)]
            else:
                dates_to_fetch = [target_date]

            refreshed = []
            seen_ids = set()
            for fetch_date in dates_to_fetch:
                try:
                    data = get_ncaa_scoreboard(sport_slug, division, sport_name, timezone_name, fetch_date)
                    if data.get("_diagnostic"):
                        diagnostics.append({
                            "sport": sport_name,
                            "requested_date": str(fetch_date),
                            **data["_diagnostic"],
                        })
                    for event in data.get("events", []):
                        event["_sport_name"] = sport_name
                        event["_requested_ncaa_date"] = str(fetch_date)
                        event_id = str(event.get("id", ""))
                        if event_id and event_id in seen_ids:
                            continue
                        if event_id:
                            seen_ids.add(event_id)
                        refreshed.append(event)
                except requests.RequestException as exc:
                    errors.append(f"{sport_name} ({sport_slug}/{division}, {fetch_date}): {exc}")
                except Exception as exc:
                    errors.append(f"{sport_name} ({sport_slug}/{division}, {fetch_date}): {type(exc).__name__}: {exc}")

            if refreshed:
                refreshed_by_id = {str(e.get("id")): e for e in refreshed if e.get("id")}
                new_combined = []
                for event in combined:
                    if event.get("_sport_name") == sport_name and event.get("_division") == division:
                        event_id = str(event.get("id", ""))
                        if event_id in refreshed_by_id:
                            new_combined.append(refreshed_by_id.pop(event_id))
                        else:
                            new_combined.append(event)
                    else:
                        new_combined.append(event)
                new_combined.extend(refreshed_by_id.values())
                combined = new_combined

    return {
        "events": combined,
        "errors": errors,
        "diagnostics": diagnostics,
        "fetched_at": datetime.now(ZoneInfo(timezone_name)).isoformat(),
        "snapshot_cached_at": snapshot.get("cached_at"),
    }


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


def _conference_matchup_badge(game):
    """Return a conference-matchup badge when both teams share a conference."""
    away_conf = _pretty_conference(game.get("away_conference", ""))
    home_conf = _pretty_conference(game.get("home_conference", ""))
    if not away_conf or not home_conf:
        return ""
    if away_conf.lower() in {"independent", "independents"} or home_conf.lower() in {"independent", "independents"}:
        return ""
    if _normalize_team_name(away_conf) == _normalize_team_name(home_conf):
        return f"🏟️ CONFERENCE • {away_conf}"
    return ""


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

def _extract_current_volleyball_points(competitor, period_value=""):
    """Extract the current volleyball set points from scoreboard competitor data.

    NCAA scoreboard payloads can expose per-set values directly on each
    competitor (usually as linescores/periodScores). This is preferable to
    making a separate game-detail request on every refresh.
    """
    if not isinstance(competitor, dict):
        return None, None

    def key_norm(key):
        return str(key).lower().replace("_", "").replace("-", "")

    def num(value):
        try:
            if isinstance(value, bool) or value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    candidate_keys = {
        "linescores", "linescore", "periodscores", "periodscore",
        "setscores", "setscore", "scoresbyset", "scorebyset",
        "scoresbyperiod", "scorebyperiod",
    }

    # Prefer a linescore array. For a live volleyball match, the last
    # populated period is the current set.
    for key, value in competitor.items():
        if key_norm(key) not in candidate_keys or not isinstance(value, list):
            continue
        parsed = []
        for row in value:
            score = None
            period = None
            if isinstance(row, dict):
                period = row.get("period", row.get("set", row.get("number")))
                score = row.get("score", row.get("value", row.get("points", row.get("displayValue"))))
            else:
                score = row
            if isinstance(score, str):
                m = re.search(r"(\d+)", score)
                score = m.group(1) if m else None
            score = num(score)
            if score is not None and 0 <= score <= 60:
                parsed.append((period, score))
        if parsed:
            return parsed[-1][1], len(parsed)

    return None, None



@st.cache_data(ttl=30, show_spinner=False)
def get_espn_volleyball_scoreboard(target_date):
    """Fetch ESPN women's college volleyball as a low-cost fallback for set scores."""
    if not target_date:
        return None
    try:
        date_str = target_date.strftime("%Y%m%d") if hasattr(target_date, "strftime") else str(target_date).replace("-", "")
        url = "https://site.api.espn.com/apis/site/v2/sports/volleyball/womens-college-volleyball/scoreboard"
        response = requests.get(url, params={"dates": date_str}, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _team_names_match(name_a, name_b):
    """Loose team-name matcher for NCAA ↔ ESPN volleyball feeds."""
    def norm(value):
        text = _normalize_team_name(value or "")
        for token in ("university", "college", "state", "the"):
            text = text.replace(token, " ")
        return " ".join(text.split())
    a, b = norm(name_a), norm(name_b)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _espn_vb_linescores(competitor):
    """Return ESPN volleyball per-set point values in set order."""
    values = []
    for row in competitor.get("linescores") or []:
        if not isinstance(row, dict):
            continue
        raw = row.get("value", row.get("score", row.get("displayValue")))
        try:
            if isinstance(raw, str):
                match = re.search(r"\d+", raw)
                raw = match.group(0) if match else None
            value = int(float(raw))
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 60:
            values.append(value)
    return values


def _espn_vb_current_set_number(event, count):
    status = event.get("status", {}) if isinstance(event, dict) else {}
    period = status.get("period")
    if period is None:
        period = status.get("type", {}).get("shortDetail", "")
    try:
        return max(1, min(int(period), count))
    except (TypeError, ValueError):
        match = re.search(r"(\d+)", str(period or ""))
        if match:
            return max(1, min(int(match.group(1)), count))
        return count


def _extract_espn_vb_scores(event, away_name, home_name):
    """Return full ESPN set rows plus current-set data for a matching event."""
    if not isinstance(event, dict):
        return None
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    if not away or not home:
        return None
    away_team = away.get("team", {}).get("displayName", "")
    home_team = home.get("team", {}).get("displayName", "")
    if not (_team_names_match(away_team, away_name) and _team_names_match(home_team, home_name)):
        return None

    away_sets = _espn_vb_linescores(away)
    home_sets = _espn_vb_linescores(home)
    count = min(len(away_sets), len(home_sets))
    if count == 0:
        return None

    rows = [
        {"Set": str(i + 1), "Away": away_sets[i], "Home": home_sets[i]}
        for i in range(count)
    ]
    current_set = _espn_vb_current_set_number(event, count)
    state = event.get("status", {}).get("type", {}).get("state", "")
    if state == "post":
        current_set = None
        current_away = current_home = None
    else:
        current_away = away_sets[current_set - 1]
        current_home = home_sets[current_set - 1]
    return rows, current_set, current_away, current_home


@st.cache_data(ttl=30, show_spinner=False)
def get_espn_volleyball_summary(event_id):
    if not event_id: return None
    try:
        r=requests.get("https://site.api.espn.com/apis/site/v2/sports/volleyball/womens-college-volleyball/summary", params={"event":str(event_id)}, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status(); return r.json()
    except Exception: return None

def _espn_summary_event(payload):
    if not isinstance(payload,dict): return None
    header=payload.get("header") or {}
    comps=header.get("competitions") or payload.get("competitions") or []
    return {"competitions":comps,"status":header.get("status") or payload.get("status") or {}} if comps else None


def apply_espn_volleyball_fallback(games, target_date):
    """Fill missing volleyball set history/current points from one cached ESPN feed."""
    targets = [
        g for g in games
        if g.get("sport") == "🏐 Women's Volleyball"
        and g.get("state") in ("in", "post")
        and (
            not g.get("volleyball_set_scores")
            or (g.get("state") == "in" and (g.get("volleyball_current_away") is None or g.get("volleyball_current_home") is None))
        )
    ]
    if not targets:
        return games

    payload = get_espn_volleyball_scoreboard(target_date)
    if not payload:
        return games
    events = payload.get("events") or []
    for game in targets:
        for event in events:
            extracted = _extract_espn_vb_scores(event, game.get("away", ""), game.get("home", ""))
            if not extracted:
                summary_event = _espn_summary_event(get_espn_volleyball_summary(event.get("id")))
                if summary_event:
                    extracted = _extract_espn_vb_scores(summary_event, game.get("away", ""), game.get("home", ""))
            if not extracted:
                continue
            rows, set_no, current_away, current_home = extracted
            game["volleyball_set_scores"] = rows
            game["away_points_by_set"] = [r["Away"] for r in rows]
            game["home_points_by_set"] = [r["Home"] for r in rows]
            if set_no is not None:
                game["volleyball_current_set"] = set_no
                game["volleyball_current_away"] = current_away
                game["volleyball_current_home"] = current_home
            # ESPN's linescore is also a reliable set-win count. For a live
            # match, only completed sets count; for a final, every set counts.
            if game.get("state") == "post":
                game["away_score"] = sum(1 for r in rows if r["Away"] > r["Home"])
                game["home_score"] = sum(1 for r in rows if r["Home"] > r["Away"])
            else:
                completed = rows[:-1] if len(rows) > 0 else []
                game["away_score"] = sum(1 for r in completed if r["Away"] > r["Home"])
                game["home_score"] = sum(1 for r in completed if r["Home"] > r["Away"])
            game["diff"] = abs(int(game.get("away_score", 0)) - int(game.get("home_score", 0)))
            break
    return games

def parse_games(data, timezone_name, target_date=None, fetch_volleyball_details=True):
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
        volleyball_current_away = None
        volleyball_current_home = None
        volleyball_linescore_count = None
        if event.get("_sport_name") == "🏐 Women's Volleyball":
            volleyball_current_away, away_line_count = _extract_current_volleyball_points(away, status.get("period", ""))
            volleyball_current_home, home_line_count = _extract_current_volleyball_points(home, status.get("period", ""))
            volleyball_linescore_count = away_line_count or home_line_count
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
            "event_name": event.get("_event_name", ""),
            "event_context": event.get("_event_context", ""),
            "tournament_name": event.get("_tournament_name", ""),
            "round_name": event.get("_round_name", ""),
            "volleyball_current_set": volleyball_linescore_count,
            "volleyball_current_away": volleyball_current_away,
            "volleyball_current_home": volleyball_current_home,
        })
    # Volleyball set/point details used to be fetched serially, and each game
    # could trigger both /game and /boxscore. That made a busy volleyball slate
    # noticeably increase dashboard load time. Fetch the details in a small
    # bounded pool instead. Results are cached for 60 seconds, while the main
    # NCAA scoreboard still refreshes every 30 seconds.
    volleyball_games = [
        game for game in games
        if fetch_volleyball_details
        and game.get("sport") == "🏐 Women's Volleyball" and game.get("state") in ("in", "post")
        and game.get("id") and not str(game.get("id")).startswith("ncaa-")
    ]

    def fetch_vb_info(game):
        return game, get_volleyball_set_info(game.get("id"), game.get("away_id", ""), game.get("home_id", ""))

    if volleyball_games:
        # Four concurrent requests keeps the UI responsive without opening a
        # large burst of connections to the NCAA API.
        with ThreadPoolExecutor(max_workers=min(4, len(volleyball_games))) as executor:
            futures = [executor.submit(fetch_vb_info, game) for game in volleyball_games]
            for future in as_completed(futures):
                try:
                    game, info = future.result()
                except Exception:
                    continue
                if not info:
                    continue
                game["away_score"] = info["away_sets"]
                game["home_score"] = info["home_sets"]
                game["away_points_by_set"] = info["away_points"]
                game["home_points_by_set"] = info["home_points"]
                game["volleyball_set_scores"] = info["rows"]
                game["volleyball_current_set"] = info.get("current_set_number") or game.get("volleyball_current_set")
                game["volleyball_current_away"] = info.get("current_set_away") if info.get("current_set_away") is not None else game.get("volleyball_current_away")
                game["volleyball_current_home"] = info.get("current_set_home") if info.get("current_set_home") is not None else game.get("volleyball_current_home")
                game["diff"] = abs(info["away_sets"] - info["home_sets"])

    if fetch_volleyball_details:
        games = apply_espn_volleyball_fallback(games, target_date)
    return games


def enrich_volleyball_details(games):
    """Fetch detailed NCAA volleyball linescores for an already-filtered subset."""
    targets=[g for g in games if g.get("sport")=="🏐 Women's Volleyball" and g.get("state") in ("in","post") and g.get("id") and not str(g.get("id")).startswith("ncaa-")]
    if not targets: return games
    def fetch(g): return g,get_volleyball_set_info(g.get("id"),g.get("away_id",""),g.get("home_id",""))
    with ThreadPoolExecutor(max_workers=min(4,len(targets))) as ex:
        futures=[ex.submit(fetch,g) for g in targets]
        for f in as_completed(futures):
            try: g,info=f.result()
            except Exception: continue
            if not info: continue
            g["away_score"]=info["away_sets"]; g["home_score"]=info["home_sets"]
            g["away_points_by_set"]=info["away_points"]; g["home_points_by_set"]=info["home_points"]
            g["volleyball_set_scores"]=info["rows"]
            g["volleyball_current_set"]=info.get("current_set_number") or g.get("volleyball_current_set")
            g["volleyball_current_away"]=info.get("current_set_away") if info.get("current_set_away") is not None else g.get("volleyball_current_away")
            g["volleyball_current_home"]=info.get("current_set_home") if info.get("current_set_home") is not None else g.get("volleyball_current_home")
            g["diff"]=abs(info["away_sets"]-info["home_sets"])
    return apply_espn_volleyball_fallback(games,None)

def dedupe_games(games):
    """Remove duplicate NCAA events that can appear in multiple football feeds.

    NCAA can expose the same football matchup through overlapping FBS/FCS
    scoreboard responses with different event IDs. Prefer the event ID when
    available, but also use matchup/date/time as a fallback so the user sees
    each game only once.
    """
    unique = []
    seen_ids = set()
    seen_matchups = set()
    for game in games:
        event_id = str(game.get("id") or "").strip()
        matchup = (
            _normalize_team_name(game.get("away")),
            _normalize_team_name(game.get("home")),
            str(game.get("event_date") or ""),
            str(game.get("event_time") or ""),
        )
        if event_id and event_id in seen_ids:
            continue
        if matchup in seen_matchups:
            continue
        if event_id:
            seen_ids.add(event_id)
        seen_matchups.add(matchup)
        unique.append(game)
    return unique


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


def _live_status_text(game):
    """Use familiar sport-specific live labels instead of generic Period N."""
    if game.get("state") != "in":
        return ""
    sport = game.get("sport", "")
    period = game.get("period", "")
    clock = game.get("clock", "")
    try:
        p = int(period)
    except (TypeError, ValueError):
        p = None
    if "Football" in sport and p is not None:
        label = f"Q{p}"
    elif "Basketball" in sport and p is not None:
        label = "1st Half" if p == 1 else ("2nd Half" if p == 2 else f"OT{p-2}")
    elif "Soccer" in sport and p is not None:
        label = "1st Half" if p == 1 else ("2nd Half" if p == 2 else f"OT{p-2}")
    elif "Volleyball" in sport and p is not None:
        label = f"Set {p}"
    elif sport in ("⚾ Baseball", "🥎 Softball") and p is not None:
        label = f"Inning {p}"
    elif period:
        label = f"Period {period}"
    else:
        label = "LIVE"
    return f"{label} • {clock}" if clock else label


def _recent_score_change(game):
    """Return a small score-change label for a game changed on the latest refresh."""
    item = st.session_state.get("recent_score_changes", {}).get(str(game.get("id")))
    return item.get("label", "") if item else ""


def _upcoming_countdown(event_time):
    """Return a friendly countdown for an upcoming game."""
    if not event_time:
        return ""
    now = datetime.now(event_time.tzinfo)
    seconds = int((event_time - now).total_seconds())
    if seconds <= 0:
        return "Starting now"
    minutes = seconds // 60
    if minutes < 60:
        return f"Starts in {minutes} min"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"Starts in {hours}h {mins:02d}m" if mins else f"Starts in {hours}h"
    days, rem = divmod(hours, 24)
    return f"Starts in {days}d {rem}h"


def _is_ranked_game(game, rankings=None):
    """Return (ranked_team_count, ranked labels) using the already-cached rankings."""
    ranking_map = rankings or {}
    away_rank = ranking_map.get(_normalize_team_name(game.get("away", "")))
    home_rank = ranking_map.get(_normalize_team_name(game.get("home", "")))
    count = int(bool(away_rank)) + int(bool(home_rank))
    labels = []
    if away_rank:
        labels.append(f"#{away_rank} {game.get('away', '')}")
    if home_rank:
        labels.append(f"#{home_rank} {game.get('home', '')}")
    return count, labels


def _late_close_reason(game, close_thresholds):
    """Detect a close live game in the decisive/final period of the sport."""
    if game.get("state") != "in":
        return False
    sport = game.get("sport", "")
    try:
        period = int(game.get("period"))
    except (TypeError, ValueError):
        period = None
    threshold = int(close_thresholds.get(sport, 7))
    diff = int(game.get("diff", 999))

    if diff > threshold:
        return False
    if sport == "🏈 Football":
        return period == 4
    if sport in ("🏀 Men's Basketball", "🏀 Women's Basketball", "⚽ Men's Soccer", "⚽ Women's Soccer"):
        return period == 2
    if sport == "🏐 Women's Volleyball":
        return period == 5
    return False


def _volleyball_set_scoreboard(game):
    """Render a compact NCAA-style volleyball linescore table."""
    rows = game.get("volleyball_set_scores") or []
    if not rows:
        return ""

    # Keep the columns in set order and remove duplicate labels. The NCAA card
    # only shows sets that have started, followed by the total sets column.
    cleaned = []
    seen = set()
    for idx, row in enumerate(rows, start=1):
        try:
            set_label = str(row.get("Set") or idx)
            a = int(row.get("Away"))
            h = int(row.get("Home"))
        except (TypeError, ValueError):
            continue
        if set_label in seen:
            continue
        seen.add(set_label)
        cleaned.append((set_label, a, h))

    if not cleaned:
        return ""

    n = len(cleaned)
    grid = f"minmax(105px,1fr) repeat({n},28px) 32px"
    headers = "".join(f'<span>{label}</span>' for label, _, _ in cleaned)
    away = "".join(f'<span>{a}</span>' for _, a, _ in cleaned)
    home = "".join(f'<span>{h}</span>' for _, _, h in cleaned)
    away_total = game.get("away_score", 0)
    home_total = game.get("home_score", 0)

    return (
        '<div class="vb-set-table">'
        f'<div class="vb-set-label" style="grid-template-columns:{grid}"><span></span>{headers}<span>T</span></div>'
        f'<div class="vb-set-row" style="grid-template-columns:{grid}"><strong>{game.get("away", "Away")}</strong>{away}<b>{away_total}</b></div>'
        f'<div class="vb-set-row" style="grid-template-columns:{grid}"><strong>{game.get("home", "Home")}</strong>{home}<b>{home_total}</b></div>'
        '</div>'
    )


def render_game(game, favorite=False, close=False, rankings=None, records=None, compact=False):
    status_badge = "🔴 LIVE NOW" if game["state"] == "in" else ("FINAL" if game["state"] == "post" else "UPCOMING")
    live_detail = _live_status_text(game)
    matchup_badges = format_matchup_badges(game)
    meta = " • ".join(x for x in [
        status_badge,
        game["division"],
        "⭐ FAVORITE" if favorite else "",
        "🔥 CLOSE" if close else "",
        live_detail or game["detail"],
        f"TV: {', '.join(game['broadcasts'])}" if game["broadcasts"] else "",
    ] if x)
    matchup_meta = "<br>" + " &nbsp;•&nbsp; ".join(matchup_badges) if matchup_badges else ""

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
        away_score = _volleyball_score_label(game, "away")
        home_score = _volleyball_score_label(game, "home")
    else:
        away_score = home_score = "—"

    clock = ""
    if game["state"] == "in":
        if game.get("sport") == "🏐 Women's Volleyball":
            clock = f" • Period {game['period']}" if game.get("period") else ""
        else:
            clock = f" • Period {game['period']} • {game['clock']}" if game['clock'] else f" • Period {game['period']}"

    start_time = ""
    countdown = ""
    if game.get("event_time") and game["state"] == "pre":
        start_time = game["event_time"].strftime("%I:%M %p %Z").lstrip("0")
        countdown = _upcoming_countdown(game["event_time"])

    change_label = _recent_score_change(game)
    change_html = f'<span class="score-change">{change_label}</span>' if change_label else ""
    start_meta = f" • Start: {start_time}" if start_time else ""
    if countdown:
        start_meta += f' • <span class="countdown">{countdown}</span>'
    card_class = "game-card compact-game-card" if compact else "game-card"
    st.markdown(f"""
    <div class="{card_class}">
      <div class="meta">{game['sport']} • {meta}{matchup_meta}</div>
      <div class="team">{away_logo}{away_label}{game['away']} ✈️<span class="score">{away_score}</span></div>
      <div class="team">{home_logo}{home_label}{game['home']} 🏠<span class="score">{home_score}</span></div>
      {_volleyball_live_tracker(game) if game.get("sport") == "🏐 Women's Volleyball" else ''}
      {_volleyball_set_scoreboard(game) if game.get("sport") == "🏐 Women's Volleyball" else ''}
      <div class="meta">Score difference: {game['diff']}{' set' if game.get('sport') == "🏐 Women's Volleyball" and game['diff'] == 1 else (' sets' if game.get('sport') == "🏐 Women's Volleyball" else '')}{change_html}{clock}{start_meta}</div>
    </div>
    """, unsafe_allow_html=True)

    if game.get("venue"):
        st.caption("📍 Venue: " + game["venue"])

def _alert_key(game_id):
    return f"game_alert_{game_id}"


def _game_label(game):
    return f"{game.get('away', 'Away')} at {game.get('home', 'Home')}"


def render_alert_toggle(game, context, instance=0):
    """Render a persistent alert toggle with a unique Streamlit widget key.

    The same game can occasionally appear more than once in a filtered dashboard,
    so the widget key includes the render context/instance while the stored alert
    preference remains keyed only to the game ID.
    """
    if context not in ("main", "upcoming"):
        return bool(st.session_state.get(_alert_key(game["id"]), False))
    state_key = _alert_key(game["id"])
    widget_key = f"{state_key}_{context}_{instance}"
    enabled = bool(st.session_state.get(state_key, False))
    value = st.checkbox(
        "🔔 Flash alerts",
        value=enabled,
        key=widget_key,
        help="Flash the screen when this game's score changes.",
    )
    st.session_state[state_key] = value
    return value


def update_score_alerts(all_games, previous_snapshots=None):
    """Detect score/state changes for games the user has marked for alerts."""
    previous = previous_snapshots if previous_snapshots is not None else st.session_state.get("previous_game_snapshots", {})
    flashes = []
    for game in all_games:
        gid = str(game.get("id"))
        snapshot = (game.get("away_score", 0), game.get("home_score", 0), game.get("state"), game.get("period", ""), game.get("clock", ""))
        if st.session_state.get(_alert_key(gid), False):
            old = previous.get(gid)
            if old is not None and old != snapshot and (
                old[0] != snapshot[0] or old[1] != snapshot[1] or old[2] != snapshot[2]
            ):
                flashes.append(game)
    return flashes


def update_score_history(all_games, timezone_name, max_entries=12):
    """Keep a short session-local log of score/state changes, newest first."""
    previous = st.session_state.setdefault("previous_game_snapshots", {})
    history = st.session_state.setdefault("score_change_history", [])
    current = {}
    changes = []
    recent_changes = {}

    for game in all_games:
        gid = str(game.get("id") or "")
        if not gid:
            continue
        snapshot = (
            game.get("away_score", 0),
            game.get("home_score", 0),
            game.get("state"),
            game.get("period", ""),
            game.get("clock", ""),
        )
        current[gid] = snapshot
        old = previous.get(gid)
        if old is not None and old != snapshot and (
            old[0] != snapshot[0] or old[1] != snapshot[1] or old[2] != snapshot[2]
        ):
            if snapshot[2] == "post":
                change = "Final"
            elif snapshot[2] == "in" and old[2] == "pre":
                change = "Game started"
            elif snapshot[0] != old[0] or snapshot[1] != old[1]:
                change = f"Score changed to {snapshot[0]}–{snapshot[1]}"
            else:
                change = "Game status changed"
            change_item = {
                "game_id": gid,
                "away": game.get("away", "Away"),
                "home": game.get("home", "Home"),
                "sport": game.get("sport", "College Sports"),
                "change": change,
                "away_score": snapshot[0],
                "home_score": snapshot[1],
                "timestamp": datetime.now(ZoneInfo(timezone_name)).strftime("%I:%M:%S %p").lstrip("0"),
            }
            changes.append(change_item)
            if snapshot[0] != old[0] or snapshot[1] != old[1]:
                try:
                    away_delta = int(snapshot[0]) - int(old[0])
                    home_delta = int(snapshot[1]) - int(old[1])
                except (TypeError, ValueError):
                    away_delta = home_delta = 0
                if away_delta and not home_delta:
                    recent_changes[gid] = {"label": f"▲ {game.get('away','Away')} +{away_delta}"}
                elif home_delta and not away_delta:
                    recent_changes[gid] = {"label": f"▲ {game.get('home','Home')} +{home_delta}"}
                else:
                    recent_changes[gid] = {"label": "▲ Score changed"}

    if changes:
        history = changes + history
        st.session_state.score_change_history = history[:max_entries]
    st.session_state.previous_game_snapshots = current
    st.session_state.recent_score_changes = recent_changes
    return st.session_state.score_change_history


def render_score_history(history):
    if not history:
        st.caption("No score changes detected yet. The history fills in as the scoreboard refreshes.")
        return
    for item in history[:12]:
        st.markdown(
            f'<div class="history-row"><b>{item["away"]} {item["away_score"]}–{item["home_score"]} {item["home"]}</b><br>'
            f'<span class="history-time">{item["timestamp"]} • {item["sport"]} • {item["change"]}</span></div>',
            unsafe_allow_html=True,
        )


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
def live_dashboard(timezone_label, selected_timezone, sport_filter, close_thresholds, conference_filter, top25_only, date_offset, live_only, favorites_only, compact_mode, close_only):
    st.title("🏆 College Sports Live")
    selected_date = today_in_timezone(selected_timezone) + timedelta(days=date_offset)
    if date_offset == 0:
        date_label = "Today"
    elif date_offset == 1:
        date_label = "Tomorrow"
    elif date_offset == -1:
        date_label = "Yesterday"
    else:
        date_label = selected_date.strftime("%A, %B %-d, %Y") if hasattr(selected_date, "strftime") else str(selected_date)
    st.caption(f"NCAA college scores • {date_label} • Game times shown in {timezone_label}")

    try:
        refresh_started = time.perf_counter()
        data = get_all_scoreboards(selected_timezone, selected_date, sport_filter)
        refresh_duration = time.perf_counter() - refresh_started
        games = parse_games(data, selected_timezone, selected_date, fetch_volleyball_details=not close_only)
        games = dedupe_games(games)

        # The NCAA football scoreboard can sometimes return the next slate of
        # games even when a specific date was requested. Never let those
        # future games leak into the selected date. Use the actual parsed
        # local event date as the source of truth.
        games = [g for g in games if g.get("event_date") == selected_date]

        fetched_at_raw = data.get("fetched_at")
        fetched_at = None
        if fetched_at_raw:
            try:
                fetched_at = datetime.fromisoformat(fetched_at_raw)
            except (TypeError, ValueError):
                pass
        now_local = datetime.now(ZoneInfo(selected_timezone))
        age_seconds = max(0, (now_local - fetched_at).total_seconds()) if fetched_at else None
        errors = data.get("errors", [])
        failed_sports = sorted({str(e).split(" (")[0] for e in errors})
        if errors:
            connection_text = "⚠️ NCAA Data: Partial"
            connection_class = "update-warn"
            connection_detail = f"{len(errors)} feed error{'s' if len(errors) != 1 else ''}"
            if failed_sports:
                connection_detail += " • " + ", ".join(failed_sports[:3])
        else:
            connection_text = "🟢 NCAA Data: Connected"
            connection_class = "update-good"
            connection_detail = "All selected NCAA feeds responded"
        if age_seconds is None:
            freshness_class = "update-bad"
            freshness_text = "Scoreboard update time unavailable"
        elif age_seconds < 60:
            freshness_class = "update-good"
            freshness_text = f"Last updated {int(age_seconds)} sec ago"
        elif age_seconds < 180:
            freshness_class = "update-warn"
            freshness_text = f"Last updated {int(age_seconds // 60)} min ago"
        else:
            freshness_class = "update-bad"
            freshness_text = f"Last updated {int(age_seconds // 60)} min ago"
        updated_display = fetched_at.strftime("%I:%M:%S %p %Z").lstrip("0") if fetched_at else "Unknown"
        st.markdown(f'<div class="update-bar"><span class="{freshness_class}">🕐 {freshness_text}</span> &nbsp;•&nbsp; Updated at {updated_display} &nbsp;•&nbsp; Auto-refresh every {REFRESH_SECONDS}s &nbsp;•&nbsp; Refresh took {refresh_duration:.2f}s<br><span class="{connection_class}">{connection_text}</span> <span class="meta">• {connection_detail}</span></div>', unsafe_allow_html=True)
    except Exception as exc:
        st.error(f"Could not retrieve scores: {type(exc).__name__}: {exc}")
        st.stop()

    all_games_for_alerts = list(games)
    previous_snapshots = dict(st.session_state.get("previous_game_snapshots", {}))
    history = update_score_history(all_games_for_alerts, selected_timezone)
    flashes = update_score_alerts(all_games_for_alerts, previous_snapshots)
    if flashes:
        inject_flash_css()
        names = " • ".join(_game_label(g) for g in flashes[:4])
        st.markdown(f'<div class="scoreboard-flash">🚨 SCORE ALERT 🚨<br>{names}</div>', unsafe_allow_html=True)

    if show_diagnostics:
        with st.expander("🛠️ Scoreboard Diagnostics", expanded=True):
            st.write({"selected_time_zone": timezone_label, "selected_date": str(selected_date), "fetched_at": data.get("fetched_at"), "raw_combined_event_count": len(data.get("events", [])), "parsed_game_count": len(games), "errors": data.get("errors", [])})
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
    def close_limit(game):
        return int(close_thresholds.get(game.get("sport"), 7))
    if close_only:
        # In fast mode, fetch the heavier volleyball detail only for matches
        # whose current set/match margin already qualifies as close.
        close_vb_candidates = [g for g in live_games if g.get("sport") == "🏐 Women's Volleyball" and g.get("diff", 999) <= close_limit(g)]
        if close_vb_candidates:
            enrich_volleyball_details(close_vb_candidates)
    close_games = [g for g in live_games if g["diff"] <= close_limit(g)]
    other_live_games = [g for g in live_games if g["diff"] > close_limit(g)]
    if close_only:
        games = [g for g in games if g["state"] != "in" or g["diff"] <= close_limit(g)]
        live_games = [g for g in games if g["state"] == "in"]
        close_games = [g for g in live_games if g["diff"] <= close_limit(g)]
        other_live_games = []
    favorite_games = [g for g in games if is_favorite(g, favorites)]
    live_sorted = sorted(live_games, key=lambda g: (g["diff"], g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone))))
    final_sorted = sorted([g for g in games if g["state"] == "post"], key=lambda g: g["event_time"] or datetime.min.replace(tzinfo=ZoneInfo(selected_timezone)), reverse=True)
    upcoming_today = sorted([g for g in games if g["state"] == "pre"], key=lambda g: g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone)))

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("🔴 Live", len(live_games)); c2.metric("🔥 Close", len(close_games)); c3.metric("⭐ My Teams", len(favorite_games)); c4.metric("🏆 Games", len(games)); c5.metric("🔔 Alerts", sum(bool(st.session_state.get(_alert_key(g["id"]), False)) for g in all_games_for_alerts))

    if not close_only:
        st.markdown("---")
        st.subheader("⭐ My Teams")
        if favorites:
            favorite_items = list(favorites.items())
            columns_per_row = 3
            for row_start in range(0, len(favorite_items), columns_per_row):
                row = favorite_items[row_start:row_start + columns_per_row]
                cols = st.columns(columns_per_row)
                for col, (favorite_name, favorite_id) in zip(cols, row):
                    with col:
                        # Do not collapse a team's schedule to its first game.  A team
                        # can play multiple games on the same date (doubleheaders,
                        # tournaments, rescheduled games, etc.), so show every match.
                        team_games = [g for g in games if is_favorite(g, {favorite_name: favorite_id})]
                        team_games = sorted(
                            team_games,
                            key=lambda g: (
                                0 if g["state"] == "in" else (1 if g["state"] == "pre" else 2),
                                g.get("event_time") or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone)),
                            ),
                        )
    
                        # Use the first available record across this team's games.
                        favorite_record = ""
                        for tg in team_games:
                            opponent_is_home = _normalize_team_name(tg["home"]) in {
                                _normalize_team_name(favorite_name)
                            } | {
                                _normalize_team_name(a) for a in FAVORITE_NAME_ALIASES.get(favorite_name, set())
                            }
                            if opponent_is_home:
                                favorite_record = tg.get("home_record") or record_maps.get(tg["sport"], {}).get(_normalize_team_name(tg["home"])) or record_maps.get(tg["sport"], {}).get(f"id:{tg.get('home_id', '')}") or ""
                            else:
                                favorite_record = tg.get("away_record") or record_maps.get(tg["sport"], {}).get(_normalize_team_name(tg["away"])) or record_maps.get(tg["sport"], {}).get(f"id:{tg.get('away_id', '')}") or ""
                            if favorite_record:
                                break
    
                        header_record = f" ({favorite_record})" if favorite_record else ""
                        if not team_games:
                            st.markdown(
                                f'<div class="myteam-card"><div class="myteam-name">⭐ {favorite_name}{header_record}</div>'
                                f'<div class="myteam-status">No game on this date</div>'
                                f'<div class="myteam-opponent">—</div></div>', unsafe_allow_html=True)
                            continue
    
                        game_rows = []
                        for game in team_games:
                            home_aliases = {_normalize_team_name(favorite_name)} | {
                                _normalize_team_name(a) for a in FAVORITE_NAME_ALIASES.get(favorite_name, set())
                            }
                            is_home = _normalize_team_name(game["home"]) in home_aliases
                            opponent = game["away"] if is_home else game["home"]
                            opponent_record = game.get("away_record") if is_home else game.get("home_record")
                            opponent_record = opponent_record or record_maps.get(game["sport"], {}).get(_normalize_team_name(opponent)) or record_maps.get(game["sport"], {}).get(f"id:{game.get('away_id' if is_home else 'home_id', '')}") or ""
                            favorite_game_record = game.get("home_record") if is_home else game.get("away_record")
                            favorite_game_record = favorite_game_record or favorite_record
    
                            result_prefix = ""
                            if game["state"] == "in":
                                status = "🔴 LIVE"
                                if game.get("sport") == "🏐 Women's Volleyball":
                                    score = f'{_volleyball_score_label(game, "home")}–{_volleyball_score_label(game, "away")}'
                                else:
                                    score = f'{game["home_score"]}–{game["away_score"]}'
                            elif game["state"] == "post":
                                status = "FINAL"
                                if game.get("sport") == "🏐 Women's Volleyball":
                                    score = f'{_volleyball_score_label(game, "home")}–{_volleyball_score_label(game, "away")}'
                                else:
                                    score = f'{game["home_score"]}–{game["away_score"]}'
                                fav_score = game["home_score"] if is_home else game["away_score"]
                                opp_score = game["away_score"] if is_home else game["home_score"]
                                try:
                                    if int(fav_score) > int(opp_score):
                                        result_prefix = "✅ WIN"
                                    elif int(fav_score) < int(opp_score):
                                        result_prefix = "❌ LOSS"
                                    else:
                                        result_prefix = "➖ TIE"
                                except (TypeError, ValueError):
                                    pass
                            else:
                                status = game.get("event_time").strftime("%I:%M %p %Z").lstrip("0") if game.get("event_time") else "UPCOMING"
                                score = "—"
    
                            alert = bool(st.session_state.get(_alert_key(game["id"]), False))
                            alert_text = " • 🔔" if alert else ""
                            matchup_badges = format_matchup_badges(game)
                            matchup_text = " • ".join(matchup_badges)
                            result_text = "vs" if is_home else "at"
                            favorite_icon = "🏠" if is_home else "✈️"
                            opponent_icon = "✈️" if is_home else "🏠"
                            favorite_team_label = f"{favorite_name}{f' ({favorite_game_record})' if favorite_game_record else ''} {favorite_icon}"
                            opponent_label = f"{opponent}{f' ({opponent_record})' if opponent_record else ''} {opponent_icon}"
                            game_rows.append(
                                f'<div class="myteam-game-row">'
                                f'<div class="myteam-status">{result_prefix + " • " if result_prefix else ""}{status}{alert_text} • {game["sport"]}{(" • " + matchup_text) if matchup_text else ""}</div>'
                                f'<div class="myteam-score">{score}</div>'
                                f'<div class="myteam-opponent">{favorite_team_label} {result_text} {opponent_label}</div>'
                                f'</div>'
                            )
    
                        st.markdown(
                            f'<div class="myteam-card"><div class="myteam-name">⭐ {favorite_name}{header_record}</div>'
                            + ''.join(game_rows)
                            + '</div>',
                            unsafe_allow_html=True,
                        )
        else:
            st.info("Select teams in the sidebar to build your My Teams dashboard.")
    
        st.markdown("---")
        with st.expander("📈 Score Change History", expanded=False):
            render_score_history(history)

    st.subheader("🔥 Close Games")
    close_sorted = sorted(close_games, key=lambda g: (g["diff"], g.get("event_time") or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone))))
    if not close_sorted:
        st.info("No close live games match the current filters.")
    elif len({close_limit(g) for g in close_sorted}) > 1:
        st.caption("Sport-specific close-game thresholds are applied.")
    for i, game in enumerate(close_sorted):
        context = "main"
        render_alert_toggle(game, context, i)
        render_game({**game, "_render_context":context}, favorite=is_favorite(game, favorites), close=True, rankings=ranking_maps.get(game["sport"], {}), records=record_maps.get(game["sport"], {}), compact=compact_mode)


    if not close_only:
        st.markdown("---")
        st.subheader("📺 Other Live Games")
        other_live_sorted = sorted(other_live_games, key=lambda g: (g.get("event_time") or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone)), g.get("diff", 999)))
        if not other_live_sorted:
            st.info("No other live games match the current filters.")
        other_start = len(close_sorted)
        for i, game in enumerate(other_live_sorted):
            render_alert_toggle(game, "other-live", other_start + i)
            render_game({**game, "_render_context":"other-live"}, favorite=is_favorite(game, favorites), close=False, rankings=ranking_maps.get(game["sport"], {}), records=record_maps.get(game["sport"], {}), compact=compact_mode)
    
        st.markdown("---")
        st.subheader("🏁 Final")
        if not final_sorted:
            st.info("No final games match the current filters.")
        final_start = len(close_sorted)
        for i, game in enumerate(final_sorted):
            context = "main"
            render_alert_toggle(game, context, final_start + i)
            render_game({**game, "_render_context":context}, favorite=is_favorite(game, favorites), close=False, rankings=ranking_maps.get(game["sport"], {}), records=record_maps.get(game["sport"], {}), compact=compact_mode)
    
        st.markdown("---")
        st.subheader("📅 Upcoming")
        if not upcoming_today: st.info("No upcoming games match the current filters.")
        for i, game in enumerate(upcoming_today):
            render_alert_toggle(game, "upcoming", i)
            render_game({**game, "_render_context":"upcoming"}, favorite=is_favorite(game, favorites), close=False, rankings=ranking_maps.get(game["sport"], {}), records=record_maps.get(game["sport"], {}), compact=compact_mode)

# Sidebar controls
with st.sidebar:
    st.header("⚙️ Settings")
    timezone_label = st.selectbox("Time zone", list(TIMEZONES.keys()), index=list(TIMEZONES.keys()).index(DEFAULT_TIMEZONE))
    selected_timezone = TIMEZONES[timezone_label]

    st.subheader("📅 Game Date")
    today_local = today_in_timezone(selected_timezone)
    selected_game_date = st.date_input(
        "Search any date",
        value=today_local,
        min_value=date(2000, 1, 1),
        max_value=date(2035, 12, 31),
        help="Choose any calendar date to load NCAA games for that day.",
    )
    date_offset = (selected_game_date - today_local).days

    st.markdown("**🏅 Sports**")
    st.caption("Select one or more sports to load. Leaving all unchecked makes no NCAA score requests.")
    sport_filter = []
    for _sport_name in SPORTS.keys():
        if st.checkbox(_sport_name, value=False, key=f"sport_select_{_sport_name}"):
            sport_filter.append(_sport_name)
    conference_options = ["ACC","AAC","America East","Atlantic 10","ASUN","Big 12","Big East","Big Sky","Big South","Big Ten","Big West","CAA","C-USA","Horizon League","Ivy League","MAAC","MAC","MEAC","Missouri Valley","Mountain West","NEC","Ohio Valley","Pac-12","Patriot League","SEC","SoCon","Southland","Summit League","Sun Belt","SWAC","WAC","WCC","West Coast","Independent"]
    conference_filter = st.multiselect("🏟️ Conferences", conference_options, default=[])
    top25_only = st.checkbox("🏆 Top 25 teams only", value=False)
    live_only = st.checkbox("🔴 Live games only", value=False)
    close_only = st.checkbox(
        "🔥 Close games only",
        value=False,
        help="Show only live games that meet the close-game threshold. Final and upcoming games remain hidden."
    )
    favorites_only = st.checkbox("⭐ My Teams only", value=False)
    with st.expander("🔥 Close-game settings", expanded=False):
        st.caption("Set the score margin that counts as a close game for each sport. Volleyball uses set margin; its points-per-set scores are shown separately. A game at the threshold is included.")
        close_thresholds = {}
        threshold_limits = {
            "🏈 Football": (1, 30),
            "⚽ Men's Soccer": (1, 10),
            "⚽ Women's Soccer": (1, 10),
            "🏀 Men's Basketball": (1, 20),
            "🏀 Women's Basketball": (1, 20),
            "🏐 Women's Volleyball": (1, 10),
            "⚾ Baseball": (1, 10),
            "🥎 Softball": (1, 10),
        }
        for sport_name in SPORTS:
            low, high = threshold_limits[sport_name]
            close_thresholds[sport_name] = st.slider(
                sport_name, min_value=low, max_value=high,
                value=DEFAULT_CLOSE_THRESHOLDS[sport_name],
                key=f"close_threshold_{sport_name}",
            )
    compact_mode = st.checkbox("📱 Compact scoreboard", value=False, help="Tighten cards and spacing so more games fit on screen.")

    st.markdown("---")
    st.subheader("⭐ Favorite Teams")
    if "favorites" not in st.session_state: st.session_state.favorites = dict(DEFAULT_FAVORITES)
    favorite_options = list(TEAM_IDS.keys())
    current_favorites = [name for name in favorite_options if name in st.session_state.favorites]
    selected_favorites = st.multiselect("My Teams", favorite_options, default=current_favorites)
    st.session_state.favorites = {name: TEAM_IDS[name] for name in selected_favorites}

    st.markdown("---")
    st.subheader("🔔 Score Alerts")
    st.caption("Use the 🔔 Flash alerts checkbox on a game card. Marked games flash on screen when their score changes.")
    show_diagnostics = st.checkbox("Show diagnostics", value=False)

    st.caption("Scores refresh quietly every 30 seconds. Manual refresh only refreshes the NCAA score feeds, leaving rankings and logos cached.")
    if st.button("🔄 Refresh now", use_container_width=True):
        _get_cached_scoreboard_snapshot.clear()
        st.rerun()

if not sport_filter:
    st.info("Select one or more sports in the sidebar to load scores. No score feeds are requested until you choose a sport.")
live_dashboard(timezone_label, selected_timezone, sport_filter, close_thresholds, conference_filter, top25_only, date_offset, live_only, favorites_only, compact_mode, close_only)

