#!/usr/bin/env python3
"""
Chess VODs fetcher.

Finds chess games that streamers played on stream and works out where each game
starts inside the streamer's Twitch VOD. Writes data.json for the website.

Sources (all official, no scraping):
  - Chess.com Published-Data API  (no key)  streamer list + games
  - Lichess API                   (no key)  live streamer list + games
  - Twitch Helix API              (needs TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET)

Standard library only, so it runs anywhere Python 3.9+ exists (including GitHub Actions).
"""
import datetime as dt
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
LICHESS_SEEN = os.path.join(HERE, "data", "lichess_streamers.json")
EXTRA = os.path.join(HERE, "streamers_extra.json")
REMOVALS = os.path.join(HERE, "removals.json")   # people who asked to be taken off the site

VOD_DAYS = int(os.environ.get("VOD_DAYS", "30"))     # how far back to look
VODS_PER_STREAMER = 40                               # Twitch keeps ~7-60 days of VODs
LEAD_IN = 10                                         # start playback a bit before the game
MAX_GAME_SECONDS = 4 * 3600                          # ignore nonsense durations
UA = "chess-vods/1.0 (+{})".format(os.environ.get("CONTACT", "github.com"))

TWITCH_RE = re.compile(r"twitch\.tv/([A-Za-z0-9_]{3,25})", re.I)


# ------------------------------------------------------------------ http
def http(url, headers=None, data=None, retries=4, raw=False):
    h = {"User-Agent": UA}
    h.update(headers or {})
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=h, data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", errors="replace")
                return body if raw else (json.loads(body) if body.strip() else None)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = 60 if e.code == 429 else 5 * (attempt + 1)
                log(f"  {e.code} from {urllib.parse.urlparse(url).netloc}, waiting {wait}s")
                time.sleep(wait)
                continue
            log(f"  HTTP {e.code} for {url}")
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            log(f"  network error for {url}: {e}")
            return None


def log(msg):
    print(msg, flush=True)


def fail(msg):
    """Stop with an error that also shows up as a GitHub Actions annotation."""
    if os.environ.get("GITHUB_ACTIONS"):
        print("::error::" + msg.replace("\n", " "), flush=True)
    sys.exit(msg)


def find_twitch(obj):
    """Return the first twitch login found anywhere inside a JSON value."""
    if isinstance(obj, str):
        m = TWITCH_RE.search(obj)
        return m.group(1).lower() if m else None
    if isinstance(obj, dict):
        # prefer explicitly twitch-labelled fields
        for k, v in obj.items():
            if "twitch" in k.lower():
                t = find_twitch(v)
                if t:
                    return t
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            t = find_twitch(v)
            if t:
                return t
    return None


# ------------------------------------------------------------------ streamers
def chesscom_streamers():
    data = http("https://api.chess.com/pub/streamers") or {}
    out = []
    for s in data.get("streamers", []):
        user, tw = s.get("username"), find_twitch(s)
        if user and tw:
            out.append({"platform": "chesscom", "username": user.lower(), "twitch": tw})
    log(f"Chess.com streamers with Twitch: {len(out)}")
    return out


def lichess_streamers():
    """Lichess only lists streamers who are live right now, so we remember every one we see."""
    seen = load_json(LICHESS_SEEN, {})
    live = http("https://lichess.org/api/streamer/live") or []
    new = 0
    for s in live:
        user = (s.get("id") or s.get("name") or "").lower()
        tw = find_twitch(s.get("streamer", s))
        if user and tw:
            if user not in seen:
                new += 1
            seen[user] = tw
    save_json(LICHESS_SEEN, seen)
    log(f"Lichess streamers known: {len(seen)} ({new} new this run)")
    return [{"platform": "lichess", "username": u, "twitch": t} for u, t in seen.items()]


def extra_streamers():
    return [{"platform": e["platform"], "username": e["username"].lower(), "twitch": e["twitch"].lower()}
            for e in load_json(EXTRA, [])]


