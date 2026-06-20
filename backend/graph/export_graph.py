import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from graph.abbr_graph import build_abbr_graph


graph = build_abbr_graph()

png_data = graph.get_graph().draw_mermaid_png()

output_path = Path(__file__).resolve().parent / "abbr_workflow.png"

with open(output_path, "wb") as f:
    f.write(png_data)

print(f"Graph exported to: {output_path}")