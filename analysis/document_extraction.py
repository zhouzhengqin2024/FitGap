from io import BytesIO
from pathlib import Path
from zipfile import is_zipfile

from docx import Document
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError


MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024
SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.txt'}


class DocumentExtractionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _read_uploaded_file(uploaded_file):
    uploaded_file.seek(0)
    content = uploaded_file.read()
    uploaded_file.seek(0)
    return content


def _validate_upload(uploaded_file):
    if not uploaded_file:
        raise DocumentExtractionError('empty_file')

    if uploaded_file.size > MAX_UPLOAD_SIZE_BYTES:
        raise DocumentExtractionError('file_too_large')

    extension = Path(uploaded_file.name).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentExtractionError('unsupported_file_type')

    content = _read_uploaded_file(uploaded_file)

    if not content:
        raise DocumentExtractionError('empty_file')

    return extension, content


def _extract_pdf_text(content):
    if not content.startswith(b'%PDF'):
        raise DocumentExtractionError('corrupt_file')

    try:
        reader = PdfReader(BytesIO(content))

        if reader.is_encrypted:
            raise DocumentExtractionError('password_protected_pdf')

        text_parts = [
            page.extract_text() or ''
            for page in reader.pages
        ]
    except DocumentExtractionError:
        raise
    except (FileNotDecryptedError, PdfReadError, OSError, ValueError):
        raise DocumentExtractionError('corrupt_file')

    text = '\n'.join(part.strip() for part in text_parts if part.strip()).strip()

    if not text:
        raise DocumentExtractionError('no_readable_text')

    return text


def _extract_docx_text(content):
    if not is_zipfile(BytesIO(content)):
        raise DocumentExtractionError('corrupt_file')

    try:
        document = Document(BytesIO(content))
    except Exception as exc:
        raise DocumentExtractionError('corrupt_file') from exc

    text = '\n'.join(
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    ).strip()

    if not text:
        raise DocumentExtractionError('no_readable_text')

    return text


def _extract_txt_text(content):
    for encoding in ('utf-8', 'utf-8-sig'):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            text = None

    if text is None:
        try:
            text = content.decode('latin-1')
        except UnicodeDecodeError as exc:
            raise DocumentExtractionError('invalid_txt_encoding') from exc

    text = text.strip()

    if not text:
        raise DocumentExtractionError('empty_file')

    return text


def extract_document_text(uploaded_file):
    """Extract text from an uploaded PDF, DOCX, or TXT file without persisting it."""
    extension, content = _validate_upload(uploaded_file)

    if extension == '.pdf':
        return _extract_pdf_text(content)

    if extension == '.docx':
        return _extract_docx_text(content)

    return _extract_txt_text(content)
