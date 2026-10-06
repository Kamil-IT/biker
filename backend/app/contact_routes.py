"""The contact form of the Kontakt tab: POST /v1/contact stores one message in contact_message.

No AI, no generic cache, no e-mail: messages are read by hand (SQL). A filled
honeypot (`website`) gets the same 200 as a real message but nothing is stored,
so a bot learns nothing. A failed write is a 503 — unlike the "Request data"
counter, a lost message must not look sent.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from .models import ContactMessage, get_session
from .schemas import ContactMessageRequest, ContactMessageResponse

logger = logging.getLogger("biker.search")
router = APIRouter()


def save_contact_message(req: ContactMessageRequest) -> Optional[int]:
    """Insert the message; its id, or None when the write failed (rolled back, ERROR logged)."""
    session = get_session()
    try:
        row = ContactMessage(name=req.name, email=req.email, topic=req.topic, message=req.message)
        session.add(row)
        session.commit()
        return row.id
    except Exception as exc:  # noqa: BLE001 — the caller turns it into a 503
        session.rollback()
        logger.error("contact message store failed | topic=%r | %s", req.topic, exc)
        return None
    finally:
        session.close()


@router.post("/v1/contact", response_model=ContactMessageResponse)
async def contact(req: ContactMessageRequest) -> ContactMessageResponse:
    """Store a contact-form message. 422 for a bad field, 503 when the write fails."""
    if req.website:
        logger.warning("contact message dropped: honeypot filled | topic=%r", req.topic)
        return ContactMessageResponse()
    message_id = save_contact_message(req)
    if message_id is None:
        raise HTTPException(status_code=503, detail="Could not save the message — try again later")
    # The address and the text stay out of the log (personal data); the row has them.
    logger.info("contact message stored | id=%d topic=%r chars=%d", message_id, req.topic, len(req.message))
    return ContactMessageResponse()
