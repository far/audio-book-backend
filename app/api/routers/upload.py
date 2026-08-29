from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.config import settings
from app.api.deps import get_ingest_book_use_case
from app.api.dto import BookDTO
from app.api.security import check_epub_magic_bytes, read_upload_with_cap
from app.application.result import Err
from app.application.use_cases import IngestBook
from app.domain.errors import EmptyBookError, InvalidUploadError, UnsupportedFormatError

router = APIRouter()


@router.post("/upload", response_model=BookDTO)
async def upload_book(
    file: UploadFile,
    ingest_book: IngestBook = Depends(get_ingest_book_use_case),
) -> BookDTO:
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=422, detail="only .epub uploads are supported")

    try:
        content = await read_upload_with_cap(file, settings.max_upload_bytes)
        check_epub_magic_bytes(content)
    except InvalidUploadError as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc

    result = await ingest_book.execute(file.filename, content)
    if isinstance(result, Err):
        error = result.error
        if isinstance(error, UnsupportedFormatError):
            raise HTTPException(status_code=422, detail=f"unsupported format: {error.format}")
        if isinstance(error, EmptyBookError):
            raise HTTPException(status_code=422, detail="book has no readable chapters")
        raise HTTPException(status_code=422, detail=error.reason)

    book = result.unwrap()
    return BookDTO.from_domain(book)
