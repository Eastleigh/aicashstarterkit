"""Generate branded PDFs from product markdown files."""
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

# Brand colors
BRAND_PURPLE = (108, 92, 231)
BRAND_DARK = (10, 10, 15)
BRAND_SURFACE = (18, 18, 26)
BRAND_TEXT = (50, 50, 60)
BRAND_HEADING = (30, 30, 40)
BRAND_MUTED = (130, 130, 145)
BRAND_GREEN = (0, 214, 143)
BRAND_ACCENT_LIGHT = (240, 238, 255)


def sanitize(text: str) -> str:
    for char, replacement in UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


PRODUCT_TITLES = {
    "01-ai-income-playbook.md": "AI Income Playbook",
    "02-50-ai-prompts.md": "50 Plug-and-Play AI Prompts",
    "03-freelancer-templates.md": "Freelancer Quick-Start Templates",
    "04-digital-product-launch-guide.md": "Digital Product Launch Guide",
    "05-ai-tools-cheat-sheet.md": "AI Tools Cheat Sheet",
    "06-30-day-action-plan.md": "30-Day Action Plan",
}

PRODUCT_SUBTITLES = {
    "01-ai-income-playbook.md": "Your step-by-step path to earning with AI",
    "02-50-ai-prompts.md": "Ready-to-use prompts for real results",
    "03-freelancer-templates.md": "Templates to land your first AI clients",
    "04-digital-product-launch-guide.md": "Launch and sell digital products with AI",
    "05-ai-tools-cheat-sheet.md": "The essential tools every AI earner needs",
    "06-30-day-action-plan.md": "Your daily roadmap from zero to first income",
}

PRODUCT_NUMBERS = {
    "01-ai-income-playbook.md": "01",
    "02-50-ai-prompts.md": "02",
    "03-freelancer-templates.md": "03",
    "04-digital-product-launch-guide.md": "04",
    "05-ai-tools-cheat-sheet.md": "05",
    "06-30-day-action-plan.md": "06",
}


class ProductPDF(FPDF):
    def __init__(self, title: str):
        super().__init__()
        self.product_title = title
        self._on_cover = False

    def header(self):
        if self.page_no() <= 2:
            return
        # Thin accent line at top
        self.set_draw_color(*BRAND_PURPLE)
        self.set_line_width(0.5)
        self.line(10, 8, 200, 8)
        self.ln(4)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*BRAND_MUTED)
        self.cell(95, 6, "AI Income Blueprint", align="L")
        self.cell(95, 6, self.product_title, align="R")
        self.ln(10)

    def footer(self):
        if self._on_cover:
            return
        self.set_y(-18)
        # Thin line above footer
        self.set_draw_color(220, 220, 230)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*BRAND_MUTED)
        self.cell(95, 6, "aicashstarterkit.com", align="L")
        self.cell(95, 6, f"Page {self.page_no() - 1}", align="R")


def make_cover(pdf: ProductPDF, title: str, subtitle: str, number: str):
    """Create a professional branded cover page."""
    pdf._on_cover = True
    pdf.add_page()

    # Dark background
    pdf.set_fill_color(*BRAND_DARK)
    pdf.rect(0, 0, 210, 297, "F")

    # Accent gradient stripe at top
    pdf.set_fill_color(*BRAND_PURPLE)
    pdf.rect(0, 0, 210, 6, "F")

    # Secondary accent line
    pdf.set_fill_color(168, 85, 247)  # lighter purple
    pdf.rect(0, 6, 210, 2, "F")

    # "AI INCOME BLUEPRINT" brand label
    pdf.ln(35)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*BRAND_PURPLE)
    pdf.cell(0, 8, "AI INCOME BLUEPRINT", align="C")
    pdf.ln(12)

    # Decorative line
    line_y = pdf.get_y()
    pdf.set_draw_color(*BRAND_PURPLE)
    pdf.set_line_width(0.5)
    pdf.line(70, line_y, 140, line_y)
    pdf.ln(16)

    # Resource number badge
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(168, 85, 247)
    pdf.cell(0, 8, f"RESOURCE {number} OF 06", align="C")
    pdf.ln(20)

    # Main title
    pdf.set_font("Helvetica", "B", 34)
    pdf.set_text_color(232, 232, 237)
    pdf.multi_cell(0, 16, title, align="C")
    pdf.ln(10)

    # Subtitle
    if subtitle:
        pdf.set_font("Helvetica", "", 15)
        pdf.set_text_color(*BRAND_MUTED)
        pdf.multi_cell(0, 9, subtitle, align="C")

    # Bottom section
    pdf.set_y(240)

    # Decorative line
    pdf.set_draw_color(40, 40, 55)
    pdf.set_line_width(0.3)
    pdf.line(30, pdf.get_y(), 180, pdf.get_y())
    pdf.ln(12)

    # Bottom info
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*BRAND_MUTED)
    pdf.cell(0, 7, "Make Your First $300 With AI", align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 100)
    pdf.cell(0, 7, "aicashstarterkit.com", align="C")

    pdf._on_cover = False


