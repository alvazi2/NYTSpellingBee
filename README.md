# NYT Spelling Bee Flashcard Generator

A Python pipeline that turns NYT Spelling Bee solution screenshots into Anki flashcard decks for missed words.

## What it does

1. Extracts found and missed words from screenshots using the Anthropic vision API
2. Matches each screenshot to the correct puzzle using a reference database from nytbee.com
3. Computes missed words authoritatively (reference word list minus found words)
4. Fetches brief definitions for each missed word
5. Generates Anki-importable CSV files, grouped by the number of distinct letters in each word

Cards come in two types: **missed-word cards** (yellow theme, grouped by distinct letters, with NYT point value on the back) and **pangram cards** (purple/gold theme, one per puzzle).

## Requirements

```bash
pip install anthropic
```

An [Anthropic API key](https://console.anthropic.com) is required. Copy `config.sh.example` to `config.sh` and add your key.

## Usage

```bash
./scripts/weekly_batch_submit.sh      # update reference db + submit all unprocessed screenshots (async, 50% cheaper)
# wait a few hours
./scripts/weekly_batch_retrieve.sh    # retrieve results and regenerate Anki files
```

A synchronous fallback is also available via `scripts/weekly_sync_run.sh`.

To rebuild outputs from existing databases (no vision API calls):

```bash
./scripts/rebuild_output.sh
```

To build or update the local reference database of all past puzzles from nytbee.com (no API key needed):

```bash
./src/fetch_nytbee.py
```

## Documentation

Full architecture, script reference, output format, and card design are documented in [CLAUDE.md](CLAUDE.md).
