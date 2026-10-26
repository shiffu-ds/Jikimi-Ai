"""``python -m jikimi_edge <command>``: run | replay | calibrate | keygen | sms-test | doctor."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any

from jikimi_common.config import load_dotenv
from jikimi_common.ids import short_code
from jikimi_common.logging import setup_logging

log = logging.getLogger("jikimi_edge")


def _settings(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    from .settings import load_settings

    return load_settings(args.config, repo_root=Path.cwd())


def cmd_run(args: argparse.Namespace) -> int:
    from .runner import LiveRunner, build_pipeline, make_source

    s = _settings(args)
    if not s.device_token:
        log.error("JIKIMI_DEVICE_TOKEN missing: run `make env` / `make seed` first")
        return 2
    sources = {c.id: make_source(s, c.id, realtime=True) for c in s.cameras}
    real = any(not (c.source or "").startswith("sim:") for c in s.cameras)
    pipeline, outbox, signer = build_pipeline(s, real_perception=real)
    assert outbox is not None
    log.warning("device key %s", signer.key_id)
    runner = LiveRunner(s, pipeline, outbox, sources)
    asyncio.run(runner.run())
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from .runner import replay

    s = _settings(args)
    res = replay(s, args.camera or s.cameras[0].id, args.scenario, seed=args.seed)
    for a in res.alerts:
        print(
            json.dumps(
                {
                    "type": a.type.value,
                    "route": a.route.value if a.route else None,
                    "severity": a.severity.value,
                    "p": None if a.p_value is None else round(a.p_value, 4),
                    "score": round(a.raw_score, 3),
                    "t_s": round(a.ts_end.timestamp() - 1_793_000_000.0, 1),
                    "code": short_code(a.alert_id),
                    "why": a.explanation_roman,
                },
                ensure_ascii=False,
            )
        )
    print(
        f"# {res.frames} frames in {res.seconds:.1f}s ({res.frames / max(res.seconds, 1e-6):.0f} fps)", file=sys.stderr
    )
    return 0


def _calib_run(
    config: str, camera_id: str, seed: int, scenario: str = "normal_traffic", only: str = ""
) -> dict[str, tuple[str, list[float]]]:
    """``calibration key -> (scorer version, scores)``: one score per unit (a bike, a pair of
    people, a burst...). Single-type plugins log ``score_log`` (key = plugin name = alert type),
    the person-safety plugins ``score_logs`` with a key per pattern (e.g. person_in_danger_fall)."""
    from .runner import build_pipeline, replay
    from .settings import load_settings

    s = load_settings(config, repo_root=Path.cwd())
    pipeline, _, _ = build_pipeline(s, with_outbox=False, record_clips=False)
    wanted = {x for x in only.split(",") if x}
    plugins = [p for p in pipeline.cameras[camera_id].plugins if not wanted or p.name in wanted]
    for p in plugins:
        if hasattr(p, "score_logs"):
            p.score_logs = {}
        elif hasattr(p, "score_log"):
            p.score_log = {}
    replay(s, camera_id, scenario, seed=seed, pipeline=pipeline)
    out: dict[str, tuple[str, list[float]]] = {}
    for p in plugins:
        if getattr(p, "score_logs", None) is not None:
            for key, log in p.score_logs.items():  # type: ignore[attr-defined]
                out[key] = (p.version, list(log.values()))
        elif getattr(p, "score_log", None) is not None:
            out[p.name] = (p.version, list(p.score_log.values()))  # type: ignore[attr-defined]
    return out


def _fa_run(
    config: str, camera_id: str, seed: int, scenario: str = "normal_traffic", mode: str = "normal"
) -> list[tuple[str, str]]:
    from .runner import replay
    from .settings import load_settings

    s = load_settings(config, repo_root=Path.cwd())
    s.raw.setdefault("event_mode", {})["current"] = mode  # F16: which calibration set answers
    res = replay(s, camera_id, scenario, seed=seed)
    return [(_kind(a), a.route.value if a.route else "-") for a in res.alerts]


def _kind(a: Any) -> str:
    """Alert type, with the danger pattern or "foot" for the person-safety detectors."""
    if a.features.get("pattern"):
        return f"{a.type.value}.{a.features['pattern']}"
    return f"{a.type.value}.foot" if a.features.get("on_foot") else a.type.value


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Simulator calibration (demo only). Real sites: 48-72 h of guard-confirmed footage."""
    from concurrent.futures import ProcessPoolExecutor

    from .analytics.registry import SAFETY_PLUGINS
    from .calibration.store import CalibrationStore
    from .sim.scenarios import build

    s = _settings(args)
    if not args.plugins:  # each plugin against its own everyday population
        safety = args.scenario == "street_life"
        args.plugins = ",".join(SAFETY_PLUGINS if safety else ("loitering", "snatch"))
    # one seed per (run, camera): the same seed on two cameras renders the same scene twice
    duration = build(args.scenario, 1).duration_s
    per_run_h = duration / 3600
    runs = max(1, round(args.hours / per_run_h / len(s.cameras)))
    jobs = [
        (args.config, cam.id, 1000 + i * len(s.cameras) + k, args.scenario, args.plugins)
        for i in range(runs)
        for k, cam in enumerate(s.cameras)
    ]
    logs: dict[str, list[float]] = {}
    versions: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for n, res in enumerate(pool.map(_calib_run, *zip(*jobs, strict=True)), 1):
            for k, (version, v) in res.items():
                logs.setdefault(k, []).extend(v)
                versions[k] = version
            print(f"run {n}/{len(jobs)}: " + " ".join(f"{k} n={len(v)}" for k, v in logs.items()), file=sys.stderr)
    camera_hours = len(jobs) * per_run_h
    store = CalibrationStore(s.calibration_dir, s.site_id)
    for name, scores in sorted(logs.items()):
        if len(scores) < 20:
            print(f"{name}: only {len(scores)} units - not saved (needs more hours or a busier scene)")
            continue
        rate = len(scores) / camera_hours
        path = store.save(
            name,
            args.mode,
            scores,
            source=f"simulator {args.scenario} {camera_hours:g} camera-hours (demo only)",
            extra={"units_per_camera_hour": round(rate, 1), "model_version": versions.get(name)},
        )
        cal = store.get(name, args.mode)
        assert cal is not None
        q = statistics.quantiles(scores, n=100)
        print(
            f"{name}: n={len(scores)} units/camera-hour={rate:.0f} p50={q[49]:.3f} p95={q[94]:.3f} p99={q[98]:.3f} "
            f"thr(a=0.01)={cal.threshold(0.01):.3f} worst-case FA/h at a=0.01: {0.01 * rate:.2f} -> {path.name}"
        )
    print("note: gating (>=2 passes, hand contact) keeps the real FA/h far below the worst case; run `evaluate-fa`.")
    return 0


