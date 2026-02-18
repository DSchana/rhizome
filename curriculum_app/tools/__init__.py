"""Database tool functions for the curriculum agent."""

from .curricula import (
    add_topic_to_curriculum,
    create_curriculum,
    delete_curriculum,
    get_curriculum,
    list_curricula,
    list_topics_in_curriculum,
    remove_topic_from_curriculum,
    reorder_topic_in_curriculum,
    update_curriculum,
)
from .entries import (
    create_entry,
    delete_entry,
    get_entry,
    list_entries,
    search_entries,
    update_entry,
)
from .relations import (
    CycleError,
    add_relation,
    get_dependency_chain,
    get_related_entries,
    remove_relation,
)
from .tags import (
    create_tag,
    get_entries_by_tag,
    list_tags,
    tag_entry,
    untag_entry,
)
from .topics import (
    create_topic,
    delete_topic,
    get_subtree,
    get_topic,
    list_children,
    list_root_topics,
    update_topic,
)

__all__ = [
    # curricula
    "create_curriculum",
    "get_curriculum",
    "list_curricula",
    "update_curriculum",
    "delete_curriculum",
    "add_topic_to_curriculum",
    "remove_topic_from_curriculum",
    "reorder_topic_in_curriculum",
    "list_topics_in_curriculum",
    # topics
    "create_topic",
    "get_topic",
    "list_root_topics",
    "list_children",
    "get_subtree",
    "update_topic",
    "delete_topic",
    # entries
    "create_entry",
    "get_entry",
    "list_entries",
    "update_entry",
    "delete_entry",
    "search_entries",
    # tags
    "create_tag",
    "list_tags",
    "tag_entry",
    "untag_entry",
    "get_entries_by_tag",
    # relations
    "CycleError",
    "add_relation",
    "remove_relation",
    "get_related_entries",
    "get_dependency_chain",
]
