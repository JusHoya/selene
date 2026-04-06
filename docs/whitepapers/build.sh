#!/usr/bin/env bash
# ============================================================================
# SELENE White Paper Build System
# Generates PDF and DOCX from Markdown sources using Pandoc + XeLaTeX
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/template"
OUTPUT_DIR="$SCRIPT_DIR/output"

# Add tools to PATH (Windows/MSYS2)
export PATH="$PATH:/c/Users/hoyer/AppData/Local/Pandoc"
export PATH="$PATH:/c/Users/hoyer/AppData/Local/Programs/MiKTeX/miktex/bin/x64"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

mkdir -p "$OUTPUT_DIR"/{pdf,docx}

build_paper() {
    local dir="$1"
    local paper_dir="$SCRIPT_DIR/$dir"
    local md_file="$paper_dir/paper.md"

    if [ ! -f "$md_file" ]; then
        echo -e "${RED}SKIP${NC} $dir — no paper.md found"
        return 0
    fi

    local basename
    basename=$(basename "$dir")
    echo -e "${BLUE}BUILD${NC} $basename"

    # ── PDF via Pandoc + pdfLaTeX ──
    echo -n "  PDF... "
    (
        cd "$paper_dir"
        pandoc paper.md \
            --template="$TEMPLATE_DIR/selene.latex" \
            --pdf-engine=pdflatex \
            --number-sections \
            -V colorlinks=true \
            -o "$OUTPUT_DIR/pdf/${basename}.pdf" 2>/dev/null
    ) && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAIL${NC}"

    # ── DOCX via Pandoc ──
    echo -n "  DOCX... "
    local ref_docx="$TEMPLATE_DIR/reference.docx"
    local docx_args=()
    if [ -f "$ref_docx" ]; then
        docx_args+=(--reference-doc="$ref_docx")
    fi
    (
        cd "$paper_dir"
        pandoc paper.md \
            "${docx_args[@]}" \
            --number-sections \
            --toc \
            -o "$OUTPUT_DIR/docx/${basename}.docx" 2>/dev/null
    ) && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAIL${NC}"
}

echo "============================================"
echo " SELENE White Paper Build System"
echo "============================================"
echo ""

# Build specific paper or all
if [ "${1:-all}" = "all" ]; then
    for dir in "$SCRIPT_DIR"/[0-9][0-9]-*/; do
        [ -d "$dir" ] && build_paper "$(basename "$dir")"
    done
else
    build_paper "$1"
fi

echo ""
echo "============================================"
echo " Output: $OUTPUT_DIR/"
echo "============================================"
ls -la "$OUTPUT_DIR"/pdf/*.pdf 2>/dev/null || echo "  (no PDFs)"
ls -la "$OUTPUT_DIR"/docx/*.docx 2>/dev/null || echo "  (no DOCX)"
