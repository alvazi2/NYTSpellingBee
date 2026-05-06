#!/bin/zsh
# Sync fallback — update reference db, extract all new screenshots immediately,
# match to puzzles, and generate CSVs. No batch delay.
cd "$(dirname "$0")"
source ../config.sh

echo "==> Updating nytbee_db..."
python3 ../src/fetch_nytbee.py

echo ""
echo "==> Extracting screenshots (sync)..."
python3 ../src/extract.py \
  --folder  "$FOLDER"         \
  --db      "$SCREENSHOTS_DB" \
  --model   "$MODEL"          \
  --api-key "$API_KEY"

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
