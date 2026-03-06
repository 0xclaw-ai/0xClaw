"""Message bus module for decoupled channel-agent communication."""

from runtime.bus.events import InboundMessage, OutboundMessage
from runtime.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
