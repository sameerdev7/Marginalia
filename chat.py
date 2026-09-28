from fastapi import WebSocket


class ConnectionManager:
    """Tracks live WebSocket connections per group, in-memory.

    Single-process only — fine for one `uv run fastapi dev` worker, but a
    second worker/process wouldn't see the other's connections. A real
    deployment with multiple workers needs a pub/sub broker (Redis) in front
    of this; not needed at this project's current scale.
    """

    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}

    def connect(self, group_id: int, websocket: WebSocket) -> None:
        self.active_connections.setdefault(group_id, []).append(websocket)

    def disconnect(self, group_id: int, websocket: WebSocket) -> None:
        connections = self.active_connections.get(group_id)
        if not connections:
            return
        connections.remove(websocket)
        if not connections:
            del self.active_connections[group_id]

    async def broadcast(self, group_id: int, message: dict) -> None:
        for connection in self.active_connections.get(group_id, []):
            await connection.send_json(message)


manager = ConnectionManager()
