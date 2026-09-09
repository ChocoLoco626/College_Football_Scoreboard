from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import streamlit as st

REFRESH_SECONDS = 30
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
TIMEZONES = {
    "Eastern Time": "America/New_York",
    "Central Time": "America/Chicago",
}
DEFAULT_TIMEZONE = "Eastern Time"

# Keep the app focused on the sports you said you actually care about.
# Every sport uses the same ESPN date-window/fallback logic.
SPORTS = {
    "🏈 Football": [
        ("football", "college-football", "FBS", 80),
        ("football", "college-football", "FCS", 81),
    ],
    "⚽ Men's Soccer": [("soccer", "mens-college-soccer", "NCAA", 50)],
    "⚽ Women's Soccer": [("soccer", "womens-college-soccer", "NCAA", 50)],
    "🏀 Men's Basketball": [("basketball", "mens-college-basketball", "NCAA", 50)],
    "🏀 Women's Basketball": [("basketball", "womens-college-basketball", "NCAA", 50)],
    "🏐 Women's Volleyball": [("volleyball", "womens-college-volleyball", "NCAA", None)],
    "⚾ Baseball": [("baseball", "college-baseball", "NCAA", 50)],
    "🥎 Softball": [("softball", "college-softball", "NCAA", 50)],
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


def get_ncaa_volleyball_scoreboard(timezone_name):
    """Reliable Division I women's volleyball fallback using the NCAA scoreboard feed.

    ESPN's public volleyball scoreboard is currently inconsistent for upcoming
    matches even though ESPN's own web scoreboard lists them. The NCAA D-I
    scoreboard provides the same contests and is used as the primary volleyball
    source, with ESPN remaining the source for the other sports.
    """
    local_date = today_in_timezone(timezone_name)
    date_path = local_date.strftime("%Y/%m/%d")
    url = f"https://ncaa-api.henrygd.me/scoreboard/volleyball-women/d1/{date_path}"
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()

    events = []
    raw_games = payload.get("games", []) if isinstance(payload, dict) else []
    for item in raw_games:
        game = item.get("game", item) if isinstance(item, dict) else {}
        if not isinstance(game, dict):
            continue
        away = game.get("away", {}) or {}
        home = game.get("home", {}) or {}
        away_names = away.get("names", {}) or {}
        home_names = home.get("names", {}) or {}
        away_name = away_names.get("full") or away_names.get("short") or "Away"
        home_name = home_names.get("full") or home_names.get("short") or "Home"
        game_id = str(game.get("gameID") or game.get("gameId") or "ncaa-" + away_name + "-" + home_name)

        start = game.get("startTime") or game.get("startTimeEpoch") or game.get("date")
        event_date = local_date
        event_dt = None
        if isinstance(start, (int, float)) or (isinstance(start, str) and start.isdigit()):
            event_dt = datetime.fromtimestamp(float(start) / 1000 if float(start) > 100000000000 else float(start), tz=ZoneInfo("UTC")).astimezone(ZoneInfo(timezone_name))
            event_date = event_dt.date()
        elif isinstance(start, str) and start:
            try:
                event_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ZoneInfo(timezone_name))
                event_date = event_dt.date()
            except ValueError:
                pass

        state_raw = str(game.get("gameState", game.get("status", "P"))).upper()
        state = "in" if state_raw in ("I", "LIVE", "IN") else ("post" if state_raw in ("F", "FINAL", "POST") else "pre")
        try:
            away_score = int(away.get("score", 0))
        except (TypeError, ValueError):
            away_score = 0
        try:
            home_score = int(home.get("score", 0))
        except (TypeError, ValueError):
            home_score = 0

        events.append({
            "id": game_id,
            "date": event_dt.isoformat() if event_dt else None,
            "status": {"type": {"state": state, "shortDetail": game.get("statusDetail", "")}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "away", "team": {"id": str(away.get("id", "")), "displayName": away_name, "logo": away.get("logo", "")}, "score": str(away_score)},
                    {"homeAway": "home", "team": {"id": str(home.get("id", "")), "displayName": home_name, "logo": home.get("logo", "")}, "score": str(home_score)},
                ],
                "broadcasts": [],
            }],
            "_sport_name": "🏐 Women's Volleyball",
            "_sport": "volleyball",
            "_league": "womens-college-volleyball",
            "_division": "NCAA D-I",
        })
    return {"events": events, "_diagnostic": {
        "source": "NCAA D-I volleyball",
        "url": url,
        "payload_type": type(payload).__name__,
        "payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        "raw_game_count": len(raw_games),
        "parsed_event_count": len(events),
        "sample_raw_keys": [list(x.keys()) if isinstance(x, dict) else type(x).__name__ for x in raw_games[:5]],
        "sample_games": [
            {
                "away": ((x.get("game", x) or {}).get("away", {}) or {}).get("names", {}) if isinstance(x, dict) else {},
                "home": ((x.get("game", x) or {}).get("home", {}) or {}).get("names", {}) if isinstance(x, dict) else {},
                "startTime": ((x.get("game", x) or {}).get("startTime") if isinstance(x, dict) else None),
                "gameState": ((x.get("game", x) or {}).get("gameState") if isinstance(x, dict) else None),
            } for x in raw_games[:5]
        ],
    }}


