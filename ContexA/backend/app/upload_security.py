from __future__ import annotations

import hashlib
import io
import socket
import struct
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import CLAMD_HOST, CLAMD_PORT, MAX_UPLOAD_MB, UPLOAD_SCAN_MODE

CHUNK_SIZE = 1024 * 1024
MAX_ZIP_ENTRIES = 5000
MAX_EXPANDED_BYTES = 200 * 1024 * 1024


async def read_upload_limited(upload: UploadFile) -> bytes:
    """Read multipart input in bounded chunks instead of loading unbounded bodies."""
    maximum = MAX_UPLOAD_MB * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(min(CHUNK_SIZE, maximum + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB} MB upload limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_office_zip(data: bytes, suffix: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ValueError("The Office file contains too many archive entries.")
            total = sum(item.file_size for item in infos)
            if total > MAX_EXPANDED_BYTES:
                raise ValueError("The Office file expands beyond the safe processing limit.")
            if any(item.flag_bits & 0x1 for item in infos):
                raise ValueError("Encrypted Office files are not supported.")
            names = {item.filename for item in infos}
            required = {"[Content_Types].xml", "word/document.xml"} if suffix == ".docx" else {"[Content_Types].xml", "ppt/presentation.xml"}
            if not required.issubset(names):
                raise ValueError("The file extension does not match a valid DOCX/PPTX document.")
            # Reject path traversal names even though the parser does not extract to disk.
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise ValueError("The Office archive contains an unsafe path.")
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded Office document is not a valid ZIP container.") from exc


def validate_upload_payload(filename: str, data: bytes) -> str:
    """Validate content signatures; user-supplied MIME types are deliberately ignored."""
    suffix = Path(filename).suffix.lower()
    if not data:
        raise ValueError("The uploaded file is empty.")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("The file does not have a valid PDF signature.")
        return "application/pdf"
    if suffix in {".docx", ".pptx"}:
        _validate_office_zip(data, suffix)
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if suffix == ".docx" else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        try:
            from PIL import Image, ImageFile
            Image.MAX_IMAGE_PIXELS = 40_000_000
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
                fmt = (img.format or "").upper()
            allowed = {"PNG": ".png", "JPEG": suffix if suffix in {".jpg", ".jpeg"} else ".jpg",
                       "TIFF": suffix if suffix in {".tif", ".tiff"} else ".tif", "BMP": ".bmp", "WEBP": ".webp"}
            if fmt not in allowed:
                raise ValueError("Image format is not supported.")
            return {"PNG": "image/png", "JPEG": "image/jpeg", "TIFF": "image/tiff", "BMP": "image/bmp", "WEBP": "image/webp"}[fmt]
        except (OSError, ValueError) as exc:
            raise ValueError("The uploaded image is invalid or exceeds safe image limits.") from exc
    if suffix in {".ttf", ".otf", ".woff", ".woff2"}:
        signatures = {".ttf": (b"\x00\x01\x00\x00",), ".otf": (b"OTTO",), ".woff": (b"wOFF",), ".woff2": (b"wOF2",)}
        if not any(data.startswith(signature) for signature in signatures[suffix]):
            raise ValueError("Font file signature does not match its extension.")
        return {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}[suffix]
    if suffix in {".txt", ".md"}:
        if b"\x00" in data:
            raise ValueError("Text uploads cannot contain binary null bytes.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text uploads must be UTF-8 encoded.") from exc
        return "text/markdown" if suffix == ".md" else "text/plain"
    raise ValueError("Unsupported upload extension.")


def clamav_scan(data: bytes) -> dict[str, str]:
    """Optional ClamAV INSTREAM scan. OFF means no AV claim is made."""
    if UPLOAD_SCAN_MODE in {"", "disabled", "off", "none"}:
        return {"status": "not_configured"}
    if UPLOAD_SCAN_MODE != "clamd":
        raise HTTPException(status_code=503, detail="Unsupported upload scanner configuration.")
    try:
        with socket.create_connection((CLAMD_HOST, CLAMD_PORT), timeout=4) as sock:
            sock.sendall(b"zINSTREAM\0")
            view = memoryview(data)
            for offset in range(0, len(data), CHUNK_SIZE):
                part = view[offset:offset + CHUNK_SIZE]
                sock.sendall(struct.pack("!I", len(part)))
                sock.sendall(part)
            sock.sendall(struct.pack("!I", 0))
            response_bytes = bytearray()
            while len(response_bytes) < 4096:
                part = sock.recv(1024)
                if not part:
                    break
                response_bytes.extend(part)
                if b"\0" in part or b"\n" in part:
                    break
            response = bytes(response_bytes).decode("utf-8", errors="replace").strip("\0\r\n ")
        if "FOUND" in response:
            raise HTTPException(status_code=422, detail="The uploaded file was flagged by malware scanning and was rejected.")
        if "OK" not in response:
            raise RuntimeError(response or "No ClamAV response")
        return {"status": "clean"}
    except HTTPException:
        raise
    except Exception as exc:
        # Fail closed when the operator has explicitly enabled mandatory AV scanning.
        raise HTTPException(status_code=503, detail="Upload malware scanner is unavailable; upload was rejected. Contact the administrator.") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
