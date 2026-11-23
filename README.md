# Facthhorium

Facthhorium runs Inkling 2 Mini on AMD GPUs with Loom. This version uses the UD-Q4_K_M weights and an FP16 KV cache. It was tested on the Radeon 8060S (gfx1151).

- At temperature 1, top-k 0 and top-p 1, the sampler draws from all 200,058 tokens. It sums probability mass across 32 GPU workgroups.
- Single-token decode spreads the output-head work across 96 GPU lanes and the attention maximum reduction across 32 lanes.
- The tool parser skips the argument body until a call is complete. The HTTP relay sends a keepalive every 15 seconds of silence and reports interrupted streams without replaying partial tool calls.
- The vision path accepts images using the Inkling FP16 projector.

## Computer use

Each chat request can contain up to 16 images across its message history. Each image can be up to 1 MiB compressed, with a maximum width or height of 4,096 pixels. The HTTP request limit is 32 MiB.

For long rati0 computer-use sessions, load the included Pi extension (`pi -e ./pi/facthhorium-images.ts`). When a request would exceed 16 images, it replaces the oldest historical observation images with text markers in the outgoing request. It preserves the saved session, user attachments and the current batch of tool results. If those images alone exceed the limit, split them across requests.

## Setup

On Linux, install `libseccomp.so.2`, then install the runtime with `pipx install "hrx-loom[hf]==0.2.0"` using the [pinned hrx-system source](https://github.com/ROCm/hrx-system/tree/e9cc3017765171611afe609cb92744602cf7cace). This package provides `loom-serve`; put it on your `PATH`. From the repository root, fetch the tokenizer and model files.

```sh
curl -fL 'https://huggingface.co/loom-fun/unsloth-Inkling-2-Mini-loom/resolve/9b1eedd839ec3d648031f81256fd5fcdd4cf6c10/tokenizer.json' -o tokenizer.json
```

Fetch both model files from [unsloth/Inkling-2-Mini-GGUF](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF) into `parameter/`:

```sh
mkdir -p parameter
curl -fL 'https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/main/Inkling-2-Mini-UD-Q4_K_M.gguf' -o parameter/Inkling-2-Mini-UD-Q4_K_M.gguf
curl -fL 'https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/main/mmproj-F16.gguf' -o parameter/mmproj-F16.gguf
```

Start the server on a loopback port (the caller, such as llama-swap, supplies the port):

```sh
./serve-facthhorium.sh 8080
```

By default, logs are written to `logs/` beside the server. Set `FACTHHORIUM_LOG_DIR` to change the directory. Relay diagnostics and timing records use `llama-server.log`; Loom stderr uses `facthhorium-loom-serve.log`. For rati0’s speed card, set `FACTHHORIUM_LOG_DIR="$HOME/.local/share/ai-workspace/logs"` in the launcher environment.

## Decode speed

Measured on the same Z13 at temperature 1, top-k 0 and top-p 1, with 96 generated tokens. Times exclude prefill. The short rows are medians of three requests. Each longer row is one request per version.

| Input tokens | v0.1 tok/s | v0.2 tok/s |
|---:|---:|---:|
| 71 | 45.5 | 45.4 |
| 4,103 | 40.1 | 39.8 |
| 16,391 | 36.0 | 36.1 |
| 32,775 | 29.0 | 31.9 |
| 65,543 | 21.2 | 25.6 |

For single-token decode, the eight global attention passes can split the KV scan across 256 workgroups per KV head. Sliding-window attention and batched decode keep 64 splits. Each model pass retains its own KV history.

## External sources

The Loom programs derive from [loom-fun/unsloth-Inkling-2-Mini-loom](https://huggingface.co/loom-fun/unsloth-Inkling-2-Mini-loom/tree/9b1eedd839ec3d648031f81256fd5fcdd4cf6c10). Runtime `hrx-loom` is an external dependency from [ROCm/hrx-system](https://github.com/ROCm/hrx-system/tree/e9cc3017765171611afe609cb92744602cf7cace). Program generation used [loom-fun/loom-skills](https://github.com/loom-fun/loom-skills/tree/618f89e134ea7bdc579f01f2d1825622df12912d). See `licenses/` for notices.
