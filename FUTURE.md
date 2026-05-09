# Future Improvements

Tracked here so they don't get lost between sessions.

- **Stop passing the API key as a CLI argument.** All five shell scripts pass `--api-key "$API_KEY"`, which exposes the key in `ps aux`. The Anthropic SDK already reads `ANTHROPIC_API_KEY` from the environment, so the cleaner pattern is `export ANTHROPIC_API_KEY="$API_KEY"` in each script and dropping `--api-key` from the Python invocations. Deferred for now to avoid churning the scripts.
- **Add `export` to the assignments in `config.sh`.** They currently work because every Python invocation receives the values through explicit `--flag "$VAR"` arguments. If the API-key change above is ever made, the env-var path requires either `export` or inline assignment (`ANTHROPIC_API_KEY=… python3 …`).
- **Automatically push updated CSV files to Anki.** After `generate.py` runs, push the updated decks into Anki without a manual File → Import step. Likely via [AnkiConnect](https://ankiweb.net/shared/info/2055492159) (a local HTTP API add-on) or by copying files into Anki's media/collection folder directly.
