from datetime import datetime
import requests
import streamlit as st

REFRESH_SECONDS = 30
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# ESPN sport/league combinations. Some sports are seasonal, so an empty
# scoreboard is normal when that sport is out of season.
SPORTS = {
    "All Sports": None,
    "🏈 Football": [("football", "college-football", "FBS", 80), ("football", "college-football", "FCS", 81)],
    "🏀 Men's Basketball": [("basketball", "mens-college-basketball", "NCAA", None)],
    "🏀 Women's Basketball": [("basketball", "womens-college-basketball", "NCAA", None)],
    "⚾ Baseball": [("baseball", "college-baseball", "NCAA", None)],
    "🥎 Softball": [("softball", "college-softball", "NCAA", None)],
    "🏒 Men's Hockey": [("hockey", "mens-college-hockey", "NCAA", None)],
    "🏒 Women's Hockey": [("hockey", "womens-college-hockey", "NCAA", None)],
    "⚽ Men's Soccer": [("soccer", "mens-college-soccer", "NCAA", None)],
    "⚽ Women's Soccer": [("soccer", "womens-college-soccer", "NCAA", None)],
    "🥍 Men's Lacrosse": [("lacrosse", "mens-college-lacrosse", "NCAA", None)],
    "🥍 Women's Lacrosse": [("lacrosse", "womens-college-lacrosse", "NCAA", None)],
    "🏐 Men's Volleyball": [("volleyball", "mens-college-volleyball", "NCAA", None)],
    "🏐 Women's Volleyball": [("volleyball", "womens-college-volleyball", "NCAA", None)],
    "🏑 Field Hockey": [("field-hockey", "college-field-hockey", "NCAA", None)],
    "🤸 Women's Gymnastics": [("gymnastics", "womens-college-gymnastics", "NCAA", None)],
    "🎾 Men's Tennis": [("tennis", "mens-college-tennis", "NCAA", None)],
    "🎾 Women's Tennis": [("tennis", "womens-college-tennis", "NCAA", None)],
    "🤼 Wrestling": [("wrestling", "college-wrestling", "NCAA", None)],
    "⛳ Men's Golf": [("golf", "college-golf", "NCAA", None)],
    "⛳ Women's Golf": [("golf", "college-womens-golf", "NCAA", None)],
    "🏊 Swimming & Diving": [("swimming-and-diving", "college-swimming-and-diving", "NCAA", None)],
    "🏃 Track & Field": [("track-and-field", "college-track-and-field", "NCAA", None)],
    "🏃 Cross Country": [("cross-country", "college-cross-country", "NCAA", None)],
    "🚣 Rowing": [("rowing", "college-rowing", "NCAA", None)],
    "🤽 Water Polo": [("water-polo", "college-water-polo", "NCAA", None)],
}

DEFAULT_FAVORITES = {"Kentucky": "96", "Auburn": "2", "West Florida": "2908"}
TEAM_IDS = {
    "Kentucky": "96", "Auburn": "2", "West Florida": "2908", "Alabama": "333",
    "Georgia": "61", "Florida": "57", "Florida State": "52", "Miami": "2390",
    "LSU": "99", "Tennessee": "2633", "Clemson": "228", "Ohio State": "194",
    "Michigan": "130", "Notre Dame": "87",
}

