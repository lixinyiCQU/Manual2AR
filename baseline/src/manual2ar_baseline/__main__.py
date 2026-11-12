"""GT/state tools and explicitly experimental photo observations; no AR or camera UI."""
import argparse
from pathlib import Path

from .gt import load_bundle, normalize, snapshot, verify_sources
from .provider import ModelError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("snapshot")
    capture.add_argument("--selection", type=Path, required=True)
    capture.add_argument("--reference-root", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("normalize")
    build.add_argument("--sources", type=Path, required=True)
    build.add_argument("--mapping", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--review-decisions", type=Path)
    check = commands.add_parser("validate")
    check.add_argument("bundle", type=Path)
    check.add_argument("--reference-root", type=Path)
    state = commands.add_parser("validate-state")
    state.add_argument("--bundle", type=Path, required=True)
    state.add_argument("--cases", type=Path, required=True)
    state.add_argument("--output", type=Path, required=True)
    observe = commands.add_parser("observe-photo")
    manual = commands.add_parser("confirm-photo")
    for command in (observe, manual):
        command.add_argument("--bundle", type=Path, required=True)
        command.add_argument("--protocol", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--resume-run", type=Path, required=command is manual)
        context = command.add_mutually_exclusive_group()
        context.add_argument("--same-context", action="store_true")
        context.add_argument("--context-id")
    observe.add_argument("--reference-root", type=Path, required=True)
    observe.add_argument("--image", type=Path, required=True)
    observe.add_argument("--config", type=Path, required=True)
    observe.add_argument("--model")
    observe.add_argument("--intent")
    manual.add_argument("--condition", action="append", required=True)
    manual.add_argument("--statement", required=True)
    review = commands.add_parser("review-photo")
    score = commands.add_parser("score-photo")
    for command in (review, score):
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    score.add_argument("--labels", type=Path, required=True)
    compile_command = commands.add_parser("compile-official")
    compile_command.add_argument("--archive", type=Path, required=True)
    compile_command.add_argument("--manifest", type=Path, required=True)
    compile_command.add_argument("--intent", required=True)
    compile_command.add_argument("--capabilities", type=Path, default=Path(__file__).resolve().parents[2] / 'capabilities/v1.json')
    compile_command.add_argument("--config", type=Path, required=True)
    compile_command.add_argument("--model")
    compile_command.add_argument("--source-url")
    compile_command.add_argument("--device-path", default='/zh/a1-mini/')
    compile_command.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare-gt")
    compare.add_argument("--compiled", type=Path, required=True)
    compare.add_argument("--gt", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    plan = commands.add_parser('eval-plan')
    plan.add_argument('--suite', type=Path, required=True)
    plan.add_argument('--archive', type=Path, required=True)
    plan.add_argument('--manifest', type=Path, required=True)
    plan.add_argument('--capabilities', type=Path, default=Path(__file__).resolve().parents[2] / 'capabilities/v1.json')
    plan.add_argument('--repeats', type=int, default=3)
    plan.add_argument('--output', type=Path, required=True)
    run = commands.add_parser('eval-run')
    report = commands.add_parser('eval-report')
    for command in (run, report):
        command.add_argument('--plan', type=Path, required=True)
    for command in (plan, run):
        command.add_argument('--config', type=Path, required=True)
        command.add_argument('--model')
    report.add_argument('--labels', type=Path)
    report.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command.startswith('eval-'):
            from .evaluation import make_plan, run_plan, report
            from .provider import load_settings
            if args.command == 'eval-plan':
                make_plan(args.suite, args.archive, args.manifest, args.capabilities, load_settings(args.config, args.model), args.output,
                          repeats=args.repeats, repo_root=Path(__file__).resolve().parents[3])
                print('Frozen evaluation plan; no model calls: ' + str(args.output / 'plan.json'))
            elif args.command == 'eval-run':
                run_plan(args.plan, load_settings(args.config, args.model))
                print('Evaluation attempts retained: ' + str(args.plan))
            else:
                report(args.plan, args.output, labels_path=args.labels)
                print('Evaluation report: ' + str(args.output / 'REPORT.md'))
        elif args.command == "compile-official":
            from .compiler import compile_task, render_resources
            from .sources import retrieve
            from .provider import CompatibleClient, load_settings
            sources, source_root, retrieval = retrieve(args.archive, args.manifest, args.intent, device_path=args.device_path, source_url=args.source_url, assembly_context=True)
            result = compile_task(sources, source_root, retrieval, args.intent, args.capabilities,
                CompatibleClient(load_settings(args.config, args.model), max_tokens=16000), args.output,
                ar_resources=render_resources(Path(__file__).resolve().parents[3]))
            print('Official compilation: ' + result['status'] + '; review: ' + str(args.output / 'REVIEW.md'))
        elif args.command == "compare-gt":
            from .compiler import compare_gt
            result = compare_gt(args.compiled, args.gt, args.output)
            print('Independent GT comparison; semantic accuracy is not rated; report: ' + str(args.output))
        elif args.command == "snapshot":
            snapshot(args.selection, args.reference_root, args.output)
            print("Reference excerpts captured; normalization is not approved.")
        elif args.command == "normalize":
            normalize(args.sources, args.mapping, args.output, args.review_decisions)
            import json
            print("Normalized bundle written: " + json.loads((args.output / "review.json").read_bytes())["status"])
        elif args.command == "validate-state":
            from .validation import run
            report = run(args.bundle, args.cases, args.output)
            print(f"Controlled state cases: {report['passed']}/{report['total']} passed; report: {args.output}")
            if report["passed"] != report["total"]:
                parser.exit(1, "State validation failed; inspect results.json.\n")
        elif args.command in ("observe-photo", "confirm-photo"):
            from .photos import confirm, observe as observe_photo, prepare_session
            sources, protocol, session = prepare_session(args.bundle, args.protocol, resume=args.resume_run,
                intent=getattr(args, "intent", None), same_context=args.same_context, context_id=args.context_id)
            if args.command == "observe-photo":
                from .provider import CompatibleClient, load_settings
                client = CompatibleClient(load_settings(args.config, args.model))
                plan = observe_photo(session, sources, protocol, args.image, args.reference_root, args.output, client)
            else:
                plan = confirm(session, protocol, args.condition, args.statement, args.output)
            print("Experimental photo session: " + plan["mode"] + "; " + plan["reason"])
            print("Evidence record: " + str(args.output))
        elif args.command in ("review-photo", "score-photo"):
            from .photo_review import review_saved, score as score_photo
            if args.command == "review-photo":
                review_saved(args.run, args.output)
                print("Unrated review package: " + str(args.output))
            else:
                result = score_photo(args.run, args.labels, args.output)
                print(f"Rated conditions: {result['rated']}; unrated: {result['unrated']}; score: {args.output}")
        else:
            sources, task = load_bundle(args.bundle)
            if args.reference_root:
                verify_sources(sources, args.reference_root)
            import json
            status = json.loads((args.bundle / "review.json").read_bytes())["status"]
            print(f"Valid bundle: {len(task.nodes)} nodes, {len(task.conditions)} conditions, "
                  f"{len(task.requirements)} mapped requirements; source={sources.source_selection}; normalization={status}")
    except (OSError, ValueError, ModelError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
