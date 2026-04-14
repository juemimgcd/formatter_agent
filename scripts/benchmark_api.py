from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class BenchmarkResult:
    name: str
    total: int
    concurrency: int
    success: int
    errors: int
    avg_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    rps: float
    sample_bodies: list[dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark rebuild_agent HTTP endpoints."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API service base URL.",
    )
    parser.add_argument(
        "--query",
        default="接口压测",
        help="Query used for POST /api/v1/tasks/search.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=1,
        help="max_results used for POST /api/v1/tasks/search.",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--warmup-health",
        type=int,
        default=5,
        help="Warmup request count for /health.",
    )
    parser.add_argument(
        "--warmup-create",
        type=int,
        default=2,
        help="Warmup request count for POST /api/v1/tasks/search.",
    )
    parser.add_argument(
        "--health-total",
        type=int,
        default=100,
        help="Total requests for GET /health.",
    )
    parser.add_argument(
        "--health-concurrency",
        type=int,
        default=20,
        help="Concurrency for GET /health.",
    )
    parser.add_argument(
        "--create-total",
        type=int,
        default=20,
        help="Total requests for POST /api/v1/tasks/search.",
    )
    parser.add_argument(
        "--create-concurrency",
        type=int,
        default=5,
        help="Concurrency for POST /api/v1/tasks/search.",
    )
    parser.add_argument(
        "--detail-total",
        type=int,
        default=50,
        help="Total requests for GET /api/v1/tasks/{task_id}.",
    )
    parser.add_argument(
        "--detail-concurrency",
        type=int,
        default=10,
        help="Concurrency for GET /api/v1/tasks/{task_id}.",
    )
    parser.add_argument(
        "--detail-delay-ms",
        type=int,
        default=500,
        help="Delay before benchmarking task detail after create.",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip GET /health benchmark.",
    )
    parser.add_argument(
        "--skip-create",
        action="store_true",
        help="Skip POST /api/v1/tasks/search benchmark.",
    )
    parser.add_argument(
        "--skip-detail",
        action="store_true",
        help="Skip GET /api/v1/tasks/{task_id} benchmark.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP request timeout.",
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


async def warmup(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    health_count: int,
    create_count: int,
    query: str,
    max_results: int,
) -> None:
    for _ in range(max(0, health_count)):
        await client.get(f"{base_url}/health")
    for _ in range(max(0, create_count)):
        await client.post(
            f"{base_url}/api/v1/tasks/search",
            json={"query": query, "max_results": max_results},
        )


async def run_case(
    client: httpx.AsyncClient,
    *,
    name: str,
    method: str,
    url: str,
    total: int,
    concurrency: int,
    json_body: dict[str, Any] | None = None,
) -> tuple[BenchmarkResult, list[httpx.Response | None]]:
    latencies: list[float] = []
    statuses: list[int] = []
    sample_bodies: list[dict[str, Any]] = []
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(index: int) -> httpx.Response | None:
        async with semaphore:
            start = time.perf_counter()
            try:
                response = await client.request(method, url, json=json_body)
            except Exception as exc:
                latencies.append((time.perf_counter() - start) * 1000)
                statuses.append(0)
                if index < 3:
                    sample_bodies.append({"error": f"{type(exc).__name__}: {exc}"})
                return None

            latencies.append((time.perf_counter() - start) * 1000)
            statuses.append(response.status_code)
            if index < 3:
                try:
                    sample_bodies.append(response.json())
                except Exception:
                    sample_bodies.append({"text": response.text[:200]})
            return response

    start_all = time.perf_counter()
    responses = await asyncio.gather(*[one(i) for i in range(total)])
    duration = time.perf_counter() - start_all
    success = sum(1 for status in statuses if 200 <= status < 300)
    result = BenchmarkResult(
        name=name,
        total=total,
        concurrency=concurrency,
        success=success,
        errors=total - success,
        avg_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
        p50_ms=round(percentile(latencies, 0.50), 2),
        p95_ms=round(percentile(latencies, 0.95), 2),
        min_ms=round(min(latencies), 2) if latencies else 0.0,
        max_ms=round(max(latencies), 2) if latencies else 0.0,
        rps=round(total / duration, 2) if duration > 0 else 0.0,
        sample_bodies=sample_bodies,
    )
    return result, responses


def extract_task_id(responses: list[httpx.Response | None]) -> str | None:
    for response in responses:
        if response is None:
            continue
        try:
            task_id = response.json().get("data", {}).get("task_id")
        except Exception:
            task_id = None
        if task_id:
            return str(task_id)
    return None


def render_text(results: list[BenchmarkResult]) -> str:
    lines: list[str] = []
    for result in results:
        lines.extend(
            [
                f"{result.name}",
                f"  total={result.total} concurrency={result.concurrency}",
                f"  success={result.success} errors={result.errors} rps={result.rps}",
                (
                    "  avg_ms={avg} p50_ms={p50} p95_ms={p95} min_ms={min_v} max_ms={max_v}"
                ).format(
                    avg=result.avg_ms,
                    p50=result.p50_ms,
                    p95=result.p95_ms,
                    min_v=result.min_ms,
                    max_v=result.max_ms,
                ),
            ]
        )
    return "\n".join(lines)


async def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    results: list[BenchmarkResult] = []

    async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
        await warmup(
            client,
            base_url,
            health_count=args.warmup_health,
            create_count=args.warmup_create,
            query=args.query,
            max_results=args.max_results,
        )

        create_responses: list[httpx.Response | None] = []

        if not args.skip_health:
            health_result, _ = await run_case(
                client,
                name="GET /health",
                method="GET",
                url=f"{base_url}/health",
                total=args.health_total,
                concurrency=args.health_concurrency,
            )
            results.append(health_result)

        if not args.skip_create:
            create_result, create_responses = await run_case(
                client,
                name="POST /api/v1/tasks/search",
                method="POST",
                url=f"{base_url}/api/v1/tasks/search",
                total=args.create_total,
                concurrency=args.create_concurrency,
                json_body={"query": args.query, "max_results": args.max_results},
            )
            results.append(create_result)

        if not args.skip_detail and create_responses:
            task_id = extract_task_id(create_responses)
            if task_id:
                await asyncio.sleep(max(0, args.detail_delay_ms) / 1000)
                detail_result, _ = await run_case(
                    client,
                    name="GET /api/v1/tasks/{task_id}",
                    method="GET",
                    url=f"{base_url}/api/v1/tasks/{task_id}",
                    total=args.detail_total,
                    concurrency=args.detail_concurrency,
                )
                results.append(detail_result)

    if args.output == "json":
        print(
            json.dumps(
                [asdict(result) for result in results],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print(render_text(results))


if __name__ == "__main__":
    asyncio.run(main())
