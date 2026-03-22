import markdown
from pathlib import Path

MD_PATH = Path(__file__).parent / "trend_cards_dior_shanghai.md"
HTML_PATH = Path(__file__).parent / "trend_cards_dior_shanghai.html"

md_text = MD_PATH.read_text(encoding="utf-8")
body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: 'Georgia', serif;
    max-width: 820px;
    margin: 60px auto;
    padding: 0 40px 60px;
    background: #fff;
    color: #1a1a1a;
    line-height: 1.7;
  }}
  h1 {{ font-size: 1.6em; border-bottom: 2px solid #1a1a1a; padding-bottom: 10px; }}
  h2 {{ font-size: 1.2em; margin-top: 40px; color: #111; }}
  h3 {{ font-size: 1em; color: #333; }}
  code {{
    background: #f0f0f0;
    padding: 2px 7px;
    border-radius: 3px;
    font-size: 0.85em;
    font-family: monospace;
  }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 30px 0; }}
  strong {{ color: #000; }}
  p {{ margin: 8px 0; }}
  blockquote {{
    border-left: 3px solid #ccc;
    margin: 10px 0;
    padding-left: 16px;
    color: #555;
  }}
</style>
</head>
<body>
{body}
</body>
</html>"""

HTML_PATH.write_text(html, encoding="utf-8")
print(f"HTML saved to: {HTML_PATH}")
