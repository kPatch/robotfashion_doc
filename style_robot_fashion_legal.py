#!/usr/bin/env python3
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ET.register_namespace("w", W_NS)
ET.register_namespace("a", A_NS)
ET.register_namespace("r", R_NS)

W = f"{{{W_NS}}}"
A = f"{{{A_NS}}}"


def wtag(name: str) -> str:
    return f"{W}{name}"


def set_wval(el: ET.Element, value: str) -> None:
    el.set(wtag("val"), value)


def ensure(parent: ET.Element, tag: str) -> ET.Element:
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    return child


def upsert_before(parent: ET.Element, tag: str, before_tags: tuple[str, ...]) -> ET.Element:
    child = parent.find(tag)
    if child is not None:
        return child
    child = ET.Element(tag)
    children = list(parent)
    for idx, existing in enumerate(children):
        if existing.tag in before_tags:
            parent.insert(idx, child)
            return child
    parent.append(child)
    return child


def accept_tracked_changes(elem: ET.Element) -> None:
    for child in list(elem):
        accept_tracked_changes(child)

    children = list(elem)
    for child in children:
        if child.tag == wtag("ins"):
            idx = list(elem).index(child)
            elem.remove(child)
            for grandchild in reversed(list(child)):
                elem.insert(idx, grandchild)
        elif child.tag == wtag("del"):
            elem.remove(child)


def set_run_props(rpr: ET.Element, font: str = "Times New Roman", size_half_points: str = "22", color: str = "000000") -> None:
    rfonts = upsert_before(
        rpr,
        wtag("rFonts"),
        (
            wtag("b"),
            wtag("bCs"),
            wtag("i"),
            wtag("iCs"),
            wtag("caps"),
            wtag("smallCaps"),
            wtag("color"),
            wtag("sz"),
            wtag("szCs"),
        ),
    )
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(wtag(attr), font)
    for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        rfonts.attrib.pop(wtag(attr), None)

    color_el = ensure(rpr, wtag("color"))
    color_el.set(wtag("val"), color)
    color_el.attrib.pop(wtag("themeColor"), None)
    color_el.attrib.pop(wtag("themeTint"), None)
    color_el.attrib.pop(wtag("themeShade"), None)

    set_wval(ensure(rpr, wtag("sz")), size_half_points)
    set_wval(ensure(rpr, wtag("szCs")), size_half_points)


def style_by_id(styles_root: ET.Element, style_id: str) -> ET.Element | None:
    for style in styles_root.findall(wtag("style")):
        if style.get(wtag("styleId")) == style_id:
            return style
    return None


def set_style_run(style: ET.Element, *, font: str, size: str, color: str = "000000", bold: bool | None = None, caps: bool | None = None) -> None:
    rpr = ensure(style, wtag("rPr"))
    set_run_props(rpr, font=font, size_half_points=size, color=color)
    if bold is not None:
        b = rpr.find(wtag("b"))
        if bold and b is None:
            ET.SubElement(rpr, wtag("b"))
        elif not bold and b is not None:
            rpr.remove(b)
        bcs = rpr.find(wtag("bCs"))
        if bold and bcs is None:
            ET.SubElement(rpr, wtag("bCs"))
        elif not bold and bcs is not None:
            rpr.remove(bcs)
    if caps is not None:
        caps_el = rpr.find(wtag("caps"))
        if caps and caps_el is None:
            ET.SubElement(rpr, wtag("caps"))
        elif not caps and caps_el is not None:
            rpr.remove(caps_el)


def set_style_para(style: ET.Element, *, jc: str | None = None, before: str | None = None, after: str | None = None, line: str | None = None) -> None:
    ppr = ensure(style, wtag("pPr"))
    p_bdr = ppr.find(wtag("pBdr"))
    if p_bdr is not None:
        ppr.remove(p_bdr)
    if jc is not None:
        set_wval(ensure(ppr, wtag("jc")), jc)
    spacing = ensure(ppr, wtag("spacing"))
    if before is not None:
        spacing.set(wtag("before"), before)
    if after is not None:
        spacing.set(wtag("after"), after)
    if line is not None:
        spacing.set(wtag("line"), line)
        spacing.set(wtag("lineRule"), "auto")


