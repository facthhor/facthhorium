# Facthhorium

Facthhorium serves the Inkling-2-Mini GGUF through AMD Loom using the included Loom programs, model card, configuration, and a small OpenAI-compatible relay. It requires a compatible AMD GPU and the external Loom runtime. Model weights and runtime binaries are not included.

## Changes in this build

- Three-pass attention and MoE decode configuration for full-vocabulary sampling.
- Image input through the configured vision projector.
- The relay forwards long streaming requests and responses without buffering the full body, sends keepalives, and reports upstream stream failures.
- `loom-serve` is found on `PATH`; logs default to `./logs` and are created automatically. Set `FACTHHORIUM_LOG_DIR` to use another directory.

## Setup

Install `hrx-loom==0.2.0` using the upstream installation instructions. Put `loom-serve` on `PATH`. Fetch the pinned tokenizer into this directory:

```sh
curl -L 'https://huggingface.co/loom-fun/unsloth-Inkling-2-Mini-loom/resolve/9b1eedd839ec3d648031f81256fd5fcdd4cf6c10/tokenizer.json' -o tokenizer.json
```

Fetch both model files from [unsloth/Inkling-2-Mini-GGUF](https://huggingface.co/unsloth/Inkling-2-Mini-GGUF) into `parameter/`:

```sh
mkdir -p parameter
curl -L 'https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/main/Inkling-2-Mini-UD-Q4_K_M.gguf' -o parameter/Inkling-2-Mini-UD-Q4_K_M.gguf
curl -L 'https://huggingface.co/unsloth/Inkling-2-Mini-GGUF/resolve/main/mmproj-F16.gguf' -o parameter/mmproj-F16.gguf
```

Start the server on a loopback port (the caller, such as llama-swap, supplies the port):

```sh
./serve-facthhorium.sh 8080
```

## Benchmark

The attached `context-speed.png` summarizes the measured context-speed runs. `measurements.csv` and `method.md` contain the measurements and full settings. Results describe only those runs and the hardware recorded in the method.

## External sources

The Loom programs derive from [loom-fun/unsloth-Inkling-2-Mini-loom](https://huggingface.co/loom-fun/unsloth-Inkling-2-Mini-loom/tree/9b1eedd839ec3d648031f81256fd5fcdd4cf6c10). Runtime `hrx-loom` is an external dependency from [ROCm/hrx-system](https://github.com/ROCm/hrx-system/tree/e9cc3017765171611afe609cb92744602cf7cace). Program generation used [loom-fun/loom-skills](https://github.com/loom-fun/loom-skills/tree/618f89e134ea7bdc579f01f2d1825622df12912d). See `licenses/` for notices. The GGUF checkpoint and runtime are distributed separately under their upstream terms.
