import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "data" / "projects.db"
FRONTEND_DIR = BASE_DIR / "frontend"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TIMEOUT = 15


def load_dotenv() -> dict:
    env_file = BASE_DIR / ".env"
    values = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_dotenv = load_dotenv()


def get_api_key() -> str:
    return (
        os.environ.get("DEEPSEEK_API_KEY")
        or _dotenv.get("DEEPSEEK_API_KEY")
        or os.environ.get("COMMONSENSE_API_KEY")
        or _dotenv.get("COMMONSENSE_API_KEY")
        or ""
    )


SMELL_THRESHOLDS = {
    "long_function_lines": 30,
    "long_params": 5,
    "deep_nesting": 4,
    "god_class_methods": 10,
    "god_class_lines": 300,
    "long_file_lines": 500,
    "long_line_chars": 100,
    "magic_number_repeat": 2,
    "duplicate_block_lines": 6,
    "duplicate_min_tokens": 40,
}

READABILITY_WEIGHTS = {
    "avg_function_length": 20,
    "avg_complexity": 20,
    "comment_ratio": 15,
    "docstring_coverage": 15,
    "naming_quality": 15,
    "nesting_depth": 10,
    "long_line_ratio": 5,
}
MAX_PROJECT_NAME_LEN = 60
MAX_DESCRIPTION_LEN = 200
MAX_UPLOAD_FILES = 200
MAX_SINGLE_FILE_SIZE = 5 * 1024 * 1024

TEST_SANDBOX = {
    "timeout": 60,
    "env_block": ("DEEPSEEK_API_KEY", "COMMONSENSE_API_KEY"),
    "extra_args": ["-p", "no:cacheprovider", "--tb=short", "-q"],
}

COMPLEXITY_BUCKETS = {"low": (0, 5), "medium": (6, 10), "high": (11, 20), "critical": (21, 9999)}
TYPE_HINTS_MIN_COVERAGE = 70.0
DOCSTRING_MIN_COVERAGE = 60.0
DUPLICATION_MIN_LINES = 6
CONFIG_FILE = BASE_DIR / "data" / "config.json"

_NUMERIC_FIELDS = {
    "type_hints_min_coverage": float,
    "docstring_min_coverage": float,
    "duplication_min_lines": int,
}


def load_user_config() -> None:
    """启动时从 data/config.json 加载用户自定义阈值，原地覆盖默认值。"""
    global TYPE_HINTS_MIN_COVERAGE, DOCSTRING_MIN_COVERAGE, DUPLICATION_MIN_LINES
    if not CONFIG_FILE.exists():
        return
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(data.get("smell_thresholds"), dict):
        SMELL_THRESHOLDS.update(data["smell_thresholds"])
    if isinstance(data.get("readability_weights"), dict):
        READABILITY_WEIGHTS.update(data["readability_weights"])
    for key, cast in _NUMERIC_FIELDS.items():
        if key in data:
            try:
                globals()[key] = cast(data[key])
            except (TypeError, ValueError):
                pass


def save_user_config() -> None:
    """将当前阈值持久化到 data/config.json。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "smell_thresholds": SMELL_THRESHOLDS,
        "readability_weights": READABILITY_WEIGHTS,
        "type_hints_min_coverage": TYPE_HINTS_MIN_COVERAGE,
        "docstring_min_coverage": DOCSTRING_MIN_COVERAGE,
        "duplication_min_lines": DUPLICATION_MIN_LINES,
    }
    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


load_user_config()