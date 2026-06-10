# NCSU Financial Mathematics — Summer 2026

**Optimal Market Making for Cryptocurrency Options — The Avellaneda–Stoikov
Framework and its Extension to Options**

A 10-week summer research program. Week 1 is the introduction (delivered
last week); Weeks 2–10 are the technical curriculum. Industry mentor:
Dendi Suhubdy (Bitwyre). Guest practitioner: Fenni Kang (Coincall).

## Course documents

Each document is provided as Markdown (the editable source), a compilable
LaTeX file, Word, PDF, and a themed PowerPoint deck:

| Document | Source | Formats |
|----------|--------|---------|
| Syllabus | `syllabus.md` | `.tex` `.docx` `.pdf` `.pptx` |
| Tutor Handbook | `handbook.md` | `.tex` `.docx` `.pdf` `.pptx` |
| Problem Sets | `problem_sets.md` | `.tex` `.docx` `.pdf` `.pptx` |
| Solutions | `solutions.md` | `.tex` `.docx` `.pdf` `.pptx` |

`assets/ncsu_logo.png` is the NC State wordmark used on every document.
`latex/header.tex` maps the Unicode math symbols used in the text so the
LaTeX compiles on a stock TeX install. The `.pptx` decks use the NC State
theme (Wolfpack Red `#CC0000`, Arial) from
`OptimalMarketMaking_WeeklyUpdate_06_08.pptx`.

The original GLFT-centered materials were removed from the working tree to
avoid confusion; they remain available in git history (the initial commit)
if needed for reference.

### Weekly student presentations

`weekly_presentations/` holds a student-facing deck for each of the 10
weeks (Week 1 = introduction), as both a **PDF** (LaTeX Beamer) and a
**PPTX** (NC State theme). Regenerate with `python build_weekly.py`
followed by `pdflatex` on each `week*.tex`.

## Key design points

- **Avellaneda–Stoikov** is the central framework (GLFT removed). The
  advanced final week covers Avellaneda–Stoikov extensions (multi-asset,
  adverse selection, signal-driven, discrete-inventory, robust).
- **Problem sets are Python/PyTorch**; differentiation is implicit via
  autograd (students do not hand-roll AD).
- **Fast-computation week (Week 7) is C++**, exposed to Python via
  **`pybind11`**, taught explicitly; PyTorch autograd is the reference for
  Greeks.
- Milestones land at Weeks 5, 7, and 9.
- Fenni Kang (Coincall) guest sessions: taker strategies (Week 9) and
  corporate structured products (Week 10).

## Rebuilding the documents

```sh
# Word + LaTeX
for f in syllabus handbook problem_sets solutions; do
  pandoc "$f.md" -o "$f.docx"
  pandoc "$f.md" -s --include-in-header=latex/header.tex -o "$f.tex"
done

# PDF (compile the LaTeX; pdflatex or xelatex both work)
pdflatex syllabus.tex && pdflatex syllabus.tex   # twice for the TOC/refs

# PowerPoint decks (requires python-pptx)
python build_decks.py
```