def _poisson_upper(events: int, level: float = 0.95) -> float:
    """Exact one-sided upper bound on a Poisson mean (0 -> 3.0, 1 -> 4.74, 2 -> 6.30); bisection, so
    the edge needs no SciPy. Same values as ``jikimi_ml.eval.stats.poisson_upper``."""

    def cdf(lam: float) -> float:
        term = total = math.exp(-lam)
        for i in range(1, events + 1):
            term *= lam / i
            total += term
        return total

    lo, hi = 0.0, 10.0 + 10.0 * events
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > 1 - level else (lo, mid)
    return hi


def cmd_evaluate_fa(args: argparse.Namespace) -> int:
    """Empirical false alarms per camera-hour on held-out normal traffic (plan F7 acceptance)."""
    from collections import Counter
    from concurrent.futures import ProcessPoolExecutor

    from .sim.scenarios import build

    s = _settings(args)
    per_run_h = build(args.scenario, 1).duration_s / 3600
    runs = max(1, round(args.hours / per_run_h / len(s.cameras)))
    jobs = [
        (args.config, cam.id, args.seed0 + i * len(s.cameras) + k, args.scenario, args.mode)
        for i in range(runs)
        for k, cam in enumerate(s.cameras)
    ]
    counts: Counter[str] = Counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for res in pool.map(_fa_run, *zip(*jobs, strict=True)):
            counts.update(f"{t}:{r}" for t, r in res)
    hours = len(jobs) * per_run_h
    out = {
        "scenario": args.scenario,
        "mode": args.mode,
        "seeds": [jobs[0][2], jobs[-1][2]],
        "camera_hours": round(hours, 2),
        "alerts": dict(counts),
    }
    events = {r: sum(v for k, v in counts.items() if k.endswith(r)) for r in ("ALERT_NOW", "VERIFY")}
    out["fa_per_camera_hour"] = {r: round(n / hours, 3) for r, n in events.items()}
    # what the data rules out: "0 in 10 h" still allows up to 0.3/h at 95 %
    out["fa_per_camera_hour_upper95"] = {r: round(_poisson_upper(n) / hours, 3) for r, n in events.items()}
    print(json.dumps(out, indent=2))
    return 0