def make_toc_page(pdf: ProductPDF, headings: list[tuple[str, int]]):
    """Create a table of contents page for documents with many sections."""
    if len(headings) < 3:
        return

    pdf.add_page()
    pdf.ln(8)

    # Light accent bar
    pdf.set_fill_color(*BRAND_ACCENT_LIGHT)
    pdf.rect(10, pdf.get_y() - 2, 190, 18, "F")

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*BRAND_HEADING)
    pdf.cell(0, 14, "Table of Contents", align="L")
    pdf.ln(20)

    for i, (heading, level) in enumerate(headings):
        indent = 0 if level == 2 else 8
        font_style = "B" if level == 2 else ""
        font_size = 11 if level == 2 else 10
        text_color = BRAND_HEADING if level == 2 else BRAND_TEXT

        pdf.set_font("Helvetica", font_style, font_size)
        pdf.set_text_color(*text_color)
        pdf.set_x(pdf.l_margin + indent)

        # Number prefix for H2s
        if level == 2:
            pdf.set_text_color(*BRAND_PURPLE)
            pdf.cell(8, 8, f"{i + 1}.", align="L")
            pdf.set_text_color(*text_color)
            pdf.cell(0, 8, heading)
        else:
            pdf.cell(0, 7, f"   {heading}")
        pdf.ln(3 if level == 2 else 2)

    pdf.ln(8)


