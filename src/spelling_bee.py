#!/usr/bin/env python3
"""NYT Spelling Bee Flashcard Generator

Usage:
    python spelling_bee.py [--folder DIR] [--output DIR] [--date YYYY-MM-DD] [--model MODEL]
    python spelling_bee.py --submit [--date YYYY-MM-DD]
    python spelling_bee.py --retrieve
"""

import argparse
import base64
import json
from datetime import date as date_type, datetime
import re
import uuid
from collections import defaultdict
from pathlib import Path

import anthropic

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png'}

API_PROMPT = """\
This is a screenshot from the NYT Spelling Bee results screen.
Please extract:
1. The 7 puzzle letters (if the honeycomb/letter grid is visible)
2. The pangram (if visible — it appears in bold at the top of the word list)
3. All words WITH a yellow checkmark (found by the user)
4. All words WITHOUT a checkmark (missed by the user)

Return JSON only, no other text:
{
  "puzzle_letters": ["A","B","C","D","E","F","G"],
  "pangram": "word or null",
  "found": ["word1", "word2"],
  "missed": ["word1", "word2"]
}
"""

# ── Database ──────────────────────────────────────────────────────────────────

def load_db(db_path: Path) -> dict:
    if db_path.exists():
        with open(db_path) as f:
            db = json.load(f)
        db.setdefault('puzzle_order', list(db.get('puzzles', {}).keys()))
        db.setdefault('pending_batches', [])
        return db
    return {"processed_files": {}, "puzzles": {}, "puzzle_order": [], "pending_batches": []}


def save_db(db: dict, db_path: Path) -> None:
    with open(db_path, 'w') as f:
        json.dump(db, f, indent=2)


# ── Vision API ────────────────────────────────────────────────────────────────

def extract_from_screenshot(image_path: Path, client: anthropic.Anthropic, model: str) -> dict:
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    media_type = 'image/jpeg' if image_path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": API_PROMPT},
            ],
        }]
    )

    text = message.content[0].text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text.strip())


# ── Puzzle key helpers ────────────────────────────────────────────────────────

def key_from_pangram(pangram: str) -> str:
    return "".join(sorted(set(pangram.upper())))


def key_from_letters(letters: list) -> str:
    return "".join(sorted(set(l.upper() for l in letters)))


def derive_letters(extraction: dict) -> list:
    if extraction.get('puzzle_letters') and len(extraction['puzzle_letters']) == 7:
        return sorted(set(l.upper() for l in extraction['puzzle_letters']))
    if extraction.get('pangram'):
        return sorted(set(extraction['pangram'].upper()))
    return []


# ── Puzzle matching ───────────────────────────────────────────────────────────

def find_matching_puzzle(extraction: dict, db: dict) -> str | None:
    # Primary: match by pangram key (O(1))
    if extraction.get('pangram'):
        key = key_from_pangram(extraction['pangram'])
        if key in db['puzzles']:
            return key

    # Secondary: match by puzzle letters (O(1))
    letters = extraction.get('puzzle_letters') or []
    if len(letters) == 7:
        key = key_from_letters(letters)
        if key in db['puzzles']:
            return key

    # Fallback: any word overlap with the last 2 puzzles
    new_words = {w.lower() for w in extraction.get('found', []) + extraction.get('missed', [])}
    if not new_words:
        return None

    for key in reversed(db['puzzle_order'][-2:]):
        puzzle = db['puzzles'].get(key)
        if not puzzle:
            continue
        existing = {w.lower() for w in puzzle.get('found', []) + puzzle.get('missed', [])}
        if new_words & existing:
            return key

    return None


# ── Pangram inference ────────────────────────────────────────────────────────

def infer_pangram(puzzle: dict) -> None:
    """Derive pangram and letters from the word list when the API didn't return them."""
    if puzzle.get('pangrams') and puzzle.get('letters'):
        return
    all_words = puzzle.get('found', []) + puzzle.get('missed', [])
    for word in all_words:
        letter_set = set(word.upper())
        if len(letter_set) == 7 and all(set(w.upper()) <= letter_set for w in all_words):
            if not puzzle.get('pangrams'):
                puzzle['pangrams'] = [word]
            if not puzzle.get('letters'):
                puzzle['letters'] = sorted(letter_set)
            return


