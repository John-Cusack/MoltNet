"""Custom exception hierarchy for MoltNet."""


class MoltNetError(Exception):
    """Base exception for all MoltNet errors."""

    pass


class RegistryError(MoltNetError):
    """Error related to the LLM registry."""

    pass


class ModelNotFoundError(RegistryError):
    """Requested model not found in registry."""

    def __init__(self, model_key: str):
        self.model_key = model_key
        super().__init__(f"Model not found: {model_key}")


class BackendError(MoltNetError):
    """Error from an LLM backend."""

    def __init__(self, backend: str, message: str):
        self.backend = backend
        super().__init__(f"[{backend}] {message}")


class BudgetExceededError(MoltNetError):
    """Budget limit exceeded for current cycle."""

    def __init__(self, spent: float, limit: float):
        self.spent = spent
        self.limit = limit
        super().__init__(f"Budget exceeded: ${spent:.4f} spent, limit ${limit:.4f}")
