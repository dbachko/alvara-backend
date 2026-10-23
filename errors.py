"""Domain-specific errors with stable HTTP mappings."""


class AlvaraError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(AlvaraError):
    """The process configuration is incomplete or unsafe."""


class InvalidTokenId(AlvaraError):
    """A requested token identifier is malformed or out of range."""


class TokenNotFound(AlvaraError):
    """The contract reports that a token does not exist."""


class InvalidGenome(AlvaraError):
    """The contract returned a genome that cannot be rendered safely."""


class ArtifactNotFound(AlvaraError):
    """A requested local artifact has not been generated."""


class ArtifactGenerationError(AlvaraError):
    """A deterministic artifact could not be generated."""


class StatePersistenceError(AlvaraError):
    """Persisted generator state is invalid or cannot be saved."""


class UpstreamUnavailable(AlvaraError):
    """The configured chain data source could not answer safely."""
