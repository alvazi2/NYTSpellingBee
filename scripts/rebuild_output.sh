#!/bin/zsh
# Rebuild outputs — re-match all screenshots and regenerate CSVs from existing
# databases. No vision API calls; run after updating nytbee_db to pick up
# screenshots that were previously skipped due to missing puzzle entries.
cd "$(dirname "$0")"
source ../config.sh

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
