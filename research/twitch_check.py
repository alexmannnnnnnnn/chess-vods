"""One-off research: do these Twitch channels stream TETR.IO with saved VODs?"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

LOGINS = ["turtle55478", "vincehd_", "kw1ksc0per", "whatsefficiency", "error404tetr",
          "127127127127127127127127", "anberdoodle", "fuzzytsun", "loal12310", "vichevjr_",
          "bennxt", "wumbotize", "enrenity", "cubci"]

def get(url, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

tok = get("https://id.twitch.tv/oauth2/token", data=urllib.parse.urlencode({
    "client_id": os.environ["TWITCH_CLIENT_ID"], "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
    "grant_type": "client_credentials"}).encode())["access_token"]
H = {"Client-Id": os.environ["TWITCH_CLIENT_ID"], "Authorization": "Bearer " + tok}

users = {u["login"]: u for u in get("https://api.twitch.tv/helix/users?" +
         "&".join("login=" + l for l in LOGINS), H)["data"]}
now = datetime.now(timezone.utc)
lines, streaming = [], 0
for login in LOGINS:
    u = users.get(login.lower())
    if not u:
        lines.append(f"{login}: no such Twitch account"); continue
    ch = get(f"https://api.twitch.tv/helix/channels?broadcaster_id={u['id']}", H)["data"][0]
    vods = get(f"https://api.twitch.tv/helix/videos?user_id={u['id']}&type=archive&first=50", H)["data"]
    recent = [v for v in vods if (now - datetime.fromisoformat(v["created_at"].replace("Z", "+00:00"))).days <= 30]
    tetris = [v for v in recent if re.search(r"tetr|tetris|tl\b|league", v["title"], re.I)]
    hours = sum(int(h or 0) + int(m or 0) / 60 for h, m in
                (re.match(r"(?:(\d+)h)?(?:(\d+)m)?", v["duration"]).groups() for v in recent))
    last = recent[0]["created_at"][:10] if recent else (vods[0]["created_at"][:10] if vods else "never")
    if recent:
        streaming += 1
    lines.append(f"{login}: last category '{ch['game_name']}' | VODs last 30d: {len(recent)} "
                 f"({hours:.0f}h), titles mentioning tetris: {len(tetris)} | last VOD {last}")
    time.sleep(0.3)

summary = f"{streaming} of {len(LOGINS)} channels have VODs from the last 30 days\n" + "\n".join(lines)
print(summary)
print("::notice title=TETR.IO Twitch check::" + summary.replace("%", "%25").replace("\n", "%0A"))
