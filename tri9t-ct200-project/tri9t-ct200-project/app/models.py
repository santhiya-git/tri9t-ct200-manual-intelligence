from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def utcnow(): return datetime.now(timezone.utc)

class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_key: Mapped[str] = mapped_column(String(100), index=True, default="ct200")
    version_number: Mapped[int] = mapped_column(Integer, index=True)
    source_filename: Mapped[str] = mapped_column(String(255))
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    nodes: Mapped[list["DocumentNode"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("document_key", "version_number", name="uq_document_version"),)

class DocumentNode(Base):
    __tablename__ = "document_nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    logical_id: Mapped[str] = mapped_column(String(64), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    node_key: Mapped[str] = mapped_column(String(255), index=True)
    heading: Mapped[str] = mapped_column(Text)
    section_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    level: Mapped[int] = mapped_column(Integer)
    parent_node_id: Mapped[int | None] = mapped_column(ForeignKey("document_nodes.id"), nullable=True, index=True)
    body_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[DocumentVersion] = relationship(back_populates="nodes", foreign_keys=[version_id])
    parent: Mapped["DocumentNode | None"] = relationship(remote_side=[id], foreign_keys=[parent_node_id], back_populates="children")
    children: Mapped[list["DocumentNode"]] = relationship(back_populates="parent", foreign_keys=[parent_node_id], cascade="save-update")
    __table_args__ = (UniqueConstraint("version_id", "node_key", name="uq_node_path_per_version"), Index("ix_node_version_logical", "version_id", "logical_id"))

class Selection(Base):
    __tablename__ = "selections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    items: Mapped[list["SelectionItem"]] = relationship(back_populates="selection", cascade="all, delete-orphan")

class SelectionItem(Base):
    __tablename__ = "selection_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("document_nodes.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    logical_id: Mapped[str] = mapped_column(String(64), index=True)
    heading_snapshot: Mapped[str] = mapped_column(Text)
    text_snapshot: Mapped[str] = mapped_column(Text)
    content_hash_snapshot: Mapped[str] = mapped_column(String(64))
    selection: Mapped[Selection] = relationship(back_populates="items")
    node: Mapped[DocumentNode] = relationship(foreign_keys=[node_id])
    version: Mapped[DocumentVersion] = relationship(foreign_keys=[version_id])
