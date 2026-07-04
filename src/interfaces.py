from abc import ABC, abstractmethod
from typing import Tuple
from src.models import Job


class DatabaseInterface(ABC):
    """Abstract interface for the database layer (DIP)."""

    @abstractmethod
    def save_job(self, job: Job) -> Tuple[bool, dict]:
        """
        Saves or updates a job in the database with deduplication.

        Returns:
            Tuple of (is_new, saved_document_dict)
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Closes the database connection."""
        ...


class VerifierInterface(ABC):
    """Abstract interface for verifying jobs (DIP)."""

    @abstractmethod
    def verify(self, job: Job, req_role: str, req_location: str, req_experience: str) -> bool:
        """
        Verifies if a scraped Job matches the requested Role, Location, and Experience.
        """
        ...

