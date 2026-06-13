"""
make_brand_v3.py — regenerate every brand export from ascent-mark-v3.svg.
Run from platform/static/brand:   python3 make_brand_v3.py
Requires: pip install cairosvg pillow
"""
import os
import re

import cairosvg

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = open(os.path.join(HERE, "ascent-mark-v3.svg")).read()
# strip the outer <svg> wrapper to embed the artwork in compositions
INNER = re.sub(r"^.*?<svg[^>]*>", "", MARK, flags=re.S)
INNER = re.sub(r"</svg>\s*$", "", INNER, flags=re.S)

FONT = "DejaVu Sans"          # present on every Linux build box; clean + neutral


def render(svg, out, w, h):
    cairosvg.svg2png(bytestring=svg.encode(), write_to=os.path.join(HERE, out),
                     output_width=w, output_height=h)
    print(f"  {out}  {w}x{h}")


def mark_only(size_px, out):
    render(MARK, out, size_px, size_px)


def framed_icon(out, size_px):
    """App-icon: near-black rounded square, warm vignette, gold ring, mark."""
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<defs>
  <radialGradient id="vig" cx="0.5" cy="0.42" r="0.75">
    <stop offset="0" stop-color="#1c160c"/>
    <stop offset="0.65" stop-color="#0d0b07"/>
    <stop offset="1" stop-color="#070604"/>
  </radialGradient>
  <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#f0d489"/><stop offset="0.5" stop-color="#a87e26"/>
    <stop offset="1" stop-color="#6e5316"/>
  </linearGradient>
</defs>
<rect x="0" y="0" width="1024" height="1024" rx="224" fill="url(#vig)"/>
<rect x="26" y="26" width="972" height="972" rx="206" fill="none" stroke="url(#ring)" stroke-width="7" opacity="0.85"/>
<rect x="40" y="40" width="944" height="944" rx="196" fill="none" stroke="#3c2c0c" stroke-width="3" opacity="0.7"/>
<g transform="translate(512,532) scale(0.62) translate(-512,-512)">{INNER}</g>
</svg>'''
    render(svg, out, size_px, size_px)


def banner(out, W, H, title="ASCENT TERMINAL", sub="PROOF, NOT PROMISES"):
    """Wide layouts: dark field, faint data-flow diagonals, mark + set type."""
    mark_h = int(H * 0.66)
    mark_x = int(W * 0.055)
    mark_y = (H - mark_h) // 2
    tx = mark_x + mark_h + int(H * 0.18)
    title_size = int(H * 0.215)
    sub_size = int(H * 0.082)
    ty = int(H * 0.52)
    sy = int(H * 0.70)
    lines = "".join(
        f'<path d="M{int(W*0.0+i*W*0.09)} {H} L{int(W*0.12+i*W*0.09)} 0" '
        f'stroke="#d9b54a" stroke-width="1.5" opacity="0.05"/>' for i in range(14))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
<defs>
  <radialGradient id="bgv" cx="0.22" cy="0.4" r="1">
    <stop offset="0" stop-color="#161208"/><stop offset="0.6" stop-color="#0b0a07"/>
    <stop offset="1" stop-color="#060504"/>
  </radialGradient>
  <linearGradient id="ttl" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#f6e6ae"/><stop offset="0.55" stop-color="#d9b54a"/>
    <stop offset="1" stop-color="#a87e26"/>
  </linearGradient>
</defs>
<rect width="{W}" height="{H}" fill="url(#bgv)"/>
{lines}
<g transform="translate({mark_x},{mark_y}) scale({mark_h/1024})">{INNER}</g>
<text x="{tx}" y="{ty}" font-family="{FONT}" font-weight="bold" font-size="{title_size}"
      letter-spacing="{int(title_size*0.16)}" fill="url(#ttl)">{title}</text>
<text x="{tx}" y="{sy}" font-family="{FONT}" font-size="{sub_size}"
      letter-spacing="{int(sub_size*0.55)}" fill="#9d957f">{sub}</text>
</svg>'''
    render(svg, out, W, H)


def wordmark(out_png, out_svg):
    W, H = 1600, 420
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
<defs>
  <linearGradient id="ttl" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#f6e6ae"/><stop offset="0.55" stop-color="#d9b54a"/>
    <stop offset="1" stop-color="#a87e26"/>
  </linearGradient>
</defs>
<g transform="translate(20,30) scale(0.36)">{INNER}</g>
<text x="430" y="226" font-family="{FONT}" font-weight="bold" font-size="84"
      letter-spacing="11" fill="url(#ttl)">ASCENT TERMINAL</text>
<text x="434" y="296" font-family="{FONT}" font-size="40"
      letter-spacing="20" fill="#9d957f">CLIMB WITH CLARITY</text>
</svg>'''
    open(os.path.join(HERE, out_svg), "w").write(svg)
    render(svg, out_png, W, H)
    print(f"  {out_svg}")


print("Rendering brand v3 exports:")
mark_only(1024, "ascent-logo-mark-1024.png")
mark_only(1024, "ascent-logo-mark-dark-1024.png")     # gold-on-transparent works on dark
mark_only(128, "ascent-icon-128.png")
framed_icon("app-icon-ios-1024.png", 1024)
framed_icon("app-icon-play-512.png", 512)
framed_icon("discord-server-icon-512.png", 512)
banner("discord-banner-1200x300.png", 1200, 300)
banner("patreon-cover-1600x400.png", 1600, 400)
banner("play-feature-1024x500.png", 1024, 500)
wordmark("ascent-wordmark.png", "ascent-wordmark.svg")
# keep ascent-mark.svg as the canonical mark file too
open(os.path.join(HERE, "ascent-mark.svg"), "w").write(MARK)
print("  ascent-mark.svg (canonical, replaced with v3)")
print("Done.")
