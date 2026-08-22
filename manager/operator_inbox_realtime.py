from manager.chat_realtime import RedisChatRealtime


class OperatorInboxRealtime(RedisChatRealtime):
    channel_prefix = "order-chat:operator-inbox:"
