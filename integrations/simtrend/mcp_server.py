from pathlib import Path
import os

os.chdir(Path(__file__).resolve().parent)

from simtrend_app.mcp_server import main

if __name__ == "__main__":
    main()
