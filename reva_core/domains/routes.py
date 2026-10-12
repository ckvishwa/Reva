"""`/v1/domains/*` and `/v1/today`: HTTP to Kernel calls, nothing else (AR-CORE-009).

Deliberately does NOT use `from __future__ import annotations`; see the note in
`reva_core/api/routes.py` about FastAPI and closure dependencies.
"""

import base64
import binascii
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from reva_core.api.auth import build_auth_dependency
from reva_core.domains.service import DomainRequestError, DomainService, translate
from reva_core.orchestration.lifecycle import CoreLifecycle

# collection -> (Kernel aggregate type, list query, create command)
FINANCE_COLLECTIONS: dict[str, tuple[str, str, str]] = {
    "accounts": ("account", "list_accounts", "account.create"),
    "categories": ("category", "list_categories", "category.create"),
    "transactions": ("transaction", "list_transactions", "transaction.create"),
    "budgets": ("budget", "list_budgets", "budget.set"),
    "bills": ("bill", "list_bills", "bill.create"),
    "networth-snapshots": (
        "networth_snapshot",
        "list_networth_snapshots",
        "networth_snapshot.create",
    ),
}
FINANCE_REPORTS = (
    "spend_by_category",
    "cashflow",
    "budget_status",
    "upcoming_bills",
    "account_balances",
)
_INT_PARAMS = {"limit", "offset", "days", "min_amount_minor", "max_amount_minor"}
_MAX_IMPORT_BYTES = 8 * 1024 * 1024

# Privacy defaults from ARD-700 section 4 (informational; enforced by what the Core exposes).
PRIVACY = {"finance": {"sync_default": True, "hosted_model_access": False}}


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = Field(pattern="^(csv|ofx|json)$")
    data_base64: str = Field(min_length=1, max_length=12 * 1024 * 1024)
    options: dict[str, Any] = Field(default_factory=dict)


def _query_params(request: Request) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, value in request.query_params.items():
        if key in _INT_PARAMS:
            try:
                params[key] = int(value)
            except ValueError as exc:
                raise DomainRequestError(
                    "validation_error", 422, "must be an integer", key
                ) from exc
        else:
            params[key] = value
    return params


