from manager.chat import ChatManager, ChatRoomRepository, ChatRoomManager, MessageRepository, MessageManager


def get_chat_manager():
    return ChatManager(get_message_manager())


def get_chat_room_manager():
    return ChatRoomManager(ChatRoomRepository())


def get_message_manager():
    return MessageManager(MessageRepository())

