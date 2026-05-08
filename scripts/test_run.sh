#!/bin/zsh
# Test run — extract, match, and generate for a specific screenshot creation date.
# Usage: ./test_run.sh [YYYY-MM-DD]   (omit the date to process all unprocessed screenshots)
cd "$(dirname "$0")"
source ../config.sh

TEST_DATE="${1:-}"

DATE_ARGS=()
if [[ -n "$TEST_DATE" ]]; then
  DATE_ARGS=(--date "$TEST_DATE")
fi

echo "==> Extracting screenshots (sync)..."
python3 ../src/extract.py \
  --folder  "$FOLDER"         \
  --db      "$SCREENSHOTS_DB" \
  --model   "$MODEL"          \
  --api-key "$API_KEY"        \
  "${DATE_ARGS[@]}"

echo ""
echo "==> Matching screenshots to puzzles..."
python3 ../src/merge.py \
  --screenshots-db "$SCREENSHOTS_DB" \
  --nytbee-db      "$NYTBEE_DB"      \
  --output         "$MERGED_DB"

echo ""
echo "==> Generating Anki CSV files..."
python3 ../src/generate.py \
  --merged-db      "$MERGED_DB"      \
  --definitions-db "$DEFINITIONS_DB" \
  --output         "$OUTPUT"         \
  --model          "$MODEL"          \
  --api-key        "$API_KEY"