def cmd_keygen(args: argparse.Namespace) -> int:
    from .evidence.signer import DeviceSigner
    from .pipeline import data_paths

    s = _settings(args)
    signer = DeviceSigner(data_paths(s)["device_key"])
    print(
        json.dumps(
            {"device_id": s.device_id, "site_id": s.site_id, "key_id": signer.key_id, "public_key": signer.public_key}
        )
    )
    return 0


def cmd_sms_test(args: argparse.Namespace) -> int:
    from .outbox.sms_gateway import make_gateway
    from .pipeline import data_paths

    s = _settings(args)
    gw = make_gateway(s.sms_gateway, data_paths(s)["sms"], s.modem_port)
    ok = gw.send(args.to, "JIKIMI: test SMS. Jawab 1 bhejein.")
    print(json.dumps({"gateway": gw.name, "sent": ok, "healthy": gw.healthy()}))
    return 0 if ok else 1


def cmd_discover(args: argparse.Namespace) -> int:
    """F20: find ONVIF cameras/recorders on the LAN, list their streams, print RTSP templates."""
    import os

    from .onboarding.discovery import discover
    from .onboarding.onvif import OnvifClient, OnvifError
    from .onboarding.templates import TEMPLATES, mask, urls

    devices = discover(args.timeout, args.interface)
    password = os.environ.get(args.password_env, "") if args.password_env else ""
    out: list[dict[str, object]] = []
    for d in devices:
        entry: dict[str, object] = {
            "ip": d.ip,
            "name": d.name,
            "hardware": d.hardware,
            "brand": d.brand,
            "onvif": d.xaddrs[0],
        }
        if args.user:
            client = OnvifClient(d.xaddrs[0], args.user, password)
            try:
                entry["streams"] = [
                    {
                        "profile": s.name,
                        "size": f"{s.width}x{s.height}",
                        "encoding": s.encoding,
                        "uri": mask(s.uri or ""),
                    }
                    for s in client.streams()
                ]
            except OnvifError as exc:
                entry["onvif_error"] = str(exc)
            finally:
                client.close()
        if d.brand:
            main, sub = urls(d.brand, d.ip, placeholder=True)
            entry["rtsp_templates"] = {"main": main, "sub": sub}
        out.append(entry)
    if not devices:
        out.append({"note": "no ONVIF device answered; try the templates", "brands": sorted(TEMPLATES)})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_probe_stream(args: argparse.Namespace) -> int:
    """F20: connection test (resolution, fps, bitrate, failed reads) before a stream goes into site.yaml."""
    import os

    from .onboarding.probe import probe

    url = os.environ.get(args.url_env, "") if args.url_env else args.url
    if not url:
        print(json.dumps({"error": "give --url-env NAME (keeps the password out of shell history) or --url"}))
        return 2
    report = probe(url, seconds=args.seconds, live=not Path(url).exists())
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if report.ok else 1


