#!/bin/zsh
# Weekly step 2 — retrieve completed batch results, match to puzzles, generate CSVs.
cd "$(dirname "$0")"
source ../config.sh

echo "==> Retrieving batch results..."
python3 ../src/extract.py \
  --folder  "$FOLDER"         \
  --db      "$SCREENSHOTS_DB" \
  --api-key "$API_KEY"        \
  --retrieve

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
