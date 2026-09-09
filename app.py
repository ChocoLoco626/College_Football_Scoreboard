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
    "🏐 Women's Volleyball": [("volleyball", "womens-college-volleyball", "NCAA", 50)],
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
    if group is not None:
        base_params["groups"] = str(group)

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
    for date_value in date_windows:
        params = {**base_params, "dates": date_value}
        response = requests.get(
            url, params=params, timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        data = response.json()
        last_data = data
        for event in data.get("events", []):
            event_id = str(event.get("id", ""))
            if event_id:
                merged_events[event_id] = event

    # Final fallback: ESPN's default scoreboard date. Some college feeds can
    # temporarily return a sparse dated response, especially volleyball.
    if not merged_events:
        response = requests.get(
            url, params=base_params, timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        data = response.json()
        for event in data.get("events", []):
            event_id = str(event.get("id", ""))
            if event_id:
                merged_events[event_id] = event

    return {"events": list(merged_events.values())} if merged_events else last_data


@st.cache_data(ttl=20)
def get_all_scoreboards(timezone_name):
    combined = []
    errors = []
    for sport_name, configs in SPORTS.items():
        for sport, league, division, group in configs:
            try:
                data = get_scoreboard(sport, league, group, timezone_name)
                for event in data.get("events", []):
                    event["_sport_name"] = sport_name
                    event["_sport"] = sport
                    event["_league"] = league
                    event["_division"] = division
                    combined.append(event)
            except requests.RequestException as exc:
                errors.append(f"{sport_name}: {exc}")
    return {"events": combined, "errors": errors}


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
        try:
            event_dt = datetime.fromisoformat(event.get("date", "").replace("Z", "+00:00")).astimezone(ZoneInfo(timezone_name))
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
        st.error(f"Could not retrieve ESPN scores: {exc}")
        st.stop()

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
