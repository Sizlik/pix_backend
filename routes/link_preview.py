from fastapi import APIRouter, Depends, HTTPException

from db.models.users import User
from db.schemas.link_preview import LinkTitleRequest, LinkTitleResponse
from dependecies.link_preview import get_link_preview_manager
from errors import LinkPreviewValidationError
from manager.link_preview import LinkPreviewManager
from routes.users import current_user_dependency

router = APIRouter(prefix="/link-preview", tags=["Link preview"])


@router.post("/title", response_model=LinkTitleResponse)
async def get_link_title(
    request: LinkTitleRequest,
    _user: User = Depends(current_user_dependency),
    manager: LinkPreviewManager = Depends(get_link_preview_manager),
):
    try:
        title = await manager.get_title(str(request.url))
    except LinkPreviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return LinkTitleResponse(title=title)
