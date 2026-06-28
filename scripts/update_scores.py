#!/usr/bin/env python3
"""Fetch FIFA World Cup 2026 results (all stages) and update world-cup.html."""

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

# Map API stage → JS grp label (None = use group letter from extract_group())
STAGE_TO_GRP = {
    'GROUP_STAGE':          None,
    'LAST_32':              'R32',
    'LAST_16':              'R16',
    'QUARTER_FINALS':       'QF',
    'SEMI_FINALS':          'SF',
    'THIRD_PLACE_PLAY_OFF': '3rd',
    'FINAL':                'Final',
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


def parse_existing_scores(content: str) -> dict:
    """Return {(home, away): (hg, ag)} for done matches that already have numeric scores."""
    pattern = r"home:'([^']+)',away:'([^']+)',hg:(\d+),ag:(\d+),s:'done'"
    return {
        (m.group(1), m.group(2)): (int(m.group(3)), int(m.group(4)))
        for m in re.finditer(pattern, content)
    }


def build_matches_js(raw_matches: list, existing_scores: dict) -> str:
    lines = []
    unknown_teams = set()

    for m in raw_matches:
        stage = m.get('stage', '')
        if stage not in STAGE_TO_GRP:
            continue  # skip unknown stages

        raw_home = m['homeTeam']['name']
        raw_away = m['awayTeam']['name']
        home = normalize(raw_home)
        away = normalize(raw_away)

        if raw_home not in TEAM_MAP and raw_home != home:
            unknown_teams.add(raw_home)
        if raw_away not in TEAM_MAP and raw_away != away:
            unknown_teams.add(raw_away)

        date     = fmt_date(m['utcDate'])
        grp_key  = STAGE_TO_GRP[stage]
        grp      = grp_key if grp_key else extract_group(m.get('group', ''))
        s        = match_status(m['status'], m['utcDate'])
        utc_time = m['utcDate'][11:16]

        aet = False
        pen = None

        if m['status'] == 'FINISHED':
            score    = m.get('score', {})
            ft       = score.get('fullTime', {})
            et       = score.get('extraTime', {})
            pens     = score.get('penalties', {})
            winner   = m.get('winner')  # 'HOME_TEAM', 'AWAY_TEAM', 'DRAW'

            ft_h = ft.get('home')
            ft_a = ft.get('away')
            et_h = et.get('home') if et else None
            et_a = et.get('away') if et else None
            p_h  = pens.get('home') if pens else None
            p_a  = pens.get('away') if pens else None

            # Use ET score if played, else FT score
            if et_h is not None and et_a is not None:
                hg, ag = et_h, et_a
                aet = True
            else:
                hg, ag = ft_h, ft_a

            # Penalty shootout: mark winner, keep ET/FT score as-is
            if p_h is not None and p_a is not None:
                pen = 'home' if winner == 'HOME_TEAM' else ('away' if winner == 'AWAY_TEAM' else None)

            # Fallback to cached score if API returns null for a finished match
            if hg is None or ag is None:
                fallback = existing_scores.get((home, away))
                if fallback:
                    hg, ag = fallback
                    print(f'INFO: using cached score for {home} vs {away}: {hg}–{ag}')

            hgs = str(hg) if hg is not None else 'null'
            ags = str(ag) if ag is not None else 'null'
        else:
            hgs = ags = 'null'

        entry = (
            f"  {{date:'{date}',grp:'{grp}',home:'{home}',away:'{away}',"
            f"hg:{hgs},ag:{ags},s:'{s}',t:'{utc_time}'"
        )
        if aet:
            entry += ',aet:true'
        if pen:
            entry += f",pen:'{pen}'"
        entry += '},'
        lines.append(entry)

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

    html_path = os.path.join(os.path.dirname(__file__), '..', 'world-cup.html')

    with open(html_path, 'r', encoding='utf-8') as f:
        existing_content = f.read()
    existing_scores = parse_existing_scores(existing_content)

    print('Fetching matches from football-data.org …')
    data    = fetch_json(f'{BASE_URL}/competitions/{WC_CODE}/matches')
    matches = data.get('matches', [])
    print(f'Received {len(matches)} matches total.')

    new_js = build_matches_js(matches, existing_scores)
    update_html(html_path, new_js)
