# Chessed on Stream

Find the chess games you played against streamers, then watch them from the streamer's side of the stream.

Like [pubg.report](https://pubg.report), but for chess: official game data from Chess.com and Lichess is matched against streamers' Twitch VODs, so every game links to the exact moment it started.

## How it works

- `fetch.py` runs every 2 hours on GitHub Actions (`.github/workflows/update.yml`). It:
  1. Gets the streamer lists from Chess.com and Lichess (each links a chess account to a Twitch channel).
  2. Gets each streamer's Twitch VODs from the last 30 days.
  3. Gets their games from the same period and keeps the ones played during a VOD.
  4. Saves everything to `data.json`, then `build_pages.py` makes a page per streamer (e.g. `/witty_alien/`) plus `sitemap.xml`, and the job commits it all.
- GitHub Pages serves the repo's top folder as the website. Search runs in the browser, so there's no server to maintain.

Lichess only lists streamers while they're live, so the Lichess list grows over time as the job spots them (`data/lichess_streamers.json`).

## Setup

1. **Twitch key:** at dev.twitch.tv/console, register an application (redirect URL `http://localhost`, category Website Integration, client type Confidential). Copy the Client ID and create a Client Secret.
2. **Add the key to this repo:** Settings → Secrets and variables → Actions → New repository secret. Add `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
3. **Run the first update:** Actions tab → "Update games" → Run workflow. The first run takes 10–30 minutes.
4. **Website:** Settings → Pages shows the address (Source: Deploy from a branch, `main`, `/ (root)`).

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
python build_pages.py
python -m http.server 8000            # then open http://localhost:8000
```

The Twitch player only works when the page is served from a web address (it won't play from a file opened directly).

## Removal requests

The footer's **Remove me** link opens a GitHub issue form. To approve a request, add the label
**approved** to the issue. The "Process removal request" job then adds the name to `removals.json`,
reruns the update, replies, and closes the issue. To remove someone by hand, edit `removals.json`:

```json
{ "players": ["their_username"], "streamers": ["their_twitch_or_chess_name"] }
```

Players lose the games they played against streamers; streamers lose their page and all their games.

## Settings

- `VOD_DAYS` (environment variable, default 30): how far back to look. Twitch deletes VODs after 7–60 days depending on the channel.

## Custom domain

After connecting a domain in Settings → Pages, add a repository **variable** (not secret) named `SITE_URL`, e.g. `https://chessedonstream.com`, and add `SITE_URL: ${{ vars.SITE_URL }}` to the build step's env, so link previews and the sitemap use it.

## Limits

- Only Twitch for now. Streamers who stream on YouTube or Kick are skipped.
- A game is matched if it started during a VOD. If a streamer was playing on another account or had the game off-screen, the link will still point to that moment.
- Usernames must match exactly (not case-sensitive).