# ── Puzzle creation / merging ─────────────────────────────────────────────────

def create_puzzle(extraction: dict, filename: str) -> tuple[str, dict]:
    letters = derive_letters(extraction)
    pangrams = [extraction['pangram']] if extraction.get('pangram') else []

    if extraction.get('pangram'):
        key = key_from_pangram(extraction['pangram'])
    elif letters:
        key = key_from_letters(letters)
    else:
        key = str(uuid.uuid4())[:8]

    puzzle = {
        'letters': letters,
        'pangrams': pangrams,
        'found': list(extraction.get('found', [])),
        'missed': list(extraction.get('missed', [])),
        'screenshots': [filename],
    }
    infer_pangram(puzzle)
    return key, puzzle


def merge_into_puzzle(puzzle: dict, extraction: dict, filename: str) -> None:
    if filename not in puzzle['screenshots']:
        puzzle['screenshots'].append(filename)

    if extraction.get('pangram') and extraction['pangram'] not in puzzle['pangrams']:
        puzzle['pangrams'].append(extraction['pangram'])

    if not puzzle['letters']:
        puzzle['letters'] = derive_letters(extraction)

    existing_found  = {w.lower() for w in puzzle['found']}
    existing_missed = {w.lower() for w in puzzle['missed']}

    for w in extraction.get('found', []):
        if w.lower() not in existing_found:
            puzzle['found'].append(w)
            existing_found.add(w.lower())

    for w in extraction.get('missed', []):
        if w.lower() not in existing_missed:
            puzzle['missed'].append(w)
            existing_missed.add(w.lower())

    infer_pangram(puzzle)


# ── Word grouping ─────────────────────────────────────────────────────────────

def distinct_key(word: str) -> str:
    return " ".join(sorted(set(word.upper())))


def group_words(words: list) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for w in words:
        groups[distinct_key(w)].append(w)
    for k in groups:
        groups[k].sort(key=str.lower)
    return dict(groups)


# ── Definitions ──────────────────────────────────────────────────────────────

DEFINITION_PROMPT = (
    'Return a JSON object mapping each word to a brief definition '
    '(format: "part_of_speech: short definition", max 10 words). '
    'Use null for unknown words. No other text.\n\nWords: '
)

DEFINITION_BATCH = 100


def fetch_definitions(words: list, db: dict, db_path: Path,
                      client: anthropic.Anthropic, model: str) -> None:
    """Fetch definitions via the Anthropic API in batches and cache in db['definitions'].
    Words already cached (including None for not-found) are skipped.
    Progress is saved after each batch so restarts resume from where they left off."""
    db.setdefault('definitions', {})
    seen: set = set()
    missing = []
    for w in words:
        key = w.lower()
        if key not in db['definitions'] and key not in seen:
            missing.append(key)
            seen.add(key)

    if not missing:
        return

    total_batches = (len(missing) + DEFINITION_BATCH - 1) // DEFINITION_BATCH
    print(f"Fetching definitions for {len(missing)} word(s) ({total_batches} batch(es))...")
    for i in range(0, len(missing), DEFINITION_BATCH):
        batch = missing[i:i + DEFINITION_BATCH]
        batch_num = i // DEFINITION_BATCH + 1
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": DEFINITION_PROMPT + json.dumps(batch)}],
            )
            text = next(b for b in msg.content if b.type == 'text').text.strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            result = json.loads(text)
            for word, defn in result.items():
                db['definitions'][word.lower()] = defn
            print(f"  batch {batch_num}/{total_batches} done")
        except Exception as e:
            print(f"  Definition fetch error (batch {batch_num}/{total_batches}): {e}")
            # Don't cache on error — words will be retried on next run
        save_db(db, db_path)


# ── Anki CSV ──────────────────────────────────────────────────────────────────

def _html_bubble(letter: str) -> str:
    return (
        f'<span style="background:#FFD700;border-radius:50%;padding:3px 8px;'
        f'margin:2px;font-weight:bold;display:inline-block">{letter}</span>'
    )


