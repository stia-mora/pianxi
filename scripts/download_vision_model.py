"""Run with the configured VLM Python environment on a new machine."""

import os
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(__file__).resolve().parents[1]
weights_dir = Path(os.environ.get("PIANXI_MODEL_WEIGHTS", "F:/Model-weights"))
target_dir = (
    weights_dir / "Qwen3-VL-2B-Instruct"
    if weights_dir.exists()
    else root / ".hf-cache/vision-model"
)

snapshot_download(
    "Qwen/Qwen3-VL-2B-Instruct",
    local_dir=str(target_dir),
    ignore_patterns=["*.md", ".gitattributes"],
    max_workers=4,
)