def get_scoreboard(sport, league, group=None, timezone_name=TIMEZONES[DEFAULT_TIMEZONE]):
    """Fetch today's ESPN schedule, with a tomorrow-inclusive fallback.

    The important part is that EVERY supported sport follows this exact path,
    rather than volleyball having special-case behavior.
    """
    url = f"{ESPN_BASE}/{sport}/{league}/scoreboard"
    today = today_in_timezone(timezone_name)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    today_str = today.strftime("%Y%m%d")
    window_str = f"{today_str}-{tomorrow.strftime('%Y%m%d')}"

    base_params = {"limit": 1000}

    # Most NCAA scoreboards benefit from groups=50, but ESPN's women's
    # volleyball feed is more reliable without that filter.  We therefore
    # try both forms whenever a group was supplied, merging the results.
    request_variants = []
    if group is not None:
        request_variants.append({"limit": 1000, "groups": str(group)})
        request_variants.append({"limit": 1000})
    else:
        request_variants.append({"limit": 1000})

    # ESPN's college volleyball feed can be inconsistent about which calendar
    # date is returned for events near midnight/time-zone boundaries. Fetch a
    # slightly wider window, then the app performs the authoritative local
    # time-zone filtering after parsing each event timestamp.
    date_windows = [
        today_str,
        f"{yesterday.strftime('%Y%m%d')}-{tomorrow.strftime('%Y%m%d')}",
    ]

    merged_events = {}
    last_data = {"events": []}
    diagnostics = {
        "source": f"ESPN {sport}/{league}",
        "url": url,
        "requests": [],
        "merged_event_count": 0,
    }
    for date_value in date_windows:
        for variant in request_variants:
            params = {**variant, "dates": date_value}
            response = requests.get(
                url, params=params, timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            data = response.json()
            last_data = data
            diagnostics["requests"].append({
                "dates": date_value,
                "params": params,
                "http_status": response.status_code,
                "event_count": len(data.get("events", [])),
                "top_keys": list(data.keys())[:20] if isinstance(data, dict) else [],
            })
            for event in data.get("events", []):
                event_id = str(event.get("id", ""))
                if event_id:
                    merged_events[event_id] = event

    # Final fallback: ESPN's default scoreboard date. Some college feeds can
    # temporarily return a sparse dated response, especially volleyball.
    if not merged_events:
        response = requests.get(
            url, params={"limit": 1000}, timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        data = response.json()
        for event in data.get("events", []):
            event_id = str(event.get("id", ""))
            if event_id:
                merged_events[event_id] = event

    diagnostics["merged_event_count"] = len(merged_events)
    result = {"events": list(merged_events.values())} if merged_events else last_data
    result["_diagnostic"] = diagnostics
    return result


@st.cache_data(ttl=20)
def get_all_scoreboards(timezone_name):
    combined = []
    errors = []
    diagnostics = []
    for sport_name, configs in SPORTS.items():
        for sport, league, division, group in configs:
            try:
                if sport_name == "🏐 Women's Volleyball":
                    data = get_ncaa_volleyball_scoreboard(timezone_name)
                else:
                    data = get_scoreboard(sport, league, group, timezone_name)
                if data.get("_diagnostic"):
                    diagnostics.append({"sport": sport_name, **data["_diagnostic"]})
                for event in data.get("events", []):
                    event["_sport_name"] = sport_name
                    event["_sport"] = sport
                    event["_league"] = league
                    event["_division"] = division
                    combined.append(event)
            except requests.RequestException as exc:
                errors.append(f"{sport_name}: {exc}")
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
        })
    return games


