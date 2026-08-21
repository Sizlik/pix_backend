class IntegrationNotConfigured(RuntimeError):
    def __init__(self, integration: str) -> None:
        self.integration = integration
        super().__init__(f"{integration} is not configured")


class MoySkladDocumentExportError(RuntimeError):
    def __init__(self, reason: str, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__("MoySklad document export failed")


class MoySkladOrderLookupUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("MoySklad order lookup unavailable")


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


class MoySkladOrderStateMissing(RuntimeError):
    def __init__(self, state_name: str) -> None:
        self.state_name = state_name
        super().__init__("required MoySklad order state is missing")


class AddressNotFound(LookupError):
    pass


class AddressNameConflict(ValueError):
    pass


class IdempotencyKeyReused(RuntimeError):
    pass


class OrderCreationInProgress(RuntimeError):
    pass


class OrderCreationIdempotencyUnavailable(RuntimeError):
    pass
