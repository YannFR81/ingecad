# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Annotative scaling as AutoCAD stores it: read the scale representations.

An annotative object is defined at a paper size and carries one *scale
representation* per annotation scale it supports; model space and every
layout viewport each have one current annotation scale, and the object is
shown through the representation for that scale (AutoCAD Command Reference,
glossary p. 2645/2671). Nothing here is IngeCAD's own format -- every piece
is read where AutoCAD writes it, so a colleague's drawing round-trips as it
came (measured on the corpus: docs/reference/annotative/):

* the flag: XDATA ``AcadAnnotative`` = ``AnnotativeData { 1070 1, 1070 flag }``
  -- present with flag 0 on many objects, so presence alone means nothing;
* the representations: entity -> extension dictionary ->
  ``AcDbContextDataManager`` -> ``ACDB_ANNOTATIONSCALES`` -> one
  ``ACDB_*OBJECTCONTEXTDATA_CLASS`` object per scale, each pointing (340) at
  a SCALE in the ``ACAD_SCALELIST`` dictionary. The entity's own fields
  always mirror the representation flagged as default (290 = 1);
* CANNOSCALE: by *name*, in the ``AcDbVariableDictionary``;
* a layout viewport's scale: XRECORD ``ASDK_XREC_ANNOTATION_SCALE_INFO`` in
  its extension dictionary, pointing (340) at a SCALE. It is its own
  property: on 457 of 707 real viewports it is NOT the viewport's zoom;
* ANNOALLVISIBLE, saved per model space and per layout: XDATA ``AcadAnnoAV``
  on the LAYOUT object, default 1.

TEXT and MTEXT representations store no height: it follows from the scale,
``height x factor(scale) / factor(default)`` (exactly x6.000 between 1:1250
and 1:7500 on a real file).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

ANNO_APPID = "AcadAnnotative"
ALL_VISIBLE_APPID = "AcadAnnoAV"
SCALE_INFO_KEY = "ASDK_XREC_ANNOTATION_SCALE_INFO"
CONTEXT_MANAGER_KEY = "AcDbContextDataManager"
SCALES_KEY = "ACDB_ANNOTATIONSCALES"
_BODY_MARKER = "AcDbAnnotScaleObjectContextData"


@dataclass(frozen=True)
class Scale:
    """One entry of the drawing's scale list (a SCALE object)."""

    handle: str
    name: str
    paper: float
    drawing: float

    @property
    def factor(self) -> float:
        """Drawing units per paper unit: how much bigger than its paper size
        an annotation is drawn at this scale."""
        return self.drawing / self.paper if self.paper else 1.0


@dataclass(frozen=True)
class Representation:
    """One scale representation of an annotative object."""

    scale: Scale
    is_default: bool
    #: the class body: every tag after the annot-scale marker, 340 excluded
    tags: tuple = field(repr=False)

    def first(self, code: int, default=None):
        return next((v for c, v in self.tags if c == code), default)

    def all(self, code: int) -> list:
        return [v for c, v in self.tags if c == code]


def _subclass_tags(obj) -> list[list]:
    xtags = getattr(obj, "xtags", None)
    if xtags is None:
        return []
    return [[(t.code, t.value) for t in sub] for sub in xtags.subclasses]


def scale_from_object(obj) -> Optional[Scale]:
    if obj is None or obj.dxftype() != "SCALE":
        return None
    values = {}
    for sub in _subclass_tags(obj):
        for code, value in sub:
            values.setdefault(code, value)
    try:
        return Scale(obj.dxf.handle, str(values.get(300, "")),
                     float(values.get(140, 1.0)), float(values.get(141, 1.0)))
    except (TypeError, ValueError):
        return None


def scale_by_handle(doc, handle) -> Optional[Scale]:
    if not handle:
        return None
    return scale_from_object(doc.entitydb.get(handle))


def scale_list(doc) -> list[Scale]:
    """The drawing's named scales, in dictionary order."""
    scales = doc.rootdict.get("ACAD_SCALELIST")
    if scales is None:
        return []
    out = []
    for _key, obj in scales.items():
        scale = scale_from_object(obj)
        if scale is not None:
            out.append(scale)
    return out


def find_scale(doc, name: str) -> Optional[Scale]:
    return next((s for s in scale_list(doc) if s.name == name), None)


def is_annotative(entity) -> bool:
    """True when the object is annotative (the flag, not mere presence)."""
    dxftype = entity.dxftype()
    if dxftype in ("MULTILEADER", "MLEADER"):
        return bool(entity.dxf.get("is_annotative", 0))
    if not entity.has_xdata(ANNO_APPID):
        return False
    ints = [t.value for t in entity.get_xdata(ANNO_APPID) if t.code == 1070]
    return len(ints) >= 2 and ints[1] == 1


