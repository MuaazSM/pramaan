"""Light-theme print CSS for reports/certificates (references/BRAND.md §3,
§10; references/tokens.css's ``[data-theme="light"]`` values, inlined here
since WeasyPrint/Playwright render a standalone HTML string with no access
to the web app's stylesheet pipeline).
"""

from __future__ import annotations

from pramaan_reporting.assets import GEIST_MONO_FILE, GEIST_SANS_FILE, font_data_uri

# references/tokens.css: [data-theme="light"] + shared brand/semantic tokens.
INK_900 = "#0B0D12"
INK_400 = "#5B6479"
INK_300 = "#8A93A6"
INK_50 = "#F3F5F8"
BRAND_600 = "#5451D6"
LINE = "rgba(11,13,18,0.14)"
OK = "#0E9E86"  # darkened from --ok #2BD4B4 for AA contrast on white
WARN = "#B8790A"  # darkened from --warn #F5B041
DANGER = "#C23237"  # darkened from --danger #F2555A
AI = "#6E4FD1"  # darkened from --ai #B18CFF


def print_css() -> str:
    sans_uri = font_data_uri(GEIST_SANS_FILE)
    mono_uri = font_data_uri(GEIST_MONO_FILE)
    return f"""
@font-face {{
  font-family: "Geist Sans";
  src: url("{sans_uri}") format("woff2");
  font-weight: 100 900;
  font-style: normal;
}}
@font-face {{
  font-family: "Geist Mono";
  src: url("{mono_uri}") format("woff2");
  font-weight: 100 900;
  font-style: normal;
}}
@page {{
  size: A4;
  margin: 22mm 16mm 20mm 16mm;
  @bottom-left {{
    content: "Pramaan \\2014 " string(case-id) " \\2014  report " string(report-hash);
    font-family: "Geist Mono";
    font-size: 8pt;
    color: {INK_400};
  }}
  @bottom-right {{
    content: "Page " counter(page) " of " counter(pages);
    font-family: "Geist Sans";
    font-size: 8pt;
    color: {INK_400};
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: "Geist Sans", sans-serif;
  font-size: 10.5pt;
  line-height: 1.5;
  color: {INK_900};
  background: #ffffff;
  margin: 0;
}}
/* These two elements exist only to feed the @page running header/footer
   via CSS string-set — they must stay in the normal box tree
   (display:none stops WeasyPrint from evaluating string-set at all) but
   must never be visible inline on page 1. */
.case-id-marker, .report-hash-marker {{
  position: absolute;
  visibility: hidden;
  height: 0;
  width: 0;
  overflow: hidden;
  font-size: 0;
  line-height: 0;
}}
.case-id-marker {{ string-set: case-id content(); }}
.report-hash-marker {{ string-set: report-hash content(); }}
h1, h2, h3 {{ font-weight: 600; letter-spacing: -0.01em; margin: 0 0 8px 0; }}
h1 {{ font-size: 22pt; }}
h2 {{
  font-size: 13pt;
  margin-top: 22px;
  border-bottom: 1px solid {LINE};
  padding-bottom: 4px;
}}
h3 {{ font-size: 11pt; margin-top: 14px; }}
p {{ margin: 4px 0; }}
.mono {{
  font-family: "Geist Mono", monospace;
  font-variant-numeric: tabular-nums;
  word-break: break-all;
  overflow-wrap: anywhere;
}}
.muted {{ color: {INK_400}; }}
.small {{ font-size: 8.5pt; }}
table {{ width: 100%; border-collapse: collapse; margin: 6px 0 12px 0; }}
th, td {{
  text-align: left;
  padding: 4px 6px;
  border-bottom: 1px solid {LINE};
  vertical-align: top;
}}
th {{
  font-size: 8.5pt;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: {INK_400};
  font-weight: 600;
}}
td.mono, th.mono {{ font-family: "Geist Mono", monospace; font-size: 8.5pt; }}
.cover {{ text-align: left; padding-top: 40px; }}
.wordmark {{ font-size: 28pt; font-weight: 600; letter-spacing: -0.02em; color: {INK_900}; }}
.wordmark .dot {{ color: {BRAND_600}; }}
.tagline {{ color: {INK_400}; margin-top: 2px; }}
.integrity-box {{
  margin-top: 28px;
  padding: 14px 16px;
  border: 1px solid {LINE};
  border-radius: 10px;
  background: {INK_50};
}}
.integrity-box .row {{
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin: 3px 0;
}}
.integrity-box .row > span {{ min-width: 0; }}
.integrity-box .row > span.mono {{ text-align: right; }}
.chip {{
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 8.5pt;
  font-weight: 600;
}}
.chip-ok {{ background: rgba(14,158,134,0.12); color: {OK}; }}
.chip-warn {{ background: rgba(184,121,10,0.12); color: {WARN}; }}
.chip-danger {{ background: rgba(194,50,55,0.12); color: {DANGER}; }}
.chip-ai {{ background: rgba(110,79,209,0.12); color: {AI}; }}
.tier-badge {{
  font-family: "Geist Mono", monospace;
  font-size: 8pt;
  padding: 1px 5px;
  border: 1px solid {LINE};
  border-radius: 4px;
}}
.limitations li {{ margin-bottom: 6px; }}
.notice {{
  border: 1px solid {LINE};
  border-left: 3px solid {BRAND_600};
  padding: 8px 12px;
  border-radius: 4px;
  background: {INK_50};
  font-size: 9pt;
  margin: 10px 0;
}}
.sig-line {{
  margin-top: 34px;
  border-top: 1px solid {INK_900};
  width: 60%;
  padding-top: 4px;
  font-size: 8.5pt;
  color: {INK_400};
}}
.thumbs {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }}
.thumb {{ width: 120px; }}
.thumb img {{ width: 120px; border: 1px solid {LINE}; border-radius: 4px; display: block; }}
.thumb .cap {{ font-size: 7.5pt; color: {INK_400}; margin-top: 2px; }}
.section-break {{ page-break-before: always; }}
"""
