#!/usr/bin/env python3
"""Generate Anki flashcard CSV files from merged_db.json.

Reads:  data/merged_db.json        (output of merge.py)
        data/definitions_db.json   (definition cache, created if absent)
Writes: output/spelling_bee_*.csv
        data/definitions_db.json   (updated with any newly fetched definitions)

Usage: python generate.py [--merged-db FILE] [--definitions-db FILE]
                          [--output DIR] [--model MODEL] [--api-key KEY]
"""

import argparse
import html
import json
import re
from collections import defaultdict
from pathlib import Path

import anthropic

from scoring import score_word

_ROOT = Path(__file__).resolve().parent.parent  # project root (src/../)

DEFINITION_PROMPT = (
    'Return a JSON object mapping each word to a brief definition '
    '(format: "part_of_speech: short definition", max 10 words). '
    'Use null for unknown words. No other text.\n\nWords: '
)
DEFINITION_BATCH = 100


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_json(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2))


# ── Definitions ───────────────────────────────────────────────────────────────

def fetch_definitions(words: list[str], defs_db: dict, defs_path: Path,
                      client: anthropic.Anthropic, model: str) -> None:
    missing = list(dict.fromkeys(w.lower() for w in words if w.lower() not in defs_db))
    if not missing:
        return

    total = (len(missing) + DEFINITION_BATCH - 1) // DEFINITION_BATCH
    print(f"Fetching definitions for {len(missing)} word(s) ({total} batch(es))...")

    for i in range(0, len(missing), DEFINITION_BATCH):
        batch     = missing[i:i + DEFINITION_BATCH]
        batch_num = i // DEFINITION_BATCH + 1
        try:
            msg = client.messages.create(
                model=model, max_tokens=2048,
                messages=[{"role": "user",
                           "content": DEFINITION_PROMPT + json.dumps(batch)}],
            )
            text = next(b for b in msg.content if b.type == 'text').text.strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            for word, defn in json.loads(text).items():
                defs_db[word.lower()] = defn
            print(f"  batch {batch_num}/{total} done")
        except Exception as e:
            print(f"  definition batch {batch_num}/{total} error: {e}")
        save_json(defs_db, defs_path)


# ── Card rendering ────────────────────────────────────────────────────────────

def _bubble(letter: str, center: bool = False) -> str:
    bg, fg = ('#7B2FBE', '#FFFFFF') if center else ('#FFD700', '#000000')
    return (
        f'<span style="background:{bg};color:{fg};border-radius:50%;padding:3px 8px;'
        f'margin:2px;font-weight:bold;display:inline-block">{letter.upper()}</span>'
    )


def distinct_key(word: str) -> str:
    return " ".join(sorted(set(word.upper())))


def group_words(words: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list] = defaultdict(list)
    for w in words:
        groups[distinct_key(w)].append(w)
    for k in groups:
        groups[k].sort(key=str.lower)
    return dict(groups)


# ── CSV generation ────────────────────────────────────────────────────────────

def generate_csv(puzzles: list[dict], output_path: Path,
                 letter_count: int | None, defs_db: dict) -> int:
    """Write one Anki TSV file. Returns the number of cards written."""
    deck = ("Spelling Bee::Complete" if letter_count is None
            else f"Spelling Bee::{letter_count} Letters")
    rows: list[tuple[str, str]] = []

    # Pangram cards — always in the complete set and the 7-letter set
    if letter_count is None or letter_count == 7:
        for p in puzzles:
            letters = sorted(set(l.upper() for l in p.get('puzzle_letters', [])))
            center = (p.get('center_letter') or '').upper()
            bubbles = "".join(_bubble(l, center=(l == center)) for l in letters)
            front = (
                f'<div style="text-align:center">'
                f'<div style="color:#7B2FBE;font-weight:bold;margin-bottom:6px">'
                f'★ PANGRAM CARD ★</div>{bubbles}</div>'
            )
            pangram_html = "<br>".join(
                f'<b style="font-size:1.5em;color:#7B2FBE">{pg.upper()}</b>'
                for pg in p.get('pangrams', [])
            )
            back = f'<div style="text-align:center">{pangram_html or "?"}</div>'
            rows.append((front, back))

    # Missed-word cards — globally deduplicated across all puzzles
    seen: dict[str, str] = {}
    for p in puzzles:
        for w in p.get('missed', []):
            if w.lower() not in seen:
                seen[w.lower()] = w

    all_pangrams = {pg.lower() for p in puzzles for pg in p.get('pangrams', [])}

    for key, words in sorted(group_words(list(seen.values())).items()):
        n = len(key.split())
        if letter_count is not None and n != letter_count:
            continue
        bubbles = "".join(_bubble(l) for l in key.split())
        front   = f'<div style="text-align:center">{bubbles}</div>'
        parts   = []
        for w in words:
            pts   = score_word(w, all_pangrams)
            defn  = defs_db.get(w.lower())
            entry = (f'<b>{w.capitalize()}</b>'
                     f' <span style="font-size:0.8em;color:#AAA;font-weight:normal">'
                     f'({pts} pt{"s" if pts != 1 else ""})</span>')
            if defn:
                entry += (f'<br><span style="font-size:0.85em;color:#666;'
                          f'font-style:italic">{html.escape(defn)}</span>')
            parts.append(f'<div style="margin:4px 0">{entry}</div>')
        back = f'<div style="text-align:center">{"".join(parts)}</div>'
        rows.append((front, back))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("#separator:tab\n#html:true\n")
        f.write(f"#deck:{deck}\n")
        for front, back in rows:
            f.write(f"{front}\t{back}\n")

    return len(rows)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Anki CSV files from merged puzzle database")
    parser.add_argument('--merged-db',      default=str(_ROOT / 'data' / 'merged_db.json'),
                        help='Output of merge.py')
    parser.add_argument('--definitions-db', default=str(_ROOT / 'data' / 'definitions_db.json'),
                        help='Definition cache (created if absent)')
    parser.add_argument('--output',         default=str(_ROOT / 'output'),
                        help='Output folder for CSV files')
    parser.add_argument('--model',          default='claude-haiku-4-5',
                        help='Model for fetching definitions')
    parser.add_argument('--api-key',        help='Anthropic API key')
    args = parser.parse_args()

    merged_db = load_json(Path(args.merged_db))
    if not merged_db:
        print("merged_db is empty — run merge.py first.")
        return

    defs_path = Path(args.definitions_db)
    defs_db   = load_json(defs_path)
    client    = anthropic.Anthropic(api_key=args.api_key) if args.api_key else anthropic.Anthropic()

    puzzles    = list(merged_db.values())
    all_missed = [w for p in puzzles for w in p.get('missed', [])]
    fetch_definitions(all_missed, defs_db, defs_path, client, args.model)

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    print(f"\nBuilding outputs from {len(puzzles)} puzzle(s)...")

    generate_csv(puzzles, output / 'spelling_bee_complete.csv', None, defs_db)
    print("  spelling_bee_complete.csv")

    for n in range(2, 8):
        path  = output / f'spelling_bee_{n}_letters.csv'
        count = generate_csv(puzzles, path, n, defs_db)
        if count:
            print(f"  spelling_bee_{n}_letters.csv  ({count} cards)")
        else:
            path.unlink(missing_ok=True)

    print("Done.")


if __name__ == '__main__':
    main()
