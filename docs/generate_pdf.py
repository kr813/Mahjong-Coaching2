import re
import subprocess
from pathlib import Path
import markdown

docs_dir = Path(__file__).resolve().parent
md_path = docs_dir / "code_detail.md"
html_path = docs_dir / "code_detail.html"
pdf_path = docs_dir / "code_detail.pdf"

md_text = md_path.read_text(encoding="utf-8")

# ```mermaid ... ``` を <div class="mermaid"> ... </div> に置換
def replace_mermaid(match):
    code = match.group(1).strip()
    return f'<div class="mermaid">\n{code}\n</div>'

md_text_processed = re.sub(r"```mermaid\n(.*?)\n```", replace_mermaid, md_text, flags=re.DOTALL)

# Markdown -> HTML 変換
html_body = markdown.markdown(
    md_text_processed,
    extensions=["tables", "fenced_code", "toc", "attr_list", "def_list"]
)

full_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>Mahjong-Coaching2 バックエンド 詳細仕様書</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.8/dist/mermaid.min.js"></script>
<script>
    mermaid.initialize({{
        startOnLoad: true,
        theme: 'neutral',
        themeVariables: {{
            fontSize: '11px',
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Meiryo, sans-serif'
        }},
        flowchart: {{
            useMaxWidth: true,
            htmlLabels: true
        }},
        sequence: {{
            useMaxWidth: true,
            showSequenceNumbers: true,
            actorMargin: 15,
            messageMargin: 12,
            mirrorActors: false,
            width: 100
        }}
    }});

    window.addEventListener('load', () => {{
        const adjustSvg = () => {{
            const svgs = document.querySelectorAll('.mermaid svg');
            svgs.forEach(svg => {{
                svg.style.maxWidth = '100%';
                svg.style.height = 'auto';
                svg.removeAttribute('height');
            }});
        }};
        setTimeout(adjustSvg, 500);
        setTimeout(adjustSvg, 1500);
    }});
</script>
<style>
    @page {{
        size: A4;
        margin: 18mm 15mm 20mm 15mm;
        @bottom-right {{
            content: counter(page);
        }}
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, sans-serif;
        color: #1e293b;
        line-height: 1.65;
        font-size: 10.5pt;
        background: #ffffff;
        margin: 0;
        padding: 0;
    }}
    h1 {{
        font-size: 20pt;
        color: #0f172a;
        border-bottom: 3px solid #2563eb;
        padding-bottom: 8px;
        margin-top: 0;
        margin-bottom: 16px;
    }}
    h2 {{
        font-size: 14pt;
        color: #1e3a8a;
        border-bottom: 1.5px solid #cbd5e1;
        padding-bottom: 5px;
        margin-top: 24px;
        margin-bottom: 12px;
        page-break-after: avoid;
    }}
    h3 {{
        font-size: 12pt;
        color: #1e40af;
        margin-top: 18px;
        margin-bottom: 8px;
        page-break-after: avoid;
    }}
    h4 {{
        font-size: 11pt;
        color: #334155;
        margin-top: 14px;
        margin-bottom: 6px;
        page-break-after: avoid;
    }}
    p, li {{
        color: #334155;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 14px 0;
        font-size: 9.5pt;
        page-break-inside: avoid;
    }}
    th, td {{
        border: 1px solid #cbd5e1;
        padding: 7px 10px;
        text-align: left;
    }}
    th {{
        background: #f1f5f9;
        color: #0f172a;
        font-weight: 600;
    }}
    tr:nth-child(even) td {{
        background: #f8fafc;
    }}
    code {{
        font-family: Consolas, "Courier New", monospace;
        font-size: 9.5pt;
        background: #f1f5f9;
        color: #0f172a;
        padding: 2px 5px;
        border-radius: 4px;
        border: 1px solid #e2e8f0;
    }}
    pre {{
        background: #0f172a;
        color: #f8fafc;
        padding: 12px 14px;
        border-radius: 6px;
        overflow-x: auto;
        font-size: 9pt;
        line-height: 1.45;
        margin: 12px 0;
        page-break-inside: avoid;
    }}
    pre code {{
        background: transparent;
        color: inherit;
        padding: 0;
        border: none;
        font-size: inherit;
    }}
    .mermaid {{
        margin: 16px auto;
        text-align: center;
        page-break-inside: avoid;
        background: #fafafa;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 10px;
        box-sizing: border-box;
        width: 100%;
        max-width: 100%;
        overflow: hidden;
    }}
    .mermaid svg {{
        max-width: 100% !important;
        height: auto !important;
        display: block;
        margin: 0 auto;
    }}
    hr {{
        border: 0;
        height: 1px;
        background: #e2e8f0;
        margin: 24px 0;
    }}
    blockquote {{
        border-left: 4px solid #2563eb;
        margin: 12px 0;
        padding: 6px 14px;
        background: #eff6ff;
        color: #1e3a8a;
    }}
    .cover-badge {{
        display: inline-block;
        background: #2563eb;
        color: #ffffff;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 9pt;
        font-weight: bold;
        margin-bottom: 8px;
    }}
</style>
</head>
<body>
<div class="cover-badge">SYSTEM SPECIFICATION</div>
{html_body}
</body>
</html>
"""

html_path.write_text(full_html, encoding="utf-8")
print(f"Generated HTML: {html_path}")

browser_candidates = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

browser_exe = next((p for p in browser_candidates if Path(p).exists()), None)
if not browser_exe:
    raise RuntimeError("Neither Chrome nor Edge was found.")

file_url = html_path.as_uri()

cmd = [
    browser_exe,
    "--headless",
    "--disable-gpu",
    "--no-pdf-header-footer",
    "--run-all-compositor-stages-before-draw",
    "--virtual-time-budget=6000",
    f"--print-to-pdf={pdf_path}",
    file_url,
]

res = subprocess.run(cmd, capture_output=True, text=True)
if pdf_path.exists():
    print(f"Successfully generated PDF: {pdf_path} (Size: {pdf_path.stat().st_size} bytes)")
else:
    print(f"Failed to generate PDF. Stderr: {res.stderr}")
