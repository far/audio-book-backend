from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_session_store
from app.api.dto import BookDTO
from app.application.ports import SessionStore

router = APIRouter()


@router.get("/session/{book_id}", response_model=BookDTO)
async def get_session(book_id: str, session_store: SessionStore = Depends(get_session_store)) -> BookDTO:
    book = await session_store.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="session not found")
    return BookDTO.from_domain(book)