def _xdict_get(entity, key):
    if not entity.has_extension_dict:
        return None
    try:
        xdict = entity.get_extension_dict()
        return xdict[key] if key in xdict else None
    except Exception:
        return None


def representations(entity) -> list[Representation]:
    """Every scale representation the object carries (empty if none)."""
    manager = _xdict_get(entity, CONTEXT_MANAGER_KEY)
    if manager is None or SCALES_KEY not in manager:
        return []
    doc = entity.doc
    out = []
    for _key, obj in manager[SCALES_KEY].items():
        subs = _subclass_tags(obj)
        if not subs:
            continue    # a dangling entry: the context object is gone
        is_default = False
        body: list = []
        in_body = False
        scale_handle = None
        for sub in subs[1:]:
            for code, value in sub:
                if code == 100:
                    in_body = in_body or value == _BODY_MARKER
                    continue
                if not in_body:
                    if code == 290:
                        is_default = bool(value)
                    continue
                if code == 340 and scale_handle is None:
                    scale_handle = value
                    continue
                body.append((code, value))
        scale = scale_by_handle(doc, scale_handle)
        if scale is not None:
            out.append(Representation(scale, is_default, tuple(body)))
    return out


def _variable(doc, name: str) -> Optional[str]:
    variables = doc.rootdict.get("AcDbVariableDictionary")
    if variables is None or name not in variables:
        return None
    try:
        return str(variables.get(name).dxf.value)
    except Exception:
        return None


def current_scale(doc) -> Optional[Scale]:
    """CANNOSCALE: the annotation scale of model space."""
    name = _variable(doc, "CANNOSCALE")
    return find_scale(doc, name) if name else None


def viewport_scale(viewport) -> Optional[Scale]:
    """The annotation scale a layout viewport shows annotations at."""
    record = _xdict_get(viewport, SCALE_INFO_KEY)
    if record is None or record.dxftype() != "XRECORD":
        return None
    handle = next((t.value for t in record.tags if t.code == 340), None)
    return scale_by_handle(viewport.doc, handle)


def all_visible(layout) -> bool:
    """ANNOALLVISIBLE of a space (its LAYOUT object); AutoCAD's default is 1."""
    try:
        obj = layout.dxf_layout
    except AttributeError:
        obj = layout
    try:
        if obj.has_xdata(ALL_VISIBLE_APPID):
            ints = [t.value for t in obj.get_xdata(ALL_VISIBLE_APPID)
                    if t.code == 1070]
            if ints:
                return ints[0] != 0
    except Exception:
        pass
    return True


def has_annotative(space) -> bool:
    """Does ``space`` (a layout or block) hold any annotative object?"""
    return any(is_annotative(e) for e in space)


# -- picking the representation to draw ---------------------------------------

#: returned by :func:`representation_for` when the object must not be drawn
HIDDEN = object()


def representation_for(entity, scale: Optional[Scale],
                       show_all: bool = True):
    """What to draw for ``entity`` in a space whose annotation scale is
    ``scale``: a :class:`Representation`, None (draw the entity as it is) or
    :data:`HIDDEN`.

    A scale is matched by its SCALE object first and by name second (xref
    binding leaves duplicates such as ``1:100_1_1``). An object that does not
    support the space's scale is hidden when ANNOALLVISIBLE is 0 and shown at
    its default representation otherwise -- the manual says "only one" is
    shown (p. 2151) and not which; the default is what the object's own
    fields hold.
    """
    if scale is None or not is_annotative(entity):
        return None
    reps = representations(entity)
    if not reps:
        return None
    match = next((r for r in reps if r.scale.handle == scale.handle), None)
    if match is None:
        match = next((r for r in reps if r.scale.name == scale.name), None)
    if match is None:
        return None if show_all else HIDDEN
    return None if match.is_default else match


def _default_factor(entity) -> Optional[float]:
    rep = next((r for r in representations(entity) if r.is_default), None)
    return rep.scale.factor if rep is not None else None


