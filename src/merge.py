#!/usr/bin/env python3
"""Match screenshots to nytbee_db puzzle entries and build merged_db.json.

Reads:  data/screenshots_db.json  (output of extract.py)
        data/nytbee_db.json       (reference puzzle database)
Writes: data/merged_db.json       (keyed by YYYY-MM-DD, rebuilt from scratch each run)

Re-running is always safe — previously skipped screenshots are retried, so run
again after updating nytbee_db to pick up puzzles that were too recent last time.

Matching logic (applied in order):
  1. Word-overlap voting: each word in (found ∪ missed) votes for every nytbee_db
     date that contains it. The date with the most votes wins.
  2. Date upper bound: puzzle_date must not exceed the screenshot's file_date
     (a puzzle cannot be published after you took the screenshot).
  3. Letter-set filter: if the honeycomb was visible, the puzzle's 7 letters must
     match the extracted puzzle_letters.
  A match requires at least MIN_OVERLAP words in common.

Usage: python merge.py [--screenshots-db FILE] [--nytbee-db FILE] [--output FILE]
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from scoring import score_word

_ROOT = Path(__file__).resolve().parent.parent  # project root (src/../)

MIN_OVERLAP = 3    # minimum word overlap to accept a match
MIN_RATIO   = 0.7  # at least 70% of screenshot words must appear in the matched puzzle


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def save_json(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2))


# ── Matching ──────────────────────────────────────────────────────────────────

def build_word_index(nytbee_db: dict) -> dict[str, set[str]]:
    """word (lowercase) → set of puzzle dates that contain it"""
    index: dict[str, set[str]] = defaultdict(set)
    for date, entry in nytbee_db.items():
        for word in entry['words']:
            index[word.lower()].add(date)
    return index


def match_screenshot(screenshot: dict, nytbee_db: dict,
                     word_index: dict[str, set[str]],
                     min_overlap: int = MIN_OVERLAP,
                     min_ratio: float = MIN_RATIO) -> tuple[str | None, int]:
    """Return (matched_date, overlap_count), or (None, best_count) if no match."""
    file_date = screenshot.get('file_date')  # upper bound: puzzle_date <= file_date
    all_words = {w.lower() for w in screenshot.get('found', []) + screenshot.get('missed', [])}

    if not all_words:
        return None, 0

    # Vote: each screenshot word contributes 1 vote to every candidate date
    votes: dict[str, int] = defaultdict(int)
    for word in all_words:
        for date in word_index.get(word, ()):
            votes[date] += 1

    if not votes:
        return None, 0

    # Constraint: puzzle must have been published before the screenshot was taken
    if file_date:
        votes = {d: v for d, v in votes.items() if d <= file_date}

    # Constraint: if honeycomb was visible, puzzle letters must match exactly
    raw_letters = screenshot.get('puzzle_letters') or []
    if len(raw_letters) == 7:
        target = sorted(l.lower() for l in raw_letters)
        votes = {d: v for d, v in votes.items()
                 if sorted(nytbee_db[d]['puzzle_letters']) == target}

    if not votes:
        return None, 0

    # Among equally-scored candidates, prefer the most recent date (closest to
    # the screenshot) — same letter sets reuse the same word list across dates.
    best_date  = max(votes, key=lambda d: (votes[d], d))
    best_count = votes[best_date]

    if best_count < min_overlap or best_count / len(all_words) < min_ratio:
        return None, best_count

    return best_date, best_count


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match screenshots to puzzle database and build merged_db")
    parser.add_argument('--screenshots-db', default=str(_ROOT / 'data' / 'screenshots_db.json'),
                        help='Output of extract.py')
    parser.add_argument('--nytbee-db',      default=str(_ROOT / 'data' / 'nytbee_db.json'),
                        help='Reference puzzle database')
    parser.add_argument('--output',         default=str(_ROOT / 'data' / 'merged_db.json'),
                        help='Output merged database')
    parser.add_argument('--min-overlap',    type=int, default=MIN_OVERLAP,
                        help=f'Minimum word overlap to accept a match (default: {MIN_OVERLAP})')
    parser.add_argument('--min-ratio',      type=float, default=MIN_RATIO,
                        help=f'Minimum fraction of screenshot words present in the matched puzzle '
                             f'(default: {MIN_RATIO})')
    args = parser.parse_args()

    screenshots_db = load_json(Path(args.screenshots_db))
    nytbee_db      = load_json(Path(args.nytbee_db))
    word_index     = build_word_index(nytbee_db)

    date_to_files: dict[str, list[str]] = defaultdict(list)
    date_to_found: dict[str, set[str]]  = defaultdict(set)
    skipped = 0

    for filename, shot in screenshots_db.get('screenshots', {}).items():
        if shot.get('status') != 'ok':
            continue

        date, count = match_screenshot(shot, nytbee_db, word_index,
                                        args.min_overlap, args.min_ratio)

        if date is None:
            print(f"  SKIP {filename}: no puzzle match (best overlap: {count} word(s))")
            skipped += 1
            continue

        date_to_files[date].append(filename)
        for w in shot.get('found', []):
            date_to_found[date].add(w.lower())
        print(f"  {filename} → {date} ({count} words matched)")

    # Build merged_db — missed words computed authoritatively from nytbee_db
    merged_db: dict[str, dict] = {}
    for date in sorted(date_to_files):
        nyt    = nytbee_db[date]
        found  = sorted(date_to_found[date])
        missed = [w for w in nyt['words'] if w.lower() not in date_to_found[date]]
        pg_set = {p.lower() for p in nyt['pangrams']}
        merged_db[date] = {
            'puzzle_letters':  nyt['puzzle_letters'],
            'center_letter':   nyt['center_letter'],
            'pangrams':        nyt['pangrams'],
            'found':           found,
            'missed':          missed,
            'screenshots':     sorted(date_to_files[date]),
            'points_earned':   sum(score_word(w, pg_set) for w in found),
            'points_possible': sum(score_word(w, pg_set) for w in nyt['words']),
        }

    save_json(merged_db, Path(args.output))
    print(f"\n{len(merged_db)} puzzle(s) written → {args.output}  "
          f"({skipped} screenshot(s) skipped)")


if __name__ == '__main__':
    main()