def cmd_setup(args: argparse.Namespace) -> int:
    """F20: the Urdu setup wizard on the LAN (find camera -> test -> draw zone -> detect -> save)."""
    from .onboarding.wizard import Wizard, serve
    from .runner import load_detectors

    settings = _settings(args)
    if args.config.endswith("site.demo.yaml"):
        print("note: adding cameras to the demo site; copy edge/config/site.example.yaml for a real one")
    detector, _, _ = load_detectors(settings, need_pose=False)
    wizard = Wizard(Path(args.config), Path(args.env_file), detector=detector, allow_files=args.allow_files)
    serve(wizard, args.host, args.port)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from jikimi_ml_runtime import available_backends

    from .ingest.clip_writer import ffmpeg_available

    s = _settings(args)
    checks = {
        "ffmpeg (H.264 clips)": ffmpeg_available(),
        "inference backends": available_backends() or "none (sim cameras only)",
        "device token set": bool(s.device_token),
        "calibration sets": sorted(p.name for p in (s.calibration_dir / s.site_id).glob("*.json")) or "missing",
        "yunet face model": (s.repo_root / "models/face_detection_yunet_2023mar.onnx").exists(),
        "sms gateway": s.sms_gateway,
        "sms numbers": len(s.sms_numbers),
        "disk free GB": round(shutil.disk_usage(s.repo_root).free / 1e9, 1),
    }
    for k, v in checks.items():
        print(f"  {k:<24} {v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="jikimi-edge", description="Jikimi AI edge runtime")
    ap.add_argument("--config", default="edge/config/site.demo.yaml")
    ap.add_argument("--log-level", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run cameras + sync agent")
    rp = sub.add_parser("replay", help="replay a simulator scenario fast and print alerts")
    rp.add_argument("--scenario", default="loiter_basic")
    rp.add_argument("--camera", default=None)
    rp.add_argument("--seed", type=int, default=1)
    cp = sub.add_parser("calibrate", help="build conformal calibration sets from simulated normal traffic")
    cp.add_argument("--hours", type=float, default=4.0, help="camera-hours of simulated normal traffic")
    cp.add_argument("--workers", type=int, default=3)
    cp.add_argument("--scenario", default="normal_traffic", help="festival_traffic for an event mode (F16)")
    cp.add_argument("--mode", default="normal", help="calibration set to write, e.g. chand_raat")
    cp.add_argument(
        "--plugins",
        default="",
        help="plugins to calibrate (default: loitering,snatch; the safety plugins with --scenario street_life)",
    )
    fp = sub.add_parser("evaluate-fa", help="empirical false alarms per camera-hour on held-out normal traffic")
    fp.add_argument("--hours", type=float, default=2.0)
    fp.add_argument("--workers", type=int, default=3)
    fp.add_argument("--scenario", default="normal_traffic")
    fp.add_argument("--seed0", type=int, default=50_000, help="first seed; add more hours with new scenes")
    fp.add_argument("--mode", default="normal", help="event mode the pipeline runs in (its calibration set)")
    sub.add_parser("keygen", help="create/show the device signing key")
    sp = sub.add_parser("sms-test", help="send a test SMS through the configured gateway")
    sp.add_argument("--to", required=True)
    sub.add_parser("doctor", help="check the edge environment")
    dp = sub.add_parser("discover", help="find ONVIF cameras / DVRs on the LAN and their RTSP streams (F20)")
    dp.add_argument("--timeout", type=float, default=3.0)
    dp.add_argument("--interface", default=None, help="IP of the network card facing the cameras")
    dp.add_argument("--user", default="", help="ONVIF user, to list each device's stream URIs")
    dp.add_argument("--password-env", default="", help="name of the env var holding the ONVIF password")
    pp = sub.add_parser("probe-stream", help="test an RTSP stream (or video file) before adding it (F20)")
    pp.add_argument("--url-env", default="", help="env var with the RTSP URL, e.g. CAM_GATE_01_RTSP")
    pp.add_argument("--url", default="", help="RTSP URL or video file (prefer --url-env for passwords)")
    pp.add_argument("--seconds", type=float, default=8.0)
    wp = sub.add_parser("setup", help="Urdu setup wizard in the browser: add a camera and its zone (F20)")
    wp.add_argument("--host", default="0.0.0.0", help="127.0.0.1 = only from this machine")  # noqa: S104
    wp.add_argument("--port", type=int, default=8090)
    wp.add_argument("--env-file", default=".env", help="where the RTSP URLs (with passwords) are written")
    wp.add_argument("--allow-files", action="store_true", help="also accept a video file as the camera (testing)")
    args = ap.parse_args(argv)
    setup_logging(args.log_level)
    handlers = {
        "run": cmd_run,
        "replay": cmd_replay,
        "calibrate": cmd_calibrate,
        "evaluate-fa": cmd_evaluate_fa,
        "keygen": cmd_keygen,
        "sms-test": cmd_sms_test,
        "doctor": cmd_doctor,
        "discover": cmd_discover,
        "probe-stream": cmd_probe_stream,
        "setup": cmd_setup,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
