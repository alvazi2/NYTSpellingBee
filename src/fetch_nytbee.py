#!/usr/bin/env python3
"""Fetch NYT Spelling Bee puzzle data from nytbee.com into a local database.

Usage:
    python fetch_nytbee.py [--from YYYY-MM-DD] [--db PATH]

Fetches all puzzles up to (but not including) the current and prior week.
Re-running is safe — already-fetched dates are skipped.
"""

import argparse
import json
import re
import socket
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'nytbee_db.json'
BASE_URL = 'https://www.nytbee.com/Bee_{}.html'
SITE_START_DATE = date(2019, 5, 17)
FETCH_DELAY = 1.0  # seconds between requests, to be polite
RETRY_ATTEMPTS = 3  # total attempts on transient failures (5xx, timeout, network error)
RETRY_BACKOFF = 3.0  # base backoff seconds between retries (linear: 3s, 6s, …)


# ── Database ──────────────────────────────────────────────────────────────────

def load_db(db_path):
    if db_path.exists():
        with open(db_path) as f:
            return json.load(f)
    return {}


def save_db(db, db_path):
    with open(db_path, 'w') as f:
        json.dump(db, f, indent=2, sort_keys=True)


# ── Cutoff date ───────────────────────────────────────────────────────────────

def last_safe_date():
    """Last date we're allowed to fetch: the Sunday ending the week before last.

    Excludes the current calendar week and the prior calendar week (Mon–Sun).
    Example: today = Monday May 04 → last safe = Sunday April 26.
    """
    today = date.today()
    start_of_current_week = today - timedelta(days=today.weekday())
    return start_of_current_week - timedelta(days=8)


# ── HTML parsing ──────────────────────────────────────────────────────────────

# nytbee.com switched formats on 2024-07-28:
#   Old format: words in first <ul class="column-list">, plain <li> text
#   New format: words in <li> items identified by <a href="javascript:void(0)">
# Both formats wrap pangrams in <strong>.

class NewFormatParser(HTMLParser):
    """New format (2024-07-28+): <li>word <a href="javascript:void(0)">↗</a></li>."""

    def __init__(self):
        super().__init__()
        self.words = []
        self.pangrams = []
        self._in_li = False
        self._has_js_link = False
        self._is_pangram = False
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'li':
            self._in_li = True
            self._has_js_link = False
            self._is_pangram = False
            self._text_parts = []
        elif tag == 'strong' and self._in_li:
            self._is_pangram = True
        elif tag == 'a' and self._in_li:
            if dict(attrs).get('href', '').startswith('javascript:'):
                self._has_js_link = True

    def handle_endtag(self, tag):
        if tag == 'li' and self._in_li:
            if self._has_js_link:
                word = ''.join(self._text_parts).strip().lower()
                word = ''.join(c for c in word if c.isalpha())
                if len(word) >= 4:
                    self.words.append(word)
                    if self._is_pangram:
                        self.pangrams.append(word)
            self._in_li = False

    def handle_data(self, data):
        if self._in_li:
            self._text_parts.append(data)


def parse_old_format(html):
    """Old format (before 2024-07-28): words in first <ul class="column-list">."""
    match = re.search(r'<ul class="column-list">(.*?)</ul>', html, re.DOTALL)
    if not match:
        return [], []
    words, pangrams = [], []
    for item in re.findall(r'<li>(.*?)</li>', match.group(1), re.DOTALL):
        is_pangram = '<strong>' in item
        word = re.sub(r'<[^>]+>', '', item).strip().lower()
        if word.isalpha() and len(word) >= 4:
            words.append(word)
            if is_pangram:
                pangrams.append(word)
    return words, pangrams


def parse_html(html):
    parser = NewFormatParser()
    parser.feed(html)
    if parser.words:
        return parser.words, parser.pangrams
    return parse_old_format(html)


# ── Fetching ──────────────────────────────────────────────────────────────────

def _fetch_html(url):
    """Fetch URL with retries on transient failures. Returns (html, None), (None, '404'), or raises."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    last_err = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode('utf-8'), None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, '404'
            if e.code < 500 or attempt == RETRY_ATTEMPTS:
                raise
            last_err = e
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            if attempt == RETRY_ATTEMPTS:
                raise
            last_err = e
        wait = RETRY_BACKOFF * attempt
        print(f'    transient error ({last_err}); retrying in {wait:.0f}s...')
        time.sleep(wait)


def fetch_puzzle(d):
    url = BASE_URL.format(d.strftime('%Y%m%d'))
    html, status = _fetch_html(url)
    if status == '404':
        return None

    raw_words, raw_pangrams = parse_html(html)
    words = sorted(set(raw_words))

    if len(words) < 4:
        return None

    all_letters = set(''.join(words))
    puzzle_letters = sorted(all_letters)
    center_letter = next(
        (l for l in puzzle_letters if all(l in w for w in words)),
        None,
    )
    # Prefer <strong>-marked pangrams from the page; fall back to derivation
    pangrams = sorted(set(raw_pangrams)) or sorted(w for w in words if set(w) == all_letters)

    return {
        'words': words,
        'pangrams': pangrams,
        'puzzle_letters': puzzle_letters,
        'center_letter': center_letter,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def date_range(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser(description='Fetch NYT Spelling Bee puzzles from nytbee.com')
    ap.add_argument('--from', dest='start', metavar='YYYY-MM-DD',
                    help=f'Earliest date to fetch (default: {SITE_START_DATE})')
    ap.add_argument('--db', metavar='PATH',
                    help='Database path (default: data/nytbee_db.json)')
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH
    db = load_db(db_path)

    end = last_safe_date()
    start = date.fromisoformat(args.start) if args.start else SITE_START_DATE

    to_fetch = [d for d in date_range(start, end) if d.isoformat() not in db]

    if not to_fetch:
        print(f'Database is up to date (through {end}).')
        return

    print(f'Fetching {len(to_fetch)} puzzle(s) up to {end}...')
    fetched = skipped = 0

    for i, d in enumerate(to_fetch):
        puzzle = fetch_puzzle(d)
        if puzzle:
            db[d.isoformat()] = puzzle
            fetched += 1
            pangram_str = ', '.join(puzzle['pangrams']) or '(none found)'
            print(f'  {d}: {len(puzzle["words"])} words  pangram: {pangram_str}')
        else:
            skipped += 1
            print(f'  {d}: no data (skipped)')

        save_db(db, db_path)
        if i < len(to_fetch) - 1:
            time.sleep(FETCH_DELAY)

    print(f'\nDone. Fetched {fetched}, skipped {skipped}.')


if __name__ == '__main__':
    main()
