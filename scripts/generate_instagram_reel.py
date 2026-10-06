#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from kendo_keiko.weekend_reel import (  # noqa: E402
    CONFIG_EXIT_CODE,
    DEFAULT_EVENTS_URL,
    NO_EVENTS_EXIT_CODE,
    ReelConfigError,
    ReelError,
    ReelStateStore,
    ReelUnknownResult,
    SKIPPED_EXIT_CODE,
    create_default_s3_store,
    fetch_reel_payload,
    generate_reel_assets,
    resolve_schedule,
    run_key,
    select_reel_events,
)


def default_state_dir() -> Path:
    configured = os.environ.get("INSTAGRAM_REEL_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "kendo-keiko" / "instagram-reel"


def default_output_dir() -> Path:
    return ROOT_DIR / "output" / "instagram-reel"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="金〜日の掲載イベントからInstagram Reel素材を生成・投稿します。"
    )
    parser.add_argument("--target-friday", help="対象金曜日。明示指定時のみ水木以外でも実行")
    parser.add_argument("--events-url", default=DEFAULT_EVENTS_URL)
    parser.add_argument("--events-file", type=Path)
    parser.add_argument("--area", action="append", default=[], help="対象地域。複数指定可。省略時は全国")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    parser.add_argument("--state-dir", type=Path, default=default_state_dir())
    parser.add_argument("--page-seconds", type=float, default=6.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="publish", action="store_false", help="素材生成のみ（既定）")
    mode.add_argument("--publish", dest="publish", action="store_true", help="認証・S3・Instagram APIを使って投稿")
    parser.add_argument("--verify-destination", action="store_true", help="投稿せず、設定したInstagram投稿先だけ読み取り確認")
    parser.set_defaults(publish=False)
    return parser


