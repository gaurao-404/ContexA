from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import fitz
from docx import Document as WordDocument
from pptx import Presentation

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def parse_pdf(data: bytes) -> tuple[list[dict[str, Any]], str]:
    pages: list[dict[str, Any]] = []
    all_text: list[str] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page_index, page in enumerate(doc):
            page_text = page.get_text("text") or ""
            spans: list[dict[str, Any]] = []
            ocr_used = False
            # OCR fallback for rasterized/scanned pages: retain approximate PDF-point boxes.
            if not page_text.strip() and page.get_images():
                try:
                    from PIL import Image
                    import pytesseract
                    scale = 2.0
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
                    words: list[str] = []
                    for wi, word in enumerate(ocr.get("text", [])):
                        word = str(word).strip()
                        if not word:
                            continue
                        words.append(word)
                        x0 = float(ocr["left"][wi]) / scale
                        y0 = float(ocr["top"][wi]) / scale
                        x1 = x0 + float(ocr["width"][wi]) / scale
                        y1 = y0 + float(ocr["height"][wi]) / scale
                        spans.append({"text": word, "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                                      "color": 0, "size": 10.0, "font": "OCR"})
                    page_text = " ".join(words)
                    ocr_used = bool(words)
                except Exception:
                    # Continue so that a scanned-only PDF can return a helpful no-text error upstream.
                    ocr_used = False
            raw = page.get_text("dict")
            if not ocr_used:
                # Native PDF text spans contain the most precise color and glyph dimensions.
                for block in raw.get("blocks", []):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            value = (span.get("text") or "").strip()
                            if not value:
                                continue
                            spans.append({"text": value, "bbox": [round(float(v), 2) for v in span.get("bbox", [0, 0, 0, 0])],
                                "color": int(span.get("color", 0)), "size": float(span.get("size", 0)), "font": str(span.get("font", ""))})
            pages.append({"page": page_index + 1, "text": page_text, "spans": spans,
                          "width": float(page.rect.width), "height": float(page.rect.height),
                          **({"note": "Scanned PDF text extracted with OCR; bounding boxes are approximate."} if ocr_used else {})})
            all_text.append(page_text)
    finally:
        doc.close()
    return pages or [{"page": 1, "text": "", "spans": [], "width": 612.0, "height": 792.0}], "\n\n".join(all_text)


def parse_docx(data: bytes) -> tuple[list[dict[str, Any]], str]:
    document = WordDocument(io.BytesIO(data))
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    # Page layout is not reliably exposed by python-docx; preserve paragraph order instead.
    joined = "\n".join(paragraphs)
    chunks = [joined[i:i + 4500] for i in range(0, max(len(joined), 1), 4500)] or [""]
    pages = [{"page": index + 1, "text": chunk, "spans": [], "width": 0, "height": 0,
              "note": "DOCX preview uses extracted text; precise page layout is not available."}
             for index, chunk in enumerate(chunks)]
    return pages, joined


def parse_pptx(data: bytes) -> tuple[list[dict[str, Any]], str]:
    presentation = Presentation(io.BytesIO(data))
    pages: list[dict[str, Any]] = []
    all_text: list[str] = []
    for index, slide in enumerate(presentation.slides):
        lines: list[str] = []
        spans: list[dict[str, Any]] = []
        missing_alt_text: list[dict[str, Any]] = []
        for shape in slide.shapes:
            if str(getattr(shape, "shape_type", "")) in {"PICTURE (13)", "13"}:
                try:
                    c_nv_pr = shape._element.nvPicPr.cNvPr
                    description = (c_nv_pr.get("descr") or "").strip()
                    title = (c_nv_pr.get("title") or "").strip()
                    # Office often inserts the image filename as a non-empty but useless description.
                    generic_alt = re.compile(r"^(?:image|picture|graphic)(?:[ _-]?\d+)?(?:\.[a-z0-9]{2,5})?$", re.I)
                    has_meaningful_alt = any(value and len(value) > 3 and not generic_alt.match(value.strip())
                                             for value in (description, title))
                    if not has_meaningful_alt:
                        missing_alt_text.append({
                            "name": getattr(shape, "name", "Picture"),
                            "location_bbox": {"bbox": [round(shape.left / 914400, 3), round(shape.top / 914400, 3),
                                round((shape.left + shape.width) / 914400, 3), round((shape.top + shape.height) / 914400, 3)],
                                "coordinate_system": "slide_inches"},
                        })
                except Exception:
                    # Keep extraction resilient if a non-standard OOXML picture shape is encountered.
                    pass
            if not getattr(shape, "has_text_frame", False):
                continue
            text = shape.text.strip()
            if text:
                lines.append(text)
                spans.append({"text": text, "bbox": [shape.left / 914400, shape.top / 914400,
                            (shape.left + shape.width) / 914400, (shape.top + shape.height) / 914400],
                              "color": 0, "size": 0, "font": ""})
        page_text = "\n".join(lines)
        pages.append({"page": index + 1, "text": page_text, "spans": spans,
                      "width": presentation.slide_width / 914400, "height": presentation.slide_height / 914400,
                      "missing_alt_text": missing_alt_text})
        all_text.append(page_text)
    return pages or [{"page": 1, "text": "", "spans": []}], "\n\n".join(all_text)


def parse_plain_text(data: bytes) -> tuple[list[dict[str, Any]], str]:
    text = data.decode("utf-8", errors="replace")
    chunks = [text[i:i + 4500] for i in range(0, max(len(text), 1), 4500)] or [""]
    return [{"page": i + 1, "text": chunk, "spans": [], "width": 0, "height": 0}
            for i, chunk in enumerate(chunks)], text


def parse_image(data: bytes) -> tuple[list[dict[str, Any]], str]:
    try:
        from PIL import Image
        import pytesseract
        image = Image.open(io.BytesIO(data))
        text = pytesseract.image_to_string(image)
    except Exception as exc:
        raise ValueError("Image OCR is unavailable. Install the Tesseract OCR system binary, then retry this image.") from exc
    return [{"page": 1, "text": text, "spans": [], "width": 0, "height": 0,
             "note": "Image text was extracted with OCR; spatial highlighting is unavailable for this format."}], text


def parse_document(filename: str, data: bytes) -> tuple[list[dict[str, Any]], str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix or '(no extension)'}. Upload PDF, DOCX, PPTX, TXT, Markdown, or an image.")
    if suffix == ".pdf":
        return parse_pdf(data)
    if suffix == ".docx":
        return parse_docx(data)
    if suffix == ".pptx":
        return parse_pptx(data)
    if suffix in {".txt", ".md"}:
        return parse_plain_text(data)
    return parse_image(data)


def page_spans_for_text(pages: list[dict[str, Any]], phrase: str) -> tuple[int, dict[str, Any] | None]:
    """Find a phrase in extracted spans; return first page and a source-coordinate bbox."""
    if not phrase:
        return 1, None
    phrase_lower = phrase.lower()
    for page in pages:
        text_lower = str(page.get("text", "")).lower()
        found = text_lower.find(phrase_lower)
        if found < 0:
            continue
        # Exact span match first; substring matches usually occur in one PDF text span.
        for span in page.get("spans", []):
            if phrase_lower in str(span.get("text", "")).lower() or str(span.get("text", "")).lower() in phrase_lower:
                return int(page.get("page", 1)), {"bbox": span.get("bbox"), "coordinate_system": "pdf_points"}
        return int(page.get("page", 1)), None
    return 1, None
