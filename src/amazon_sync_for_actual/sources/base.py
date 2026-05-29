"""Base interface every Amazon order source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import AmazonOrder

__all__ = ["AmazonSource"]


class AmazonSource(ABC):
    """Produces :class:`~amazon_sync_for_actual.models.AmazonOrder` objects."""

    @abstractmethod
    def fetch_orders(self) -> List[AmazonOrder]:
        """Return all available Amazon orders from this source."""
        raise NotImplementedError
