# Source changes

`server.py` is adapted from the deployed Facthhorium relay. Its long-stream forwarding, keepalive, stream failure handling, and launch resource options are retained. Machine-specific model and log paths were removed; `loom-serve` is resolved on `PATH`, and logs default to the package `logs/` directory.

`serve.sh` and `serve-facthhorium.sh` preserve the caller-supplied port and Facthhorium model ID while resolving files relative to their own directory.

In v0.1 the `.loom` programs, `facthhorium.json`, `llm_config.json`, and `weights.loom` were copied from the deployed engine without intentional edits. Weights, tokenizer, and runtime binaries are excluded.

In v0.2, `program/llm.loom` widens single-token global attention and its reduction. `program/control.loom` admits 16 image occurrences. The relay names Facthhorium errors and accepts requests up to 32 MiB. The optional Pi extension limits older observation images in outgoing requests.

In v0.2.1, the Pi extension trims older observation images 8 at a time instead of one per request, keeping the request prefix stable for Loom's prefix cache.

In v0.3 (preview), the target and verifier use the Facthhorium sampler and single-token global attention in loom-fun’s DSpark program. The package loads the XL target and Q8_0 drafter, restores image inputs, and keeps the v0.2.1 relay and Pi extension. The KV cache stays FP16. The model card uses a 4,096-token prefill capacity, matching upstream, because 512-token chunks made long-prompt prefill non-repeatable. The relay allows up to 15 minutes for the first-launch warmup.
