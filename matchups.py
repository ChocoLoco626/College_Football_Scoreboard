"""Cached matchup intelligence for the NCAA scoreboard.

This module intentionally uses a local, curated rivalry database instead of
calling Wikipedia during every scoreboard refresh.  Event/postseason labels
come from the NCAA feed when available and are classified locally.
"""
import re


def _norm(name):
    return " ".join(str(name or "").lower().replace("&", "and").replace(".", "").split())


# Common school-name aliases.  The value is the stable short school key used
# by MATCHUP_INFO below.  Matching accepts the full NCAA display name too.
TEAM_ALIASES = {
    "alabama": ["alabama", "alabama crimson tide"],
    "auburn": ["auburn", "auburn tigers"],
    "arkansas": ["arkansas", "arkansas razorbacks"],
    "arkansas state": ["arkansas state", "arkansas state red wolves"],
    "army": ["army", "army black knights", "army west point"],
    "baylor": ["baylor", "baylor bears"],
    "boise state": ["boise state", "boise state broncos"],
    "boston college": ["boston college", "boston college eagles"],
    "byu": ["byu", "brigham young", "byu cougars"],
    "california": ["california", "cal", "california golden bears"],
    "clemson": ["clemson", "clemson tigers"],
    "colorado": ["colorado", "colorado buffaloes"],
    "connecticut": ["connecticut", "uconn", "connecticut huskies"],
    "duke": ["duke", "duke blue devils"],
    "florida": ["florida", "florida gators"],
    "florida state": ["florida state", "florida state seminoles", "florida st"],
    "georgia": ["georgia", "georgia bulldogs"],
    "georgia tech": ["georgia tech", "georgia tech yellow jackets"],
    "harvard": ["harvard", "harvard crimson"],
    "illinois": ["illinois", "illinois fighting illini"],
    "iowa": ["iowa", "iowa hawkeyes"],
    "iowa state": ["iowa state", "iowa state cyclones"],
    "kansas": ["kansas", "kansas jayhawks"],
    "kansas state": ["kansas state", "kansas state wildcats"],
    "kentucky": ["kentucky", "kentucky wildcats"],
    "louisville": ["louisville", "louisville cardinals"],
    "lsu": ["lsu", "louisiana state", "lsu tigers"],
    "maryland": ["maryland", "maryland terrapins"],
    "miami": ["miami", "miami hurricanes", "miami (fl)"],
    "michigan": ["michigan", "michigan wolverines"],
    "michigan state": ["michigan state", "michigan state spartans"],
    "minnesota": ["minnesota", "minnesota golden gophers"],
    "mississippi": ["mississippi", "ole miss", "ole miss rebels"],
    "mississippi state": ["mississippi state", "mississippi state bulldogs"],
    "missouri": ["missouri", "missouri tigers"],
    "navy": ["navy", "navy midshipmen"],
    "nebraska": ["nebraska", "nebraska cornhuskers"],
    "north carolina": ["north carolina", "unc", "north carolina tar heels"],
    "north carolina state": ["north carolina state", "nc state", "nc state wolfpack"],
    "northwestern": ["northwestern", "northwestern wildcats"],
    "notre dame": ["notre dame", "notre dame fighting irish"],
    "ohio state": ["ohio state", "ohio state buckeyes"],
    "oklahoma": ["oklahoma", "oklahoma sooners"],
    "oklahoma state": ["oklahoma state", "oklahoma state cowboys"],
    "oregon": ["oregon", "oregon ducks"],
    "oregon state": ["oregon state", "oregon state beavers"],
    "penn state": ["penn state", "pennsylvania state", "penn state nittany lions"],
    "pittsburgh": ["pittsburgh", "pitt", "pittsburgh panthers"],
    "princeton": ["princeton", "princeton tigers"],
    "purdue": ["purdue", "purdue boilermakers"],
    "south carolina": ["south carolina", "south carolina gamecocks"],
    "stanford": ["stanford", "stanford cardinal"],
    "syracuse": ["syracuse", "syracuse orange"],
    "tcu": ["tcu", "texas christian", "tcu horned frogs"],
    "tennessee": ["tennessee", "tennessee volunteers", "tennessee vols"],
    "texas": ["texas", "texas longhorns"],
    "texas a and m": ["texas a and m", "texas am", "texas a&m", "texas a and m aggies"],
    "texas tech": ["texas tech", "texas tech red raiders"],
    "ucla": ["ucla", "ucla bruins"],
    "usc": ["usc", "southern california", "usc trojans"],
    "utah": ["utah", "utah utes"],
    "virginia": ["virginia", "virginia cavaliers"],
    "virginia tech": ["virginia tech", "virginia tech hokies"],
    "wake forest": ["wake forest", "wake forest demon deacons"],
    "washington": ["washington", "washington huskies"],
    "washington state": ["washington state", "washington state cougars"],
    "west virginia": ["west virginia", "west virginia mountaineers"],
    "wisconsin": ["wisconsin", "wisconsin badgers"],
    "yale": ["yale", "yale bulldogs"],
}

