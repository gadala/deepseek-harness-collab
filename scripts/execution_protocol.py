#!/usr/bin/env python3
"""Batch-local coordination receipts. No model calls, launch, sandbox or lifecycle control."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from work_time_gate import evaluate

QUALITY = {"worker", "scope", "negative", "contract", "independent", "integration"}
TRANSITIONS = {
    "reserved": {"running", "unknown", "delivered", "failed"},
    "running": {"running", "unknown", "delivered", "failed"},
    "unknown": {"running", "unknown", "delivered", "failed"},
    "delivered": set(), "failed": set(),
}


class ProtocolError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise ProtocolError(message)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), "missing/invalid " + name)
    return value


def strings(value, name):
    require(isinstance(value, list), "missing/invalid " + name)
    for item in value:
        text(item, name)
    require(len(value) == len(set(value)), "duplicate " + name)
    return value


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("nonfinite JSON")))


def snapshot(value):
    require(isinstance(value, dict) and set(value) == {"baseline", "interfaces"}, "invalid snapshot")
    text(value["baseline"], "baseline")
    require(isinstance(value["interfaces"], dict), "invalid interfaces")
    for key, version in value["interfaces"].items():
        text(key, "interface"); text(version, "interface hash/version")
    return copy.deepcopy(value)


def path_key(value):
    return os.path.normcase(str(value))


def exact_path(value, root, write=False):
    text(value, "path")
    require(not any(c in value for c in "*?[]\x00"), "wildcards/control path not allowed")
    raw = Path(value)
    require(".." not in raw.parts, "parent traversal not allowed")
    if os.name == "nt":
        for part in raw.parts[1:] if raw.is_absolute() else raw.parts:
            require(not part.endswith((" ", ".")) and ":" not in part,
                    "ambiguous Windows path/alternate stream")
            require(not re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", part),
                    "Windows device path")
    resolved = (raw if raw.is_absolute() else root / raw).resolve()
    if write:
        require(resolved != root and resolved.is_relative_to(root), "write outside authorized cwd")
    require(not resolved.is_dir(), "exact files required, not directory grants")
    return str(resolved)


def validate(card):
    require(isinstance(card, dict) and type(card.get("schemaVersion")) is int
            and card["schemaVersion"] == 1, "invalid task schema")
    for key in ("taskId", "attemptId", "department", "goal"):
        text(card.get(key), key)
    root = Path(text(card.get("cwd"), "cwd"))
    require(root.is_absolute() and root.is_dir(), "cwd must be an existing absolute directory")
    root = root.resolve()
    result = copy.deepcopy(card)
    result["cwd"] = str(root)
    for key in ("nonGoals", "readSet", "writeSet", "dependencies", "risks", "unknowns", "checks"):
        strings(card.get(key), key)
    require(not (QUALITY - set(card["checks"])), "missing quality gates")
    require(bool(card["nonGoals"]), "nonGoals required")
    require(card["taskId"] not in card["dependencies"], "self dependency")
    for key in ("readSet", "writeSet"):
        result[key] = [exact_path(v, root, key == "writeSet") for v in card[key]]
        keys = [path_key(v) for v in result[key]]
        require(len(keys) == len(set(keys)), "aliased duplicate path")
    result["snapshot"] = snapshot(card.get("snapshot"))
    permissions = card.get("permissions")
    require(isinstance(permissions, dict), "permissions required")
    for key in ("gitIndex", "deploy", "recursiveDelegation"):
        require(type(permissions.get(key)) is bool, "explicit boolean permission required")
    require(permissions["recursiveDelegation"] is False, "recursive delegation not supported by this protocol")
    result["resources"] = strings(card.get("resources", []), "resources")
    return result


def file_hash(path):
    p = Path(path)
    if not p.exists():
        return None
    require(p.is_file(), "evidence/output must be a file")
    h = hashlib.sha256()
    with p.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def receipt(path):
    p = Path(path).resolve()
    value = file_hash(p)
    require(value is not None, "missing evidence")
    return {"path": str(p), "sha256": value}


def evidence(item):
    require(isinstance(item, dict), "evidence receipt required")
    p = Path(text(item.get("path"), "evidence path"))
    require(p.is_absolute(), "absolute evidence path required")
    h = item.get("sha256")
    require(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h), "invalid evidence hash")
    require(file_hash(p) == h, "missing or changed evidence")
    return {"path": str(p.resolve()), "sha256": h}


def manifests(card):
    return {p: file_hash(p) for p in sorted(set(card["readSet"] + card["writeSet"]))}


@contextmanager
def transaction(registry, create=False):
    """Fail-fast exclusive creation lock + replace. Never expire a possibly live lock."""
    registry = Path(registry).resolve()
    require(registry.parent.is_dir(), "registry parent must exist")
    lock = registry.with_suffix(registry.suffix + ".lock")
    token = json.dumps({"pid": os.getpid(), "createdAt": timestamp(), "token": uuid.uuid4().hex})
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(token); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        raise ProtocolError("registry busy or abandoned lock; inspect owner, never auto-unlock") from None
    temporary = None
    try:
        if create:
            require(not registry.exists(), "registry exists; initialization cannot overwrite")
            data = {}
        else:
            data = load(registry)
            require(isinstance(data, dict) and data.get("schemaVersion") == 1
                    and isinstance(data.get("tasks"), list), "invalid registry")
        yield data
        fd, temporary = tempfile.mkstemp(prefix=registry.name + ".", suffix=".tmp", dir=registry.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, registry)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        if lock.exists() and lock.read_text(encoding="utf-8") == token:
            lock.unlink()


def initialize(registry, current):
    current = snapshot(current)
    with transaction(registry, create=True) as data:
        data.update(schemaVersion=1, snapshot=current, tasks=[], events=[])
    return {"status": "initialized"}


def time_gate():
    return evaluate(datetime.now(timezone.utc))


def find(data, task, attempt):
    matches = [t for t in data["tasks"] if t["taskId"] == task and t["attemptId"] == attempt]
    require(len(matches) == 1, "unknown task/attempt")
    return matches[0]


def current_acceptance(data, task, seen=None):
    if task.get("acceptance") != "accepted":
        return task.get("acceptance", "pending")
    try:
        seen = set() if seen is None else set(seen)
        require(task["taskId"] not in seen, "cyclic dependency")
        seen.add(task["taskId"])
        latest = {t["taskId"]: t for t in data["tasks"]}
        for dep in task["card"]["dependencies"]:
            require(dep in latest and current_acceptance(data, latest[dep], seen) == "accepted", "dependency stale")
        require(task["card"]["snapshot"] == data["snapshot"], "snapshot changed")
        require(manifests(task["card"]) == task["acceptedManifest"], "workspace changed")
        for item in task["acceptedEvidence"]:
            evidence(item)
    except (ProtocolError, OSError):
        return "stale"
    return "accepted"


def event(data, task, action):
    data["events"].append({"at": timestamp(), "taskId": task["taskId"],
                           "attemptId": task["attemptId"], "action": action})


def reserve(registry, card):
    card = validate(card)
    require(time_gate()["status"] == "allow", "time gate forbids new Harness request")
    with transaction(registry) as data:
        require(card["snapshot"] == data["snapshot"], "stale baseline/interface snapshot")
        controls = {path_key(Path(registry).resolve()), path_key(Path(registry).resolve().with_suffix(Path(registry).suffix + ".lock"))}
        require(not ({path_key(p) for p in card["writeSet"]} & controls), "control registry/lock cannot be worker writes")
        require(not any(t["attemptId"] == card["attemptId"] for t in data["tasks"]), "duplicate batch attempt ID")
        prior = [t for t in data["tasks"] if t["taskId"] == card["taskId"]]
        require(not any(t["attemptId"] == card["attemptId"] for t in prior), "duplicate attempt; reconcile first")
        if prior:
            require(all(t["released"] for t in prior), "task still reserved")
            text(card.get("retryReason"), "retryReason")
        latest = {t["taskId"]: t for t in data["tasks"]}
        for dep in card["dependencies"]:
            require(dep in latest and latest[dep]["released"]
                    and current_acceptance(data, latest[dep]) == "accepted", "dependency not current accepted/released")
        writes = {path_key(p) for p in card["writeSet"]}
        reads = {path_key(p) for p in card["readSet"]}
        for other in data["tasks"]:
            if other["released"]:
                continue
            old_writes = {path_key(p) for p in other["card"]["writeSet"]}
            old_reads = {path_key(p) for p in other["card"]["readSet"]}
            require(not (writes & (old_writes | old_reads) or reads & old_writes), "write/read reservation conflict")
            require(not (set(card["resources"]) & set(other["card"]["resources"])), "resource reservation conflict")
        task = {"taskId": card["taskId"], "attemptId": card["attemptId"], "card": card,
                "phase": "reserved", "process": "unknown", "descendants": "unknown",
                "released": False, "acceptance": "pending", "receipt": None,
                "initialManifest": manifests(card), "risks": card["risks"], "unknowns": card["unknowns"]}
        data["tasks"].append(task); event(data, task, "reserved")
    return {"status": "reserved", "taskId": card["taskId"], "attemptId": card["attemptId"]}


def preflight(registry, task_id, attempt_id):
    gate = time_gate()
    require(gate["status"] == "allow", "time gate forbids new Harness request")
    with transaction(registry) as data:
        task = find(data, task_id, attempt_id)
        require(not task["released"] and task["phase"] in {"reserved", "running"}, "not eligible for dispatch/continuation")
        require(task["card"]["snapshot"] == data["snapshot"], "stale baseline/interface snapshot")
        require(not task["unknowns"], "resolve unknowns before new request")
        if task["phase"] == "reserved":
            require(not task.get("dispatchIssued"), "launch check already issued; reconcile before retry")
            require(manifests(task["card"]) == task["initialManifest"], "baseline drift before start")
            task["dispatchIssued"] = True
        else:
            require(task["process"] == "running", "continuation requires live runtime")
        latest = {t["taskId"]: t for t in data["tasks"]}
        for dep in task["card"]["dependencies"]:
            require(dep in latest and current_acceptance(data, latest[dep]) == "accepted", "stale dependency")
        event(data, task, "preflight_allowed")
    return {"status": "allow", "taskId": task_id, "attemptId": attempt_id,
            "gate": gate, "note": "Immediate-use check only; not a future permit or model transport interception."}


def update(registry, record):
    with transaction(registry) as data:
        task = find(data, record.get("taskId"), record.get("attemptId"))
        phase = record.get("phase")
        require(not task["released"] and phase in TRANSITIONS[task["phase"]], "illegal lifecycle transition")
        proof = evidence(record.get("evidence"))
        risks = strings(record.get("risks"), "risks")
        unknowns = strings(record.get("unknowns"), "unknowns")
        removed = (set(task["risks"]) - set(risks)) | (set(task["unknowns"]) - set(unknowns))
        if removed:
            text(record.get("resolution"), "risk/unknown resolution backed by lifecycle evidence")
        process = record.get("process")
        descendants = record.get("descendants")
        require(process in {"running", "unknown", "stopped", "not_started"}, "invalid process state")
        require(descendants in {"unknown", "running", "stopped", "none"}, "invalid descendants state")
        code = record.get("exitCode")
        require(code is None or type(code) is int, "invalid process exit code")
        runtime = record.get("runtime")
        if runtime is not None:
            require(isinstance(runtime, dict), "invalid runtime receipt")
            text(runtime.get("handle"), "exec handle")
            if runtime.get("sessionId") is not None:
                text(runtime["sessionId"], "session ID")
            strings(runtime.get("children"), "real child IDs")
            previous = task.get("runtime")
            if previous:
                require(runtime["handle"] == previous["handle"], "runtime handle changed")
                if previous.get("sessionId") is not None:
                    require(runtime.get("sessionId") == previous["sessionId"], "parent session changed")
                require(set(previous.get("children", [])).issubset(runtime["children"]), "previous child omitted")
            task["runtime"] = copy.deepcopy(runtime)
        if process == "not_started":
            require(not task.get("runtime"), "known runtime cannot become not_started")
        if descendants == "none":
            require(not task.get("runtime", {}).get("children"), "known children require stop evidence, not none")
        if phase == "running":
            require(process == "running" and task.get("runtime"), "running requires actual runtime")
            # Observation, not launch permission: a fast worker may already have written.
        elif phase in {"delivered", "failed"}:
            require(process in {"stopped", "not_started"} and descendants in {"stopped", "none"},
                    "settlement requires parent AND descendants stop evidence")
            if process == "stopped":
                require(task.get("runtime"), "stopped execution requires real runtime receipt")
            if phase == "delivered":
                require(process == "stopped" and code == 0, "delivered requires real zero exit")
            task["deliveredManifest"] = manifests(task["card"])
        elif phase == "unknown":
            require(process == "unknown" or descendants == "unknown", "unknown must remain explicit")
        task.update(phase=phase, process=process, descendants=descendants, exitCode=code,
                    receipt=proof, risks=risks, unknowns=unknowns)
        if record.get("resolution"):
            task["resolution"] = text(record["resolution"], "resolution")
        event(data, task, phase)
    return {"status": phase, "acceptance": "pending", "released": False}


def accept(registry, result):
    with transaction(registry) as data:
        task = find(data, result.get("taskId"), result.get("attemptId"))
        require(result.get("schemaVersion") == 1 and result.get("reviewer") == "codex", "independent Codex receipt required")
        require(task["phase"] == "delivered" and not task["released"], "not delivered or already released")
        require(snapshot(result.get("snapshot")) == data["snapshot"] == task["card"]["snapshot"], "stale acceptance snapshot")
        require(not strings(result.get("unknowns"), "unknowns") and not task["unknowns"], "unresolved unknowns")
        risks = strings(result.get("risks"), "risks")
        require(set(task["risks"]).issubset(risks), "acceptance omitted residual risks")
        latest = {t["taskId"]: t for t in data["tasks"]}
        for dep in task["card"]["dependencies"]:
            require(dep in latest and current_acceptance(data, latest[dep]) == "accepted", "dependency stale at acceptance")
        checks = result.get("checks")
        require(isinstance(checks, list), "checks required")
        names = [c.get("name") for c in checks if isinstance(c, dict)]
        require(len(names) == len(checks) == len(set(names)), "invalid/duplicate checks")
        require(set(task["card"]["checks"]).issubset(names), "missing quality evidence")
        proofs = [evidence(task["receipt"])]
        for check in checks:
            text(check.get("command"), "check command/manual procedure")
            require(type(check.get("exitCode")) is int and check["exitCode"] == 0, "failed/unrun required check")
            require(check.get("performedBy") == ("worker" if check["name"] == "worker" else "codex"),
                    "worker evidence cannot replace independent verification")
            proofs.append(evidence(check.get("evidence")))
        artifacts = result.get("artifacts")
        require(isinstance(artifacts, list) and bool(artifacts), "artifacts required")
        proofs.extend(evidence(a) for a in artifacts)
        require(manifests(task["card"]) == task["deliveredManifest"], "workspace changed since delivery")
        task.update(acceptance="accepted", acceptedManifest=manifests(task["card"]),
                    acceptedEvidence=proofs, acceptanceReceipt=copy.deepcopy(result))
        event(data, task, "acceptance_recorded")
    return {"status": "acceptance_recorded", "note": "Evidence integrity only; not test execution/authentication."}


def release(registry, task_id, attempt_id, proof):
    proof = evidence(proof)
    with transaction(registry) as data:
        task = find(data, task_id, attempt_id)
        require(not task["released"] and task["phase"] in {"delivered", "failed"}
                and task["process"] in {"stopped", "not_started"}
                and task["descendants"] in {"stopped", "none"}, "cannot release live/unknown reservation")
        evidence(task["receipt"])
        task.update(released=True, releaseReceipt=proof)
        event(data, task, "released")
    return {"status": "released"}


def refresh(registry, current):
    current = snapshot(current)
    with transaction(registry) as data:
        data["snapshot"] = current
        data["events"].append({"at": timestamp(), "action": "snapshot_refreshed"})
    return {"status": "snapshot_refreshed", "note": "Old passes become stale; existing locks stay held."}


def inspect(registry):
    data = load(registry)
    require(isinstance(data, dict) and data.get("schemaVersion") == 1, "invalid registry")
    data = copy.deepcopy(data)
    for task in data["tasks"]:
        task["acceptance"] = current_acceptance(data, task)
    return data


def handoff(registry):
    data = inspect(registry)
    keys = ("taskId", "attemptId", "phase", "process", "descendants", "released", "acceptance",
            "receipt", "risks", "unknowns")
    latest = {}
    history = []
    for task in data["tasks"]:
        prior = latest.get(task["taskId"])
        if prior is not None:
            history.append({"taskId": prior["taskId"], "attemptId": prior["attemptId"],
                            "phase": prior["phase"], "acceptance": prior["acceptance"],
                            "released": prior["released"], "receipt": prior["receipt"]})
        latest[task["taskId"]] = task
    tasks = []
    for task in latest.values():
        item = copy.deepcopy(task["card"])
        item.update({key: task[key] for key in keys})
        item.update(authorizationInherited=False, runtime=task.get("runtime"),
                    dispatchIssued=task.get("dispatchIssued", False), resolution=task.get("resolution"),
                    acceptanceReceipt=task.get("acceptanceReceipt"))
        tasks.append(item)
    return {"schemaVersion": 1, "registry": str(Path(registry).resolve()),
            "snapshot": data["snapshot"], "tasks": tasks, "history": history,
            "note": "Reference only: recheck baseline, lifecycle, permissions and time gate before new work."}


def summary(registry):
    data = inspect(registry)
    latest = {}
    for task in data["tasks"]:
        latest[task["taskId"]] = task
    return {"schemaVersion": 1, "snapshot": data["snapshot"], "tasks": [
        {"taskId": t["taskId"], "attemptId": t["attemptId"], "phase": t["phase"],
         "process": t["process"], "descendants": t["descendants"], "released": t["released"],
         "acceptance": t["acceptance"], "risks": t["risks"], "unknowns": t["unknowns"]}
        for t in latest.values()
    ]}


def validate_handoff(registry, value):
    require(value == handoff(registry), "handoff incomplete or stale; regenerate from current registry")
    return {"status": "handoff_matches_current_registry", "authorizationInherited": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "validate", "reserve", "update", "accept", "release",
                                            "refresh", "inspect", "summary", "handoff", "validate-handoff", "receipt", "preflight"])
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--record", type=Path, help="Task, lifecycle, acceptance, snapshot or handoff JSON")
    parser.add_argument("--path", type=Path, help="Evidence file for receipt")
    args = parser.parse_args()
    try:
        if args.action == "receipt":
            require(args.path is not None, "--path required")
            result = receipt(args.path)
        else:
            if args.action != "validate":
                require(args.registry is not None, "--registry required")
            if args.action in {"inspect", "summary", "handoff"}:
                result = (inspect(args.registry) if args.action == "inspect" else
                          summary(args.registry) if args.action == "summary" else handoff(args.registry))
            else:
                require(args.record is not None, "--record required")
                record = load(args.record)
                if args.action == "validate": result = {"status": "valid", "card": validate(record)}
                elif args.action == "init": result = initialize(args.registry, record)
                elif args.action == "reserve": result = reserve(args.registry, record)
                elif args.action == "update": result = update(args.registry, record)
                elif args.action == "accept": result = accept(args.registry, record)
                elif args.action == "preflight": result = preflight(args.registry, record.get("taskId"), record.get("attemptId"))
                elif args.action == "refresh": result = refresh(args.registry, record)
                elif args.action == "validate-handoff": result = validate_handoff(args.registry, record)
                else:
                    result = release(args.registry, record.get("taskId"), record.get("attemptId"), record.get("evidence"))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ProtocolError, OSError, ValueError, KeyError, TypeError) as error:
        # Do not dump input, logs, environment or auth configuration.
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
