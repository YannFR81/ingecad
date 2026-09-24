# Annotative scaling — plan (2026-09-24)

Requested by Rafael (review 4, video 23-09-2026, 32:00–43:05): texts,
dimensions and arrows must measure the same **on paper** (e.g. 2.5 mm) in
every layout viewport, whatever its scale. Marco: **"igual a AutoCAD"**.

The research behind this plan lives in `docs/reference/annotative/`
(gitignored — it quotes the AutoCAD manual and describes private drawings):
`autocad-annotative-scaling.md` (the behaviour, page by page) and
`file-format-measurements.md` (how AutoCAD stores it, measured on the
1 657-drawing corpus).

## What AutoCAD does, in five lines

1. An annotative object has a paper size and **one scale representation per
   annotation scale** it supports, each with its own position.
2. Model space has one current annotation scale (**CANNOSCALE**); **each
   layout viewport has its own** — a property of the viewport, *not* its zoom
   (they differ on 457 of 707 real viewports).
3. A space draws each object through the representation for its scale; an
   object without that scale is hidden when **ANNOALLVISIBLE** = 0 and shown
   (at one representation) when 1.
4. An annotative text style has a paper height; an annotative dimension style
   forces DIMSCALE to 0 and CANNOSCALE sizes it.
5. A new annotative object supports only the current scale; OBJECTSCALE adds
   and removes scales, ANNOAUTOSCALE adds the new scale on change.

## Where it lives in the file (all of it read and written as AutoCAD does)

| what | where |
|---|---|
| the flag | XDATA `AcadAnnotative` `AnnotativeData { 1070 1, 1070 flag }` — flag 0 exists, presence ≠ annotative |
| representations | entity → xdict → `AcDbContextDataManager` → `ACDB_ANNOTATIONSCALES` → `ACDB_*OBJECTCONTEXTDATA_CLASS` (290 default, 340 → SCALE) |
| scale list | root `ACAD_SCALELIST` → SCALE (300 name, 140 paper, 141 drawing units) |
| CANNOSCALE | `AcDbVariableDictionary` → DICTIONARYVAR, by **name** |
| viewport scale | XRECORD `ASDK_XREC_ANNOTATION_SCALE_INFO` in the VIEWPORT's xdict (340 → SCALE) |
| ANNOALLVISIBLE | XDATA `AcadAnnoAV` on each LAYOUT object |

TEXT/MTEXT representations store **no height**: `height × factor(s) /
factor(default)`. A dimension representation has its **own `*D` block**.

## Phases

| phase | content | status |
|---|---|---|
| **A0 · LibreDWG** | XDATA of several applications fused into one (#1422); `ACAD` APPID hard-coded (#1423); context data kept out of DXF (#1424); **`dxf2dwg` import of the context classes** | 3 of 4 done and vendored 2026-09-24; the import is open |
| **A1 · Show** | `core/annotative.py` reader; the render draws each space at its scale (model: CANNOSCALE, viewport: its XRECORD, sheet: default); ANNOALLVISIBLE; live pan off for viewports at another scale; Save as DWG warns when scales would be lost | **done 2026-09-24** |
| **A2 · Create** (Rafael's ask) | Annotative checkbox in the text style (paper height) and the dimension style (Fit tab, DIMSCALE 0); TEXT/MTEXT/dimensions born annotative at CANNOSCALE; the annotation-scale control on the status bar (model space) and the viewport's own scale; a new viewport gets one | next |
| **A3 · Edit** | copy/move/rotate/scale/erase carry every representation (ezdxf's `copy()` shares the context objects, `delete` orphans them — measured); OBJECTSCALE, ANNOAUTOSCALE, ANNORESET, ANNOUPDATE, SCALELISTEDIT; SELECTIONANNODISPLAY | |
| later | annotative blocks and attributes (creation), MLEADER and hatch representations, MSLTSCALE, SAVEFIDELITY | |

## Decisions and assumptions, to revisit with evidence

- **Unsupported scale with ANNOALLVISIBLE = 1 shows the default
  representation.** The manual says "only one" is shown, not which; the
  default is what the object's own fields hold. Check against BricsCAD or
  AutoCAD on a real drawing when one is at hand.
- **A viewport without the XRECORD shows annotations at CANNOSCALE.** Only
  50 of 757 real viewports lack it (sample of 120 drawings). A2 writes the XRECORD for every viewport
  IngeCAD creates.
- **Objects drawn on the sheet itself** show their default representation.
- **Save as DWG** keeps each object at its default representation until
  `dxf2dwg` imports the context classes, and says so. DXF keeps everything.

## Known failures met on the way (not annotative; each blocks Save as DWG)

`Invalid DXF code 16 for DIMENSION_ANG3PT`, `No class for BLOCKROTATEACTION`,
`No class for FIELD`, and ezdxf's `charmap` error on lone surrogates while
writing the R2000 intermediate.
