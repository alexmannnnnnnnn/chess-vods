# Chessed on Stream

Find the chess games you played against streamers, then watch them from the streamer's side of the stream.

Like [pubg.report](https://pubg.report), but for chess: official game data from Chess.com and Lichess is matched against streamers' Twitch VODs, so every game links to the exact moment it started.

## How it works

- `fetch.py` runs every 2 hours on GitHub Actions (`.github/workflows/update.yml`). It:
  1. Gets the streamer lists from Chess.com and Lichess (each links a chess account to a Twitch channel).
  2. Gets each streamer's Twitch VODs from the last 30 days.
  3. Gets their games from the same period and keeps the ones played during a VOD.
  4. Saves everything to `docs/data.json` and commits it.
- GitHub Pages serves `docs/` as the website. Search runs in the browser, so there's no server to maintain.

Lichess only lists streamers while they're live, so the Lichess list grows over time as the job spots them (`data/lichess_streamers.json`).

## Setup

1. **Twitch key:** at dev.twitch.tv/console, register an application (redirect URL `http://localhost`, category Website Integration, client type Confidential). Copy the Client ID and create a Client Secret.
2. **Add the key to this repo:** Settings → Secrets and variables → Actions → New repository secret. Add `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
3. **Run the first update:** Actions tab → "Update games" → Run workflow. The first run takes 10–30 minutes.
4. **Website:** Settings → Pages shows the address (Source: Deploy from a branch, `main`, `/docs`).

## Adding streamers by hand

Some streamers aren't in either official list. Add them to `streamers_extra.json`:

```json
[
  {"platform": "chesscom", "username": "their_chesscom_name", "twitch": "their_twitch_login"},
  {"platform": "lichess",  "username": "their_lichess_name",  "twitch": "their_twitch_login"}
]
```

## Running it on your own computer

```
python fetch.py                       # asks for the Twitch keys
python -m http.server 8000 -d docs    # then open http://localhost:8000
```

The Twitch player only works when the page is served from a web address (it won't play from a file opened directly).

## Settings

- `VOD_DAYS` (environment variable, default 30): how far back to look. Twitch deletes VODs after 7–60 days depending on the channel.

## Limits

- Only Twitch for now. Streamers who stream on YouTube or Kick are skipped.
- A game is matched if it started during a VOD. If a streamer was playing on another account or had the game off-screen, the link will still point to that moment.
- Usernames must match exactly (not case-sensitive).