def _record(store: ReelStateStore, key: str, *, status: str, target_friday: dt.date, input_sha256: str | None = None, **extra: object) -> None:
    record = {
        "status": status,
        "target_friday": target_friday.isoformat(),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    if input_sha256 is not None:
        record["input_sha256"] = input_sha256
    record.update(extra)
    store.record(key, record)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify_destination and args.publish:
        build_parser().error("--verify-destination cannot be combined with --publish")
    if args.verify_destination:
        try:
            from kendo_keiko.weekend_reel import InstagramApiClient, InstagramApiConfig

            config = InstagramApiConfig.from_env()
            destination = InstagramApiClient(config).verify_destination()
            print(
                "Verified Instagram destination: "
                f"@{destination['username']} ({destination.get('account_type') or 'professional account'})"
            )
            return 0
        except ReelConfigError as exc:
            print(f"[CONFIG] {exc}", file=sys.stderr)
            return CONFIG_EXIT_CODE
        except ReelError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.events_file is not None and args.events_url != DEFAULT_EVENTS_URL:
        parser = build_parser()
        parser.error("--events-file and --events-url are mutually exclusive")
    decision = resolve_schedule(explicit_friday=args.target_friday)
    if decision.target_friday is None:
        print(f"[SKIPPED] {decision.status}: {decision.reason}")
        return SKIPPED_EXIT_CODE
    target_friday = decision.target_friday
    configured_areas = [item.strip() for item in os.environ.get("INSTAGRAM_REEL_AREAS", "").split(",") if item.strip()]
    areas = args.area or configured_areas
    destination_id = os.environ.get("INSTAGRAM_USER_ID", "dry-run-destination")
    key = run_key(destination_id, target_friday)
    store = ReelStateStore(args.state_dir.expanduser())
    input_sha256_for_error: str | None = None
    event_ids_for_error: list[str] = []
    try:
        with store.lock():
            if decision.status == "skipped_late":
                _record(store, key, status="skipped_late", target_friday=target_friday)
                print(f"[SKIPPED] {decision.reason}: {target_friday.isoformat()}")
                return SKIPPED_EXIT_CODE
            existing = store.get(key)
            if args.publish and existing and existing.get("status") in {
                "published",
                "unknown",
                "publishing",
                "container_processing",
            }:
                print(f"[SKIPPED] existing run state prevents duplicate posting: {target_friday.isoformat()}")
                return SKIPPED_EXIT_CODE
            if args.events_file is not None:
                from kendo_keiko.weekend_reel import _load_and_hash_bytes

                payload, input_sha256 = _load_and_hash_bytes(args.events_file)
                source_url = str(args.events_file)
            else:
                payload, input_sha256 = fetch_reel_payload(args.events_url)
                source_url = args.events_url
            input_sha256_for_error = input_sha256
            selection = select_reel_events(payload, target_friday, areas=areas)
            event_ids_for_error = [event.event_id for event in selection.events]
            if not selection.events:
                _record(
                    store,
                    key,
                    status="skipped_no_events",
                    target_friday=target_friday,
                    input_sha256=input_sha256,
                    event_ids=[],
                    excluded=list(selection.excluded),
                )
                print(f"[NO_EVENTS] no publishable events for {target_friday.isoformat()}", file=sys.stderr)
                return NO_EVENTS_EXIT_CODE
            output_dir = args.output_dir.expanduser() / target_friday.isoformat()
            assets = generate_reel_assets(
                selection,
                input_sha256=input_sha256,
                output_dir=output_dir,
                mode="publish" if args.publish else "dry_run",
                regions=areas,
                source_url=source_url,
                page_seconds=args.page_seconds,
            )
            _record(
                store,
                key,
                status="prepared" if args.publish else "dry_run",
                target_friday=target_friday,
                input_sha256=input_sha256,
                event_ids=[event.event_id for event in selection.events],
                excluded=list(selection.excluded),
                output_dir=str(output_dir),
                source_url=source_url,
                video_file="reel.mp4",
                media_id=None,
                permalink=None,
            )
            if not args.publish:
                print(f"Generated Reel dry-run: {assets.video_path} ({len(selection.events)} events, {assets.probe.duration_seconds:.1f}s)")
                return 0

            from kendo_keiko.weekend_reel import InstagramApiClient, InstagramApiConfig

            config = InstagramApiConfig.from_env()
            # This is deliberately read-only and occurs before upload or publish.
            config_check = InstagramApiClient(config).verify_destination()
            _record(store, key, status="destination_verified", target_friday=target_friday, input_sha256=input_sha256, event_ids=[event.event_id for event in selection.events], destination=config_check)
            video_store = create_default_s3_store()
            video_url = video_store.upload(assets.video_path, target_friday=target_friday, input_sha256=input_sha256)
            client = InstagramApiClient(config)
            container_id = client.create_reel_container(video_url=video_url, caption=assets.caption_path.read_text(encoding="utf-8"))
            _record(store, key, status="container_created", target_friday=target_friday, input_sha256=input_sha256, event_ids=[event.event_id for event in selection.events], container_id=container_id)
            client.wait_for_container(container_id)
            _record(store, key, status="container_processing", target_friday=target_friday, input_sha256=input_sha256, event_ids=[event.event_id for event in selection.events], container_id=container_id)
            media_id = client.publish_container(container_id)
            permalink = client.permalink(media_id)
            _record(store, key, status="published", target_friday=target_friday, input_sha256=input_sha256, event_ids=[event.event_id for event in selection.events], container_id=container_id, media_id=media_id, permalink=permalink)
            print(f"Published Instagram Reel for {target_friday.isoformat()} (media ID recorded in state)")
            return 0
    except ReelUnknownResult as exc:
        try:
            with store.lock():
                _record(
                    store,
                    key,
                    status="unknown",
                    target_friday=target_friday,
                    input_sha256=input_sha256_for_error,
                    event_ids=event_ids_for_error,
                    container_id=exc.container_id,
                )
        except Exception:
            pass
        print("[UNKNOWN] Instagram API result is unknown; inspect the saved state before retrying.", file=sys.stderr)
        return CONFIG_EXIT_CODE
    except ReelConfigError as exc:
        try:
            with store.lock():
                _record(store, key, status="failed", target_friday=target_friday, input_sha256=input_sha256_for_error, event_ids=event_ids_for_error, error=str(exc))
        except Exception:
            pass
        print(f"[CONFIG] {exc}", file=sys.stderr)
        return CONFIG_EXIT_CODE
    except ReelError as exc:
        try:
            with store.lock():
                _record(store, key, status="failed", target_friday=target_friday, input_sha256=input_sha256_for_error, event_ids=event_ids_for_error, error=str(exc))
        except Exception:
            pass
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
