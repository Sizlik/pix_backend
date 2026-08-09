from db.link_preview_repository import LinkPreviewRepository
from manager.link_preview import LinkPreviewManager


async def get_link_preview_manager():
    yield LinkPreviewManager(LinkPreviewRepository())
