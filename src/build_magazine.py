import os
import json
import pypdf
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

def compile_magazine(json_path, static_cover_path, output_pdf_path):
    os.makedirs("build", exist_ok=True)
    os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)

    # 1. Load structured JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. Render Jinja2 Template
    env = Environment(loader=FileSystemLoader("."))
    template = env.get_template("template.html")
    rendered_html = template.render(data=data)

    rendered_html_path = os.path.abspath("build/rendered_content.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # 3. Compile PDF via Headless Chromium (Skia Rendering)
    intermediate_pdf = "build/dynamic_pages.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.pdf(
            path=intermediate_pdf,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    # 4. Merge with Static Covers
    merger = pypdf.PdfMerger()
    if os.path.exists(static_cover_path):
        merger.append(static_cover_path)
    merger.append(intermediate_pdf)
    merger.write(output_pdf_path)
    merger.close()

if __name__ == "__main__":
    compile_magazine(
        json_path="schema.json",
        static_cover_path="assets/static_front_cover.pdf",
        output_pdf_path="output/19-Aug-2026_Magazine.pdf"
    )
