#!/bin/zsh
# Weekly step 2 — retrieve completed batch results and regenerate PDF + CSV
cd "$(dirname "$0")"
source ../config.sh

python3 ../src/spelling_bee.py \
  --folder  "$FOLDER" \
  --output  "$OUTPUT" \
  --db      "$DB"     \
  --api-key "$API_KEY" \
  --retrieve
