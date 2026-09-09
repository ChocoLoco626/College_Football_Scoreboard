# 🏈 College Football Live Scoreboard

A Python/Streamlit college-football scoreboard using ESPN scoreboard data.

## Features

- FBS and FCS scores
- Combined FBS + FCS scoreboard
- Live game status and clock
- Close-game filter (default: under 10 points)
- Closest games sorted first (all games, not just close games)
- My Teams dashboard with a section for each favorite team
- Favorite games highlighted in the all-games list
- All games are always displayed and sorted by closeness
- Team logos when supplied by ESPN
- Broadcast/TV information when supplied by ESPN
- Automatic refresh
- Manual refresh button
- FBS/FCS division filter
- No SMS functionality

Default favorite teams:
- Kentucky
- Auburn
- West Florida

## Install

Python 3.10+ is recommended.

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Then:

```bash
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

## ESPN data

The application requests the ESPN college-football scoreboard endpoint for both:
- FBS: `groups=80`
- FCS: `groups=81`

It combines the two results into one scoreboard.

## Favorites

Use the sidebar's **Favorite Teams** selector. Favorite games are given priority in the Favorites view.

The initial list includes Kentucky, Auburn, and West Florida, and more teams can be selected from the list. The My Teams dashboard displays each selected team separately.

## Notes

ESPN does not appear to provide this scoreboard endpoint as a conventional documented public developer API. ESPN can change the endpoint or its response structure. The program includes request timeouts and handles an unavailable division without crashing the entire scoreboard.


## 📱 iPhone / Cloud Hosting

The app is a responsive Streamlit web app, so it can be opened directly in Safari on an iPhone.

### Recommended free cloud option: Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload the project files to the repository.
3. Open Streamlit Community Cloud.
4. Choose the GitHub repository and `app.py`.
5. Deploy.
6. Open the resulting `*.streamlit.app` address on your iPhone.
7. In Safari, use **Share → Add to Home Screen**.

This is the simplest option for this project.

### Alternative: Render

The project includes a `Dockerfile` and `render.yaml` for Render.

Create a new Render Web Service from the GitHub repository and choose the free plan. The service can be opened from Safari on your iPhone.

The free Render service can spin down after 15 minutes without inbound traffic, so the first visit after inactivity may take a little longer.

### Alternative: Ubuntu laptop

The project includes:
- `run_ubuntu.sh`
- `college-football-scoreboard.service`
- `docker-compose.yml`

On Ubuntu:

```bash
cd ~/college_football_scoreboard
chmod +x run_ubuntu.sh
./run_ubuntu.sh
```

Then browse to:

```text
http://YOUR-LAPTOP-IP:8501
```

from an iPhone connected to the same Wi-Fi network.

For access from outside your home network, do not simply expose port 8501 to the internet. Use a VPN such as Tailscale or a properly configured reverse proxy/tunnel.

### Important live-refresh change

The app uses Streamlit's periodic fragment refresh instead of an infinite `sleep()`/`rerun()` loop. This is much friendlier to cloud hosting because only the live dashboard fragment refreshes on the configured interval.