st.set_page_config(page_title="College Sports Live", page_icon="🏆", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.game-card { border:1px solid rgba(128,128,128,.35); border-radius:14px; padding:15px 18px; margin:8px 0; }
.score { font-size:30px; font-weight:800; float:right; }
.team { font-size:18px; font-weight:700; margin:8px 0; min-height:38px; }
.meta { color:#9ca3af; font-size:13px; }
.section { margin-top:18px; }
</style>
""", unsafe_allow_html=True)


def get_scoreboard(sport, league, group=None):
    url = f"{ESPN_BASE}/{sport}/{league}/scoreboard"
    params = {"limit": 1000}
    if group is not None:
        params["groups"] = str(group)
    response = requests.get(url, params=params, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=20)
def get_all_scoreboards():
    combined = []
    errors = []
    for sport_name, configs in SPORTS.items():
        if sport_name == "All Sports" or not configs:
            continue
        for sport, league, division, group in configs:
            try:
                data = get_scoreboard(sport, league, group)
                for event in data.get("events", []):
                    event["_sport_name"] = sport_name
                    event["_sport"] = sport
                    event["_league"] = league
                    event["_division"] = division
                    combined.append(event)
            except requests.RequestException as exc:
                errors.append(f"{sport_name}: {exc}")
    return {"events": combined, "errors": errors}


def parse_games(data):
    games = []
    for event in data.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        if len(competitors) < 2:
            continue
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        def score(c):
            try: return int(c.get("score", 0))
            except (TypeError, ValueError): return 0

        hs, aws = score(home), score(away)
        status = event.get("status", {})
        type_info = status.get("type", {})
        state = type_info.get("state", "pre")
        games.append({
            "id": event.get("id"), "sport": event.get("_sport_name", "College Sports"),
            "division": event.get("_division", "NCAA"),
            "home": home.get("team", {}).get("displayName", "Home"),
            "away": away.get("team", {}).get("displayName", "Away"),
            "home_id": str(home.get("team", {}).get("id", "")), "away_id": str(away.get("team", {}).get("id", "")),
            "home_logo": home.get("team", {}).get("logo", ""), "away_logo": away.get("team", {}).get("logo", ""),
            "home_score": hs, "away_score": aws, "diff": abs(hs - aws), "state": state,
            "detail": type_info.get("shortDetail") or type_info.get("detail") or "",
            "clock": status.get("displayClock", ""), "period": status.get("period", ""),
            "broadcasts": [n for b in competition.get("broadcasts", []) for n in b.get("names", [])],
        })
    return games


def is_favorite(game, favorites):
    return game["home_id"] in favorites.values() or game["away_id"] in favorites.values()


def render_game(game, favorite=False, close=False):
    status_badge = "🔴 LIVE" if game["state"] == "in" else ("FINAL" if game["state"] == "post" else "UPCOMING")
    meta = " • ".join(x for x in [
        status_badge, game["division"], "⭐ FAVORITE" if favorite else "", "🔥 CLOSE" if close else "",
        game["detail"], f"TV: {', '.join(game['broadcasts'])}" if game["broadcasts"] else ""
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
    st.markdown(f"""
    <div class="game-card">
      <div class="meta">{game['sport']} • {meta}</div>
      <div class="team">{away_logo} {game['away']}<span class="score">{away_score}</span></div>
      <div class="team">{home_logo} {game['home']}<span class="score">{home_score}</span></div>
      <div class="meta">Score difference: {game['diff']}{clock}</div>
    </div>""", unsafe_allow_html=True)


if "favorites" not in st.session_state:
    st.session_state.favorites = dict(DEFAULT_FAVORITES)

with st.sidebar:
    st.header("🏆 College Sports Controls")
    sport_filter = st.multiselect("Sports", list(SPORTS.keys())[1:], default=list(SPORTS.keys())[1:])
    threshold = st.slider("Close-game threshold", 1, 30, 10)
    st.divider()
    st.header("⭐ Favorite Teams")
    favorite_choices = st.multiselect("Teams", list(TEAM_IDS.keys()), default=list(DEFAULT_FAVORITES.keys()))
    st.session_state.favorites = {name: TEAM_IDS[name] for name in favorite_choices}
    st.divider()
    refresh = st.number_input("Refresh interval (seconds)", min_value=10, max_value=300, value=30, step=5)
    if st.button("🔄 Refresh now", use_container_width=True):
        get_all_scoreboards.clear()
        st.rerun()


@st.fragment(run_every=30)
def live_dashboard():
    st.title("🏆 College Sports Live")
    st.caption("ESPN college scores • Football FBS/FCS + other NCAA sports • Live games prioritized")
    try:
        data = get_all_scoreboards()
        games = parse_games(data)
    except Exception as exc:
        st.error(f"Could not retrieve ESPN scores: {exc}")
        st.stop()

    selected = set(sport_filter)
    if selected:
        games = [g for g in games if g["sport"] in selected]

    favorites = st.session_state.favorites
    live_games = [g for g in games if g["state"] == "in"]
    close_games = [g for g in live_games if g["diff"] < threshold]
    favorite_games = [g for g in games if is_favorite(g, favorites)]
    games_by_closeness = sorted(games, key=lambda g: (g["state"] != "in", g["diff"], g["state"] == "post"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Live", len(live_games)); c2.metric(f"🔥 Under {threshold}", len(close_games)); c3.metric("⭐ My Teams", len(favorite_games)); c4.metric("🏆 Total Games", len(games))
    st.markdown("---")

    st.subheader("⭐ My Teams")
    if favorite_games:
        for favorite_name, favorite_id in favorites.items():
            team_games = [g for g in games if g["home_id"] == favorite_id or g["away_id"] == favorite_id]
            st.markdown(f"### ⭐ {favorite_name}")
            if not team_games:
                st.caption("No games found on the current ESPN scoreboards.")
            else:
                team_games.sort(key=lambda g: (g["state"] != "in", g["diff"], g["state"] == "post"))
                for game in team_games:
                    render_game(game, favorite=True, close=(game["state"] == "in" and game["diff"] < threshold))
    else:
        st.info("Select teams in the sidebar to build your My Teams dashboard.")

    st.markdown("---")
    st.subheader("🏆 All Games — Sorted by Closeness")
    if not games_by_closeness:
        st.info("No games are currently available for the selected sports. This is normal for sports that are out of season.")
    else:
        for game in games_by_closeness:
            render_game(game, favorite=is_favorite(game, favorites), close=(game["state"] == "in" and game["diff"] < threshold))

    if data.get("errors"):
        st.caption("Some ESPN sport feeds were unavailable or out of season; available feeds are still shown.")
    st.caption(f"Last updated {datetime.now().strftime('%I:%M:%S %p')} • Live refresh is every {REFRESH_SECONDS} seconds")

live_dashboard()
