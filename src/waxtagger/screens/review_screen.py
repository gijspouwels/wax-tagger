"""
Screen 4: Review batch results, accept/skip per track, apply changes.
"""

import asyncio
from typing import TYPE_CHECKING

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from waxtagger.enricher import TrackResult, apply_changes, write_log
from waxtagger import config

if TYPE_CHECKING:
    from waxtagger.app import WaxTaggerApp


class ReviewScreen:
    def __init__(self, app: "WaxTaggerApp", results: list[TrackResult], mode: str = "auto"):
        self.app = app
        self.results = results
        self.mode = mode
        self._window: toga.Window = None

        # Per-row skip state (index → bool)
        self._skip_states: dict[int, bool] = {}

    def build_window(self) -> toga.Window:
        style_col = Pack(direction=COLUMN, margin=12, flex=1)

        # ── Summary header ────────────────────────────────────────────────────
        found   = sum(1 for r in self.results if r.status in ("found", "pinned"))
        not_found = sum(1 for r in self.results if r.status == "not_found")
        errors  = sum(1 for r in self.results if r.status == "error")
        header_text = (
            f"{found} tracks with matches  ·  "
            f"{not_found} not found  ·  "
            f"{errors} errors"
        )
        header = toga.Label(
            header_text,
            style=Pack(margin=(0, 0, 8, 0), font_size=13),
        )

        # ── Table ─────────────────────────────────────────────────────────────
        # Toga Table: columns as list of headings, data as list of tuples
        table_data = []
        for i, r in enumerate(self.results):
            changes_summary = self._changes_summary(r)
            action_label = "skip" if r.status in ("not_found", "error") else "accept"
            self._skip_states[i] = r.status in ("not_found", "error")
            table_data.append((
                r.track.title,
                r.track.artist,
                r.source_used.capitalize() if r.source_used else "—",
                changes_summary,
                action_label,
            ))

        self._table = toga.Table(
            headings=["Track", "Artist", "Source", "Proposed changes", "Action"],
            data=table_data,
            style=Pack(flex=1),
            on_select=self._on_row_select,
        )

        # ── Buttons ───────────────────────────────────────────────────────────
        apply_btn = toga.Button(
            "Apply",
            on_press=self._on_apply,
            style=Pack(margin=4),
        )
        dry_btn = toga.Button(
            "Dry Run Preview",
            on_press=self._on_dry_preview,
            style=Pack(margin=4),
        )
        toggle_btn = toga.Button(
            "Toggle selected",
            on_press=self._on_toggle_selected,
            style=Pack(margin=4),
        )
        cancel_btn = toga.Button(
            "Cancel",
            on_press=self._on_cancel,
            style=Pack(margin=4),
        )

        btn_row = toga.Box(
            children=[toggle_btn, dry_btn, apply_btn, cancel_btn],
            style=Pack(direction=ROW, margin=(8, 0, 0, 0), align_items="end"),
        )

        self._status_label = toga.Label("", style=Pack(flex=1, margin=(4, 0)))

        content = toga.Box(
            children=[header, self._table, self._status_label, btn_row],
            style=style_col,
        )

        self._window = toga.Window(title="WaxTagger — Review Results", size=(900, 600))
        self._window.content = content
        return self._window

    def _changes_summary(self, result: TrackResult) -> str:
        if result.status == "not_found":
            return "No match found"
        if result.status == "error":
            return f"Error: {result.error or 'unknown'}"
        if not result.proposed_changes:
            return "Nothing to change"
        fields = [c.field for c in result.proposed_changes]
        return ", ".join(fields)

    def _on_row_select(self, widget, row):
        pass  # Selection is tracked; toggle via button

    def _on_toggle_selected(self, widget):
        """Toggle skip state for selected row."""
        if self._table.selection is None:
            return
        # Find index of selected row
        selected = self._table.selection
        # toga Table data is indexed by row object; use linear search
        for i, row in enumerate(self._table.data):
            if row == selected:
                self._skip_states[i] = not self._skip_states.get(i, False)
                # Update action column text
                action = "skip" if self._skip_states[i] else "accept"
                # Rebuild table data for that row
                r = self.results[i]
                self._table.data[i] = (
                    r.track.title,
                    r.track.artist,
                    r.source_used.capitalize() if r.source_used else "—",
                    self._changes_summary(r),
                    action,
                )
                break

    async def _on_apply(self, widget):
        await self._run_apply(dry=False)

    async def _on_dry_preview(self, widget):
        await self._run_apply(dry=True)

    async def _run_apply(self, dry: bool):
        mode = "dry" if dry else self.mode
        to_apply = [
            r for i, r in enumerate(self.results)
            if not self._skip_states.get(i, False) and r.chosen is not None
        ]

        if not to_apply:
            await self._window.dialog(toga.InfoDialog("Nothing to apply", "All tracks are skipped or have no match."))
            return

        self._status_label.text = f"{'Previewing' if dry else 'Applying'} {len(to_apply)} tracks…"

        loop = asyncio.get_event_loop()
        log_entries = []

        def do_apply():
            entries = []
            for result in to_apply:
                entry = apply_changes(result, self.app.registry, mode=mode)
                entries.append(entry)
            return entries

        try:
            log_entries = await loop.run_in_executor(None, do_apply)
        except Exception as e:
            self._status_label.text = f"Error: {e}"
            return

        updated = sum(1 for e in log_entries if e.get("status") == "updated")
        dry_count = sum(1 for e in log_entries if e.get("status") == "dry_run")

        if dry:
            msg = f"Dry run complete: {dry_count} tracks would be updated."
        else:
            # Write log
            log_path = await loop.run_in_executor(
                None, lambda: write_log(log_entries, config.LOG_DIR)
            )
            msg = f"Done! {updated} tracks updated.\nLog: {log_path}"

        self._status_label.text = msg
        await self._window.dialog(toga.InfoDialog("Done", msg))

        if not dry:
            self._window.close()

    def _on_cancel(self, widget):
        self._window.close()