def update_styles(xml: bytes) -> bytes:
    root = ET.fromstring(xml)

    doc_defaults = ensure(root, wtag("docDefaults"))
    rpr_default = ensure(ensure(doc_defaults, wtag("rPrDefault")), wtag("rPr"))
    set_run_props(rpr_default)
    ppr_default = ensure(ensure(doc_defaults, wtag("pPrDefault")), wtag("pPr"))
    spacing = ensure(ppr_default, wtag("spacing"))
    spacing.set(wtag("after"), "120")
    spacing.set(wtag("line"), "240")
    spacing.set(wtag("lineRule"), "auto")

    for sid in ("Normal", "BodyText", "ListParagraph"):
        style = style_by_id(root, sid)
        if style is not None:
            set_style_run(style, font="Times New Roman", size="22", color="000000", bold=False, caps=False)
            set_style_para(style, jc="both" if sid != "ListParagraph" else None, after="120", line="240")

    title = style_by_id(root, "Title")
    if title is not None:
        set_style_run(title, font="Times New Roman", size="24", color="000000", bold=True, caps=False)
        set_style_para(title, jc="center", before="0", after="120", line="240")

    subtitle = style_by_id(root, "Subtitle")
    if subtitle is not None:
        set_style_run(subtitle, font="Times New Roman", size="22", color="000000", bold=False, caps=False)
        set_style_para(subtitle, jc="center", before="0", after="120", line="240")

    for sid in ("Heading1", "Heading2", "Heading3"):
        style = style_by_id(root, sid)
        if style is not None:
            set_style_run(style, font="Times New Roman", size="22", color="000000", bold=True, caps=False)
            set_style_para(style, jc="both", before="240", after="120", line="240")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def update_theme(xml: bytes) -> bytes:
    root = ET.fromstring(xml)
    for tag in ("majorFont", "minorFont"):
        for font_scheme in root.findall(f".//{A}fontScheme"):
            font = font_scheme.find(f"{A}{tag}")
            if font is not None:
                latin = font.find(f"{A}latin")
                if latin is not None:
                    latin.set("typeface", "Times New Roman")
                ea = font.find(f"{A}ea")
                if ea is not None:
                    ea.set("typeface", "Times New Roman")
                cs = font.find(f"{A}cs")
                if cs is not None:
                    cs.set("typeface", "Times New Roman")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def paragraph_style_id(p: ET.Element) -> str | None:
    pstyle = p.find(f"./{W}pPr/{W}pStyle")
    return pstyle.get(wtag("val")) if pstyle is not None else None


def update_content_part(xml: bytes, *, update_sections: bool = False) -> bytes:
    root = ET.fromstring(xml)
    accept_tracked_changes(root)

    for p in root.findall(f".//{W}p"):
        style_id = paragraph_style_id(p)
        ppr = ensure(p, wtag("pPr"))
        p_bdr = ppr.find(wtag("pBdr"))
        if p_bdr is not None:
            ppr.remove(p_bdr)
        if style_id == "Title":
            set_wval(ensure(ppr, wtag("jc")), "center")
            size = "24"
            bold = True
        elif style_id in {"Heading1", "Heading2", "Heading3"}:
            set_wval(ensure(ppr, wtag("jc")), "both")
            size = "22"
            bold = True
        else:
            existing_jc = ppr.find(wtag("jc"))
            if existing_jc is None:
                set_wval(ensure(ppr, wtag("jc")), "both")
            size = "22"
            bold = None

        for r in p.findall(f".//{W}r"):
            rpr = ensure(r, wtag("rPr"))
            set_run_props(rpr, size_half_points=size)
            if bold is True and rpr.find(wtag("b")) is None:
                ET.SubElement(rpr, wtag("b"))
            if bold is True and rpr.find(wtag("bCs")) is None:
                ET.SubElement(rpr, wtag("bCs"))

    if update_sections:
        for sect in root.findall(f".//{W}sectPr"):
            pg_mar = ensure(sect, wtag("pgMar"))
            pg_mar.set(wtag("top"), "1440")
            pg_mar.set(wtag("right"), "1440")
            pg_mar.set(wtag("bottom"), "1440")
            pg_mar.set(wtag("left"), "1440")
            pg_mar.set(wtag("header"), "720")
            pg_mar.set(wtag("footer"), "720")
            pg_mar.set(wtag("gutter"), "0")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def update_document(xml: bytes) -> bytes:
    return update_content_part(xml, update_sections=True)


def update_header_footer(xml: bytes) -> bytes:
    return update_content_part(xml, update_sections=False)


def update_numbering(xml: bytes) -> bytes:
    root = ET.fromstring(xml)
    for rpr in root.findall(f".//{W}rPr"):
        set_run_props(rpr)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def restyle_docx(src: Path, dst: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        with ZipFile(src) as zin:
            zin.extractall(tmp)

        updates = {
            "word/document.xml": update_document,
            "word/styles.xml": update_styles,
            "word/stylesWithEffects.xml": update_styles,
            "word/theme/theme1.xml": update_theme,
            "word/numbering.xml": update_numbering,
        }
        for rel, updater in updates.items():
            path = tmp / rel
            if path.exists():
                path.write_bytes(updater(path.read_bytes()))

        for path in list((tmp / "word").glob("header*.xml")) + list((tmp / "word").glob("footer*.xml")):
            path.write_bytes(update_header_footer(path.read_bytes()))

        if dst.exists():
            dst.unlink()
        with ZipFile(dst, "w", ZIP_DEFLATED) as zout:
            for path in sorted(tmp.rglob("*")):
                if path.is_file():
                    zout.write(path, path.relative_to(tmp).as_posix())


def main() -> None:
    src = Path("Robot_Fashion_Institutional_Participation_and_Funding_Agreement_REVISED_2026-07-12.docx")
    dst = Path("Robot_Fashion_Institutional_Participation_and_Funding_Agreement_LEGAL_STYLE_2026-07-15.docx")
    shutil.copy2(src, dst.with_suffix(".source-backup.docx"))
    restyle_docx(src, dst)
    print(dst)


if __name__ == "__main__":
    main()
