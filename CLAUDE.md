# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A Python pipeline that processes NYT Spelling Bee screenshots via the Anthropic vision API, matches them against a reference puzzle database, and generates Anki import files of missed words.

## Dependencies

```bash
pip install anthropic
```

API key is passed via `--api-key` in each shell script (stored in `config.sh`).

## Shell Scripts

Located in `scripts/`. Run from anywhere — each script `cd`s to its own directory first.

| Script | Purpose |
|---|---|
| `scripts/weekly_batch_submit.sh` | Update nytbee_db, then submit all unprocessed screenshots as a batch (50% cheaper, async) |
| `scripts/weekly_batch_retrieve.sh` | Retrieve completed batch, run merge and generate |
| `scripts/weekly_sync_run.sh` | Synchronous fallback — update nytbee_db, extract, merge, generate immediately |
| `scripts/rebuild_output.sh` | Re-run merge + generate from existing databases (no vision API calls) |
| `scripts/test_run.sh` | Extract a specific date's screenshots, then merge and generate |

**Recommended weekly workflow:**
```bash
./scripts/weekly_batch_submit.sh      # update nytbee_db + submit batch (~1-2 min)
# wait a few hours
./scripts/weekly_batch_retrieve.sh    # collect results + merge + generate outputs
```

All settings (API key, folder, model, database paths) live in `config.sh` (project root, gitignored).

## Architecture

Three-stage pipeline, each stage a standalone script that can also be run directly from the project root:

### Stage 1 — `src/extract.py`

Scans `data/screenshots/` sorted by creation time (`st_birthtime`). Skips files already extracted successfully (`status: "ok"`) or pending in a batch. Files with `status: "error"` are retried automatically on the next run. New files are sent to the Anthropic vision API (sync or batch). Stores the raw API response verbatim per file — the vision API is never re-run for already-succeeded files.

Supports `--date YYYY-MM-DD` to process only screenshots created on a specific date (useful for testing).

### Stage 2 — `src/merge.py`

Reads `data/screenshots_db.json` and `data/nytbee_db.json`. Rebuilds `data/merged_db.json` from scratch on every run, so previously-skipped screenshots are retried automatically after nytbee_db updates.

**Matching logic** (applied per screenshot):
1. **Word-overlap voting** — each word in `found ∪ missed` votes for every nytbee_db date that contains it
2. **Date upper bound** — puzzle date must not exceed the screenshot's `st_birthtime` (a puzzle can't be published after you took the screenshot)
3. **Letter-set filter** — if the honeycomb was visible, puzzle letters must match exactly
4. **Recency tiebreaker** — among equally-scored candidates, prefer the most recent date
5. **Acceptance thresholds** — requires `MIN_OVERLAP = 3` words AND `MIN_RATIO = 0.7` (70% of screenshot words present in the matched puzzle); otherwise the screenshot is skipped with a message

**Missed words** are computed authoritatively as `nytbee_db[date].words − found_words`, not from the vision API.

Screenshots skipped due to no match (e.g. puzzles too recent for nytbee_db) are picked up automatically on the next weekly run after nytbee_db updates.

### Stage 3 — `src/generate.py`

Reads `data/merged_db.json`. Fetches definitions for all missed words via the API (batches of 100 words), cached in `data/definitions_db.json`. Writes Anki CSV files to `output/`.

## Batch API Workflow

`extract.py --submit` submits all unprocessed screenshots in a single batch. The mapping from positional index (`req_0000`, `req_0001`, …) back to filenames is stored in `pending_batches` inside `data/screenshots_db.json`.

`extract.py --retrieve` processes all completed batches, updating `screenshots_db.json`. Batches still in progress are left in `pending_batches` and checked again on the next `--retrieve` call.

## Rate Limit Handling

In sync mode, `anthropic.RateLimitError` stops the run cleanly — the file is not marked as processed, so the next run resumes from the same file. Other exceptions mark the file as `"error"` status and continue.

## Output Files

Each run of `generate.py` writes Anki CSV files to `output/`:

| File | Contents |
|---|---|
| `output/spelling_bee_complete.csv` | All cards |
| `output/spelling_bee_2_letters.csv` | Missed-word cards with 2 distinct letters |
| `output/spelling_bee_3_letters.csv` | Missed-word cards with 3 distinct letters |
| `output/spelling_bee_4_letters.csv` | Missed-word cards with 4 distinct letters |
| `output/spelling_bee_5_letters.csv` | Missed-word cards with 5 distinct letters |
| `output/spelling_bee_6_letters.csv` | Missed-word cards with 6 distinct letters |
| `output/spelling_bee_7_letters.csv` | Pangram cards + missed-word cards with 7 distinct letters |
| `output/spelling_bee_most_missed.csv` | Top 25 most-frequently-missed words, grouped by distinct letter set |

