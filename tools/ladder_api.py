import json
import os.path
import sys
from collections import defaultdict

import requests

API_TOKEN = "93ba08144f047986de6ef16c0e24f75fdf218a39"


class Result:
    def __init__(self):
        self.elo_change = 0
        self.matches = 0
        self.wins = 0

    def add_elo(self, elo):
        self.elo_change += elo
        self.matches += 1
        self.wins += 1 if elo >= 0 else 0

    def __repr__(self):
        delta = f"{'+' if self.elo_change > 0 else ''}{self.elo_change}"
        rate = self.wins / self.matches if self.matches > 0 else 1
        return f"{delta:>4} (won {100 * rate:3.0f}% of {self.matches} game{'s' if self.matches > 1 else ''})"


class LadderAPI:
    bot_ids = {"Zoe": 330, "EvilZoe": 334, "Eris": 248, "AdditionalPylons": 33, "Buckshot": 378, "Xena": 446}

    # Your AuthorId goes here
    SoupCatcher = 698
    TeamXena = 1029

    author = defaultdict(lambda: 0, {"Zoe": SoupCatcher, "EvilZoe": SoupCatcher, "Xena": TeamXena})

    def __init__(self, bot="Zoe", tags=None, token=API_TOKEN):
        self.token = token
        self.bot = bot
        self.bot_id = self.bot_ids[bot]
        self.tags = [] if tags is None else tags
        self.data_file = f"db/{'.'.join([bot] + self.tags)}.json"
        self.me = self.author[bot]
        self.load_db()

    def load_db(self):
        if not os.path.exists(self.data_file):
            with open(self.data_file, "w") as f:
                json.dump({"latest": 0}, f, indent=2)
        with open(self.data_file, "r") as f:
            self.data = json.load(f)

    def save_db(self):
        with open(self.data_file, "w") as f:
            json.dump(self.data, f, indent=2)

    def sync_db(self):
        matches = self.new_matches()
        if matches:
            print(f"Found {len(matches)} new match{'es' if len(matches) > 1 else ''}")
            self.add_participation(matches)
            if "matches" not in self.data:
                self.data["matches"] = []
            self.data["matches"] = matches + self.data["matches"]
            self.data["latest"] = self.data["matches"][0]["id"]
            self.save_db()

    def add_participation(self, matches):
        n = 0
        total = len(matches)
        print("")
        for m in matches:
            p = self.match_participation(m["id"])
            m["participation"] = p
            n += 1
            print(f"\u001b[1FLoading... {100 * n / total:.0f}%")

    @property
    def latest(self):
        return self.data["latest"]

    def get(self, endpoint, args):
        url = f"https://aiarena.net/api/{endpoint}?{'&'.join([f'{k}={v}' for k, v in args.items()])}"
        r = requests.get(url, headers={"Authorization": f"Token {self.token}"})
        data = r.json()
        assert r.ok, f"{endpoint}/{args} failed: {data}"
        return data

    def get_matches(self, n=100, offset=0):
        r = self.get("matches", {"bot": self.bot_id, "ordering": "-started", "limit": n, "offset": offset})
        return r["results"]

    def new_matches(self, batch_size=20):
        matches = []
        found = False
        for offs in range(0, 500, batch_size):
            ms = self.get_matches(n=batch_size, offset=offs)
            for m in ms:
                if m["id"] == self.latest:
                    found = True
                    break
                if m["requested_by"] is None and m["result"] is not None and self.matches_tags(m):
                    matches.append(m)
            if found:
                break
        return matches

    def match_participation(self, match_id):
        return self.get("match-participations", {"bot": self.bot_id, "match": match_id})["results"][0]

    def elo_change(self, match):
        r = match["participation"]
        nr = r["participant_number"]
        opponent = match["result"][f"bot{3 - nr}_name"]
        return (opponent, r["elo_change"])

    def is_opponent_id(self, t):
        return len(t) == 32 and all("0" <= c <= "9" or "a" <= c <= "f" for c in t)

    def matches_tags(self, match):
        tags = [t["tag_name"] for t in match["tags"] if t["user"] == self.me]
        return all(t in tags for t in self.tags)

    def is_crash(self, match):
        r = match["result"]
        return (
            r["type"] == "Player1Crash"
            and r["bot1_name"] == self.bot
            or r["type"] == "Player2Crash"
            and r["bot2_name"] == self.bot
        )

    def print_elo_changes(self, limit):
        changes = defaultdict(lambda: Result())
        total = Result()
        matches = self.data["matches"][:limit]
        for match in matches:
            if match["result"] and not self.is_crash(match):
                opponent, elo = self.elo_change(match)
                if isinstance(elo, int):
                    changes[opponent].add_elo(elo)
                    total.add_elo(elo)
        cs = [(o, r) for o, r in changes.items()]
        cs.sort(key=lambda p: p[1].elo_change)
        for o, r in cs:
            print(f"{o:23}: {r}")
        print(f"{'Total':23}: {total}")


def main():
    bot = "Zoe"
    tags = []
    limit = 1000
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "-n":
            limit = int(sys.argv[i + 1])
            i += 1
        else:
            bot_args = sys.argv[i].split(".")
            bot = bot_args[0]
            tags = bot_args[1:]
        i += 1
    api = LadderAPI(bot, tags)
    api.sync_db()
    api.print_elo_changes(limit)


if __name__ == "__main__":
    main()
