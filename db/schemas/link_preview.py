from pydantic import AnyHttpUrl, BaseModel, field_validator


class LinkTitleRequest(BaseModel):
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def reject_embedded_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("URL credentials are not allowed")
        return value


class LinkTitleResponse(BaseModel):
    title: str | None
