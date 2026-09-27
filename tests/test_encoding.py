# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Accents survive Save-as-DWG (LibreDWG issue #1393)."""
from core.document import Document
from core.encoding import (INTERMEDIATE_DXF_VERSION, decode_escapes,
                           decode_escapes_in_document, escape_non_ascii,
                           write_dwg_intermediate)

ACC = "CAÑERÍA Ø m² Nº45°"


def test_escaping_is_reversible_and_leaves_ascii_alone():
    assert escape_non_ascii("PLANTA 1:100") == "PLANTA 1:100"
    assert escape_non_ascii("Nº 45°") == "N\\U+00BA 45\\U+00B0"
    assert decode_escapes("N\\U+00BA 45\\U+00B0") == "Nº 45°"
    assert decode_escapes(escape_non_ascii(ACC)) == ACC
    # MTEXT formatting codes are ASCII and must pass through untouched
    fmt = "{\\C1;ROJO} y \\P otra"
    assert escape_non_ascii(fmt) == fmt
    assert decode_escapes(fmt) == fmt


def test_escaping_survives_beyond_the_basic_plane():
    assert decode_escapes(escape_non_ascii("plano 𝜋 fin")) == "plano 𝜋 fin"


def test_the_intermediate_dxf_is_r2000_and_restores_the_document(tmp_path):
    """Pre-R13 input makes dxf2dwg return an empty DWG (LibreDWG #1386), so
    the intermediate always goes out as R2000 — and the caller's drawing must
    not notice that its version was borrowed for the write."""
    doc = Document.new()
    msp = doc.modelspace()
    mtext = msp.add_mtext(ACC, dxfattribs={"char_height": 2, "insert": (0, 5)})
    blk = doc.doc.blocks.new("BÑ")
    inner = blk.add_mtext(ACC, dxfattribs={"char_height": 1})
    version_before = doc.doc.dxfversion

    out = tmp_path / "inter.dxf"
    write_dwg_intermediate(doc.doc, out)

    body = out.read_text(encoding="cp1252", errors="replace")
    assert INTERMEDIATE_DXF_VERSION in body
    # the text goes out as the user typed it: LibreDWG PR #1375 carries the
    # accents through now, so nothing is escaped on our side any more
    assert "\\U+00D1" not in body
    assert "CAÑERÍA" in out.read_text(encoding="cp1252", errors="replace")

    assert doc.doc.dxfversion == version_before
    assert mtext.text == ACC and inner.text == ACC


def test_reading_back_decodes_the_escapes_everywhere(tmp_path):
    doc = Document.new()
    doc.modelspace().add_mtext("N\\U+00BA 3", dxfattribs={"char_height": 1})
    blk = doc.doc.blocks.new("B2")
    blk.add_mtext("cota 45\\U+00B0", dxfattribs={"char_height": 1})

    assert decode_escapes_in_document(doc.doc) == 2
    assert doc.modelspace()[0].text == "Nº 3"
    assert list(blk)[0].text == "cota 45°"
    # idempotent: a second pass finds nothing left to do
    assert decode_escapes_in_document(doc.doc) == 0


# -- Save as DWG on real drawings (the 2026-09-27 corpus sweep) -----------------

def test_intermediate_writes_a_blob_mixing_lone_surrogates_and_other_text(tmp_path):
    # XRECORD groups 300/302 carrying binary blobs LibreDWG emits as text:
    # undecodable bytes arrive as lone surrogates, mixed with characters
    # cp1252 lacks. ezdxf's "dxfreplace" handed the whole run to
    # surrogateescape, which died on the other characters: the whole
    # Save as DWG failed ("'charmap' codec can't encode").
    import ezdxf

    from core import ezdxf_patches
    from core.encoding import write_dwg_intermediate

    ezdxf_patches.apply()
    doc = ezdxf.new("R2018")
    xrec = doc.objects.add_xrecord(doc.rootdict.dxf.handle)
    blob = "eMatP\udc9e\udce7ڢ\udc95ok"
    xrec.reset([(300, blob)])
    out = tmp_path / "blob.dxf"
    write_dwg_intermediate(doc, out)
    raw = out.read_bytes()
    # the surrogates go back to the bytes they came from; the rest escaped
    assert b"eMatP\x9e\xe7\\U+06a2\x95ok" in raw


def _field_doc():
    """A drawing holding one FIELD the way ezdxf keeps it from an R2007+
    DWG: verbatim tags, with the R2007+ value layout."""
    import ezdxf
    from ezdxf.lldxf.tags import Tags
    from ezdxf.lldxf.types import DXFTag

    doc = ezdxf.new("R2018")
    tags = [(0, "FIELD"), (5, "ABC"), (330, "0"), (100, "AcDbField"),
            (1, "_text"), (2, "%<\\_FldIdx 0>%"), (90, 1), (360, "ABD"),
            (97, 0), (91, 63), (92, 0), (94, 13), (95, 2), (96, 0), (300, ""),
            # own value: flags 3 (bit 1: no payload), kUnknown, R2007+ tail
            (93, 3), (90, 0), (94, 0), (300, ""), (302, ""),
            (93, 1), (6, "ACFD_FIELDTEXT_CHECKSUM"),
            # child value: a double
            (93, 2), (90, 2), (140, 493.0), (94, 0), (300, ""), (302, "493"),
            (301, ""), (98, 0)]
    from ezdxf.entities.dxfentity import DXFTagStorage

    field = DXFTagStorage.load(ezdxf.lldxf.extendedtags.ExtendedTags(
        Tags(DXFTag(c, v) for c, v in tags)), doc)
    doc.objects.add_object(field)
    return doc, field


def test_fields_go_to_the_intermediate_in_their_r2000_layout(tmp_path):
    # 34 of the first 266 corpus drawings failed Save as DWG with LibreDWG's
    # "No class for FIELD": it read the R2007+ format flags (93) as the
    # child count, because the intermediate is R2000.
    from core.encoding import write_dwg_intermediate

    doc, field = _field_doc()
    before = [(t.code, t.value) for t in field.xtags.subclasses[1]]
    out = tmp_path / "field.dxf"
    write_dwg_intermediate(doc, out)
    text = out.read_text(encoding="cp1252")
    body = text[text.index("AcDbField"):text.index("\n  0\n", text.index("AcDbField"))]
    pairs = body.split("\n")
    codes = [p.strip() for p in pairs[1::2]]
    # after the error message: own value (90 + payload), then 93 = 1 child
    tail = codes[codes.index("96") + 2:]
    assert tail[:3] == ["90", "91", "93"]
    assert tail[3:6] == ["6", "90", "140"]
    assert "94" not in tail and "302" not in tail and tail.count("300") == 0
    # and the caller's drawing is untouched
    assert [(t.code, t.value) for t in field.xtags.subclasses[1]] == before