def render_md_to_pdf(md_path: Path, out_path: Path, title: str, subtitle: str, number: str):
    text = md_path.read_text(encoding="utf-8")
    text = sanitize(text)
    lines = text.split("\n")

    # Collect headings for TOC
    headings: list[tuple[str, int]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            headings.append((stripped.lstrip("# ").strip(), 2))
        elif stripped.startswith("### "):
            headings.append((stripped.lstrip("# ").strip(), 3))

    # Skip first H2 in TOC (it's the subtitle, already on cover)
    if headings and headings[0][1] == 2:
        headings = headings[1:]

    pdf = ProductPDF(title)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=22)

    make_cover(pdf, title, subtitle, number)
    make_toc_page(pdf, headings)
    pdf.add_page()

    skip_first_h1 = True
    skip_first_h2 = True
    in_list = False
    in_code_block = False
    h2_count = 0

    for line in lines:
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            if in_code_block:
                pdf.ln(4)
                # Light background for code block
                code_y = pdf.get_y()
                pdf.set_fill_color(245, 245, 250)
                pdf.rect(pdf.l_margin + 6, code_y, 180, 4, "F")
            else:
                pdf.ln(4)
            continue

        # Render code block lines
        if in_code_block:
            # Code block background
            code_y = pdf.get_y()
            pdf.set_fill_color(245, 245, 250)
            pdf.rect(pdf.l_margin + 6, code_y, 180, 7, "F")
            pdf.set_font("Courier", "", 9)
            pdf.set_text_color(70, 70, 80)
            pdf.set_x(pdf.l_margin + 12)
            pdf.multi_cell(0, 6, stripped if stripped else " ")
            continue

        # Skip horizontal rules — render as styled divider
        if stripped == "---":
            pdf.ln(6)
            y = pdf.get_y()
            pdf.set_draw_color(220, 220, 230)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, y, 200, y)
            pdf.ln(6)
            continue

        # H1
        if stripped.startswith("# ") and not stripped.startswith("## "):
            if skip_first_h1:
                skip_first_h1 = False
                continue
            pdf.ln(10)
            pdf.set_font("Helvetica", "B", 24)
            pdf.set_text_color(*BRAND_HEADING)
            heading = stripped.lstrip("# ").strip()
            pdf.multi_cell(0, 12, heading)
            # Accent underline
            y = pdf.get_y() + 2
            pdf.set_draw_color(*BRAND_PURPLE)
            pdf.set_line_width(0.8)
            pdf.line(pdf.l_margin, y, pdf.l_margin + 40, y)
            pdf.ln(6)
            continue

        # H2
        if stripped.startswith("## "):
            if skip_first_h2:
                skip_first_h2 = False
                continue
            h2_count += 1
            pdf.ln(8)

            # Section number + heading
            heading = stripped.lstrip("# ").strip()
            pdf.set_font("Helvetica", "B", 17)
            pdf.set_text_color(*BRAND_PURPLE)
            num_w = pdf.get_string_width(f"{h2_count}.") + 4
            pdf.cell(num_w, 10, f"{h2_count}.")
            pdf.set_text_color(*BRAND_HEADING)
            pdf.multi_cell(0, 10, heading)

            # Thin accent line under heading
            y = pdf.get_y() + 1
            pdf.set_draw_color(*BRAND_PURPLE)
            pdf.set_line_width(0.4)
            pdf.line(pdf.l_margin, y, pdf.l_margin + 50, y)
            pdf.ln(5)
            continue

        # H3
        if stripped.startswith("### "):
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*BRAND_HEADING)
            heading = stripped.lstrip("# ").strip()
            pdf.multi_cell(0, 8, heading)
            pdf.ln(3)
            continue

        # Bold line (like **What:** or **How to start:**)
        if stripped.startswith("**") and ":**" in stripped:
            pdf.ln(3)
            match = re.match(r"\*\*(.+?):\*\*\s*(.*)", stripped)
            if match:
                label, rest = match.group(1), match.group(2)
                # Accent-colored label
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(*BRAND_PURPLE)
                label_w = pdf.get_string_width(f"{label}: ") + 2
                pdf.cell(label_w, 7, f"{label}: ")
                if rest:
                    pdf.set_font("Helvetica", "", 11)
                    pdf.set_text_color(*BRAND_TEXT)
                    pdf.multi_cell(0, 7, rest)
                else:
                    pdf.ln(7)
            else:
                clean = stripped.replace("**", "")
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(*BRAND_HEADING)
                pdf.multi_cell(0, 7, clean)
            continue

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(*BRAND_TEXT)
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
            # Extract number and content
            num_match = re.match(r"^(\d+\.)\s+(.*)", clean)
            if num_match:
                num_str, content = num_match.group(1), num_match.group(2)
                pdf.set_x(pdf.l_margin + 6)
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(*BRAND_PURPLE)
                num_w = pdf.get_string_width(num_str) + 3
                pdf.cell(num_w, 7, num_str)
                pdf.set_font("Helvetica", "", 11)
                pdf.set_text_color(*BRAND_TEXT)
                pdf.multi_cell(0, 7, content)
            else:
                pdf.set_x(pdf.l_margin + 6)
                pdf.multi_cell(0, 7, clean)
            in_list = True
            continue

        # Bullet list
        if stripped.startswith("- "):
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(*BRAND_TEXT)
            content = stripped[2:]
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", content)
            pdf.set_x(pdf.l_margin + 8)
            # Purple bullet marker
            pdf.set_text_color(*BRAND_PURPLE)
            pdf.cell(6, 7, ">")
            pdf.set_text_color(*BRAND_TEXT)
            pdf.multi_cell(0, 7, f" {clean}")
            in_list = True
            continue

        # Empty line
        if not stripped:
            if in_list:
                in_list = False
                pdf.ln(3)
            else:
                pdf.ln(5)
            continue

        # Regular paragraph
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(*BRAND_TEXT)
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        clean = re.sub(r"\*(.+?)\*", r"\1", clean)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 7, clean)
        in_list = False

    # Final page — branded footer
    pdf.add_page()
    pdf.ln(40)

    pdf.set_fill_color(*BRAND_ACCENT_LIGHT)
    pdf.rect(20, pdf.get_y() - 5, 170, 70, "F")

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*BRAND_PURPLE)
    pdf.cell(0, 12, "Ready to Take Action?", align="C")
    pdf.ln(14)

    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*BRAND_TEXT)
    pdf.multi_cell(0, 8, "This is one of 6 resources in the AI Income Blueprint.", align="C")
    pdf.ln(2)
    pdf.multi_cell(0, 8, "Use them together to build your first AI income stream.", align="C")
    pdf.ln(12)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*BRAND_PURPLE)
    pdf.cell(0, 8, "aicashstarterkit.com", align="C")

    pdf.output(str(out_path))
    print(f"  Generated: {out_path.name} ({pdf.page_no()} pages)")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating branded PDFs...")
    for filename, title in PRODUCT_TITLES.items():
        md_path = PRODUCTS_DIR / filename
        if not md_path.exists():
            print(f"  Skipping {filename} (not found)")
            continue
        out_name = filename.replace(".md", ".pdf")
        out_path = OUTPUT_DIR / out_name
        subtitle = PRODUCT_SUBTITLES.get(filename, "")
        number = PRODUCT_NUMBERS.get(filename, "01")
        render_md_to_pdf(md_path, out_path, title, subtitle, number)
    print("Done!")


if __name__ == "__main__":
    main()