def build_domains_router(lifecycle: CoreLifecycle) -> APIRouter:
    router = APIRouter(prefix="/v1")
    require_token = build_auth_dependency(lifecycle)

    def _service() -> DomainService:
        return lifecycle.domain_service

    def _call(domain: str, fn: Any) -> Any:
        """Run a Kernel call and translate typed Kernel errors."""
        service = _service()
        handle = service.handle(domain)
        module = service.binding()
        try:
            return fn(handle)
        except module.DomainError as exc:
            raise translate(module, exc) from exc

    def _finance_collection(collection: str) -> tuple[str, str, str]:
        try:
            return FINANCE_COLLECTIONS[collection]
        except KeyError as exc:
            raise DomainRequestError(
                "not_found", 404, f"unknown collection {collection!r}"
            ) from exc

    def _commit(result: Any) -> dict[str, Any]:
        return {
            "event_id": result.event_id,
            "aggregate_id": result.aggregate_id,
            "version": result.version,
        }

    @router.get("/domains")
    def list_domains(
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        service = _service()
        return {
            "domains": [
                {**service.status(name), "privacy": PRIVACY.get(name, {})}
                for name in service.enabled_domains
            ]
        }

    @router.get("/domains/{domain}/export")
    def export_domain(
        domain: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
        format: Annotated[str, Query(pattern="^(csv|json)$")] = "json",
    ) -> Response:
        data = bytes(_call(domain, lambda h: h.export(format)))
        media = "text/csv" if format == "csv" else "application/json"
        return Response(
            content=data,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{domain}-export.{format}"',
                "Cache-Control": "no-store",
            },
        )

    @router.post("/domains/{domain}/import")
    def import_domain(
        domain: str,
        payload: ImportRequest,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        try:
            raw = base64.b64decode(payload.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DomainRequestError(
                "validation_error", 422, "not valid base64", "data_base64"
            ) from exc
        if len(raw) > _MAX_IMPORT_BYTES:
            raise DomainRequestError("validation_error", 422, "larger than 8 MB", "data_base64")
        report = _call(
            domain, lambda h: h.import_data(payload.format, raw, json.dumps(payload.options))
        )
        return {
            "accepted": report.accepted,
            "duplicates": report.duplicates,
            "rejected": [{"row": r.row, "reason": r.reason, "raw": r.raw} for r in report.rejected],
            "rows": json.loads(report.rows_json),
            "dry_run": report.dry_run,
            "batch_id": report.batch_id,
        }

    @router.get("/domains/{domain}/reports/{name}")
    def report(
        domain: str,
        name: str,
        request: Request,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        if domain != "finance" or name not in FINANCE_REPORTS:
            raise DomainRequestError("not_found", 404, "unknown report")
        params = _query_params(request)
        result = _call(domain, lambda h: h.query(name, json.dumps(params)))
        return {
            "domain": domain,
            "report": name,
            "rows": json.loads(result.rows_json),
            "source_ids": result.source_ids,
        }

    @router.get("/domains/{domain}/{collection}")
    def list_collection(
        domain: str,
        collection: str,
        request: Request,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        _, list_query, _ = (
            _finance_collection(collection) if domain == "finance" else _unknown_domain(domain)
        )
        params = _query_params(request)
        result = _call(domain, lambda h: h.query(list_query, json.dumps(params)))
        return {
            "domain": domain,
            "collection": collection,
            "items": json.loads(result.rows_json),
            "source_ids": result.source_ids,
        }

    @router.post("/domains/{domain}/{collection}", status_code=status.HTTP_201_CREATED)
    def create_item(
        domain: str,
        collection: str,
        body: dict[str, Any],
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        _, _, command = (
            _finance_collection(collection) if domain == "finance" else _unknown_domain(domain)
        )
        return _commit(_call(domain, lambda h: h.command(command, json.dumps(body))))

    @router.get("/domains/{domain}/{collection}/{item_id}")
    def get_item(
        domain: str,
        collection: str,
        item_id: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        aggregate, _, _ = (
            _finance_collection(collection) if domain == "finance" else _unknown_domain(domain)
        )
        params = json.dumps({"aggregate_type": aggregate, "id": item_id})
        result = _call(domain, lambda h: h.query("get", params))
        return {"domain": domain, "collection": collection, "item": json.loads(result.rows_json)[0]}

    @router.patch("/domains/{domain}/{collection}/{item_id}")
    def update_item(
        domain: str,
        collection: str,
        item_id: str,
        body: dict[str, Any],
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        aggregate, _, _ = (
            _finance_collection(collection) if domain == "finance" else _unknown_domain(domain)
        )
        fields = {**body, "id": item_id}
        command = f"{aggregate}.update"
        if (
            aggregate == "account"
            and set(body) == {"archived"}
            and isinstance(body["archived"], bool)
        ):
            command = "account.archive" if body["archived"] else "account.unarchive"
            fields = {"id": item_id}
        if aggregate == "budget":
            command = "budget.set"
        return _commit(_call(domain, lambda h: h.command(command, json.dumps(fields))))

    @router.delete("/domains/{domain}/{collection}/{item_id}")
    def delete_item(
        domain: str,
        collection: str,
        item_id: str,
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        aggregate, _, _ = (
            _finance_collection(collection) if domain == "finance" else _unknown_domain(domain)
        )
        return _commit(
            _call(domain, lambda h: h.command(f"{aggregate}.delete", json.dumps({"id": item_id})))
        )

    @router.post("/domains/finance/bills/{item_id}/mark-paid")
    def mark_bill_paid(
        item_id: str,
        body: dict[str, Any],
        header_correlation_id: Annotated[str, Depends(require_token)],
    ) -> dict[str, Any]:
        fields = {**body, "id": item_id}
        return _commit(_call("finance", lambda h: h.command("bill.mark_paid", json.dumps(fields))))

    @router.get("/today")
    def today_summary(
        header_correlation_id: Annotated[str, Depends(require_token)],
        as_of: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    ) -> dict[str, Any]:
        service = _service()
        handles = [service.handle(name) for name in service.enabled_domains]
        module = service.binding()
        try:
            summary: dict[str, Any] = json.loads(module.today(handles, as_of))
            return summary
        except module.DomainError as exc:
            raise translate(module, exc) from exc

    return router


def _unknown_domain(domain: str) -> tuple[str, str, str]:
    raise DomainRequestError("not_found", 404, f"unknown domain {domain!r}")
