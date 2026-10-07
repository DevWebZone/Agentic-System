from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.shortener.models import ClickEvent, Link


class LinkRepository:
    """Database operations for links and their aggregate analytics."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_code(self, short_code: str) -> Link | None:
        return self.session.scalar(select(Link).where(Link.short_code == short_code))

    def add_link(self, link: Link) -> Link:
        self.session.add(link)
        self.session.flush()
        self.session.refresh(link)
        return link

    def add_click_event(self, link: Link, referrer: str | None, user_agent: str | None) -> None:
        self.session.add(ClickEvent(link_id=link.id, referrer=referrer, user_agent=user_agent))
        link.last_accessed_at = datetime.now().astimezone()

    def analytics_by_day(self, link_id: int) -> Sequence[tuple[str, int]]:
        day = func.date(ClickEvent.clicked_at)
        statement: Select[tuple[str, int]] = (
            select(day, func.count(ClickEvent.id))
            .where(ClickEvent.link_id == link_id)
            .group_by(day)
            .order_by(day)
        )
        return self.session.execute(statement).all()

    def click_count(self, link_id: int) -> int:
        return (
            self.session.scalar(
                select(func.count(ClickEvent.id)).where(ClickEvent.link_id == link_id)
            )
            or 0
        )
