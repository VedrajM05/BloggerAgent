from collections import defaultdict
from queue import Queue

event_queues = defaultdict(Queue)

def publish_event(correlationId : str,event: dict):
    print(f"publish_event {id(event_queues)}")
    event_queues[correlationId].put(event)

def get_queue(correlationId : str):
    print(f"get_queue {id(event_queues)}")
    return event_queues[correlationId]