Files for letter counts with no cards are skipped and deleted if previously generated.

## Card Design

### Missed-word cards (yellow theme)
- **Front:** Distinct letters as yellow bubbles (alphabetical order)
- **Back:** Each word in bold with its NYT point value `(N pts)`, definition below in small italic text (if available); separated by a horizontal rule, up to 10 words you actually found with the same distinct letter set ("You found: …") as a memory anchor

### Most-missed cards (red ★ theme)
- **Front:** Distinct letters as yellow bubbles + "★ MOST MISSED ★" label in red
- **Back:** Each word in bold with its NYT point value, miss count (`missed N×`), and definition; separated by a horizontal rule, up to 10 found words with the same distinct letter set ("You found: …")
- Words grouped by distinct letter set, top 25 most-missed words across all puzzles
- Override count with `--most-missed-count N`

### Pangram cards (purple/gold ★ theme)
- **Front:** All 7 puzzle letters as bubbles + "★ PANGRAM CARD ★" label. The center letter is rendered as a purple bubble; the other six are yellow.
- **Back:** Pangram word(s) in large bold uppercase
- One card per puzzle, always included in the 7-letters output

**NYT scoring:** 4-letter words = 1 pt · 5+ letters = 1 pt/letter · pangram bonus = +7 pts

## Anki CSV Format

- Headers: `#separator:tab`, `#html:true`, `#deck:Spelling Bee::<name>`
- Deck hierarchy: `Spelling Bee::Complete`, `Spelling Bee::2 Letters`, … `Spelling Bee::7 Letters`, `Spelling Bee::Most Missed`
- Import via **File → Import** (`Cmd+Shift+I`) in Anki — deck is created automatically

## Reference Puzzle Database

`src/fetch_nytbee.py` builds a reference database of all past NYT Spelling Bee puzzles scraped from nytbee.com, stored in `data/nytbee_db.json`. Run it standalone — no API key required.

```bash
./src/fetch_nytbee.py                   # fetch everything up to the cutoff
./src/fetch_nytbee.py --from 2024-01-01 # start from a specific date
```

**Cutoff rule:** puzzles from the current calendar week and the prior week (Mon–Sun) are never fetched, to avoid spoilers.

Re-running is safe — already-fetched dates are skipped. Each entry is keyed by date (`"YYYY-MM-DD"`) and contains `words`, `pangrams`, `puzzle_letters`, and `center_letter`.

## Notebooks

Notebook outputs are stripped automatically on `git add` via `nbstripout` (configured in `.gitattributes`). No manual clearing needed — but `nbstripout --install` must be run once per clone to activate the git filter.

## Statistics

Two Jupyter notebooks in `notebooks/` analyse the data interactively:

| Notebook | Contents |
|---|---|
| `notebooks/my_performance.ipynb` | Personal dashboard: scoreboard (incl. points earned and score efficiency), miss rate and score efficiency over time, calendar heatmap, hardest puzzles, most-missed words with point values, pangram performance, word-length and letter-count breakdowns, center-letter analysis, points left on the table |
| `notebooks/puzzle_analysis.ipynb` | Reference database analysis: puzzle size trends, pangram distribution, letter frequency, puzzle richness by center letter, most recurring words, distinct-letter count distribution by year |

## Databases

| File | Description |
|---|---|
| `data/screenshots_db.json` | Raw vision API results, keyed by filename. Each entry has `status` (`ok`/`error`/`pending_batch`), `file_date` (screenshot creation date from `st_birthtime`), `found`, `missed`, `puzzle_letters`, `pangram`, `extracted_at`. Also holds a top-level `pending_batches` list for in-flight batch jobs. |
| `data/nytbee_db.json` | Reference puzzle database from nytbee.com, keyed by `YYYY-MM-DD`. Each entry has `words`, `pangrams`, `puzzle_letters`, `center_letter`. |
| `data/merged_db.json` | One entry per matched puzzle date (`YYYY-MM-DD`). Contains `puzzle_letters`, `center_letter`, `pangrams` (from nytbee_db), `found` (union of found words across all screenshots for that date), `missed` (authoritative: nytbee_db words minus found), `screenshots` (filenames), `points_earned`, `points_possible` (NYT scoring). Rebuilt from scratch on every `merge.py` run. |
| `data/definitions_db.json` | Word → definition string (or `null`). Cached across runs; already-cached words are skipped. |

## Screenshot Folder

`data/screenshots/` contains JPEG files named as either UUIDs or readable words (e.g. ` Bollard.jpeg`). Some named files have a leading space. All files are treated uniformly.

## Future Improvements

See [FUTURE.md](FUTURE.md).
