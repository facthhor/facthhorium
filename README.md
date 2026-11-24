# Facthhorium

Facthhorium runs Inkling 2 Mini on AMD GPUs with Loom. It was tested on the Radeon 8060S (gfx1151).

v0.3 moves Facthhorium onto loom-fun's DSpark package, so decode uses Inkling's own drafter (speculative decoding at depth 3). It also switches to the UD-Q4_K_XL weights. The KV cache stays FP16. On a 32 GB machine the context is capped at 131,072 tokens. Compressing the global KV cache, which would raise that cap, is still in development. For longer contexts, v0.2.1 serves 204,800 tokens on UD-Q4_K_M without a drafter.

- At temperature 1, top-k 0 and top-p 1, the sampler draws from all 200,058 tokens. It sums probability mass across 32 GPU workgroups.
- Single-token decode spreads the output-head work across 96 GPU lanes and the attention maximum reduction across 32 lanes.
- The tool parser skips the argument body until a call is complete. Stray bytes after a complete call's JSON no longer fail the turn. The HTTP relay sends a keepalive every 15 seconds of silence and reports interrupted streams without replaying partial tool calls.
- The vision path accepts images using the Inkling FP16 projector.
- The drafter proposes 3 tokens per step. The target verifies them with the same full-vocabulary sampler. Set `presets.chat.execution.draft_depth` to 0 in `facthhorium.json` to run the target alone. At depth 3, greedy output can drift from depth 0 within a few hundred characters because verification computes in batches. Both settings repeat exactly for the same request.

## Computer use

Each chat request can contain up to 16 images across its message history. Each image can be up to 1 MiB compressed, with a maximum width or height of 4,096 pixels. The HTTP request limit is 32 MiB.

For long rati0 computer-use sessions, load the included Pi extension (`pi -e ./pi/facthhorium-images.ts`). When a request would exceed 16 images, it replaces the oldest historical observation images with text markers in the outgoing request, 8 at a time, so 8 to 15 images remain. Between those batch trims the earlier request stays byte-identical, so Loom's prefix cache keeps serving it instead of reprocessing the whole conversation on every action. It preserves the saved session, user attachments and the current batch of tool results. If those images alone exceed the limit, split them across requests.

## Setup