def virtual_representation(entity, rep: Representation):
    """A virtual copy of ``entity`` laid out as ``rep`` says.

    Built outside the entity database (the regen runs in a worker thread and
    ``entity.copy()`` would add dictionaries to the document), carrying the
    original handle so the drawing is attributed to the real object: picking
    and hiding keep working. None when the type has nothing to substitute.
    """
    from ezdxf.entities import factory

    dxftype = entity.dxftype()
    base = _default_factor(entity)
    ratio = rep.scale.factor / base if base else 1.0
    attribs = entity.dxfattribs(drop={"handle", "owner"})
    if dxftype == "TEXT":
        attribs["halign"] = rep.first(70, attribs.get("halign", 0))
        attribs["rotation"] = rep.first(50, attribs.get("rotation", 0.0))
        attribs["insert"] = _point(rep.first(10), attribs.get("insert"))
        attribs["align_point"] = _point(rep.first(11),
                                        attribs.get("align_point"))
        attribs["height"] = entity.dxf.height * ratio
    elif dxftype == "MTEXT":
        attribs["attachment_point"] = rep.first(
            70, attribs.get("attachment_point", 1))
        attribs["text_direction"] = _point(rep.first(10),
                                           attribs.get("text_direction"))
        attribs.pop("rotation", None)     # the direction says it
        attribs["insert"] = _point(rep.first(11), attribs.get("insert"))
        attribs["char_height"] = entity.dxf.char_height * ratio
        width = rep.first(40)
        if width is not None:
            attribs["width"] = float(width)
    elif dxftype == "DIMENSION":
        block = rep.first(2)
        if not block or block not in entity.doc.blocks:
            return None
        attribs["geometry"] = block
    elif dxftype == "INSERT":
        attribs["rotation"] = rep.first(50, attribs.get("rotation", 0.0))
        attribs["insert"] = _point(rep.first(10), attribs.get("insert"))
        for code, name in ((41, "xscale"), (42, "yscale"), (43, "zscale")):
            value = rep.first(code)
            if value is not None:
                attribs[name] = float(value)
    elif dxftype == "LEADER":
        vertices = [_point(v, None) for v in rep.all(10)]
        if len(vertices) < 2 or None in vertices:
            return None
    else:
        return None
    virtual = factory.new(dxftype, dxfattribs=attribs, doc=entity.doc)
    virtual.dxf.handle = entity.dxf.handle
    if dxftype == "MTEXT":
        virtual.text = entity.text
    elif dxftype == "LEADER":
        virtual.vertices = vertices
    elif dxftype == "INSERT" and entity.attribs:
        # attributes keep their own (default) layout for now
        virtual.attribs = list(entity.attribs)
    return virtual


# -- writing, exactly as AutoCAD does ------------------------------------------

#: context class per entity type: (DXF class name, C++ class name)
CONTEXT_CLASSES = {
    "TEXT": ("ACDB_TEXTOBJECTCONTEXTDATA_CLASS", "AcDbTextObjectContextData"),
    "MTEXT": ("ACDB_MTEXTOBJECTCONTEXTDATA_CLASS",
              "AcDbMTextObjectContextData"),
}
#: CLASS flags AutoCAD writes for SCALE and every context class (measured)
_CLASS_FLAGS = 1153


def _register_class(doc, name: str, cpp: str) -> None:
    from ezdxf.entities.dxfclass import DXFClass

    if (name, cpp) in doc.classes.classes:
        return
    cls = DXFClass.new(doc=doc)
    cls.update_dxf_attribs({
        "name": name, "cpp_class_name": cpp, "app_name": "ObjectDBX Classes",
        "flags": _CLASS_FLAGS, "was_a_proxy": 0, "is_an_entity": 0})
    doc.classes.register(cls)


def _new_object(doc, dxftype: str, owner: str, subclasses: list[list]):
    """A custom-class object from raw tags, owned by (and reacting to)
    ``owner`` -- the shape AutoCAD gives SCALE and context objects."""
    from ezdxf.entities.dxfentity import DXFTagStorage
    from ezdxf.lldxf.extendedtags import ExtendedTags

    lines = [(0, dxftype)]
    for sub in subclasses:
        lines.extend(sub)
    text = "".join(f"{c}\n{v}\n" for c, v in lines)
    obj = DXFTagStorage.load(ExtendedTags.from_text(text), doc)
    doc.entitydb.add(obj)           # assigns the handle
    doc.objects.add_object(obj)
    obj.dxf.owner = owner
    obj.set_reactors([owner])
    return obj


def ensure_scale(doc, name: str, paper: float, drawing: float) -> Scale:
    """The named scale, added to ``ACAD_SCALELIST`` when the drawing lacks it."""
    found = find_scale(doc, name)
    if found is not None:
        return found
    scales = doc.rootdict.get("ACAD_SCALELIST")
    if scales is None:
        scales = doc.rootdict.add_new_dict("ACAD_SCALELIST", hard_owned=True)
    _register_class(doc, "SCALE", "AcDbScale")
    key = f"*A{len(scales) + 1}"
    while key in scales:
        key = f"*A{int(key[2:]) + 1}"
    obj = _new_object(doc, "SCALE", scales.dxf.handle, [
        [(100, "AcDbScale"), (70, 0), (300, name), (140, repr(float(paper))),
         (141, repr(float(drawing))), (290, 1 if name == "1:1" else 0)]])
    scales[key] = obj
    return scale_from_object(obj)


