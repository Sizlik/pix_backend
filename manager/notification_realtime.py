from manager.chat_realtime import RedisChatRealtime


class NotificationRealtime(RedisChatRealtime):
    channel_prefix = "notifications:user:"
