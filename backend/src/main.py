import sys
from pathlib import Path

# Ensure project root is in python module search path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import uvicorn
from src.api.main import app
from src.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
