"""Central capability and provenance contracts for Harness tool profiles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolProfile:
    name: str
    tools: frozenset[str]
    evidence_source: str
    requires_workspace: bool = False
    permits_writes: bool = False


TOOL_PROFILES = {
    "public_research": ToolProfile("public_research", frozenset({
        "search_web", "fetch_page"}), "web_page"),
    "workspace_read": ToolProfile("workspace_read", frozenset({
        "list_workspace_files", "find_workspace_files", "read_workspace_file",
        "read_workspace_document_chunk", "search_workspace_text",
    }), "repository", requires_workspace=True),
    "workspace_git": ToolProfile("workspace_git", frozenset({
        "get_workspace_git_status", "get_workspace_git_log", "get_workspace_git_diff",
        "get_workspace_git_commit", "compare_workspace_git_revisions",
        "read_workspace_file_at_revision", "get_workspace_file_history",
    }), "repository", requires_workspace=True),
    "workspace_coding": ToolProfile("workspace_coding", frozenset({
        "list_workspace_files", "find_workspace_files", "read_workspace_file",
        "read_workspace_document_chunk", "search_workspace_text",
        "replace_workspace_text", "write_workspace_file", "run_workspace_check",
    }), "repository", requires_workspace=True, permits_writes=True),
    "google_workspace": ToolProfile("google_workspace", frozenset({
        "search_mail", "read_mail", "send_email", "search_drive", "read_drive_text",
        "create_drive_folder", "upload_drive_text", "upload_drive_image", "create_google_doc",
        "append_google_doc_text", "create_google_sheet", "read_google_sheet",
        "update_google_sheet", "append_google_sheet_rows",
    }), "external_message", permits_writes=True),
}


def get_tool_profile(name: str) -> ToolProfile:
    try:
        return TOOL_PROFILES[name]
    except KeyError as exc:
        raise ValueError("unknown Harness tool profile") from exc
