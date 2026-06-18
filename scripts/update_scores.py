#!/usr/bin/env python3
"""Fetch FIFA World Cup 2026 group-stage results and update world-cup.html."""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

API_KEY  = os.environ.get('FOOTBALL_DATA_API_KEY', '')
BASE_URL = 'https://api.football-data.org/v4'
WC_CODE  = 'WC'

# Map API team names → names used in world-cup.html
TEAM_MAP = {
    "Congo DR":                "DR Congo",
    "DR Congo":                "DR Congo",
    "Côte d'Ivoire":           "Ivory Coast",
    "Ivory Coast":             "Ivory Coast",
    "Turkey":                  "Türkiye",
    "Türkiye":                 "Türkiye",
    "Bosnia and Herzegovina":  "Bosnia",
    "Bosnia-Herzegovina":      "Bosnia",
    "Korea Republic":          "South Korea",
    "Republic of Korea":       "South Korea",
    "United States":           "USA",
    "USA":                     "USA",
    "Curacao":                 "Curaçao",
    "Curaçao":                 "Curaçao",
    "Czech Republic":          "Czechia",
    "Czechia":                 "Czechia",
    "IR Iran":                 "Iran",
    "Saudi Arabia":            "Saudi Arabia",
    "New Zealand":             "New Zealand",
    "Cape Verde":              "Cape Verde",
    "Cape Verde Islands":      "Cape Verde",
}


def normalize(name: str) -> str:
    return TEAM_MAP.get(name, name)


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={'X-Auth-Token': API_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fmt_date(iso: str) -> str:
    """'2026-06-17T...' → 'Jun 17'"""
    dt = datetime.strptime(iso[:10], '%Y-%m-%d')
    # %-d strips leading zero on Linux (GitHub Actions = Ubuntu)
    return dt.strftime('%b %-d')


def match_status(api_status: str, utc_date: str) -> str:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if api_status == 'FINISHED':
        return 'done'
    if utc_date[:10] == today:
        return 'today'
    return 'upcoming'


def extract_group(group_str: str) -> str:
    """'GROUP_A' or 'Group A' → 'A'"""
    if not group_str:
        return '?'
    m = re.search(r'([A-L])$', group_str.strip().upper())
    return m.group(1) if m else '?'


def build_matches_js(raw_matches: list) -> str:
    lines = []
    unknown_teams = set()

    for m in raw_matches:
        if m.get('stage') != 'GROUP_STAGE':
            continue

        raw_home = m['homeTeam']['name']
        raw_away = m['awayTeam']['name']
        home = normalize(raw_home)
        away = normalize(raw_away)

        if raw_home not in TEAM_MAP and raw_home != home:
            unknown_teams.add(raw_home)
        if raw_away not in TEAM_MAP and raw_away != away:
            unknown_teams.add(raw_away)

        date = fmt_date(m['utcDate'])
        grp  = extract_group(m.get('group', ''))
        s    = match_status(m['status'], m['utcDate'])

        if m['status'] == 'FINISHED':
            hg = m['score']['fullTime']['home']
            ag = m['score']['fullTime']['away']
            hgs = str(hg) if hg is not None else 'null'
            ags = str(ag) if ag is not None else 'null'
        else:
            hgs, ags = 'null', 'null'

        lines.append(
            f"  {{date:'{date}',grp:'{grp}',home:'{home}',away:'{away}',"
            f"hg:{hgs},ag:{ags},s:'{s}'}},"
        )

    if unknown_teams:
        print(f'WARNING: unmapped teams (check TEAM_MAP): {unknown_teams}', file=sys.stderr)

    return '\n'.join(lines)


def update_html(html_path: str, new_js: str) -> bool:
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern     = r'(// ── AUTO-START ──\n).*?(  // ── AUTO-END ──)'
    replacement = r'\g<1>' + new_js + '\n' + r'  // ── AUTO-END ──'
    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

    if count == 0:
        print('ERROR: AUTO-START / AUTO-END markers not found in HTML.', file=sys.stderr)
        sys.exit(1)

    if new_content == content:
        print('No score changes detected — skipping write.')
        return False

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    n = new_js.count('\n') + 1
    print(f'Wrote {n} match entries to {html_path}')
    return True


if __name__ == '__main__':
    if not API_KEY:
        print('ERROR: FOOTBALL_DATA_API_KEY environment variable not set.', file=sys.stderr)
        sys.exit(1)

    print('Fetching matches from football-data.org …')
    data    = fetch_json(f'{BASE_URL}/competitions/{WC_CODE}/matches')
    matches = data.get('matches', [])
    print(f'Received {len(matches)} matches total.')

    new_js   = build_matches_js(matches)
    html_path = os.path.join(os.path.dirname(__file__), '..', 'world-cup.html')

    update_html(html_path, new_js)
