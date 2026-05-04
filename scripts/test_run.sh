#!/bin/zsh
# Test run — ingest screenshots from a specific date and generate outputs
cd "$(dirname "$0")"
source ../config.sh

TEST_DATE="2025-04-20"   # set to the date you want to test (YYYY-MM-DD)

python3 ../src/spelling_bee.py \
  --folder  "$FOLDER" \
  --output  "$OUTPUT" \
  --db      "$DB"     \
  --model   "$MODEL"  \
  --api-key "$API_KEY" \
  --date    "$TEST_DATE"
