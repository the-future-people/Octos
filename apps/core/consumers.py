# apps/core/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class BranchConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for branch-scoped real-time invalidation signals.

    Each connected client joins a group named 'branch_<id>'.
    Any broadcast to that group reaches all connected clients instantly.
    No business data travels over this socket — only invalidation event names.
    """

    async def connect(self):
        user = self.scope.get('user')

        # Reject anonymous or unauthenticated connections immediately
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        # Derive branch id from the authenticated user — never trust the client
        branch = getattr(user, 'branch', None)
        if branch is None:
            await self.close(code=4002)
            return

        branch_id = branch.id if hasattr(branch, 'id') else int(branch)
        self.group_name = f'branch_{branch_id}'

        # Join the branch group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )

    # Receive a message from the client — we don't act on client messages
    # but we must implement this method to avoid errors
    async def receive(self, text_data=None, bytes_data=None):
        pass

    # Called by channel layer when group_send delivers an invalidation event
    async def branch_invalidate(self, event):
        await self.send(text_data=json.dumps({
            'type':   'invalidate',
            'events': event['events'],
        }))