def generate_csv(puzzles: list, output_path: Path, letter_count: int | None = None,
                 definitions: dict | None = None) -> int:
    """Generate an Anki TSV file. If letter_count is set, include only cards with that many
    distinct letters (pangram cards count as 7). Returns the number of rows written."""
    if letter_count is None:
        deck_name = "Spelling Bee::Complete"
    else:
        deck_name = f"Spelling Bee::{letter_count} Letters"

    rows = []

    # Pangram cards — only included when generating all cards or the 7-letter set
    if letter_count is None or letter_count == 7:
        for p in puzzles:
            letters = p.get('letters') or sorted(set("".join(p.get('pangrams', [""])).upper()))
            bubbles = "".join(_html_bubble(l) for l in letters)
            front = (
                f'<div style="text-align:center">'
                f'<div style="color:#7B2FBE;font-weight:bold;margin-bottom:6px">★ PANGRAM CARD ★</div>'
                f'{bubbles}</div>'
            )
            pangram_html = "<br>".join(
                f'<b style="font-size:1.5em;color:#7B2FBE">{pg.upper()}</b>'
                for pg in p.get('pangrams', [])
            )
            back = f'<div style="text-align:center">{pangram_html or "?"}</div>'
            rows.append((front, back))

    # Missed-word cards (globally deduplicated)
    seen: dict[str, str] = {}
    for p in puzzles:
        for w in p.get('missed', []):
            if w.lower() not in seen:
                seen[w.lower()] = w
    for key, words in sorted(group_words(list(seen.values())).items()):
        if letter_count is None or len(key.split()) == letter_count:
            bubbles = "".join(_html_bubble(l) for l in key.split())
            front = f'<div style="text-align:center">{bubbles}</div>'
            parts = []
            for w in words:
                defn = (definitions or {}).get(w.lower())
                entry = f'<b>{w.capitalize()}</b>'
                if defn:
                    entry += (f'<br><span style="font-size:0.85em;color:#666;'
                              f'font-style:italic">{defn}</span>')
                parts.append(f'<div style="margin:4px 0">{entry}</div>')
            back = f'<div style="text-align:center">{"".join(parts)}</div>'
            rows.append((front, back))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("#separator:tab\n")
        f.write("#html:true\n")
        f.write(f"#deck:{deck_name}\n")
        for front, back in rows:
            f.write(f"{front}\t{back}\n")
    return len(rows)


# ── Batch API ────────────────────────────────────────────────────────────────

def _pending_filenames(db: dict) -> set:
    return {f for batch in db.get('pending_batches', []) for f in batch['files']}


def submit_batch(files: list, client, model: str, db: dict, db_path: Path) -> None:
    requests = []
    for i, img_path in enumerate(files):
        with open(img_path, 'rb') as f:
            image_data = base64.standard_b64encode(f.read()).decode('utf-8')
        media_type = 'image/jpeg' if img_path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'
        requests.append({
            "custom_id": f"req_{i:04d}",  # index-based — avoids filename character restrictions
            "params": {
                "model": model,
                "max_tokens": 1024,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                        {"type": "text", "text": API_PROMPT},
                    ],
                }],
            },
        })

    batch = client.messages.batches.create(requests=requests)
    batch_date = date_type.fromtimestamp(files[0].stat().st_birthtime).isoformat()

    db['pending_batches'].append({
        "batch_id": batch.id,
        "date": batch_date,
        "submitted_at": datetime.now().isoformat(),
        "files": [f.name for f in files],
    })
    save_db(db, db_path)
    print(f"Batch {batch.id} submitted — {len(files)} screenshots from {batch_date}")
    print("Run ./weekly_batch_retrieve.sh to collect results (usually within a few hours).")