# ------------------------------------------------------------------ twitch
class Twitch:
    def __init__(self, client_id, secret):
        self.cid = client_id
        body = urllib.parse.urlencode({"client_id": client_id, "client_secret": secret,
                                       "grant_type": "client_credentials"}).encode()
        tok = http("https://id.twitch.tv/oauth2/token", data=body)
        if not tok or "access_token" not in tok:
            fail("Twitch rejected the Client ID / Secret. Double-check the TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET repository secrets.")
        self.h = {"Client-Id": client_id, "Authorization": "Bearer " + tok["access_token"]}

    def users(self, logins):
        out = {}
        for i in range(0, len(logins), 100):
            q = "&".join("login=" + urllib.parse.quote(l) for l in logins[i:i + 100])
            for u in (http("https://api.twitch.tv/helix/users?" + q, self.h) or {}).get("data", []):
                out[u["login"].lower()] = {"id": u["id"], "name": u["display_name"],
                                           "avatar": u.get("profile_image_url", "")}
        return out

    def vods(self, user_id):
        url = (f"https://api.twitch.tv/helix/videos?user_id={user_id}"
               f"&type=archive&first={VODS_PER_STREAMER}")
        out = []
        for v in (http(url, self.h) or {}).get("data", []):
            start = parse_iso(v["created_at"])
            out.append({"id": v["id"], "start": start, "end": start + parse_dur(v["duration"]),
                        "title": v.get("title", "")})
        return out


def parse_iso(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp())


def parse_dur(s):
    total = 0
    for n, unit in re.findall(r"(\d+)([hms])", s):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


# ------------------------------------------------------------------ games
PGN_TAG = re.compile(r'\[(\w+) "([^"]*)"\]')


def chesscom_start(game):
    """Game start time (epoch). PGN headers carry it; fall back to the end time."""
    end = game.get("end_time")
    tags = dict(PGN_TAG.findall(game.get("pgn", "")[:2000]))
    for d, t in (("UTCDate", "UTCTime"), ("Date", "StartTime")):
        if tags.get(d) and tags.get(t):
            try:
                st = int(dt.datetime.strptime(tags[d] + " " + tags[t], "%Y.%m.%d %H:%M:%S")
                         .replace(tzinfo=dt.timezone.utc).timestamp())
                if end and 0 <= end - st <= MAX_GAME_SECONDS:
                    return st
            except ValueError:
                pass
    return end


def chesscom_games(username, since):
    out, months = [], set()
    d = dt.datetime.fromtimestamp(since, dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    while (d.year, d.month) <= (now.year, now.month):
        months.add((d.year, d.month))
        d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    for y, m in sorted(months):
        data = http(f"https://api.chess.com/pub/player/{username}/games/{y}/{m:02d}") or {}
        for g in data.get("games", []):
            start = chesscom_start(g)
            if not start or start < since:
                continue
            w, b = g.get("white", {}), g.get("black", {})
            me_white = w.get("username", "").lower() == username
            me, opp = (w, b) if me_white else (b, w)
            res = me.get("result", "")
            out.append({
                "platform": "chesscom", "url": g.get("url", ""), "start": start,
                "end": g.get("end_time") or start, "speed": g.get("time_class", ""),
                "color": "white" if me_white else "black",
                "opponent": opp.get("username", ""), "opp_rating": opp.get("rating"),
                "rating": me.get("rating"),
                "result": "win" if res == "win" else "draw" if res in
                ("agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient") else "loss",
            })
        time.sleep(0.3)   # Chess.com asks for serial, unhurried requests
    return out


def lichess_games(username, since):
    url = (f"https://lichess.org/api/games/user/{username}?since={since * 1000}"
           f"&max=300&moves=false&opening=false")
    body = http(url, {"Accept": "application/x-ndjson"}, raw=True) or ""
    out = []
    for line in body.splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        p = g.get("players", {})
        wname = (p.get("white", {}).get("user", {}) or {}).get("name", "")
        me_white = wname.lower() == username
        me, opp = (p.get("white", {}), p.get("black", {})) if me_white else (p.get("black", {}), p.get("white", {}))
        winner = g.get("winner")
        out.append({
            "platform": "lichess", "url": "https://lichess.org/" + g["id"],
            "start": g["createdAt"] // 1000, "end": g.get("lastMoveAt", g["createdAt"]) // 1000,
            "speed": g.get("speed", ""), "color": "white" if me_white else "black",
            "opponent": (opp.get("user", {}) or {}).get("name", "Anonymous" if not opp.get("aiLevel") else "Stockfish"),
            "opp_rating": opp.get("rating"), "rating": me.get("rating"),
            "result": "draw" if not winner else ("win" if (winner == "white") == me_white else "loss"),
        })
    time.sleep(1)  # Lichess: one request at a time
    return out


# ------------------------------------------------------------------ matching
def match(games, vods):
    """Attach each game to the VOD it was played in, with offsets in seconds."""
    out = []
    for g in games:
        for v in vods:
            if v["start"] <= g["start"] <= v["end"]:
                g = dict(g)
                g["vod"] = v["id"]
                g["t"] = max(0, g["start"] - v["start"] - LEAD_IN)
                g["t_end"] = max(0, min(g["end"], v["end"]) - v["start"])
                out.append(g)
                break
    return out


# ------------------------------------------------------------------ main
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)


