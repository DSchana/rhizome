import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    JSON,
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


class Topic(Base):
    __tablename__ = "topic"
    __table_args__ = (UniqueConstraint("parent_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic.id", ondelete="CASCADE"), nullable=True, index=True
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
        ForeignKey("topic.id", ondelete="CASCADE"), nullable=False, index=True
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
        ForeignKey("knowledge_entry.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)


class RelatedKnowledgeEntries(Base):
    __tablename__ = "related_knowledge_entries"
    __table_args__ = (
        CheckConstraint("source_entry_id != target_entry_id", name="no_self_loop"),
    )

    source_entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id", ondelete="CASCADE"), primary_key=True
    )
    target_entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id", ondelete="CASCADE"), primary_key=True
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


class ReviewSession(Base):
    __tablename__ = "review_session"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ephemeral: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    started_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    additional_args: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    session_topics: Mapped[list["ReviewSessionTopic"]] = relationship(
        cascade="all, delete-orphan"
    )
    session_entries: Mapped[list["ReviewSessionEntry"]] = relationship(
        cascade="all, delete-orphan"
    )
    interactions: Mapped[list["ReviewInteraction"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    flashcards: Mapped[list["Flashcard"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ReviewSession id={self.id} ephemeral={self.ephemeral} started_at={self.started_at}>"


class ReviewSessionTopic(Base):
    __tablename__ = "review_session_topic"
    __table_args__ = (UniqueConstraint("session_id", "topic_id"),)

    session_id: Mapped[int] = mapped_column(
        ForeignKey("review_session.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<ReviewSessionTopic session={self.session_id} topic={self.topic_id}>"


class ReviewSessionEntry(Base):
    __tablename__ = "review_session_entry"
    __table_args__ = (UniqueConstraint("session_id", "entry_id"),)

    session_id: Mapped[int] = mapped_column(
        ForeignKey("review_session.id", ondelete="CASCADE"), primary_key=True
    )
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<ReviewSessionEntry session={self.session_id} entry={self.entry_id}>"


class Flashcard(Base):
    __tablename__ = "flashcard"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_session.id", ondelete="CASCADE"), nullable=True, index=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    testing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["ReviewSession | None"] = relationship(back_populates="flashcards")
    flashcard_entries: Mapped[list["FlashcardEntry"]] = relationship(
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Flashcard id={self.id} topic={self.topic_id} session={self.session_id}>"


class FlashcardEntry(Base):
    __tablename__ = "flashcard_entry"
    __table_args__ = (UniqueConstraint("flashcard_id", "entry_id"),)

    flashcard_id: Mapped[int] = mapped_column(
        ForeignKey("flashcard.id", ondelete="CASCADE"), primary_key=True
    )
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<FlashcardEntry flashcard={self.flashcard_id} entry={self.entry_id}>"


class ReviewInteraction(Base):
    __tablename__ = "review_interaction"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 5", name="score_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("review_session.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flashcard_id: Mapped[int | None] = mapped_column(
        ForeignKey("flashcard.id", ondelete="SET NULL"), nullable=True, index=True
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_response: Mapped[str] = mapped_column(Text, nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    session: Mapped["ReviewSession"] = relationship(back_populates="interactions")
    interaction_entries: Mapped[list["ReviewInteractionEntry"]] = relationship(
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewInteraction id={self.id} session={self.session_id} "
            f"pos={self.position} score={self.score}>"
        )


class ReviewInteractionEntry(Base):
    __tablename__ = "review_interaction_entry"
    __table_args__ = (UniqueConstraint("interaction_id", "entry_id"),)

    interaction_id: Mapped[int] = mapped_column(
        ForeignKey("review_interaction.id", ondelete="CASCADE"), primary_key=True
    )
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entry.id", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<ReviewInteractionEntry interaction={self.interaction_id} entry={self.entry_id}>"
