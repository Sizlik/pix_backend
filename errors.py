class IntegrationNotConfigured(RuntimeError):
    def __init__(self, integration: str) -> None:
        self.integration = integration
        super().__init__(f"{integration} is not configured")
