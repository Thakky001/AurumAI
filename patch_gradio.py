"""
patch_gradio.py
───────────────
Fixes Gradio 4.44 incompatibility with Hugging Face Space Docker proxy.

Gradio 4.44 does a HEAD request to localhost after launch() to verify
accessibility. HF Space reverse proxy causes this to return HTTP 500,
which Gradio interprets as "localhost not accessible" and raises:
    ValueError: When localhost is not accessible, a shareable link must be created.

Fix: remove that raise so launch() continues normally.
The app is still accessible via the HF Space URL — the check is unnecessary.
"""

import re
import sys
from pathlib import Path
import gradio

blocks_path = Path(gradio.__file__).parent / "blocks.py"
src = blocks_path.read_text()

# Target the specific raise ValueError block
# Original code (Gradio 4.44, blocks.py ~line 2462):
#   if not networking.url_ok(self.local_url):
#       raise ValueError(
#           "When localhost is not accessible..."
#       )
pattern = r'(if not networking\.url_ok\(self\.local_url\):)\s*raise ValueError\([^)]*\)'
replacement = r'\1\n                pass  # patched: HF Space proxy causes false 500'

new_src, count = re.subn(pattern, replacement, src, flags=re.DOTALL)

if count == 0:
    # Fallback: simpler approach — replace raise ValueError line directly
    new_src = src.replace(
        'raise ValueError(\n'
        '                    "When localhost is not accessible',
        'pass  # patched\n'
        '                if False:  # patched\n'
        '                    raise ValueError(\n'
        '                    "When localhost is not accessible'
    )
    if new_src == src:
        print("WARNING: Pattern not found — gradio may already be patched or version changed")
        sys.exit(0)

blocks_path.write_text(new_src)
print(f"✅ gradio/blocks.py patched at {blocks_path}")