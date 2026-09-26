"""Backend application runner for VibeShorts."""

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
