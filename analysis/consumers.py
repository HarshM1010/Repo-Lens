import json
from channels.generic.websocket import AsyncWebsocketConsumer


class JobProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.group_name = f"job_{self.job_id}"

        # Join room group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    # Receive message from room group
    async def job_update(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event['data']))


class DashboardStatsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = "dashboard_stats"

        # Join room group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    # Receive message from room group
    async def stats_update(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event['data']))
