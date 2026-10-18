"""Validate configuration files without cloud clients or paid calls."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.integrations import check_integrations

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--backend-env", type=Path)
parser.add_argument("--frontend-env", type=Path)
parser.add_argument("--image-only", action="store_true", help="Check sign-in and image generation only")
args = parser.parse_args()
result = check_integrations(args.backend_env, args.frontend_env, include_media=not args.image_only)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["ready"] else 1)