# Additional common NCAA school aliases used by rivalry schedules.
TEAM_ALIASES.update({
    "indiana": ["indiana", "indiana hoosiers"],
    "purdue": ["purdue", "purdue boilermakers"],
    "missouri": ["missouri", "missouri tigers", "mizzou"],
    "illinois": ["illinois", "illinois fighting illini"],
    "arizona": ["arizona", "arizona wildcats"],
    "arizona state": ["arizona state", "arizona state sun devils", "asu"],
    "georgetown": ["georgetown", "georgetown hoyas"],
    "villanova": ["villanova", "villanova wildcats"],
    "cincinnati": ["cincinnati", "cincinnati bearcats"],
    "xavier": ["xavier", "xavier musketeers"],
    "gonzaga": ["gonzaga", "gonzaga bulldogs"],
    "saint marys": ["saint marys", "saint mary's", "saint marys gaels"],
    "oregon": ["oregon", "oregon ducks"],
    "washington": ["washington", "washington huskies"],
    "stanford": ["stanford", "stanford cardinal"],
    "california": ["california", "cal", "california golden bears"],
    "colorado": ["colorado", "colorado buffaloes"],
    "colorado state": ["colorado state", "colorado state rams"],
    "brigham young": ["brigham young", "byu", "byu cougars"],
    "utah": ["utah", "utah utes"],
    "baylor": ["baylor", "baylor bears"],
    "texas christian": ["texas christian", "tcu", "tcu horned frogs"],
    "texas tech": ["texas tech", "texas tech red raiders"],
    "virginia": ["virginia", "virginia cavaliers"],
    "virginia tech": ["virginia tech", "virginia tech hokies"],
    "maryland": ["maryland", "maryland terrapins"],
    "rutgers": ["rutgers", "rutgers scarlet knights"],
    "south carolina": ["south carolina", "south carolina gamecocks"],
    "clemson": ["clemson", "clemson tigers"],
})

TEAM_KEY_BY_ALIAS = {}
for key, aliases in TEAM_ALIASES.items():
    for alias in aliases:
        TEAM_KEY_BY_ALIAS[_norm(alias)] = key


def team_key(name):
    n = _norm(name)
    if n in TEAM_KEY_BY_ALIAS:
        return TEAM_KEY_BY_ALIAS[n]
    # NCAA often appends a mascot to an otherwise exact school name.
    for alias, key in sorted(TEAM_KEY_BY_ALIAS.items(), key=lambda x: len(x[0]), reverse=True):
        if n.startswith(alias + " ") or n.endswith(" " + alias):
            return key
    return n


