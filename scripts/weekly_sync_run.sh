#!/bin/zsh
# Sync fallback — process all new screenshots immediately (no batch, no delay)
cd "$(dirname "$0")"
source ../config.sh

python3 ../src/spelling_bee.py \
  --folder  "$FOLDER" \
  --output  "$OUTPUT" \
  --db      "$DB"     \
  --model   "$MODEL"  \
  --api-key "$API_KEY"
