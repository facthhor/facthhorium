# Source changes

`server.py` is adapted from the deployed Facthhorium relay. Its long-stream forwarding, keepalive, stream failure handling, and launch resource options are retained. Machine-specific model and log paths were removed; `loom-serve` is resolved on `PATH`, and logs default to the package `logs/` directory.

`serve.sh` and `serve-facthhorium.sh` preserve the caller-supplied port and Facthhorium model ID while resolving files relative to their own directory.

The `.loom` programs, `facthhorium.json`, `llm_config.json`, and `weights.loom` are copied from the deployed engine without intentional edits. Weights, tokenizer, and runtime binaries are excluded.
