import time
from datetime import datetime
import requests
import streamlit as st

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
REFRESH_SECONDS = 30

# ESPN team IDs are used so favorites are reliable even when display names differ.
DEFAULT_FAVORITES = {
    "Kentucky": "96",
    "Auburn": "2",
    "West Florida": "2908",
}

st.set_page_config(
    page_title="College Football Live",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.game-card {
    border: 1px solid rgba(128,128,128,.35);
    border-radius: 14px;
    padding: 15px 18px;
    margin: 8px 0;
}
.score {
    font-size: 30px;
    font-weight: 800;
    text-align: right;
}
.team {
    font-size: 19px;
    font-weight: 700;
}
.meta {
    color: #9ca3af;
    font-size: 13px;
}
.badge {
    display: inline-block;
    border-radius: 999px;
    padding: 3px 9px;
    font-size: 12px;
    font-weight: 700;
    margin-right: 5px;
}
</style>
""", unsafe_allow_html=True)


def get_scoreboard(group):
    response = requests.get(
        ESPN_URL,
        params={"groups": str(group)},
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=20)
def get_all_scoreboards():
    combined = []

    for group, division in ((80, "FBS"), (81, "FCS")):
        try:
            data = get_scoreboard(group)
            for event in data.get("events", []):
                event["_division"] = division
                combined.append(event)
        except requests.RequestException:
            pass

    return {"events": combined}


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
            try:
                return int(c.get("score", 0))
            except (TypeError, ValueError):
                return 0

        hs = score(home)
        aws = score(away)

        status = event.get("status", {})
        type_info = status.get("type", {})
        state = type_info.get("state", "pre")

        games.append({
            "id": event.get("id"),
            "division": event.get("_division", "College"),
            "home": home.get("team", {}).get("displayName", "Home"),
            "away": away.get("team", {}).get("displayName", "Away"),
            "home_short": home.get("team", {}).get("shortDisplayName", home.get("team", {}).get("displayName", "Home")),
            "away_short": away.get("team", {}).get("shortDisplayName", away.get("team", {}).get("displayName", "Away")),
            "home_abbr": home.get("team", {}).get("abbreviation", ""),
            "away_abbr": away.get("team", {}).get("abbreviation", ""),
            "home_id": str(home.get("team", {}).get("id", "")),
            "away_id": str(away.get("team", {}).get("id", "")),
            "home_logo": home.get("team", {}).get("logo", ""),
            "away_logo": away.get("team", {}).get("logo", ""),
            "home_score": hs,
            "away_score": aws,
            "diff": abs(hs - aws),
            "state": state,
            "detail": type_info.get("shortDetail") or type_info.get("detail") or "",
            "status_detail": type_info.get("detail") or "",
            "clock": status.get("displayClock", ""),
            "period": status.get("period", ""),
            "broadcasts": [
                n
                for b in competition.get("broadcasts", [])
                for n in b.get("names", [])
            ],
        })

    return games


def is_favorite(game, favorites):
    return game["home_id"] in favorites.values() or game["away_id"] in favorites.values()


def render_game(game, favorite=False, close=False):
    if game["state"] == "in":
        status_badge = "🔴 LIVE"
    elif game["state"] == "post":
        status_badge = "FINAL"
    else:
        status_badge = "UPCOMING"

    fav_badge = "⭐ FAVORITE" if favorite else ""
    close_badge = "🔥 CLOSE" if close else ""

    away_record = ""
    home_record = ""

    meta = " • ".join(x for x in [
        status_badge,
        game["division"],
        fav_badge,
        close_badge,
        game["detail"],
        f"TV: {', '.join(game['broadcasts'])}" if game["broadcasts"] else "",
    ] if x)

    away_logo = f'<img src="{game["away_logo"]}" width="36">' if game["away_logo"] else ""
    home_logo = f'<img src="{game["home_logo"]}" width="36">' if game["home_logo"] else ""

    score_lines = ""
    if game["state"] in ("in", "post"):
        score_lines = f"""
        <div class="team">{away_logo} {game["away"]}<span class="score">{game["away_score"]}</span></div>
        <div class="team">{home_logo} {game["home"]}<span class="score">{game["home_score"]}</span></div>
        """
    else:
        score_lines = f"""
        <div class="team">{away_logo} {game["away"]}<span class="score">—</span></div>
        <div class="team">{home_logo} {game["home"]}<span class="score">—</span></div>
        """

    clock = ""
    if game["state"] == "in":
        clock = f" • {game['period']}Q • {game['clock']}" if game["clock"] else f" • Period {game['period']}"

    diff = f'<div class="meta">Point difference: {game["diff"]}{clock}</div>'

    st.markdown(
        f"""
        <div class="game-card">
            <div class="meta">{meta}</div>
            <div style="margin-top:9px;">
                {score_lines}
            </div>
            {diff}
        </div>
        """,
        unsafe_allow_html=True,
    )


# Session state for favorites.
if "favorites" not in st.session_state:
    st.session_state.favorites = dict(DEFAULT_FAVORITES)

with st.sidebar:
    st.header("🏈 Scoreboard Controls")

    threshold = st.slider(
        "Close-game threshold",
        min_value=1,
        max_value=30,
        value=10,
        help="A game is considered close when the score difference is less than this number.",
    )

    division_filter = st.multiselect(
        "Divisions",
        ["FBS", "FCS"],
        default=["FBS", "FCS"],
    )

    st.divider()
    st.header("⭐ Favorite Teams")

    st.caption("Favorite teams appear in the My Teams dashboard.")

    favorite_choices = st.multiselect(
        "Teams",
        options=[
            "Kentucky",
            "Auburn",
            "West Florida",
            "Alabama",
            "Georgia",
            "Florida",
            "Florida State",
            "Miami",
            "LSU",
            "Tennessee",
            "Clemson",
            "Ohio State",
            "Michigan",
            "Notre Dame",
        ],
        default=[
            "Kentucky",
            "Auburn",
            "West Florida",
        ],
    )

    team_ids = {
        "Kentucky": "96",
        "Auburn": "2",
        "West Florida": "2908",
        "Alabama": "333",
        "Georgia": "61",
        "Florida": "57",
        "Florida State": "52",
        "Miami": "2390",
        "LSU": "99",
        "Tennessee": "2633",
        "Clemson": "228",
        "Ohio State": "194",
        "Michigan": "130",
        "Notre Dame": "87",
    }

    st.session_state.favorites = {
        name: team_ids[name]
        for name in favorite_choices
        if name in team_ids
    }

    st.divider()
    refresh = st.number_input(
        "Refresh interval (seconds)",
        min_value=10,
        max_value=300,
        value=30,
        step=5,
    )

    if st.button("🔄 Refresh now", use_container_width=True):
        get_all_scoreboards.clear()
        st.rerun()


@st.fragment(run_every=30)
def live_dashboard():
    st.title("🏈 College Football Live")
    st.caption("FBS + FCS • My Teams dashboard • All games sorted by closeness")

    try:
        data = get_all_scoreboards()
        games = parse_games(data)
    except Exception as exc:
        st.error(f"Could not retrieve ESPN scores: {exc}")
        st.stop()

    games = [g for g in games if g["division"] in division_filter]

    favorites = st.session_state.favorites

    live_games = [g for g in games if g["state"] == "in"]
    close_games = [g for g in live_games if g["diff"] < threshold]
    favorite_games = [g for g in games if is_favorite(g, favorites)]

    # ALL games are shown by closeness. Live games naturally rise to the top,
    # then games with smaller score differences, then scheduled/final games.
    # Favorites are not moved ahead of this global closeness ordering.
    games_by_closeness = sorted(
        games,
        key=lambda g: (
            g["state"] != "in",
            g["diff"],
            g["state"] == "post",
        ),
    )

    close_games.sort(key=lambda g: g["diff"])
    favorite_games.sort(key=lambda g: (
        g["state"] != "in",
        g["diff"],
    ))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Live", len(live_games))
    c2.metric(f"🔥 Under {threshold}", len(close_games))
    c3.metric("⭐ My Teams", len(favorite_games))
    c4.metric("🏈 Total Games", len(games))

    st.markdown("---")

    st.subheader("⭐ My Teams")

    if favorite_games:
        # Each favorite team gets its own section.
        for favorite_name, favorite_id in favorites.items():
            team_games = [
                g for g in games
                if g["home_id"] == favorite_id or g["away_id"] == favorite_id
            ]
            if not team_games:
                st.markdown(f"### ⭐ {favorite_name}")
                st.caption("No games found on the current ESPN scoreboard.")
                continue

            st.markdown(f"### ⭐ {favorite_name}")
            team_games.sort(key=lambda g: (
                g["state"] != "in",
                g["diff"],
                g["state"] == "post",
            ))
            for game in team_games:
                render_game(
                    game,
                    favorite=True,
                    close=(game["state"] == "in" and game["diff"] < threshold),
                )
    else:
        st.info("Select teams in the sidebar to build your My Teams dashboard.")

    st.markdown("---")
    st.subheader("🏈 All Games — Sorted by Closeness")

    if not games_by_closeness:
        st.info("No games match your division filters.")
    else:
        for game in games_by_closeness:
            render_game(
                game,
                favorite=is_favorite(game, favorites),
                close=(game["state"] == "in" and game["diff"] < threshold),
            )

    st.caption(
        f"Last updated {datetime.now().strftime('%I:%M:%S %p')} • "
        f"Live refresh: every {refresh} seconds"
    )

live_dashboard()
