import os
import json
import pypdf
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

def compile_magazine():
    # Detect repository root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "schema.json")
    templates_dir = os.path.join(base_dir, "templates")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")
    output_pdf_path = os.path.join(output_dir, "Daily_Editorial_Magazine.pdf")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 1. Load Data
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Missing data file at: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. Render Template
    search_dirs = [templates_dir, base_dir]
    env = Environment(loader=FileSystemLoader(search_dirs))
    template = env.get_template("template.html")
    rendered_html = template.render(data=data)

    rendered_html_path = os.path.join(build_dir, "rendered_content.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # 3. Print HTML to PDF using Headless Chromium
    dynamic_pdf = os.path.join(build_dir, "dynamic_content.pdf")
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.pdf(
            path=dynamic_pdf,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    # 4. Merge Covers (Optional: skips gracefully if files do not exist yet)
    merger = pypdf.PdfMerger()
    
    front_cover = os.path.join(base_dir, "assets", "static_front_cover.pdf")
    back_cover = os.path.join(base_dir, "assets", "static_back_cover.pdf")

    if os.path.exists(front_cover):
        merger.append(front_cover)

    merger.append(dynamic_pdf)

    if os.path.exists(back_cover):
        merger.append(back_cover)

    merger.write(output_pdf_path)
    merger.close()
    print(f"✅ Magazine PDF generated successfully at: {output_pdf_path}")

if __name__ == "__main__":
    compile_magazine()
