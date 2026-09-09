# College Sports Live Scoreboard

A Streamlit college-sports scoreboard powered by the NCAA scoreboard API.

## Included

- Football: FBS + FCS
- Men's and women's soccer
- Men's and women's basketball
- Women's volleyball
- Baseball and softball
- Eastern Time / Central Time selector
- NCAA team logos
- My Teams dashboard
- Favorite-team highlighting
- Live status and game clock/period when supplied by NCAA
- TV/broadcast information when supplied by NCAA
- All games sorted by score closeness, with live games first
- Close-game threshold
- Automatic 30-second refresh
- Diagnostics panel for checking NCAA source data
- Volleyball set-by-set scores on demand for live/final matches when the NCAA game feed provides them

## Streamlit Community Cloud

1. Put this project in a GitHub repository.
2. Create a Streamlit app using `app.py` as the main file.
3. Deploy using the included `requirements.txt`.

The app uses the public `ncaa-api.henrygd.me` service. Its public API is rate-limited, so volleyball set details are fetched only when you press the set-score button rather than for every game automatically.
