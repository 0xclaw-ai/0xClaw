"""Chat channels module with plugin architecture."""

from runtime.channels.base import BaseChannel
from runtime.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
