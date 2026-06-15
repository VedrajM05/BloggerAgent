from fastapi import APIRouter
import json
from fastapi.responses import StreamingResponse
from services.event_manager import (get_queue, publish_event)

router = APIRouter()

@router.get("/events/{correlation_id}")
def stream_events(correlation_id: str):

    print(f"SSE CONNECTED => {correlation_id}")
    # fetches the specific FIFO queue tied to that correlation_id
    queue = get_queue(correlation_id)

    def event_generator():
        while True:
            # loop pauses here until a new event is published to this specific queue
            event = queue.get()

            print(f"EVENT RECEIVED => {event}")

            # yield keyword sends data back to the client immediately without closing the HTTP connection
            yield (
                f"data: "
                f"{json.dumps(event)}\n\n"
            )
            # If an event arrives marked as "COMPLETE", the loop breaks, the generator ends, and the server closes the stream.
            if event.get("type") == "COMPLETE":
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


@router.get("/test-publish/{correlation_id}")
def test_publish(correlation_id: str):

    publish_event(correlation_id, {
        "agent": "Test Agent",
        "message" : "Test Message",
        "status": "completed"
    })

    return {"success" : True}





