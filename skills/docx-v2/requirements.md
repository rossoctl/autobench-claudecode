# Requirements for Outputs

## Every Word document

These are properties of the finished `.docx`. They hold whichever library you build it with —
docx-js, python-docx or raw OOXML.

### Page Setup
- **US Letter**, 8.5in x 11in (12,240 x 15,840 twips). Never leave the page at A4.
- **1in margins** on all four sides (1,440 twips).

### Fonts and Colour
- **Body text Arial 12pt**, set as the document's default font rather than run by run.
- **Title and heading text black.** The built-in heading styles are blue; override them.

### Lists
- Bullets and numbers come from the document's own numbering definitions. Never type a bullet
  character into the paragraph text.

### Tables
- Table and cell widths are **absolute**, never a percentage: 9,360 twips is full width inside
  1in margins. Percentage widths do not survive a round trip through Google Docs.

# DOCX creation, editing, and analysis
