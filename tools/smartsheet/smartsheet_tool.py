"""Smartsheet tool — Smartsheet REST API v2 via smartsheet-python-sdk.

Required credentials (set in tools_config.json or env vars):
  access_token : Smartsheet personal access token or app token.
                 Generate at: app.smartsheet.com → Account → Personal Settings → API Access

In tools_config.json, reference secrets as:
  "access_token": "env:SMARTSHEET_ACCESS_TOKEN"

Tools exported:
  READ
    list_smartsheet_sheets      - list all accessible sheets
    get_smartsheet_sheet        - get a sheet with all rows and column definitions
    get_smartsheet_row          - get a single row by row ID
    list_smartsheet_columns     - list columns of a sheet
    search_smartsheet           - full-text search across Smartsheet content

  CREATE
    create_smartsheet_sheet     - create a new sheet with defined columns
    add_smartsheet_rows         - add one or more rows to a sheet
    add_smartsheet_column       - add a column to a sheet

  UPDATE
    update_smartsheet_sheet     - rename or change a sheet
    update_smartsheet_rows      - update cell values in existing rows
    update_smartsheet_column    - update a column definition

  DELETE
    delete_smartsheet_sheet     - permanently delete a sheet
    delete_smartsheet_rows      - delete one or more rows
    delete_smartsheet_column    - delete a column from a sheet
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _client(cfg: dict):
    import smartsheet
    return smartsheet.Smartsheet(access_token=cfg.get("access_token", ""))


def _row_to_dict(row, columns: dict[int, str]) -> dict:
    """Convert a Smartsheet Row to a plain dict keyed by column name."""
    cells: dict = {}
    for cell in row.cells:
        col_name = columns.get(cell.column_id, str(cell.column_id))
        cells[col_name] = cell.value
    return {
        "row_id": row.id,
        "row_number": row.row_number,
        "cells": cells,
        "created_at": str(getattr(row, "created_at", "")),
        "modified_at": str(getattr(row, "modified_at", "")),
    }


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_smartsheet_sheets(page_size: int = 50) -> dict:
        """List all Smartsheet sheets accessible to the token.

        Args:
            page_size: Number of sheets to return (default 50, max 100).

        Returns:
            dict with list of sheets (id, name, permalink, created_at, modified_at).
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            resp = smart.Sheets.list_sheets(include_all=False, page_size=page_size)
            sheets = [
                {
                    "id": s.id,
                    "name": s.name,
                    "permalink": s.permalink,
                    "created_at": str(s.created_at),
                    "modified_at": str(s.modified_at),
                }
                for s in (resp.data or [])
            ]
            return {"sheets": sheets, "count": len(sheets), "total": resp.total_count}
        except Exception as exc:
            logger.error("Smartsheet list_sheets error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_smartsheet_sheet(sheet_id: int, max_rows: int = 100) -> dict:
        """Get a Smartsheet sheet with its columns and rows.

        Args:
            sheet_id: Numeric sheet ID (from list_smartsheet_sheets).
            max_rows: Maximum number of rows to return (default 100).

        Returns:
            dict with sheet name, columns, rows (keyed by column name), and permalink.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            sheet = smart.Sheets.get_sheet(sheet_id, page_size=max_rows)
            columns = {col.id: col.title for col in (sheet.columns or [])}
            rows = [_row_to_dict(row, columns) for row in (sheet.rows or [])]
            return {
                "id": sheet.id,
                "name": sheet.name,
                "permalink": sheet.permalink,
                "columns": [{"id": col.id, "title": col.title, "type": col.type} for col in (sheet.columns or [])],
                "rows": rows,
                "total_row_count": sheet.total_row_count,
            }
        except Exception as exc:
            logger.error("Smartsheet get_sheet error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_smartsheet_row(sheet_id: int, row_id: int) -> dict:
        """Get a single row from a Smartsheet sheet.

        Args:
            sheet_id: Numeric sheet ID.
            row_id: Numeric row ID.

        Returns:
            dict with row cells keyed by column name.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            sheet = smart.Sheets.get_sheet(sheet_id, row_ids=[row_id])
            columns = {col.id: col.title for col in (sheet.columns or [])}
            rows = sheet.rows or []
            if not rows:
                return {"status": "not_found", "message": f"Row {row_id} not found."}
            return _row_to_dict(rows[0], columns)
        except Exception as exc:
            logger.error("Smartsheet get_row error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_smartsheet_columns(sheet_id: int) -> dict:
        """List columns of a Smartsheet sheet.

        Args:
            sheet_id: Numeric sheet ID.

        Returns:
            dict with list of columns (id, title, type, index).
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            resp = smart.Sheets.get_columns(sheet_id)
            cols = [
                {"id": col.id, "title": col.title, "type": col.type, "index": col.index}
                for col in (resp.data or [])
            ]
            return {"columns": cols, "count": len(cols)}
        except Exception as exc:
            logger.error("Smartsheet list_columns error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_smartsheet(query: str, scope: str = "workspaceAndFolders") -> dict:
        """Full-text search across Smartsheet content.

        Args:
            query: Search term.
            scope: Search scope — 'workspaceAndFolders' (default) or a specific
                   sheet/workspace name hint (results include all types).

        Returns:
            dict with list of matching results (objectType, objectId, parentName, text).
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            resp = smart.Search.search(query)
            results = [
                {
                    "object_type": r.object_type,
                    "object_id": r.object_id,
                    "text": r.text,
                    "parent_name": getattr(r, "parent_name", ""),
                    "parent_type": getattr(r, "parent_type", ""),
                }
                for r in (resp.results or [])
            ]
            return {"results": results, "count": len(results), "total": resp.total_count}
        except Exception as exc:
            logger.error("Smartsheet search error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_smartsheet_sheet(name: str, columns: list[dict]) -> dict:
        """Create a new Smartsheet sheet with specified columns.

        Args:
            name: Sheet name.
            columns: List of column definitions. Each dict must have:
                     - 'title' (str): Column name.
                     - 'type' (str): Column type — 'TEXT_NUMBER', 'DATE',
                       'CHECKBOX', 'CONTACT_LIST', 'PICKLIST', 'DURATION',
                       'PREDECESSOR', 'AUTO_NUMBER'. Default 'TEXT_NUMBER'.
                     - 'primary' (bool, optional): Set True for the primary column
                       (exactly one column must be primary). Default: first column.
            Example: [{"title": "Task", "type": "TEXT_NUMBER", "primary": True},
                      {"title": "Due Date", "type": "DATE"}]

        Returns:
            dict with created sheet id, name, and permalink.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            col_objs = []
            for i, c in enumerate(columns):
                col = smart.models.Column()
                col.title = c["title"]
                col.type = c.get("type", "TEXT_NUMBER")
                col.primary = c.get("primary", i == 0)
                col_objs.append(col)

            sheet_spec = smart.models.Sheet()
            sheet_spec.name = name
            sheet_spec.columns = col_objs
            result = smart.Home.create_sheet(sheet_spec)
            s = result.result
            return {
                "id": s.id,
                "name": s.name,
                "permalink": s.permalink,
                "status": "created",
            }
        except Exception as exc:
            logger.error("Smartsheet create_sheet error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_smartsheet_rows(sheet_id: int, rows: list[dict]) -> dict:
        """Add one or more rows to a Smartsheet sheet.

        Args:
            sheet_id: Numeric sheet ID.
            rows: List of row dicts. Each dict maps column title to cell value.
                  Example: [{"Task Name": "Deploy v2", "Status": "Not Started", "Due Date": "2025-01-15"}]
                  Use 'to_top': True or 'to_bottom': True (default) to control position.

        Returns:
            dict with list of created row IDs.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            sheet = smart.Sheets.get_sheet(sheet_id)
            col_map = {col.title: col.id for col in (sheet.columns or [])}

            row_objs = []
            for row_data in rows:
                row_data = dict(row_data)
                row = smart.models.Row()
                row.to_bottom = row_data.pop("to_bottom", True)
                if row_data.pop("to_top", False):
                    row.to_bottom = False
                    row.to_top = True
                for col_title, value in row_data.items():
                    col_id = col_map.get(col_title)
                    if col_id:
                        row.cells.append({"column_id": col_id, "value": value})
                row_objs.append(row)

            result = smart.Sheets.add_rows(sheet_id, row_objs)
            added = [r.id for r in (result.result or [])]
            return {"added_row_ids": added, "count": len(added), "status": "added"}
        except Exception as exc:
            logger.error("Smartsheet add_rows error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_smartsheet_column(
        sheet_id: int,
        title: str,
        column_type: str = "TEXT_NUMBER",
        index: int | None = None,
    ) -> dict:
        """Add a new column to a Smartsheet sheet.

        Args:
            sheet_id: Numeric sheet ID.
            title: Column title/name.
            column_type: Column type — 'TEXT_NUMBER' (default), 'DATE',
                         'CHECKBOX', 'CONTACT_LIST', 'PICKLIST', 'DURATION'.
            index: Zero-based position to insert the column. Appends to end if omitted.

        Returns:
            dict with new column id, title, and type.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            col = smart.models.Column()
            col.title = title
            col.type = column_type
            if index is not None:
                col.index = index
            result = smart.Sheets.add_columns(sheet_id, [col])
            c = result.result[0]
            return {"id": c.id, "title": c.title, "type": c.type, "status": "added"}
        except Exception as exc:
            logger.error("Smartsheet add_column error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_smartsheet_sheet(sheet_id: int, name: str) -> dict:
        """Rename a Smartsheet sheet.

        Args:
            sheet_id: Numeric sheet ID.
            name: New sheet name.

        Returns:
            dict with sheet id and new name.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            sheet_spec = smart.models.Sheet()
            sheet_spec.name = name
            result = smart.Sheets.update_sheet(sheet_id, sheet_spec)
            s = result.result
            return {"id": s.id, "name": s.name, "status": "updated"}
        except Exception as exc:
            logger.error("Smartsheet update_sheet error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_smartsheet_rows(sheet_id: int, rows: list[dict]) -> dict:
        """Update cell values in existing Smartsheet rows.

        Args:
            sheet_id: Numeric sheet ID.
            rows: List of row update dicts. Each dict must include 'row_id' (int)
                  plus column title/value pairs to update.
                  Example: [{"row_id": 7777777, "Status": "Complete", "Due Date": "2025-03-01"}]

        Returns:
            dict with count of updated rows.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            sheet = smart.Sheets.get_sheet(sheet_id)
            col_map = {col.title: col.id for col in (sheet.columns or [])}

            row_objs = []
            for row_data in rows:
                row_data = dict(row_data)
                row = smart.models.Row()
                row.id = row_data.pop("row_id")
                for col_title, value in row_data.items():
                    col_id = col_map.get(col_title)
                    if col_id:
                        row.cells.append({"column_id": col_id, "value": value})
                row_objs.append(row)

            result = smart.Sheets.update_rows(sheet_id, row_objs)
            updated = [r.id for r in (result.result or [])]
            return {"updated_row_ids": updated, "count": len(updated), "status": "updated"}
        except Exception as exc:
            logger.error("Smartsheet update_rows error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_smartsheet_column(
        sheet_id: int,
        column_id: int,
        title: str = "",
        column_type: str = "",
        index: int | None = None,
    ) -> dict:
        """Update a Smartsheet column definition (rename, change type, or reposition).

        Args:
            sheet_id: Numeric sheet ID.
            column_id: Numeric column ID (from list_smartsheet_columns).
            title: New column title. Leave blank to keep existing.
            column_type: New column type. Leave blank to keep existing.
            index: New zero-based position for the column. Leave blank to keep existing position.

        Returns:
            dict with column id, new title, and type.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            col = smart.models.Column()
            if index is not None:
                col.index = index
            if title:
                col.title = title
            if column_type:
                col.type = column_type
            result = smart.Sheets.update_column(sheet_id, column_id, col)
            c = result.result
            return {"id": c.id, "title": c.title, "type": c.type, "status": "updated"}
        except Exception as exc:
            logger.error("Smartsheet update_column error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_smartsheet_sheet(sheet_id: int) -> dict:
        """Permanently delete a Smartsheet sheet.

        WARNING: This is irreversible. The sheet and all its data are permanently removed.

        Args:
            sheet_id: Numeric sheet ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            smart.Sheets.delete_sheet(sheet_id)
            return {"sheet_id": sheet_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Smartsheet delete_sheet error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_smartsheet_rows(sheet_id: int, row_ids: list[int]) -> dict:
        """Delete one or more rows from a Smartsheet sheet.

        Args:
            sheet_id: Numeric sheet ID.
            row_ids: List of numeric row IDs to delete.

        Returns:
            dict with count of deleted rows.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            smart.Sheets.delete_rows(sheet_id, row_ids)
            return {"deleted_row_ids": row_ids, "count": len(row_ids), "status": "deleted"}
        except Exception as exc:
            logger.error("Smartsheet delete_rows error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_smartsheet_column(sheet_id: int, column_id: int) -> dict:
        """Delete a column from a Smartsheet sheet.

        Args:
            sheet_id: Numeric sheet ID.
            column_id: Numeric column ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("smartsheet")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Smartsheet tool is currently disabled."}
        try:
            smart = _client(cfg.config)
            smart.Sheets.delete_column(sheet_id, column_id)
            return {"sheet_id": sheet_id, "column_id": column_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Smartsheet delete_column error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_smartsheet_sheets,
        get_smartsheet_sheet,
        get_smartsheet_row,
        list_smartsheet_columns,
        search_smartsheet,
        # Create
        create_smartsheet_sheet,
        add_smartsheet_rows,
        add_smartsheet_column,
        # Update
        update_smartsheet_sheet,
        update_smartsheet_rows,
        update_smartsheet_column,
        # Delete
        delete_smartsheet_sheet,
        delete_smartsheet_rows,
        delete_smartsheet_column,
    ]
