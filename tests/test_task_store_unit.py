from datetime import date

from taskboard8_api.tasks.store import TaskStore


def test_empty_at_start() -> None:
    assert TaskStore().list() == []


def test_insertion_order_and_distinct_ids() -> None:
    s = TaskStore()
    for t in ("a", "b", "c"):
        s.add(t, None)
    tasks = s.list()
    assert [t.title for t in tasks] == ["a", "b", "c"]
    assert len({t.id for t in tasks}) == 3
    assert all(t.id for t in tasks)


def test_add_returns_task() -> None:
    t = TaskStore().add("a", date(2026, 12, 1))
    assert t.title == "a" and t.due_date == date(2026, 12, 1)


def test_list_returns_copy() -> None:
    s = TaskStore()
    s.add("a", None)
    s.list().clear()
    assert len(s.list()) == 1
