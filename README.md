# NYT Spelling Bee Flashcard Generator

A Python CLI tool that turns NYT Spelling Bee screenshots into Anki flashcard decks.

## What it does

1. Scans a folder of Spelling Bee screenshots
2. Uses the Anthropic vision API to extract missed words and pangrams
3. Fetches a brief definition for each missed word
4. Generates Anki-importable CSV files, grouped by the number of distinct letters in each word

Cards come in two types: **missed-word cards** (yellow theme, grouped by distinct letters) and **pangram cards** (purple/gold theme, one per puzzle).

## Requirements

```bash
pip install anthropic reportlab pillow
```

An [Anthropic API key](https://console.anthropic.com) is required. Copy `config.sh.example` to `config.sh` and add your key.

## Usage

```bash
./scripts/weekly_batch_submit.sh      # submit all unprocessed screenshots (async, 50% cheaper)
# wait a few hours
./scripts/weekly_batch_retrieve.sh    # retrieve results and regenerate Anki files
```

A synchronous fallback is also available via `scripts/weekly_sync_run.sh`.

## Documentation

Full architecture, script reference, output format, and card design are documented in [CLAUDE.md](CLAUDE.md).