def retrieve_batches(client, db: dict, db_path: Path, folder: Path) -> bool:
    pending = db.get('pending_batches', [])
    if not pending:
        print("No pending batches.")
        return False

    # Process completed batches in chronological date order so merge logic sees correct neighbours
    pending_by_date = sorted(pending, key=lambda b: b.get('date', ''))
    remaining = []
    processed_any = False

    for batch_info in pending_by_date:
        batch_id  = batch_info['batch_id']
        date_str  = batch_info.get('date', '?')
        print(f"Batch {batch_id} ({date_str}) ... ", end='', flush=True)

        batch = client.messages.batches.retrieve(batch_id)

        if batch.processing_status != 'ended':
            counts = batch.request_counts
            print(f"still processing ({counts.processing} in progress, {counts.succeeded} done so far)")
            remaining.append(batch_info)
            continue

        print("complete")

        # Map index → full filename (custom_id is positional to avoid filename character restrictions)
        index_to_name = {f"req_{i:04d}": f for i, f in enumerate(batch_info['files'])}

        # Collect results keyed by full filename
        extractions = {}
        for result in client.messages.batches.results(batch_id):
            filename = index_to_name.get(result.custom_id, result.custom_id)
            if result.result.type == 'succeeded':
                text = result.result.message.content[0].text.strip()
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)
                try:
                    extractions[filename] = json.loads(text.strip())
                except json.JSONDecodeError as e:
                    print(f"  JSON error for {filename}: {e}")
                    db['processed_files'][filename] = None
            else:
                print(f"  Error for {filename}: {result.result.error}")
                db['processed_files'][filename] = None

        # Process in chronological order so multi-screenshot merges work correctly
        def _birthtime(name: str) -> float:
            p = folder / name
            return p.stat().st_birthtime if p.exists() else 0.0

        for filename in sorted(batch_info['files'], key=_birthtime):
            if filename in db['processed_files']:
                continue  # error already recorded above
            if filename not in extractions:
                db['processed_files'][filename] = None
                continue

            extraction = extractions[filename]
            match_key  = find_matching_puzzle(extraction, db)

            if match_key:
                merge_into_puzzle(db['puzzles'][match_key], extraction, filename)
                db['processed_files'][filename] = match_key
                print(f"  {filename}: merged → {match_key}")
            else:
                key, puzzle = create_puzzle(extraction, filename)
                db['puzzles'][key] = puzzle
                db['puzzle_order'].append(key)
                db['processed_files'][filename] = key
                print(f"  {filename}: new puzzle {key} (#{len(db['puzzles'])} total)")

        processed_any = True
        save_db(db, db_path)

    db['pending_batches'] = remaining
    save_db(db, db_path)
    return processed_any


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="NYT Spelling Bee Flashcard Generator")
    parser.add_argument('--folder',       default='../data/screenshots',      help='Folder containing screenshots')
    parser.add_argument('--output',       default='../output',                help='Output folder for CSV files')
    parser.add_argument('--db',           default='../data/spelling_bee_db.json', help='Path to JSON database')
    parser.add_argument('--api-key',                                       help='Anthropic API key (overrides ANTHROPIC_API_KEY env var)')
    parser.add_argument('--date',                                          help='Process only screenshots created on this date (YYYY-MM-DD)')
    parser.add_argument('--limit',        type=int,                        help='Stop after N new puzzles (useful for testing)')
    parser.add_argument('--model',        default='claude-haiku-4-5',      help='Anthropic vision model')
    parser.add_argument('--ingest-only',  action='store_true',             help='Process screenshots and update the database, skip output generation')
    parser.add_argument('--output-only',  action='store_true',             help='Regenerate CSV from existing database, skip ingestion')
    parser.add_argument('--submit',       action='store_true',             help='Submit a batch job for the given --date (or auto-detect newest unprocessed date)')
    parser.add_argument('--retrieve',     action='store_true',             help='Retrieve completed batch results, then generate outputs')
    args = parser.parse_args()

    modes = [args.ingest_only, args.output_only, args.submit, args.retrieve]
    if sum(modes) > 1:
        parser.error("--ingest-only, --output-only, --submit, and --retrieve are mutually exclusive")

    folder  = Path(args.folder)
    output  = Path(args.output)
    db_path = Path(args.db)

    db = load_db(db_path)

    client = anthropic.Anthropic(api_key=args.api_key) if args.api_key else anthropic.Anthropic()

    # ── Batch submit ──────────────────────────────────────────────────────────
    if args.submit:
        already_handled = set(db['processed_files']) | _pending_filenames(db)
        all_files = sorted(
            (f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS),
            key=lambda f: f.stat().st_birthtime,
        )
        new_files = [f for f in all_files if f.name not in already_handled]

        if not new_files:
            print("No new screenshots to submit.")
            return

        if args.date:
            try:
                filter_date = date_type.fromisoformat(args.date)
            except ValueError:
                parser.error(f"--date must be in YYYY-MM-DD format, got: {args.date}")
            dates_to_submit = [filter_date]
        else:
            # Submit one batch per unprocessed date — handles skipped weeks automatically
            seen = dict.fromkeys(date_type.fromtimestamp(f.stat().st_birthtime) for f in new_files)
            dates_to_submit = list(seen)

        for d in dates_to_submit:
            batch_files = [f for f in new_files if date_type.fromtimestamp(f.stat().st_birthtime) == d]
            submit_batch(batch_files, client, args.model, db, db_path)

        if len(dates_to_submit) > 1:
            print(f"\n{len(dates_to_submit)} batches submitted. Run ./weekly_batch_retrieve.sh to collect results.")
        return

    # ── Batch retrieve ────────────────────────────────────────────────────────
    if args.retrieve:
        processed_any = retrieve_batches(client, db, db_path, folder)
        if not processed_any:
            return
        # Fall through to pangram sweep and output generation

    # ── Synchronous ingestion ─────────────────────────────────────────────────
    if not args.output_only and not args.retrieve:
        all_files = sorted(
            (f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS),
            key=lambda f: f.stat().st_birthtime,
        )

        if args.date:
            try:
                filter_date = date_type.fromisoformat(args.date)
            except ValueError:
                parser.error(f"--date must be in YYYY-MM-DD format, got: {args.date}")
            all_files = [f for f in all_files if date_type.fromtimestamp(f.stat().st_birthtime) == filter_date]
            print(f"Filtering to {args.date}: {len(all_files)} screenshot(s) on that date")

        new_files = [f for f in all_files if f.name not in db['processed_files']]
        print(f"{len(all_files)} screenshots total, {len(new_files)} unprocessed")

        puzzles_before = len(db['puzzles'])

        for img_path in new_files:
            if args.limit is not None and (len(db['puzzles']) - puzzles_before) >= args.limit:
                print(f"Reached limit of {args.limit} new puzzle(s) — stopping ingestion.")
                break

            print(f"  {img_path.name} ... ", end='', flush=True)
            try:
                extraction = extract_from_screenshot(img_path, client, args.model)
            except anthropic.RateLimitError:
                print("rate limit reached — stopping. Re-run to continue from here.")
                save_db(db, db_path)
                return
            except Exception as e:
                print(f"ERROR: {e}")
                db['processed_files'][img_path.name] = None
                save_db(db, db_path)
                continue

            match_key = find_matching_puzzle(extraction, db)

            if match_key:
                merge_into_puzzle(db['puzzles'][match_key], extraction, img_path.name)
                db['processed_files'][img_path.name] = match_key
                print(f"merged → {match_key}")
            else:
                key, puzzle = create_puzzle(extraction, img_path.name)
                db['puzzles'][key] = puzzle
                db['puzzle_order'].append(key)
                db['processed_files'][img_path.name] = key
                print(f"new puzzle {key} (#{len(db['puzzles'])} total)")

            save_db(db, db_path)

    # ── Pangram inference sweep ───────────────────────────────────────────────
    for puzzle in db['puzzles'].values():
        infer_pangram(puzzle)
    save_db(db, db_path)

    # ── Output phase ──────────────────────────────────────────────────────────
    if not args.ingest_only:
        ordered = [db['puzzles'][k] for k in db['puzzle_order'] if k in db['puzzles']]

        all_missed = [w for p in ordered for w in p.get('missed', [])]
        fetch_definitions(all_missed, db, db_path, client, args.model)
        save_db(db, db_path)
        definitions = db.get('definitions', {})

        print(f"\nBuilding outputs from {len(ordered)} puzzle(s)...")

        generate_csv(ordered, output / 'spelling_bee_complete.csv', definitions=definitions)
        print("  spelling_bee_complete.csv")

        for n in range(2, 8):
            n_csv = output / f'spelling_bee_{n}_letters.csv'
            card_count = generate_csv(ordered, n_csv, letter_count=n, definitions=definitions)
            if card_count:
                print(f"  spelling_bee_{n}_letters.csv  ({card_count} cards)")
            else:
                n_csv.unlink(missing_ok=True)

        print("Done.")


if __name__ == '__main__':
    main()
