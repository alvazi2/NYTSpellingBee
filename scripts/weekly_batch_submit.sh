#!/bin/zsh
# Weekly step 1 — update the reference puzzle database, then submit a batch job
# for all unprocessed screenshots.
cd "$(dirname "$0")"
source ../config.sh

echo "==> Updating nytbee_db..."
python3 ../src/fetch_nytbee.py

echo ""
echo "==> Submitting batch..."
python3 ../src/extract.py \
  --folder  "$FOLDER"         \
  --db      "$SCREENSHOTS_DB" \
  --model   "$MODEL"          \
  --api-key "$API_KEY"        \
  --submit