# Curated high-confidence rivalries.  Wikipedia is used as a reference when
# maintaining this list, but it is not queried by the running application.
# This avoids adding network calls to the 30-second scoreboard refresh.
MATCHUP_INFO = {
    frozenset(("kentucky", "louisville")): {"type": "rivalry", "name": "Governor's Cup", "icon": "🔥"},
    frozenset(("alabama", "auburn")): {"type": "rivalry", "name": "Iron Bowl", "icon": "🔥"},
    frozenset(("army", "navy")): {"type": "rivalry", "name": "Army–Navy Game", "icon": "🔥"},
    frozenset(("alabama", "tennessee")): {"type": "rivalry", "name": "Third Saturday in October", "icon": "🔥"},
    frozenset(("alabama", "lsu")): {"type": "rivalry", "name": "Alabama–LSU", "icon": "🔥"},
    frozenset(("alabama", "georgia")): {"type": "rivalry", "name": "Alabama–Georgia", "icon": "🔥"},
    frozenset(("auburn", "georgia")): {"type": "rivalry", "name": "Deep South's Oldest Rivalry", "icon": "🔥"},
    frozenset(("florida", "georgia")): {"type": "rivalry", "name": "World's Largest Outdoor Cocktail Party", "icon": "🔥"},
    frozenset(("florida", "florida state")): {"type": "rivalry", "name": "Florida–Florida State", "icon": "🔥"},
    frozenset(("florida", "miami")): {"type": "rivalry", "name": "Florida–Miami", "icon": "🔥"},
    frozenset(("florida state", "miami")): {"type": "rivalry", "name": "Miami–Florida State", "icon": "🔥"},
    frozenset(("clemson", "south carolina")): {"type": "rivalry", "name": "Palmetto Bowl", "icon": "🔥"},
    frozenset(("clemson", "south carolina")): {"type": "rivalry", "name": "Palmetto Bowl", "icon": "🔥"},
    frozenset(("georgia", "georgia tech")): {"type": "rivalry", "name": "Clean, Old-Fashioned Hate", "icon": "🔥"},
    frozenset(("georgia", "florida")): {"type": "rivalry", "name": "World's Largest Outdoor Cocktail Party", "icon": "🔥"},
    frozenset(("kentucky", "tennessee")): {"type": "rivalry", "name": "Kentucky–Tennessee", "icon": "🔥"},
    frozenset(("iowa", "iowa state")): {"type": "rivalry", "name": "Cy-Hawk Series", "icon": "🔥"},
    frozenset(("iowa", "minnesota")): {"type": "rivalry", "name": "Floyd of Rosedale", "icon": "🔥"},
    frozenset(("iowa", "wisconsin")): {"type": "rivalry", "name": "Iowa–Wisconsin", "icon": "🔥"},
    frozenset(("michigan", "michigan state")): {"type": "rivalry", "name": "Paul Bunyan Trophy", "icon": "🔥"},
    frozenset(("michigan", "ohio state")): {"type": "rivalry", "name": "The Game", "icon": "🔥"},
    frozenset(("minnesota", "wisconsin")): {"type": "rivalry", "name": "Paul Bunyan's Axe", "icon": "🔥"},
    frozenset(("oregon", "oregon state")): {"type": "rivalry", "name": "Civil War", "icon": "🔥"},
    frozenset(("oregon", "washington")): {"type": "rivalry", "name": "Oregon–Washington", "icon": "🔥"},
    frozenset(("oregon state", "washington")): {"type": "rivalry", "name": "Northwest Rivalry", "icon": "🔥"},
    frozenset(("usc", "ucla")): {"type": "rivalry", "name": "Crosstown Rivalry", "icon": "🔥"},
    frozenset(("texas", "oklahoma")): {"type": "rivalry", "name": "Red River Rivalry", "icon": "🔥"},
    frozenset(("texas", "texas a and m")): {"type": "rivalry", "name": "Lone Star Showdown", "icon": "🔥"},
    frozenset(("texas", "texas tech")): {"type": "rivalry", "name": "Texas–Texas Tech", "icon": "🔥"},
    frozenset(("oklahoma", "oklahoma state")): {"type": "rivalry", "name": "Bedlam Series", "icon": "🔥"},
    frozenset(("kansas", "kansas state")): {"type": "rivalry", "name": "Sunflower Showdown", "icon": "🔥"},
    frozenset(("iowa state", "kansas state")): {"type": "rivalry", "name": "Farmageddon", "icon": "🔥"},
    frozenset(("penn state", "pittsburgh")): {"type": "rivalry", "name": "Penn State–Pitt", "icon": "🔥"},
    frozenset(("penn state", "ohio state")): {"type": "rivalry", "name": "Penn State–Ohio State", "icon": "🔥"},
    frozenset(("penn state", "michigan")): {"type": "rivalry", "name": "Penn State–Michigan", "icon": "🔥"},
    frozenset(("notre dame", "usc")): {"type": "rivalry", "name": "Notre Dame–USC", "icon": "🔥"},
    frozenset(("notre dame", "michigan")): {"type": "rivalry", "name": "Notre Dame–Michigan", "icon": "🔥"},
    frozenset(("notre dame", "stanford")): {"type": "rivalry", "name": "Legends Trophy", "icon": "🔥"},
    frozenset(("duke", "north carolina")): {"type": "rivalry", "name": "Duke–UNC", "icon": "🔥"},
    frozenset(("north carolina", "north carolina state")): {"type": "rivalry", "name": "Carolina–NC State", "icon": "🔥"},
    frozenset(("north carolina", "virginia")): {"type": "rivalry", "name": "South's Oldest Rivalry", "icon": "🔥"},
    frozenset(("north carolina state", "wake forest")): {"type": "rivalry", "name": "NC State–Wake Forest", "icon": "🔥"},
    frozenset(("virginia", "virginia tech")): {"type": "rivalry", "name": "Commonwealth Clash", "icon": "🔥"},
    frozenset(("pittsburgh", "west virginia")): {"type": "rivalry", "name": "Backyard Brawl", "icon": "🔥"},
    frozenset(("harvard", "yale")): {"type": "rivalry", "name": "The Game", "icon": "🔥"},
    frozenset(("princeton", "yale")): {"type": "rivalry", "name": "Princeton–Yale", "icon": "🔥"},
    frozenset(("harvard", "princeton")): {"type": "rivalry", "name": "Harvard–Princeton", "icon": "🔥"},
    # Basketball-centric high-profile rivalries.
    frozenset(("duke", "north carolina")): {"type": "rivalry", "name": "Duke–UNC", "icon": "🔥"},
    frozenset(("kentucky", "louisville")): {"type": "rivalry", "name": "Governor's Cup", "icon": "🔥"},
}

