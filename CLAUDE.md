# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A Python CLI script that processes NYT Spelling Bee screenshots via the Anthropic vision API, extracts missed words and pangrams, fetches word definitions, and generates Anki import files.

## Dependencies

```bash
pip install anthropic reportlab pillow
```

API key is passed via `--api-key` in each shell script (stored in `config.sh`).

## Shell Scripts

Located in `scripts/`. Run from anywhere — each script `cd`s to its own directory first.

| Script | Purpose |
|---|---|
| `scripts/weekly_batch_submit.sh` | Submit one batch per unprocessed date (50% cheaper, async) |
| `scripts/weekly_batch_retrieve.sh` | Retrieve completed batches and regenerate all outputs |
| `scripts/weekly_sync_run.sh` | Synchronous fallback — process all new screenshots immediately |
| `scripts/rebuild_output.sh` | Regenerate all outputs from existing database (fetches missing definitions via API) |
| `scripts/test_run.sh` | Process a specific date (set `TEST_DATE` inside the script) |

**Recommended weekly workflow:**
```bash
./scripts/weekly_batch_submit.sh      # submit all unprocessed dates (takes ~1-2 min)
# wait a few hours
./scripts/weekly_batch_retrieve.sh    # collect results + regenerate outputs
```

All settings (API key, folder, model) live in `config.sh` (project root).

## Architecture

Single-script design (`src/spelling_bee.py`) with these logical stages:

1. **Ingestion** — Scan `data/screenshots/` sorted by creation time (`st_birthtime`), skip files already in `data/spelling_bee_db.json`. New files are processed either synchronously or via the Anthropic Batch API.

2. **Vision extraction** — Each screenshot is sent to `claude-haiku-4-5` (default). The prompt asks for puzzle letters, pangram, found words, and missed words, returning JSON.

3. **Puzzle merging** — Multi-screenshot puzzles are detected and merged:
   - Primary: pangram → 7-letter key → O(1) dict lookup
   - Secondary: `puzzle_letters` from honeycomb grid → O(1) lookup
   - Fallback: any word overlap against the last 2 puzzles (threshold = 1 word)
   - After merging, `infer_pangram()` derives the pangram from the word list if the API missed it

4. **Definitions** — `fetch_definitions()` fetches a brief definition for each missed word via the API (batches of 100 words). Results are cached in `db['definitions']`; already-cached words are skipped. Definitions appear on card backs in small italic text below the word.

5. **Output generation** — Missed words are globally deduplicated, grouped by distinct letters, and written to Anki CSV files.

## Batch API Workflow

`--submit` submits one batch per unprocessed date (auto-detects all unprocessed dates when `--date` is omitted). Each batch's `custom_id` uses a positional index (`req_0000`, `req_0001`, …) to avoid filename character restrictions. The mapping back to filenames is stored in `pending_batches` in the database.

`--retrieve` processes all completed batches in chronological date order (so merge logic sees correct neighbours), then runs the pangram inference sweep and regenerates outputs.

## Rate Limit Handling

In sync mode, `anthropic.RateLimitError` stops the run cleanly without marking any file as failed — the next run resumes from the same file. Other exceptions mark the file as `None` (permanently skipped) and continue to the next file.

## Output Files

Each run writes Anki CSV files to `output/`:

| File | Contents |
|---|---|
| `output/spelling_bee_complete.csv` | All cards |
| `output/spelling_bee_2_letters.csv` | Missed-word cards with 2 distinct letters |
| `output/spelling_bee_3_letters.csv` | Missed-word cards with 3 distinct letters |
| `output/spelling_bee_4_letters.csv` | Missed-word cards with 4 distinct letters |
| `output/spelling_bee_5_letters.csv` | Missed-word cards with 5 distinct letters |
| `output/spelling_bee_6_letters.csv` | Missed-word cards with 6 distinct letters |
| `output/spelling_bee_7_letters.csv` | Pangram cards + missed-word cards with 7 distinct letters |

Files for letter counts with no cards are skipped and deleted if previously generated.

## Card Design

### Missed-word cards (yellow theme)
- **Front:** Distinct letters as yellow bubbles (alphabetical order)
- **Back:** Each word in bold, with definition below in small italic text (if available)

### Pangram cards (purple/gold ★ theme)
- **Front:** All 7 puzzle letters as bubbles + "★ PANGRAM CARD ★" label
- **Back:** Pangram word(s) in large bold uppercase
- One card per puzzle, always included in the 7-letters output

## Anki CSV Format

- Headers: `#separator:tab`, `#html:true`, `#deck:Spelling Bee::<name>`
- Deck hierarchy: `Spelling Bee::Complete`, `Spelling Bee::2 Letters`, … `Spelling Bee::7 Letters`
- Import via **File → Import** (`Cmd+Shift+I`) in Anki — deck is created automatically

## Database

`data/spelling_bee_db.json` tracks:
- `processed_files` — filename → puzzle key (or `null` on permanent error)
- `puzzles` — keyed by 7-letter string derived from pangram
- `puzzle_order` — insertion-ordered list of puzzle keys
- `pending_batches` — list of in-flight batch jobs with their file lists
- `definitions` — word → definition string (or `null` if not found); cached across runs

## Screenshot Folder

`data/screenshots/` contains JPEG files named as either UUIDs or readable words (e.g. ` Bollard.jpeg`). Some named files have a leading space. All files are treated uniformly — passed to the vision API regardless of name.
