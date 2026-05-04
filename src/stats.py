#!/usr/bin/env python3
"""Extract statistics from the Spelling Bee database."""

import json
import os
from collections import Counter, defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "spelling_bee_db.json")


def unique_letter_count(word: str) -> int:
    return len(set(word.upper()))


def load_db(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def print_separator(width: int = 60) -> None:
    print("-" * width)


def main() -> None:
    db = load_db(DB_PATH)
    puzzles = db.get("puzzles", {})
    puzzle_order = db.get("puzzle_order", [])

    # ── Per-unique-letter-count table ───────────────────────────────────────
    # Collect all words across all puzzles, deduplicated per puzzle
    # (same word can appear in different puzzles — count each occurrence)
    by_count: dict[int, dict] = defaultdict(lambda: {"total": 0, "missed": 0, "pangrams": 0})

    all_missed: list[str] = []
    missed_word_counter: Counter = Counter()

    impossible_words: list[tuple[str, str]] = []

    for key in puzzle_order:
        puzzle = puzzles.get(key, {})
        found = puzzle.get("found", [])
        missed = puzzle.get("missed", [])
        pangrams = {w.upper() for w in puzzle.get("pangrams", [])}

        for word in found + missed:
            n = unique_letter_count(word)
            if n > 7:
                impossible_words.append((word, key))
                continue
            by_count[n]["total"] += 1
            if word.upper() in pangrams:
                by_count[n]["pangrams"] += 1

        for word in missed:
            if unique_letter_count(word) > 7:
                continue
            n = unique_letter_count(word)
            by_count[n]["missed"] += 1
            all_missed.append(word.upper())
            missed_word_counter[word.upper()] += 1

    # ── Overall summary ─────────────────────────────────────────────────────
    total_puzzles = len(puzzle_order)
    total_words = sum(v["total"] for v in by_count.values())
    total_missed = sum(v["missed"] for v in by_count.values())
    total_found = total_words - total_missed
    miss_rate_overall = total_missed / total_words * 100 if total_words else 0.0

    print()
    print("═" * 62)
    print(" SPELLING BEE — DATABASE STATISTICS")
    print("═" * 62)
    print(f"  Puzzles processed : {total_puzzles}")
    print(f"  Total words       : {total_words}  (found: {total_found}, missed: {total_missed})")
    print(f"  Overall miss rate : {miss_rate_overall:.1f}%")
    if impossible_words:
        print(f"  ⚠ Impossible words: {len(impossible_words)} (>7 unique letters, excluded — likely OCR errors)")
        for w, k in impossible_words:
            letters = puzzles[k].get("letters", [])
            print(f"      {w!r} in puzzle {k[:8]} (puzzle letters: {''.join(letters)})")
    print()

    # ── Letter-count breakdown table ────────────────────────────────────────
    header = f"{'Unique':>6}  {'Total':>6}  {'Missed':>6}  {'Miss%':>6}  {'Pangrams':>8}"
    print(" " + header)
    print(" " + "-" * len(header))

    for n in sorted(by_count.keys()):
        v = by_count[n]
        miss_pct = v["missed"] / v["total"] * 100 if v["total"] else 0.0
        pangram_col = str(v["pangrams"]) if v["pangrams"] else "-"
        print(
            f"  {n:>4}    {v['total']:>6}    {v['missed']:>6}    {miss_pct:>5.1f}%   {pangram_col:>7}"
        )

    print()

    # ── Per-puzzle difficulty ────────────────────────────────────────────────
    puzzle_stats: list[tuple[float, int, int, str, list[str]]] = []
    for key in puzzle_order:
        puzzle = puzzles.get(key, {})
        found = puzzle.get("found", [])
        missed = puzzle.get("missed", [])
        n_total = len(found) + len(missed)
        n_missed = len(missed)
        rate = n_missed / n_total * 100 if n_total else 0.0
        screenshots = puzzle.get("screenshots", [])
        label = screenshots[0] if screenshots else key
        puzzle_stats.append((rate, n_missed, n_total, label, missed))

    puzzle_stats.sort(reverse=True)

    print(" Top 10 hardest puzzles (by miss rate):")
    print_separator(62)
    print(f"  {'Miss%':>6}  {'Missed':>6}  {'Total':>6}  Screenshot / key")
    print_separator(62)
    for rate, n_missed, n_total, label, missed_words in puzzle_stats[:10]:
        short = label if len(label) <= 36 else "…" + label[-35:]
        words_preview = ", ".join(w.capitalize() for w in missed_words[:4])
        if len(missed_words) > 4:
            words_preview += f" (+{len(missed_words) - 4})"
        print(f"  {rate:>5.1f}%   {n_missed:>5}   {n_total:>5}   {short}")
        if missed_words:
            print(f"          missed: {words_preview}")
    print()

    # ── Most-missed words ───────────────────────────────────────────────────
    print(" Top 20 most-missed words:")
    print_separator(40)
    for word, count in missed_word_counter.most_common(20):
        bar = "█" * count
        print(f"  {word.lower():<18} {count:>3}×  {bar}")
    print()

    # ── Letter-count difficulty ranking ─────────────────────────────────────
    print(" Miss rate by unique-letter count (hardest first):")
    print_separator(40)
    ranked = sorted(
        by_count.items(),
        key=lambda kv: kv[1]["missed"] / kv[1]["total"] if kv[1]["total"] else 0,
        reverse=True,
    )
    for n, v in ranked:
        miss_pct = v["missed"] / v["total"] * 100 if v["total"] else 0.0
        bar_len = int(miss_pct / 2)
        print(f"  {n} letters   {miss_pct:>5.1f}%  {'█' * bar_len}")
    print()


if __name__ == "__main__":
    main()