# Expanded high-profile rivalry coverage.
MATCHUP_INFO.update({
    frozenset(("indiana", "purdue")): {"type": "rivalry", "name": "Old Oaken Bucket", "icon": "🔥"},
    frozenset(("illinois", "northwestern")): {"type": "rivalry", "name": "Land of Lincoln", "icon": "🔥"},
    frozenset(("illinois", "missouri")): {"type": "rivalry", "name": "Braggin' Rights", "icon": "🔥"},
    frozenset(("arizona", "arizona state")): {"type": "rivalry", "name": "Territorial Cup", "icon": "🔥"},
    frozenset(("california", "stanford")): {"type": "rivalry", "name": "The Big Game", "icon": "🔥"},
    frozenset(("colorado", "colorado state")): {"type": "rivalry", "name": "Rocky Mountain Showdown", "icon": "🔥"},
    frozenset(("brigham young", "utah")): {"type": "rivalry", "name": "Holy War", "icon": "🔥"},
    frozenset(("baylor", "texas christian")): {"type": "rivalry", "name": "Revivalry", "icon": "🔥"},
    frozenset(("cincinnati", "xavier")): {"type": "rivalry", "name": "Crosstown Shootout", "icon": "🔥"},
    frozenset(("georgetown", "villanova")): {"type": "rivalry", "name": "Georgetown–Villanova", "icon": "🔥"},
    frozenset(("villanova", "saint marys")): {"type": "rivalry", "name": "Villanova–Saint Mary's", "icon": "🔥"},
    frozenset(("gonzaga", "saint marys")): {"type": "rivalry", "name": "Gonzaga–Saint Mary's", "icon": "🔥"},
    frozenset(("kentucky", "indiana")): {"type": "rivalry", "name": "Kentucky–Indiana", "icon": "🔥"},
    frozenset(("kansas", "missouri")): {"type": "rivalry", "name": "Border War", "icon": "🔥"},
    frozenset(("kansas", "kansas state")): {"type": "rivalry", "name": "Sunflower Showdown", "icon": "🔥"},
    frozenset(("florida", "georgia")): {"type": "rivalry", "name": "World's Largest Outdoor Cocktail Party", "icon": "🔥"},
    frozenset(("clemson", "south carolina")): {"type": "rivalry", "name": "Palmetto Bowl", "icon": "🔥"},
    frozenset(("virginia", "virginia tech")): {"type": "rivalry", "name": "Commonwealth Clash", "icon": "🔥"},
    frozenset(("north carolina", "duke")): {"type": "rivalry", "name": "Duke–UNC", "icon": "🔥"},
    frozenset(("north carolina", "north carolina state")): {"type": "rivalry", "name": "Carolina–NC State", "icon": "🔥"},
    frozenset(("pittsburgh", "west virginia")): {"type": "rivalry", "name": "Backyard Brawl", "icon": "🔥"},
})

