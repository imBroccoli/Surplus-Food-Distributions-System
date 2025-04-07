import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import caches
from django.utils import timezone


class BusinessAnalyticsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Handle WebSocket connection"""
        if not self.scope["user"].is_authenticated:
            await self.close()
            return

        if self.scope["user"].user_type != "BUSINESS":
            await self.close()
            return

        self.user = self.scope["user"]
        self.room_name = f"business_analytics_{self.user.id}"
        self.room_group_name = f"analytics_{self.room_name}"

        # Join room group
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            text_data_json = json.loads(text_data)
            action = text_data_json.get("action")

            if action == "fetch_metrics":
                # Fetch and send latest metrics
                metrics = await self.get_latest_metrics()
                await self.send_metrics(metrics)

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "Invalid message format"}))

    async def analytics_update(self, event):
        """Handler for analytics update events"""
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event["data"]))

    @database_sync_to_async
    def get_latest_metrics(self):
        """Get latest analytics metrics from cache or database"""
        analytics_cache = caches["analytics"]
        cache_key = f"business_analytics_{self.user.id}"

        # Try to get from cache first
        cached_data = analytics_cache.get(cache_key)
        if cached_data:
            return cached_data

        # If not in cache, return empty data (will be updated by middleware)
        return {
            "metrics": {
                "total_listings": 0,
                "total_requests": 0,
                "food_saved": 0,
                "success_rate": 0,
            },
            "last_updated": timezone.now().isoformat(),
        }

    async def send_metrics(self, metrics):
        """Send metrics update to client"""
        await self.send(
            text_data=json.dumps({"type": "metrics_update", "data": metrics})
        )
