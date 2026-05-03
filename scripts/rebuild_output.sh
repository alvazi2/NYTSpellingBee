#!/bin/zsh
# Rebuild outputs only — regenerate CSV from the existing database (fetches missing definitions via API)
cd "$(dirname "$0")"
source ../config.sh

python3 ../src/spelling_bee.py \
  --folder  "$FOLDER"  \
  --output  "$OUTPUT"  \
  --db      "$DB"      \
  --api-key "$API_KEY" \
  --model   "$MODEL"   \
  --output-only