On Linux, install `libseccomp.so.2`, then install the runtime with `pipx install "hrx-loom[hf]==0.2.0"` using the [pinned hrx-system source](https://github.com/ROCm/hrx-system/tree/e9cc3017765171611afe609cb92744602cf7cace). This package provides `loom-serve`; put it on your `PATH`. From the repository root, fetch the tokenizer and model files.

```sh
curl -fL 'https://huggingface.co/loom-fun/unsloth-Inkling-2-Mini-loom/resolve/9b1eedd839ec3d648031f81256fd5fcdd4cf6c10/tokenizer.json' -o tokenizer.json
```

Fetch the target, projector and drafter files from [unsloth/Inkling-2-Mini-GGUF](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF) into `parameter/`:

```sh
mkdir -p parameter
curl -fL 'https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/ea0c79b2ecd73669e774c8519b79bfabfddbc027/Inkling-2-Mini-UD-Q4_K_XL.gguf' -o parameter/Inkling-2-Mini-UD-Q4_K_XL.gguf
curl -fL 'https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/ea0c79b2ecd73669e774c8519b79bfabfddbc027/dspark-Inkling-2-Mini-Q8_0.gguf' -o parameter/dspark-Inkling-2-Mini-Q8_0.gguf
curl -fL 'https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/main/mmproj-F16.gguf' -o parameter/mmproj-F16.gguf
```

Start the server on a loopback port (the caller, such as llama-swap, supplies the port):

```sh
./serve-facthhorium.sh 8080
```

By default, logs are written to `logs/` beside the server. Set `FACTHHORIUM_LOG_DIR` to change the directory. Relay diagnostics and timing records use `llama-server.log`; Loom stderr uses `facthhorium-loom-serve.log`. For rati0’s speed card, set `FACTHHORIUM_LOG_DIR="$HOME/.local/share/ai-workspace/logs"` in the launcher environment.

## v0.3 measurements

Measured on an ASUS ROG Flow Z13 (Ryzen AI Max+ 395, Radeon 8060S, 32 GB) at temperature 1, top-k 0 and top-p 1, with maximum reasoning effort, draft depth 3 and an FP16 KV cache. The retrieval prompts are Python source code with four facts placed at 8%, 38%, 68% and 94% depth. Each row covers three requests: one greedy and two sampled. Decode excludes prefill.

| Input tokens | Facts found | v0.3 decode tok/s | v0.2.1 decode tok/s | Prefill |
|---:|---:|---:|---:|---:|
| 9,261 | 12/12 | 60.1 | 36.9 | — |
| 36,694 | 16/16 | 50.7 | 30.4 | 24 s |
| 73,000 | 12/12 | 45.6 | 24.5 | 60 s |
| 122,593 | 12/12 | 31.7 | — | 114 s |

The v0.2.1 column uses the UD-Q4_K_M weights without a drafter. Its 142,855-token row ran at 18.0 tok/s, which is beyond v0.3's context cap. Speculative decoding helps most on predictable text such as code, file rewrites and long-context answers. It helps least on free prose. Short reasoning requests decoded at a median of 65 tok/s (math) and 61 tok/s (code).

At the same settings v0.3 solved 14 of 14 math problems with exact answers and 5 of 5 coding problems checked by unit tests. It passed 4 of 4 vision checks, including a 16-image request, and emitted the expected tool call. A repeated greedy request at 36,694 tokens produced identical output.

A verbatim-copy test checks long-range recall at draft depth 3. Each request quotes one line of Rust source that the model cannot have memorized, and asks for the six lines after it. Ten greedy requests at 50,084 input tokens and ten at 95,746 returned all 120 lines exactly.

Prefill runs in 4,096-token chunks, the upstream setting. Smaller chunks gave long prompts small run-to-run differences. GPU memory (GTT) peaked at 24.7 GiB with 122,593 input tokens. Each additional token adds about 35 KiB, which includes the drafter's own cache. The image projector loads only when a request contains an image, and it adds about 0.6 GiB. Requests whose input plus `max_tokens` exceed 131,072 tokens are rejected with a "compact history" error.

The first launch compiles the program for your GPU, which can take a few minutes. The relay waits up to 15 minutes for that warmup.

## v0.2 historical decode speed

Measured on the same Z13 at temperature 1, top-k 0 and top-p 1, with 96 generated tokens. Times exclude prefill. The short rows are medians of three requests. Each longer row is one request per version.

| Input tokens | v0.1 tok/s | v0.2 tok/s |
|---:|---:|---:|
| 71 | 45.5 | 45.4 |
| 4,103 | 40.1 | 39.8 |
| 16,391 | 36.0 | 36.1 |
| 32,775 | 29.0 | 31.9 |
| 65,543 | 21.2 | 25.6 |

For single-token decode, the eight global attention passes can split the KV scan across 256 workgroups per KV head. Sliding-window attention and batched decode keep 64 splits. Each model pass retains its own KV history.

## v0.2 historical long context and quality

A second run compared the two versions on retrieval from Python source code, with four facts placed at 8%, 38%, 68% and 94% depth. Each row is the median of three requests (one greedy, two sampled at temperature 1, top-k 0, top-p 1) with maximum reasoning effort.

| Input tokens | v0.1 tok/s | v0.2 tok/s | Facts found, both versions |
|---:|---:|---:|---:|
| 9,261 | 36.7 | 36.9 | 12/12 |
| 36,694 | 29.1 | 30.4 | 16/16 |
| 73,000 | 21.8 | 24.5 | 12/12 |
| 142,855 | 13.5 | 18.0 | 12/12 |

At the same sampling settings both versions solved 14 of 14 math problems with exact answers and 5 of 5 coding problems checked by unit tests. Below about 512 tokens of context they produce byte-identical output. Beyond that, v0.2 sums attention over more partial results, so rounding differs and long transcripts diverge. Both versions are deterministic. GPU memory peaked at 22.4 GiB with 142,855 input tokens. Each additional token of context adds 32 KiB of KV cache.

## External sources

The Loom programs derive from [loom-fun/unsloth-Inkling-2-Mini-loom](https://huggingface.co/loom-fun/unsloth-Inkling-2-Mini-loom/tree/4e018e88a3aa). Runtime `hrx-loom` is an external dependency from [ROCm/hrx-system](https://github.com/ROCm/hrx-system/tree/e9cc3017765171611afe609cb92744602cf7cace). Program generation used [loom-fun/loom-skills](https://github.com/loom-fun/loom-skills/tree/618f89e134ea7bdc579f01f2d1825622df12912d). See `licenses/` for notices.