def is_favorite(game, favorites):
    return game["home_id"] in favorites.values() or game["away_id"] in favorites.values()


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

    away_logo = f'<img src="{game["away_logo"]}" width="36">' if game["away_logo"] else ""
    home_logo = f'<img src="{game["home_logo"]}" width="36">' if game["home_logo"] else ""

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
      <div class="team">{away_logo} {game['away']}<span class="score">{away_score}</span></div>
      <div class="team">{home_logo} {game['home']}<span class="score">{home_score}</span></div>
      <div class="meta">Score difference: {game['diff']}{clock}{(' • Start: ' + start_time) if start_time else ''}</div>
    </div>
    """, unsafe_allow_html=True)


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
    st.caption(f"ESPN college scores • Showing times in {timezone_label}")

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

    # Only show games whose event timestamp lands on today's ESPN/U.S. Eastern
    # calendar date. Tomorrow is fetched only as a reliability fallback.
    today = today_in_timezone(selected_timezone)
    games = [g for g in games if g.get("event_date") == today]

    favorites = st.session_state.favorites
    live_games = [g for g in games if g["state"] == "in"]
    close_games = [g for g in live_games if g["diff"] < threshold]
    favorite_games = [g for g in games if is_favorite(g, favorites)]

    games_by_closeness = sorted(
        games,
        key=lambda g: (
            g["state"] != "in",
            g["diff"] if g["state"] in ("in", "post") else 9999,
            g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone)),
        ),
    )

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
            team_games = [g for g in games if g["home_id"] == favorite_id or g["away_id"] == favorite_id]
            st.markdown(f"### ⭐ {favorite_name}")
            if not team_games:
                st.caption("No games found on today's ESPN scoreboards.")
            else:
                team_games.sort(key=lambda g: (g["state"] != "in", g["event_time"] or datetime.max.replace(tzinfo=ZoneInfo(selected_timezone))))
                for game in team_games:
                    render_game(game, favorite=True, close=(game["state"] == "in" and game["diff"] < threshold))
    else:
        st.info("Select teams in the sidebar to build your My Teams dashboard.")

    st.markdown("---")
    st.subheader("📅 Upcoming Today")
    if not upcoming_today:
        st.info("No upcoming games are currently listed by ESPN for today in the selected sports.")
    else:
        st.caption("Games scheduled for later today, according to ESPN.")
        for game in upcoming_today:
            render_game(game, favorite=is_favorite(game, favorites), close=False)

    st.markdown("---")
    st.subheader("🏆 All Games — Sorted by Closeness")
    if not games_by_closeness:
        st.info("No games are currently available for the selected sports today.")
    else:
        for game in games_by_closeness:
            render_game(game, favorite=is_favorite(game, favorites), close=(game["state"] == "in" and game["diff"] < threshold))


live_dashboard(timezone_label, selected_timezone, sport_filter, threshold)
