"""Shared service objects handed to every tool module."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .db import ThingsDB
from .permissions import Guard
from .writer import Writer


@dataclass
class Services:
    config: Config
    db: ThingsDB
    writer: Writer
    guard: Guard

    @classmethod
    def build(cls) -> "Services":
        config = Config.load()
        db = ThingsDB(config)
        return cls(
            config=config,
            db=db,
            writer=Writer(config, db),
            guard=Guard(config, db),
        )
