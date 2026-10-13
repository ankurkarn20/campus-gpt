"""Render the shared TikZ diagrams in docs/diagrams/ to PNG images for the slides.

Usage (from the repository root):
    python docs/slides/render_diagrams.py

Requires tectonic and pdftoppm on PATH. Images are written to docs/slides/build/.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
DIAGRAMS = ["architecture", "dfd-level1", "sequence-chat", "er-academic",
            "er-platform", "ipc-processes", "job-states", "gantt"]

TEMPLATE = r"""\documentclass[border=8pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[table]{xcolor}
\usepackage{tikz}
\usepackage{pgfgantt}
\input{../common/diagram-preamble}
\begin{document}
\input{../diagrams/%s}
\end{document}
"""


def render(name: str) -> Path:
    # The wrapper must sit next to docs/diagrams/ because the diagrams
    # \input each other with paths relative to the compile directory.
    tex = HERE / f"_render-{name}.tex"
    tex.write_text(TEMPLATE % name)
    try:
        subprocess.run(["tectonic", "-X", "compile", "--outdir", str(BUILD), tex.name],
                       cwd=HERE, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        sys.exit(f"tectonic failed for {name}:\n{e.stderr[-2000:]}")
    finally:
        tex.unlink()
    pdf = BUILD / f"_render-{name}.pdf"
    png_stem = BUILD / name
    subprocess.run(["pdftoppm", "-r", "300", "-png", "-singlefile", str(pdf), str(png_stem)],
                   check=True)
    pdf.unlink()
    return png_stem.with_suffix(".png")


if __name__ == "__main__":
    BUILD.mkdir(exist_ok=True)
    for name in DIAGRAMS:
        print("rendered", render(name).relative_to(HERE.parent.parent))
