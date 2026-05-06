#!/usr/bin/env python3
"""Extract words from NYT Spelling Bee screenshots using the Anthropic vision API.

Writes data/screenshots_db.json — one entry per file, keyed by filename.
Already-processed files are skipped; re-run safely at any time.

Usage (sync):  python extract.py
Usage (batch): python extract.py --submit
               python extract.py --retrieve
"""

import argparse
import base64
import json
import re
from datetime import datetime
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
        db = json.loads(db_path.read_text())
        db.setdefault('screenshots', {})
        db.setdefault('pending_batches', [])
        return db
    return {'screenshots': {}, 'pending_batches': []}


def save_db(db: dict, db_path: Path) -> None:
    db_path.write_text(json.dumps(db, indent=2))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_response(text: str) -> dict:
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text.strip())


def _file_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_birthtime).date().isoformat()


def _pending_filenames(db: dict) -> set:
    return {f for batch in db.get('pending_batches', []) for f in batch['files']}


def _unprocessed_files(folder: Path, db: dict, date: str | None = None) -> list[Path]:
    handled = set(db['screenshots']) | _pending_filenames(db)
    files = (
        f for f in folder.iterdir()
        if f.suffix.lower() in SUPPORTED_EXTENSIONS and f.name not in handled
    )
    if date:
        files = (f for f in files if _file_date(f) == date)
    return sorted(files, key=lambda f: f.stat().st_birthtime)


# ── Sync extraction ───────────────────────────────────────────────────────────

def _extract_one(image_path: Path, client: anthropic.Anthropic, model: str) -> dict:
    data = base64.standard_b64encode(image_path.read_bytes()).decode('utf-8')
    media_type = 'image/jpeg' if image_path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": API_PROMPT},
        ]}],
    )
    return _parse_response(msg.content[0].text)


def cmd_sync(folder: Path, db: dict, db_path: Path,
             client: anthropic.Anthropic, model: str,
             date: str | None = None) -> None:
    files = _unprocessed_files(folder, db, date)
    print(f"{len(files)} unprocessed screenshot(s).")

    for img_path in files:
        print(f"  {img_path.name} ... ", end='', flush=True)
        fdate = _file_date(img_path)
        now   = datetime.now().isoformat()
        try:
            extraction = _extract_one(img_path, client, model)
            db['screenshots'][img_path.name] = {
                "status": "ok", "file_date": fdate,
                **extraction,
                "extracted_at": now, "error": None,
            }
            print("ok")
        except anthropic.RateLimitError:
            print("rate limit — stopping. Re-run to continue.")
            save_db(db, db_path)
            return
        except Exception as e:
            print(f"error: {e}")
            db['screenshots'][img_path.name] = {
                "status": "error", "file_date": fdate,
                "error": str(e), "extracted_at": now,
            }
        save_db(db, db_path)


# ── Batch API ─────────────────────────────────────────────────────────────────

def cmd_submit(folder: Path, db: dict, db_path: Path,
               client: anthropic.Anthropic, model: str,
               date: str | None = None) -> None:
    files = _unprocessed_files(folder, db, date)
    if not files:
        print("No new screenshots to submit.")
        return

    requests = []
    for i, img_path in enumerate(files):
        data = base64.standard_b64encode(img_path.read_bytes()).decode('utf-8')
        media_type = 'image/jpeg' if img_path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'
        requests.append({
            "custom_id": f"req_{i:04d}",
            "params": {
                "model": model, "max_tokens": 1024,
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": API_PROMPT},
                ]}],
            },
        })

    batch = client.messages.batches.create(requests=requests)
    db['pending_batches'].append({
        "batch_id": batch.id,
        "submitted_at": datetime.now().isoformat(),
        "files": [f.name for f in files],
    })
    save_db(db, db_path)
    print(f"Submitted batch {batch.id} — {len(files)} screenshot(s).")
    print("Run with --retrieve once complete (usually a few hours).")


def cmd_retrieve(folder: Path, db: dict, db_path: Path,
                 client: anthropic.Anthropic) -> None:
    pending = db.get('pending_batches', [])
    if not pending:
        print("No pending batches.")
        return

    remaining = []
    for batch_info in pending:
        batch_id = batch_info['batch_id']
        print(f"Batch {batch_id} ... ", end='', flush=True)
        batch = client.messages.batches.retrieve(batch_id)

        if batch.processing_status != 'ended':
            counts = batch.request_counts
            print(f"still processing ({counts.processing} running, {counts.succeeded} done)")
            remaining.append(batch_info)
            continue

        print("complete")
        index_to_name = {f"req_{i:04d}": name for i, name in enumerate(batch_info['files'])}
        now = datetime.now().isoformat()

        for result in client.messages.batches.results(batch_id):
            filename = index_to_name.get(result.custom_id, result.custom_id)
            img_path = folder / filename
            fdate = _file_date(img_path) if img_path.exists() else None

            if result.result.type == 'succeeded':
                try:
                    extraction = _parse_response(result.result.message.content[0].text)
                    db['screenshots'][filename] = {
                        "status": "ok", "file_date": fdate,
                        **extraction,
                        "extracted_at": now, "error": None,
                    }
                    print(f"  {filename}: ok")
                except Exception as e:
                    db['screenshots'][filename] = {
                        "status": "error", "file_date": fdate,
                        "error": str(e), "extracted_at": now,
                    }
                    print(f"  {filename}: parse error — {e}")
            else:
                db['screenshots'][filename] = {
                    "status": "error", "file_date": fdate,
                    "error": str(result.result.error), "extracted_at": now,
                }
                print(f"  {filename}: API error")

        save_db(db, db_path)

    db['pending_batches'] = remaining
    save_db(db, db_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract words from Spelling Bee screenshots")
    parser.add_argument('--folder',   default='../data/screenshots',
                        help='Screenshot folder')
    parser.add_argument('--db',       default='../data/screenshots_db.json',
                        help='Output database path')
    parser.add_argument('--model',    default='claude-haiku-4-5',
                        help='Vision model')
    parser.add_argument('--api-key',  help='Anthropic API key')
    parser.add_argument('--date',     metavar='YYYY-MM-DD',
                        help='Process only screenshots created on this date')
    parser.add_argument('--submit',   action='store_true',
                        help='Submit a batch job for all unprocessed screenshots')
    parser.add_argument('--retrieve', action='store_true',
                        help='Retrieve completed batch results')
    args = parser.parse_args()

    if args.submit and args.retrieve:
        parser.error("--submit and --retrieve are mutually exclusive")
    if args.retrieve and args.date:
        parser.error("--date has no effect with --retrieve")

    folder  = Path(args.folder)
    db_path = Path(args.db)
    db      = load_db(db_path)
    client  = anthropic.Anthropic(api_key=args.api_key) if args.api_key else anthropic.Anthropic()

    if args.submit:
        cmd_submit(folder, db, db_path, client, args.model, args.date)
    elif args.retrieve:
        cmd_retrieve(folder, db, db_path, client)
    else:
        cmd_sync(folder, db, db_path, client, args.model, args.date)


if __name__ == '__main__':
    main()