def set_annotative(entity, on: bool = True) -> None:
    """Write the AcadAnnotative flag the way AutoCAD does."""
    doc = entity.doc
    if ANNO_APPID not in doc.appids:
        doc.appids.add(ANNO_APPID)
    entity.set_xdata(ANNO_APPID, [
        (1000, "AnnotativeData"), (1002, "{"), (1070, 1),
        (1070, 1 if on else 0), (1002, "}")])


def set_current_scale(doc, scale: Scale) -> None:
    """CANNOSCALE, by name, where AutoCAD keeps it."""
    variables = doc.rootdict.get("AcDbVariableDictionary")
    if variables is None:
        variables = doc.rootdict.add_new_dict("AcDbVariableDictionary",
                                              hard_owned=True)
    variables.set_or_add_dict_var("CANNOSCALE", scale.name)


def set_viewport_scale(viewport, scale: Scale) -> None:
    """A layout viewport's annotation scale (its own property, not its zoom)."""
    if not viewport.has_extension_dict:
        viewport.new_extension_dict()
    xdict = viewport.get_extension_dict()
    record = (xdict[SCALE_INFO_KEY] if SCALE_INFO_KEY in xdict
              else xdict.add_xrecord(SCALE_INFO_KEY))
    record.reset([(90, 1), (340, scale.handle)])


def set_all_visible(layout, on: bool) -> None:
    """ANNOALLVISIBLE of one space (model space or a layout)."""
    obj = layout.dxf_layout
    if ALL_VISIBLE_APPID not in obj.doc.appids:
        obj.doc.appids.add(ALL_VISIBLE_APPID)
    obj.set_xdata(ALL_VISIBLE_APPID, [(1070, 1 if on else 0)])


def _body_for(entity) -> list:
    dxftype = entity.dxftype()
    if dxftype == "TEXT":
        ins = entity.dxf.insert
        align = entity.dxf.get("align_point", ins)
        return [(70, entity.dxf.get("halign", 0)),
                (50, repr(float(entity.dxf.get("rotation", 0.0)))),
                (10, repr(ins[0])), (20, repr(ins[1])),
                (11, repr(align[0])), (21, repr(align[1]))]
    if dxftype == "MTEXT":
        d = entity.dxf.get("text_direction", (1.0, 0.0, 0.0))
        ins = entity.dxf.insert
        return [(70, entity.dxf.get("attachment_point", 1)),
                (10, repr(d[0])), (20, repr(d[1])), (30, repr(d[2])),
                (11, repr(ins[0])), (21, repr(ins[1])), (31, repr(ins[2])),
                (40, repr(float(entity.dxf.get("width", 0.0)))),
                (41, "0.0"), (42, "0.0"), (43, "0.0"), (71, 0)]
    raise ValueError(f"{dxftype} cannot carry scale representations yet")


def add_representation(entity, scale: Scale, *, default: bool,
                       layout: Optional[dict] = None) -> None:
    """Give ``entity`` a representation for ``scale``.

    The body is laid out from the entity's own fields, overridden by
    ``layout`` ({group code: value}) -- how a representation at another
    scale gets its own position. Makes the entity annotative.
    """
    dxftype = entity.dxftype()
    name, cpp = CONTEXT_CLASSES[dxftype]
    doc = entity.doc
    _register_class(doc, name, cpp)
    body = _body_for(entity)
    if layout:
        body = [(c, repr(layout[c]) if isinstance(layout[c], float)
                 else layout[c]) if c in layout else (c, v) for c, v in body]
    if not entity.has_extension_dict:
        entity.new_extension_dict()
    xdict = entity.get_extension_dict()
    manager = (xdict[CONTEXT_MANAGER_KEY] if CONTEXT_MANAGER_KEY in xdict
               else xdict.add_dictionary(CONTEXT_MANAGER_KEY, hard_owned=True))
    scales = (manager[SCALES_KEY] if SCALES_KEY in manager
              else manager.add_new_dict(SCALES_KEY, hard_owned=True))
    obj = _new_object(doc, name, scales.dxf.handle, [
        [(100, "AcDbObjectContextData"), (70, 4), (290, 1 if default else 0)],
        [(100, _BODY_MARKER), (340, scale.handle)] + body])
    key = f"*A{len(scales) + 1}"
    while key in scales:
        key = f"*A{int(key[2:]) + 1}"
    scales[key] = obj
    set_annotative(entity, True)


def _point(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (tuple, list)):
        x, y = float(value[0]), float(value[1])
        z = float(value[2]) if len(value) > 2 else 0.0
        return (x, y, z)
    try:
        return (float(value.x), float(value.y), float(value.z))
    except AttributeError:
        return fallback