def credentials():
    cid = os.environ.get("TWITCH_CLIENT_ID", "").strip()
    sec = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
    if not (cid and sec) and sys.stdin.isatty():
        print("Twitch keys not set. Paste them (from dev.twitch.tv/console):")
        cid = cid or input("  Client ID: ").strip()
        sec = sec or getpass.getpass("  Client Secret (hidden): ").strip()
    if not (cid and sec):
        fail("Missing TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET. Add them as repository secrets (Settings > Secrets and variables > Actions).")
    return cid, sec


def main():
    tw = Twitch(*credentials())
    since = int(time.time()) - VOD_DAYS * 86400

    accounts = chesscom_streamers() + lichess_streamers() + extra_streamers()
    removed = load_json(REMOVALS, {})
    gone_players = {n.lower() for n in removed.get("players", [])}
    gone_streamers = {n.lower() for n in removed.get("streamers", [])}
    accounts = [a for a in accounts if a["twitch"] not in gone_streamers and a["username"] not in gone_streamers]
    uniq = {(a["platform"], a["username"]): a for a in accounts}
    accounts = list(uniq.values())

    logins = sorted({a["twitch"] for a in accounts})
    users = tw.users(logins)
    log(f"Twitch channels found: {len(users)} of {len(logins)}")

    vods = {}
    for login, u in users.items():
        vs = [v for v in tw.vods(u["id"]) if v["end"] >= since]
        if vs:
            vods[login] = vs
    log(f"Channels with VODs in the last {VOD_DAYS} days: {len(vods)}")

    games, streamers, seen_games = [], {}, set()
    todo = [a for a in accounts if a["twitch"] in vods]
    for i, a in enumerate(todo, 1):
        log(f"[{i}/{len(todo)}] {a['platform']}:{a['username']} -> twitch:{a['twitch']}")
        fetcher = chesscom_games if a["platform"] == "chesscom" else lichess_games
        found = match(fetcher(a["username"], since), vods[a["twitch"]])
        uniq_found = []
        for g in found:
            key = (g["url"], a["twitch"])
            if key not in seen_games:
                seen_games.add(key)
                uniq_found.append(g)
        found = uniq_found
        for g in found:
            g["streamer"] = a["twitch"]
            g["account"] = a["username"]
        games += found
        if found:
            s = streamers.setdefault(a["twitch"], {"twitch": a["twitch"], "name": users[a["twitch"]]["name"],
                                                   "avatar": users[a["twitch"]]["avatar"], "accounts": []})
            s["accounts"].append({"platform": a["platform"], "username": a["username"]})

    before = len(games)
    games = [g for g in games if (g.get("opponent") or "").lower() not in gone_players]
    if before != len(games):
        log(f"Hid {before - len(games)} games of players who asked to be removed")
    # a streamer left with no games after removals drops out too
    still = {g["streamer"] for g in games}
    streamers = {k: v for k, v in streamers.items() if k in still}
    games.sort(key=lambda g: g["start"], reverse=True)
    save_json(OUT, {
        "generated": int(time.time()),
        "days": VOD_DAYS,
        "streamers": sorted(streamers.values(), key=lambda s: s["name"].lower()),
        "games": games,
    }, compact=True)
    log(f"\nSaved {len(games)} on-stream games from {len(streamers)} streamers -> {OUT}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # make crashes readable in the Actions summary
        import traceback
        traceback.print_exc()
        fail(f"{type(e).__name__}: {e}")
