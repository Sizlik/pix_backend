class IntegrationNotConfigured(RuntimeError):
    def __init__(self, integration: str) -> None:
        self.integration = integration
        super().__init__(f"{integration} is not configured")


class LinkPreviewValidationError(ValueError):
    def __init__(self) -> None:
        super().__init__("URL is not allowed")


class OrderNotAccessible(RuntimeError):
    pass


class OrderNotEditable(RuntimeError):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__("order is not editable")


class OrderVersionConflict(RuntimeError):
    pass


class InvalidOrderChanges(ValueError):
    pass
