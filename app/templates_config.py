from pathlib import Path
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))