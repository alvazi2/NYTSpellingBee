#!/bin/zsh
# Weekly step 1 — submit a batch for the newest unprocessed date (or pass --date YYYY-MM-DD to override)
cd "$(dirname "$0")"
source ../config.sh

python3 ../src/spelling_bee.py \
  --folder  "$FOLDER" \
  --output  "$OUTPUT" \
  --db      "$DB"     \
  --model   "$MODEL"  \
  --api-key "$API_KEY" \
  --submit \
  "$@"
