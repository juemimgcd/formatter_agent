from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

TERMINAL_TASK_STATUSES = {
    "success",
    "partial_success",
    "degraded_success",
    "empty_result",
    "failed",
    "timeout",
}
SUCCESS_TASK_STATUSES = {
    "success",
    "partial_success",
    "degraded_success",
    "empty_result",
}


@dataclass(slots=True)
class RequestRecord:
    name: str
    status_code: int
    latency_ms: float
    error: str | None = None


@dataclass(slots=True)
class EndpointMetrics:
    name: str
    total: int
    success: int
    errors: int
    success_rate: float
    error_rate: float
    rps: float
    avg_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    status_codes: dict[str, int]
    sample_errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LoadTestReport:
    base_url: str
    scenario: str
    duration_seconds: float
    concurrency: int
    total: int
    success: int
    errors: int
    success_rate: float
    error_rate: float
    rps: float
    endpoints: list[EndpointMetrics]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run sustained load tests against rebuild_agent HTTP API and Agent task flow."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API service base URL.",
    )
    parser.add_argument(
        "--scenario",
        choices=("health", "create", "list", "detail", "agent", "mixed"),
        default="health",
        help=(
            "Load scenario to run. create only measures task acceptance; "
            "agent measures create + poll-until-terminal."
        ),
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=30.0,
        help="How long to keep sending requests.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent request workers.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Per-request HTTP timeout.",
    )
    parser.add_argument(
        "--think-time-ms",
        type=float,
        default=0.0,
        help="Sleep time after each request per worker.",
    )
    parser.add_argument(
        "--query",
        default="接口压测",
        help="Query used by create/detail/mixed scenarios.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=1,
        help="max_results used by task creation requests.",
    )
    parser.add_argument(
        "--list-limit",
        type=int,
        default=20,
        help="limit query parameter for task list requests.",
    )
    parser.add_argument(
        "--unique-query",
        action="store_true",
        help="Append worker/request ids to create requests to avoid identical queries.",
    )
    parser.add_argument(
        "--poll-timeout-seconds",
        type=float,
        default=120.0,
        help="Max seconds to wait for an agent task to reach terminal status.",
    )
    parser.add_argument(
        "--poll-interval-ms",
        type=float,
        default=500.0,
        help="Polling interval for agent/detail task completion checks.",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser.parse_args()


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * ratio
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def round_float(value: float) -> float:
    return round(value, 2)


async def create_seed_task(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    query: str,
    max_results: int,
) -> str | None:
    response = await client.post(
        f"{base_url}/api/v1/tasks/search",
        json={"query": query, "max_results": max_results},
    )
    if not 200 <= response.status_code < 300:
        return None
    try:
        return response.json().get("data", {}).get("task_id")
    except Exception:
        return None


def is_terminal_task_status(status: str | None) -> bool:
    # 判断任务状态是否已经结束，供 agent 端到端压测轮询使用。
    return status in TERMINAL_TASK_STATUSES


def is_success_task_status(status: str | None) -> bool:
    # partial/degraded 都产出了可用结果，压测口径下计为成功。
    return status in SUCCESS_TASK_STATUSES


async def create_agent_task_and_wait(
    client: httpx.AsyncClient,
    base_url: str,
    args: argparse.Namespace,
    *,
    worker_id: int,
    request_index: int,
) -> RequestRecord:
    # 创建一个任务并轮询详情接口，直到任务进入终态或等待超时。
    start = time.perf_counter()
    query = args.query
    if args.unique_query:
        query = f"{query} {worker_id}-{request_index}"

    try:
        create_response = await client.post(
            f"{base_url}/api/v1/tasks/search",
            json={"query": query, "max_results": args.max_results},
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestRecord(
            name="AGENT create+poll terminal",
            status_code=0,
            latency_ms=latency_ms,
            error=f"create failed: {type(exc).__name__}: {exc}",
        )

    if not 200 <= create_response.status_code < 300:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestRecord(
            name="AGENT create+poll terminal",
            status_code=create_response.status_code,
            latency_ms=latency_ms,
            error=create_response.text[:200],
        )

    try:
        task_id = create_response.json().get("data", {}).get("task_id")
    except Exception:
        task_id = None
    if not task_id:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestRecord(
            name="AGENT create+poll terminal",
            status_code=0,
            latency_ms=latency_ms,
            error="create response does not contain task_id",
        )

    deadline = time.perf_counter() + max(0.1, args.poll_timeout_seconds)
    poll_interval_seconds = max(0.05, args.poll_interval_ms / 1000)
    last_status = "unknown"

    while time.perf_counter() < deadline:
        try:
            detail_response = await client.get(f"{base_url}/api/v1/tasks/{task_id}")
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            return RequestRecord(
                name="AGENT create+poll terminal",
                status_code=0,
                latency_ms=latency_ms,
                error=f"detail failed: {type(exc).__name__}: {exc}",
            )

        if not 200 <= detail_response.status_code < 300:
            latency_ms = (time.perf_counter() - start) * 1000
            return RequestRecord(
                name="AGENT create+poll terminal",
                status_code=detail_response.status_code,
                latency_ms=latency_ms,
                error=detail_response.text[:200],
            )

        try:
            data = detail_response.json().get("data", {})
            last_status = data.get("status")
        except Exception:
            last_status = "invalid_detail_response"

        if is_terminal_task_status(last_status):
            latency_ms = (time.perf_counter() - start) * 1000
            return RequestRecord(
                name="AGENT create+poll terminal",
                status_code=200 if is_success_task_status(last_status) else 500,
                latency_ms=latency_ms,
                error=None
                if is_success_task_status(last_status)
                else f"terminal task status={last_status}",
            )

        await asyncio.sleep(poll_interval_seconds)

    latency_ms = (time.perf_counter() - start) * 1000
    return RequestRecord(
        name="AGENT create+poll terminal",
        status_code=0,
        latency_ms=latency_ms,
        error=f"poll timeout, last task status={last_status}",
    )


async def send_request(
    client: httpx.AsyncClient,
    base_url: str,
    args: argparse.Namespace,
    *,
    scenario: str,
    worker_id: int,
    request_index: int,
    detail_task_id: str | None,
) -> RequestRecord:
    if scenario == "agent":
        return await create_agent_task_and_wait(
            client,
            base_url,
            args,
            worker_id=worker_id,
            request_index=request_index,
        )

    if scenario == "mixed":
        scenario = random.choices(
            ["health", "list", "create", "detail"],
            weights=[45, 25, 20, 10],
            k=1,
        )[0]
        if scenario == "detail" and not detail_task_id:
            scenario = "list"

    if scenario == "health":
        name = "GET /health"
        method = "GET"
        url = f"{base_url}/health"
        body = None
    elif scenario == "list":
        name = "GET /api/v1/tasks"
        method = "GET"
        url = f"{base_url}/api/v1/tasks?limit={args.list_limit}&offset=0"
        body = None
    elif scenario == "detail":
        name = "GET /api/v1/tasks/{task_id}"
        method = "GET"
        url = f"{base_url}/api/v1/tasks/{detail_task_id}"
        body = None
    else:
        name = "POST /api/v1/tasks/search"
        method = "POST"
        url = f"{base_url}/api/v1/tasks/search"
        query = args.query
        if args.unique_query:
            query = f"{query} {worker_id}-{request_index}"
        body = {"query": query, "max_results": args.max_results}

    start = time.perf_counter()
    try:
        response = await client.request(method, url, json=body)
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestRecord(
            name=name,
            status_code=0,
            latency_ms=latency_ms,
            error=f"{type(exc).__name__}: {exc}",
        )

    latency_ms = (time.perf_counter() - start) * 1000
    error = None
    if not 200 <= response.status_code < 300:
        error = response.text[:200]
    return RequestRecord(
        name=name,
        status_code=response.status_code,
        latency_ms=latency_ms,
        error=error,
    )


async def run_load_test(args: argparse.Namespace) -> LoadTestReport:
    base_url = args.base_url.rstrip("/")
    records: list[RequestRecord] = []
    records_lock = asyncio.Lock()
    stop_at = time.perf_counter() + max(0.1, args.duration_seconds)
    think_time_seconds = max(0.0, args.think_time_ms) / 1000
    detail_task_id: str | None = None

    async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
        if args.scenario in {"detail", "mixed"}:
            detail_task_id = await create_seed_task(
                client,
                base_url,
                query=args.query,
                max_results=args.max_results,
            )
            if args.scenario == "detail" and not detail_task_id:
                raise RuntimeError("Failed to create seed task for detail scenario.")

        async def worker(worker_id: int) -> None:
            request_index = 0
            while time.perf_counter() < stop_at:
                record = await send_request(
                    client,
                    base_url,
                    args,
                    scenario=args.scenario,
                    worker_id=worker_id,
                    request_index=request_index,
                    detail_task_id=detail_task_id,
                )
                async with records_lock:
                    records.append(record)
                request_index += 1
                if think_time_seconds > 0:
                    await asyncio.sleep(think_time_seconds)

        started = time.perf_counter()
        await asyncio.gather(
            *[worker(worker_id) for worker_id in range(max(1, args.concurrency))]
        )
        elapsed = time.perf_counter() - started

    return build_report(
        base_url=base_url,
        scenario=args.scenario,
        duration_seconds=elapsed,
        concurrency=max(1, args.concurrency),
        records=records,
    )


def build_endpoint_metrics(
    name: str,
    records: list[RequestRecord],
    *,
    duration_seconds: float,
) -> EndpointMetrics:
    latencies = [record.latency_ms for record in records]
    status_codes = Counter(str(record.status_code) for record in records)
    success = sum(1 for record in records if 200 <= record.status_code < 300)
    errors = len(records) - success
    sample_errors = [
        str(record.error)
        for record in records
        if record.error
    ][:5]

    return EndpointMetrics(
        name=name,
        total=len(records),
        success=success,
        errors=errors,
        success_rate=round_float((success / len(records)) * 100) if records else 0.0,
        error_rate=round_float((errors / len(records)) * 100) if records else 0.0,
        rps=round_float(len(records) / duration_seconds) if duration_seconds > 0 else 0.0,
        avg_ms=round_float(statistics.mean(latencies)) if latencies else 0.0,
        p50_ms=round_float(percentile(latencies, 0.50)),
        p90_ms=round_float(percentile(latencies, 0.90)),
        p95_ms=round_float(percentile(latencies, 0.95)),
        p99_ms=round_float(percentile(latencies, 0.99)),
        min_ms=round_float(min(latencies)) if latencies else 0.0,
        max_ms=round_float(max(latencies)) if latencies else 0.0,
        status_codes=dict(sorted(status_codes.items())),
        sample_errors=sample_errors,
    )


def build_report(
    *,
    base_url: str,
    scenario: str,
    duration_seconds: float,
    concurrency: int,
    records: list[RequestRecord],
) -> LoadTestReport:
    total = len(records)
    success = sum(1 for record in records if 200 <= record.status_code < 300)
    errors = total - success
    grouped: dict[str, list[RequestRecord]] = defaultdict(list)
    for record in records:
        grouped[record.name].append(record)

    endpoints = [
        build_endpoint_metrics(name, endpoint_records, duration_seconds=duration_seconds)
        for name, endpoint_records in sorted(grouped.items())
    ]
    return LoadTestReport(
        base_url=base_url,
        scenario=scenario,
        duration_seconds=round_float(duration_seconds),
        concurrency=concurrency,
        total=total,
        success=success,
        errors=errors,
        success_rate=round_float((success / total) * 100) if total else 0.0,
        error_rate=round_float((errors / total) * 100) if total else 0.0,
        rps=round_float(total / duration_seconds) if duration_seconds > 0 else 0.0,
        endpoints=endpoints,
    )


def render_text(report: LoadTestReport) -> str:
    lines = [
        "Load test summary",
        f"  base_url={report.base_url}",
        f"  scenario={report.scenario} duration_seconds={report.duration_seconds}",
        f"  concurrency={report.concurrency} total={report.total}",
        (
            "  success={success} errors={errors} success_rate={success_rate}% "
            "error_rate={error_rate}% rps={rps}"
        ).format(
            success=report.success,
            errors=report.errors,
            success_rate=report.success_rate,
            error_rate=report.error_rate,
            rps=report.rps,
        ),
        "",
        "Endpoint metrics",
    ]
    for endpoint in report.endpoints:
        lines.extend(
            [
                f"- {endpoint.name}",
                (
                    "  total={total} success={success} errors={errors} "
                    "success_rate={success_rate}% error_rate={error_rate}% rps={rps}"
                ).format(
                    total=endpoint.total,
                    success=endpoint.success,
                    errors=endpoint.errors,
                    success_rate=endpoint.success_rate,
                    error_rate=endpoint.error_rate,
                    rps=endpoint.rps,
                ),
                (
                    "  avg_ms={avg} p50_ms={p50} p90_ms={p90} "
                    "p95_ms={p95} p99_ms={p99} min_ms={min_v} max_ms={max_v}"
                ).format(
                    avg=endpoint.avg_ms,
                    p50=endpoint.p50_ms,
                    p90=endpoint.p90_ms,
                    p95=endpoint.p95_ms,
                    p99=endpoint.p99_ms,
                    min_v=endpoint.min_ms,
                    max_v=endpoint.max_ms,
                ),
                f"  status_codes={endpoint.status_codes}",
            ]
        )
        if endpoint.sample_errors:
            lines.append(f"  sample_errors={endpoint.sample_errors}")
    return "\n".join(lines)


async def main() -> None:
    args = parse_args()
    report = await run_load_test(args)
    if args.output == "json":
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return
    print(render_text(report))


if __name__ == "__main__":
    asyncio.run(main())
