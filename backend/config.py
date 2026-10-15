import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("PIANXI_DATA", ROOT / "data")).resolve()
MEDIA = DATA / "media"
DB = DATA / "platform.sqlite3"
COOKIE_DIR = Path(os.environ.get("PIANXI_COOKIE_DIR", ROOT)).resolve()
ASR_PYTHON = os.environ.get(
    "PIANXI_ASR_PYTHON", str(Path.home() / ".conda/envs/douyin-qwen-asr/python.exe")
)
MAX_VIDEO_SECONDS = 900
MAX_BYTES = 500 * 1024 * 1024
ALLOW_FAKE_IP = os.environ.get("PIANXI_ALLOW_FAKE_IP") == "1"

MODEL_WEIGHTS = Path(
    os.environ.get("PIANXI_MODEL_WEIGHTS", "F:/Model-weights")
).resolve()
VISION_MODEL = Path(
    os.environ.get(
        "PIANXI_VISION_MODEL",
        str(
            MODEL_WEIGHTS / "Qwen3-VL-2B-Instruct"
            if (MODEL_WEIGHTS / "Qwen3-VL-2B-Instruct").exists()
            else ROOT / ".hf-cache/vision-model"
        ),
    )
).resolve()
ASR_MODEL = Path(
    os.environ.get(
        "PIANXI_ASR_MODEL",
        str(
            MODEL_WEIGHTS / "Qwen3-ASR-1.7B"
            if (MODEL_WEIGHTS / "Qwen3-ASR-1.7B").exists()
            else ROOT / ".hf-cache/hub/models--Qwen--Qwen3-ASR-1.7B"
        ),
    )
).resolve()
ALIGNER_MODEL = Path(
    os.environ.get(
        "PIANXI_ALIGNER_MODEL",
        str(
            MODEL_WEIGHTS / "Qwen3-ForcedAligner-0.6B"
            if (MODEL_WEIGHTS / "Qwen3-ForcedAligner-0.6B").exists()
            else ROOT / ".hf-cache/hub/models--Qwen--Qwen3-ForcedAligner-0.6B"
        ),
    )
).resolve()


def prepare():
    MEDIA.mkdir(parents=True, exist_ok=True)
