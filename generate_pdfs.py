"""Generate PDFs from product markdown files."""
import re
from pathlib import Path
from fpdf import FPDF


PRODUCTS_DIR = Path(__file__).parent / "products"
OUTPUT_DIR = Path(__file__).parent / "app" / "downloads"

UNICODE_REPLACEMENTS = {
    "\u2014": "-",   # em dash
    "\u2013": "-",   # en dash
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2026": "...", # ellipsis
    "\u2022": "-",   # bullet
    "\u2192": "->",  # right arrow
    "\u2713": "v",   # check mark
    "\u00a0": " ",   # non-breaking space
}


def sanitize(text: str) -> str:
    for char, replacement in UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    # Remove any remaining non-latin-1 characters
    return text.encode("latin-1", errors="replace").decode("latin-1")

PRODUCT_TITLES = {
    "01-ai-income-playbook.md": "AI Income Playbook",
    "02-50-ai-prompts.md": "50 Plug-and-Play AI Prompts",
    "03-freelancer-templates.md": "Freelancer Quick-Start Templates",
    "04-digital-product-launch-guide.md": "Digital Product Launch Guide",
    "05-ai-tools-cheat-sheet.md": "AI Tools Cheat Sheet",
    "06-30-day-action-plan.md": "30-Day Action Plan",
}


class ProductPDF(FPDF):
    def __init__(self, title: str):
        super().__init__()
        self.product_title = title

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"AI Income Blueprint  |  {self.product_title}", align="C")
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def make_cover(pdf: ProductPDF, title: str, subtitle: str = ""):
    pdf.add_page()
    pdf.ln(60)
    pdf.set_font("Helvetica", "B", 32)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 14, title, align="C")
    if subtitle:
        pdf.ln(8)
        pdf.set_font("Helvetica", "", 16)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 10, subtitle, align="C")
    pdf.ln(20)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(108, 92, 231)
    pdf.cell(0, 10, "AI Income Blueprint", align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 8, "aicashstarterkit.com", align="C")


def render_md_to_pdf(md_path: Path, out_path: Path, title: str):
    text = md_path.read_text(encoding="utf-8")
    text = sanitize(text)
    lines = text.split("\n")

    # Extract subtitle from first ## heading
    subtitle = ""
    for line in lines:
        if line.startswith("## ") and not subtitle:
            subtitle = line.lstrip("# ").strip()
            break

    pdf = ProductPDF(title)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    make_cover(pdf, title, subtitle)
    pdf.add_page()

    skip_first_h1 = True
    skip_first_h2 = True
    in_list = False
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            if in_code_block:
                pdf.ln(3)
            else:
                pdf.ln(3)
            continue

        # Render code block lines
        if in_code_block:
            pdf.set_font("Courier", "", 10)
            pdf.set_text_color(80, 80, 80)
            pdf.set_x(pdf.l_margin + 10)
            pdf.multi_cell(0, 6, stripped if stripped else " ")
            continue

        # Skip horizontal rules
        if stripped == "---":
            pdf.ln(4)
            continue

        # H1
        if stripped.startswith("# ") and not stripped.startswith("## "):
            if skip_first_h1:
                skip_first_h1 = False
                continue
            pdf.ln(8)
            pdf.set_font("Helvetica", "B", 22)
            pdf.set_text_color(40, 40, 40)
            heading = stripped.lstrip("# ").strip()
            pdf.multi_cell(0, 10, heading)
            pdf.ln(4)
            continue

        # H2
        if stripped.startswith("## "):
            if skip_first_h2:
                skip_first_h2 = False
                continue
            pdf.ln(6)
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(50, 50, 50)
            heading = stripped.lstrip("# ").strip()
            pdf.multi_cell(0, 9, heading)
            pdf.ln(3)
            continue

        # H3
        if stripped.startswith("### "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(60, 60, 60)
            heading = stripped.lstrip("# ").strip()
            pdf.multi_cell(0, 8, heading)
            pdf.ln(2)
            continue

        # Bold line (like **What:** or **How to start:**)
        if stripped.startswith("**") and ":**" in stripped:
            pdf.ln(3)
            match = re.match(r"\*\*(.+?):\*\*\s*(.*)", stripped)
            if match:
                label, rest = match.group(1), match.group(2)
                if rest:
                    pdf.set_font("Helvetica", "B", 11)
                    pdf.set_text_color(40, 40, 40)
                    pdf.multi_cell(0, 7, f"{label}: {rest}")
                else:
                    pdf.set_font("Helvetica", "B", 11)
                    pdf.set_text_color(40, 40, 40)
                    pdf.multi_cell(0, 7, f"{label}:")
            else:
                clean = stripped.replace("**", "")
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(40, 40, 40)
                pdf.multi_cell(0, 7, clean)
            continue

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(60, 60, 60)
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
            pdf.set_x(pdf.l_margin + 8)
            pdf.multi_cell(0, 7, clean)
            in_list = True
            continue

        # Bullet list
        if stripped.startswith("- "):
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(60, 60, 60)
            content = stripped[2:]
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", content)
            pdf.set_x(pdf.l_margin + 8)
            pdf.multi_cell(0, 7, f"-  {clean}")
            in_list = True
            continue

        # Empty line
        if not stripped:
            if in_list:
                in_list = False
                pdf.ln(2)
            else:
                pdf.ln(4)
            continue

        # Regular paragraph
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(60, 60, 60)
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        clean = re.sub(r"\*(.+?)\*", r"\1", clean)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 7, clean)
        in_list = False

    pdf.output(str(out_path))
    print(f"  Generated: {out_path.name} ({pdf.page_no()} pages)")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating PDFs...")
    for filename, title in PRODUCT_TITLES.items():
        md_path = PRODUCTS_DIR / filename
        if not md_path.exists():
            print(f"  Skipping {filename} (not found)")
            continue
        out_name = filename.replace(".md", ".pdf")
        out_path = OUTPUT_DIR / out_name
        render_md_to_pdf(md_path, out_path, title)
    print("Done!")


if __name__ == "__main__":
    main()
