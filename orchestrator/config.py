"""Settings shared by the worker and the trigger."""

import os
from pathlib import Path

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = "lifecycle"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
