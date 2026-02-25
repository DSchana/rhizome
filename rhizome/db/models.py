import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class EntryType(enum.Enum):
    fact = "fact"
    exposition = "exposition"
    overview = "overview"


class Base(DeclarativeBase):
    pass


class Curriculum(Base):
    __tablename__ = "curriculum"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    curriculum_topics: Mapped[list["CurriculumTopic"]] = relationship(
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Curriculum id={self.id} name={self.name!r}>"


class CurriculumTopic(Base):
    __tablename__ = "curriculum_topic"
    __table_args__ = (UniqueConstraint("curriculum_id", "topic_id"),)

    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum.id"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    def __repr__(self) -> str:
        return (
            f"<CurriculumTopic curriculum={self.curriculum_id} "
            f"topic={self.topic_id} pos={self.position}>"
        )


class Topic(Base):
    __tablename__ = "topic"
    __table_args__ = (UniqueConstraint("parent_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    parent: Mapped["Topic | None"] = relationship(
        back_populates="children", remote_side="Topic.id"
    )
    children: Mapped[list["Topic"]] = relationship(back_populates="parent")
    entries: Mapped[list["KnowledgeEntry"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Topic id={self.id} name={self.name!r}>"


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entry"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    additional_notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    entry_type: Mapped[EntryType | None] = mapped_column(Enum(EntryType), nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_testable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    topic: Mapped["Topic"] = relationship(back_populates="entries")
    tags: Mapped[list["Tag"]] = relationship(
        secondary="knowledge_entry_tag", back_populates="entries"
    )

    # Entries this entry points TO (outgoing edges)
    related_targets: Mapped[list["RelatedKnowledgeEntries"]] = relationship(
        foreign_keys="RelatedKnowledgeEntries.source_entry_id",
        back_populates="source_entry",
        cascade="all, delete-orphan",
    )
    # Entries that point AT this entry (incoming edges)
    related_sources: Mapped[list["RelatedKnowledgeEntries"]] = relationship(
        foreign_keys="RelatedKnowledgeEntries.target_entry_id",
        back_populates="target_entry",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeEntry id={self.id} title={self.title!r}>"


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    entries: Mapped[list["KnowledgeEntry"]] = relationship(
        secondary="knowledge_entry_tag", back_populates="tags"
    )

    def __repr__(self) -> str:
        return f"<Tag id={self.id} name={self.name!r}>"


class KnowledgeEntryTag(Base):
    __tablename__ = "knowledge_entry_tag"

    knowledge_entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)


class RelatedKnowledgeEntries(Base):
    __tablename__ = "related_knowledge_entries"
    __table_args__ = (
        CheckConstraint("source_entry_id != target_entry_id", name="no_self_loop"),
    )

    source_entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id"), primary_key=True
    )
    target_entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id"), primary_key=True
    )
    relationship_type: Mapped[str] = mapped_column(String, nullable=False)

    source_entry: Mapped["KnowledgeEntry"] = relationship(
        foreign_keys=[source_entry_id], back_populates="related_targets"
    )
    target_entry: Mapped["KnowledgeEntry"] = relationship(
        foreign_keys=[target_entry_id], back_populates="related_sources"
    )

    def __repr__(self) -> str:
        return (
            f"<RelatedKnowledgeEntries "
            f"source={self.source_entry_id} -> target={self.target_entry_id} "
            f"type={self.relationship_type!r}>"
        )
