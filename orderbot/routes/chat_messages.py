"""
Chat Message Endpoints
======================

Message processing endpoints for the ordering chatbot.

Endpoints:
----------
- POST /chat/message: Send a message (synchronous response)
- POST /chat/message/stream: Send a message (streaming response)
"""

import json
import logging

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import get_rate_limit_chat
from ..db import get_db
from ..rate_limiting import limiter
from ..schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    ActionOut,
)
from ..services.session import get_or_create_session
from .chat import chat_router

logger = logging.getLogger(__name__)


@chat_router.post("/message", response_model=ChatMessageResponse)
@limiter.limit(get_rate_limit_chat)
def chat_message(
    request: Request,
    req: ChatMessageRequest,
    db: Session = Depends(get_db),
) -> ChatMessageResponse:
    """Send a message to the chat bot and receive a response with order updates."""
    from ..message_processor import MessageProcessor, ProcessingContext

    logger.info("Processing chat message for session: %s", req.session_id[:8])
    try:
        processor = MessageProcessor(db)
        result = processor.process(ProcessingContext(
            user_message=req.message,
            session_id=req.session_id,
            item_id=req.item_id,
            add_item=req.add_item,
        ))

        processed_actions = [
            ActionOut(intent=a.get("intent", "unknown"), slots=a.get("slots", {}))
            for a in result.actions
        ]

        return ChatMessageResponse(
            reply=result.reply,
            order_state=result.order_state,
            actions=processed_actions,
            quick_replies=result.quick_replies,
            payment_url=result.payment_url,
            customer_id=result.order_state.get("customer_id"),
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (KeyError, TypeError, AttributeError, SQLAlchemyError) as e:
        logger.error("MessageProcessor failed: %s", str(e), exc_info=True)
        return ChatMessageResponse(
            reply="I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.",
            order_state={},
            actions=[],
        )


@chat_router.post("/message/stream")
@limiter.limit(get_rate_limit_chat)
def chat_message_stream(
    request: Request,
    req: ChatMessageRequest,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Streaming version of chat message endpoint.

    Uses Server-Sent Events (SSE) to stream the response as it's generated.
    """
    from ..message_processor import MessageProcessor, ProcessingContext
    from ..db import SessionLocal

    session = get_or_create_session(db, req.session_id)
    if session is None:
        def error_stream():
            yield f"data: {json.dumps({'error': 'Invalid session_id'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    session_store_id = session.get("store_id")
    session_caller_id = session.get("caller_id")

    def generate_stream():
        nonlocal session
        # The streaming generator runs in a background thread after the
        # request-scoped ``db`` session has been closed, so it needs its
        # own independent database session.
        stream_db = SessionLocal()

        try:
            logger.info("Processing streaming chat message for session: %s", req.session_id[:8])
            processor = MessageProcessor(stream_db)
            result = processor.process(ProcessingContext(
                user_message=req.message,
                session_id=req.session_id,
                caller_id=session_caller_id,
                store_id=session_store_id,
                item_id=req.item_id,
                add_item=req.add_item,
                session=session,
            ))

            # Prefetch TTS audio in parallel with token streaming
            from ..services.tts_cache import prefetch_tts
            audio_id = prefetch_tts(result.reply) if result.reply else None

            words = result.reply.split()
            for i, word in enumerate(words):
                token = word + (" " if i < len(words) - 1 else "")
                yield f"data: {json.dumps({'token': token})}\n\n"

            processed_actions = [
                {"intent": a.get("intent", "unknown"), "slots": a.get("slots", {})}
                for a in result.actions
            ]

            final_event = {
                'done': True,
                'reply': result.reply,
                'order_state': result.order_state,
                'actions': processed_actions,
            }
            if result.quick_replies:
                final_event['quick_replies'] = result.quick_replies
            if result.payment_url:
                final_event['payment_url'] = result.payment_url
            if audio_id:
                final_event['audio_id'] = audio_id
            # Include customer_id when available (after order confirmation)
            if result.order_state.get('customer_id'):
                final_event['customer_id'] = result.order_state['customer_id']
            yield f"data: {json.dumps(final_event)}\n\n"

        except Exception as e:
            logger.error("MessageProcessor failed in stream: %s", e, exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        finally:
            stream_db.rollback()
            stream_db.close()

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