BOWL_NAMES = [
    "rose bowl", "orange bowl", "sugar bowl", "cotton bowl", "peach bowl", "fiesta bowl",
    "citrus bowl", "liberty bowl", "gator bowl", "sun bowl", "holiday bowl", "music city bowl",
    "alamo bowl", "outback bowl", "las vegas bowl", "pinstripe bowl", "duke's mayo bowl",
    "pop-tarts bowl", "cheez-it bowl", "fenway bowl", "birmingham bowl", "armed forces bowl",
    "independence bowl", "frisco bowl", "boca raton bowl", "gasparilla bowl", "new orleans bowl",
    "cure bowl", "camellia bowl", "cactus bowl", "quick lane bowl", "first responder bowl",
    "48ventures bowl", "celebration bowl", "college football playoff", "national championship",
]


def _context_text(game):
    values = []
    for key in ("event_name", "event_context", "tournament_name", "round_name", "description", "detail"):
        value = game.get(key)
        if isinstance(value, (list, tuple)):
            values.extend(str(x) for x in value)
        elif value:
            values.append(str(value))
    return " | ".join(values).strip()


def _classify_postseason(game):
    text = _context_text(game).lower()
    sport = str(game.get("sport", ""))
    event_date = game.get("event_date")

    for bowl in BOWL_NAMES:
        if bowl in text:
            label = bowl.title().replace("Cfp", "CFP")
            return {"type": "postseason", "name": label, "icon": "🏆"}

    if any(x in text for x in ("ncaa tournament", "march madness", "sweet 16", "elite eight", "final four", "first four")):
        round_name = next((x.title() for x in ("first four", "round of 64", "round of 32", "sweet 16", "elite eight", "final four", "championship") if x in text), "NCAA Tournament")
        return {"type": "tournament", "name": f"NCAA Tournament • {round_name}", "icon": "🏆"}

    if "conference championship" in text or "championship game" in text:
        return {"type": "championship", "name": "Championship", "icon": "🏆"}

    if "conference tournament" in text or "quarterfinal" in text or "semifinal" in text or "title game" in text:
        return {"type": "tournament", "name": "Postseason Tournament", "icon": "🏆"}

    # Conservative date-based fallback. Only add a generic postseason marker
    # when the season window strongly suggests it; never invent a bowl name.
    if event_date and "Football" in sport and (event_date.month == 12 or event_date.month == 1):
        if game.get("state") in ("pre", "in", "post"):
            return {"type": "postseason", "name": "Bowl / CFP", "icon": "🏆"}
    if event_date and "Basketball" in sport and event_date.month in (3, 4):
        if any(x in text for x in ("tournament", "championship", "postseason", "quarterfinal", "semifinal")):
            return {"type": "tournament", "name": "Postseason Tournament", "icon": "🏆"}
    return None


def get_matchup_intelligence(game):
    away = team_key(game.get("away"))
    home = team_key(game.get("home"))
    rivalry = MATCHUP_INFO.get(frozenset((away, home)))
    postseason = _classify_postseason(game)

    # Prefer a specific postseason event label over a rivalry label when the
    # game is clearly a bowl/tournament/championship. Keep the rivalry as a
    # secondary tag so the UI can show both when appropriate.
    if postseason and rivalry:
        return {"primary": postseason, "secondary": rivalry}
    if postseason:
        return {"primary": postseason, "secondary": None}
    if rivalry:
        return {"primary": rivalry, "secondary": None}
    return {"primary": None, "secondary": None}


def format_matchup_badges(game):
    info = get_matchup_intelligence(game)
    primary = info.get("primary")
    secondary = info.get("secondary")
    badges = []
    for item in (primary, secondary):
        if item:
            badges.append(f"{item['icon']} {str(item['type']).upper()} • {item['name']}")
    return badges
