from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    #: Empty for Supabase accounts — their password never reaches this service.
    hashed_password: Mapped[str] = mapped_column(String(255), default="")
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The Supabase user id (uuid). Present once the account has signed in.
    supabase_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    #: "admin" or "member". The only thing admin unlocks is Settings.
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    data_sources: Mapped[list[DataSource]] = relationship(back_populates="owner")
    queries: Mapped[list[Query]] = relationship(back_populates="user")
    dashboards: Mapped[list[Dashboard]] = relationship(back_populates="owner")

    @property
    def is_admin(self) -> bool:
        return (self.role or "member").strip().lower() == "admin"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50))  # file, mysql, postgres
    connection_config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    schema_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User | None] = relationship(back_populates="data_sources")
    queries: Mapped[list[Query]] = relationship(back_populates="data_source")


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    natural_language: Mapped[str] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    # Groups the questions asked in one sitting so history can show them together.
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Measured drivers and recommended actions, when the question asked why.
    diagnosis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="queries")
    data_source: Mapped[DataSource] = relationship(back_populates="queries")


class Conversation(Base):
    """A chat thread. Queries join to it through `Query.session_id`.

    The id is minted client-side when a chat starts, so the row is created
    lazily on the first question rather than up front.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    layout_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User | None] = relationship(back_populates="dashboards")


class AppConfig(Base):
    """Singleton row (id=1) for runtime AI + branding settings."""

    __tablename__ = "app_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
