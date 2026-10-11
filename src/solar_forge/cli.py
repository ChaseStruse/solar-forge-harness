"""Small terminal interface; all durable behavior lives in the workflow modules."""
import argparse
from dataclasses import replace
from pathlib import Path
import sys

from . import __version__
from .agent import approve, run
from .audit import Audit
from .chat import ChatService
from .domain import Config, ForgeError, REQUEST_TEMPLATE
from .providers import HTTPProvider, assert_identity, configured_identity
from .requests import current_request, request_name, request_path
from .setup import create, initialize
from .workflow import discover, plan, prepare, record_answer
from .workspace import Workspace
from .retrieval import build_index, index_status, search, format_result, record_standalone


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog='forge', description='Request-driven, provider-independent coding harness.')
    cli.add_argument('--version', action='version', version=__version__)
    cli.add_argument('--project', type=Path, default=Path.cwd(), help='Project root (default: current directory)')
    commands = cli.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Set up your model, documents, and project guidance')
    init.add_argument('--no-interactive', action='store_true', help='Create setup templates without prompts')
    request = commands.add_parser('request', help='Create a request template')
    request.add_argument('title')
    request.add_argument('--output', help='Must be agentic_audit/requests/<request-name>/request.md')
    index = commands.add_parser('index', help='Build or inspect the local document library')
    index.add_argument('--status', action='store_true', help='Inspect freshness without rebuilding')
    lookup = commands.add_parser('search', help='Search local reference passages without a model call')
    lookup.add_argument('query', help='Quoted search query')
    chat = commands.add_parser('chat', help='Open a terminal chat interface with the configured model')
    chat.add_argument('--provider', choices=['openai', 'anthropic', 'ollama', 'compatible'])
    chat.add_argument('--model')
    chat.add_argument('--resume', help='Project-relative saved chat audit to reopen')
    for name, help_text in [('prepare', 'Discover documentation and generate domain questions'),
                            ('discover', 'Retry discovery for a run after a failed model call'),
                            ('plan', 'Generate a plan after all questions have answers'),
                            ('run', 'Approve a plan and run the bounded coding agent')]:
        command = commands.add_parser(name, help=help_text)
        if name == 'prepare':
            command.add_argument('request', nargs='?', default=None)
            command.add_argument('--no-interactive', action='store_true', help='Leave questions pending for forge answer')
        else:
            command.add_argument('audit', help='Project-relative run directory')
        command.add_argument('--provider', choices=['openai', 'anthropic', 'ollama', 'compatible'])
        command.add_argument('--model')
        if name == 'run':
            command.add_argument('--approve', action='store_true', help='Explicitly approve the current saved plan without a prompt')
    answer = commands.add_parser('answer', help='Answer pending questions interactively or one at a time')
    answer.add_argument('audit')
    answer.add_argument('--question', help='Question ID, e.g. Q1')
    answer.add_argument('--text', help='Answer to the selected question')
    status = commands.add_parser('status', help='Show run states or details for one run')
    status.add_argument('audit', nargs='?')
    return cli


def answer_interactively(audit: Audit) -> None:
    state = audit.load()
    for q in state['questions']:
        if q.get('answer'):
            continue
        print(f"\n{q['id']}: {q['question']}\nWhy: {q['rationale']}\nSources: {', '.join(q['sources'])}")
        while True:
            answer = input('Answer (Ctrl-C to save and stop): ').strip()
            if answer:
                record_answer(audit, q['id'], answer)
                break
            print('An answer is required; no default decision will be made.')
    print(f"State: {audit.load()['status']}")


def show(audit: Audit, workspace: Workspace) -> None:
    state = audit.load()
    pending = sum(not q.get('answer') for q in state['questions'])
    print(f"{audit.path.relative_to(workspace.root)}\n  {state['title']}: {state['status']}; "
          f"{pending} pending questions; {state['turns']} turns")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    workspace = Workspace(args.project)
    try:
        if not workspace.root.is_dir():
            raise ForgeError('Project root must be an existing directory.')
        if args.command == 'init':
            initialize(workspace, interactive=not args.no_interactive and sys.stdin.isatty())
            return 0
        if args.command == 'request':
            if '\n' in args.title or '\r' in args.title or not args.title.strip():
                raise ForgeError('Request title must be a nonempty single line.')
            name = args.output or request_name(args.title)
            request_path(workspace, name)
            create(workspace, name, REQUEST_TEMPLATE.replace('Your request title', args.title.strip()), internal=True)
            return 0
        if args.command == 'status':
            if args.audit:
                show(Audit.open(workspace, args.audit), workspace)
            else:
                runs = Audit.discover(workspace)
                for audit in runs:
                    show(audit, workspace)
                if not runs:
                    print('No audited runs yet. Start with forge prepare.')
            return 0
        if args.command == 'answer':
            audit = Audit.open(workspace, args.audit)
            with audit.lock():
                if args.question is not None or args.text is not None:
                    if args.question is None or args.text is None:
                        raise ForgeError('Use --question and --text together.')
                    record_answer(audit, args.question, args.text)
                else:
                    if audit.load()['status'] != 'awaiting_answers':
                        raise ForgeError('This run is not waiting for answers.')
                    answer_interactively(audit)
            return 0
        config = Config.load(workspace.path('.forge/config.toml'))
        workspace.max_file_bytes = config.max_file_bytes
        if args.command in {'index', 'search'}:
            result = (search(workspace, config, args.query) if args.command == 'search' else
                      index_status(workspace, config) if args.status else build_index(workspace, config))
            evidence = record_standalone(workspace, result)
            print(format_result(result))
            print(f'Evidence: {evidence}')
            return 0 if result['status'] == 'ready' else 1
        # Changing provider implies its default endpoint/key; explicit config still
        # applies when only the model changes.
        if args.provider and args.provider != config.kind:
            config = replace(config, kind=args.provider, base_url='', api_key_env='')
        if args.model:
            config = replace(config, model=args.model)
        workspace.max_file_bytes = config.max_file_bytes
        provider = HTTPProvider(config)
        if args.command == 'chat':
            from .terminal_chat import run_terminal_chat
            run_terminal_chat(ChatService(workspace, config, provider), resume=args.resume)
            return 0
        if args.command == 'prepare':
            audit = prepare(workspace, config, current_request(workspace, args.request), provider)
            show(audit, workspace)
            if not args.no_interactive and sys.stdin.isatty() and audit.load()['status'] == 'awaiting_answers':
                with audit.lock():
                    answer_interactively(audit)
            return 0
        audit = Audit.open(workspace, args.audit)
        with audit.lock():
            assert_identity(audit.load(), configured_identity(config))
            if args.command == 'discover':
                discover(audit, provider, config.max_prompt_bytes)
            elif args.command == 'plan':
                plan(workspace, config, audit, provider)
                print((audit.path / 'plan.md').read_text())
            elif args.command == 'run':
                state = audit.load()
                if state['status'] == 'planned':
                    print((audit.path / 'plan.md').read_text())
                    if not args.approve:
                        if not sys.stdin.isatty():
                            raise ForgeError('Review plan.md and pass --approve, or run in an interactive terminal.')
                        if input('Approve this plan and permit project file edits and configured verification commands? [y/N] ').strip().lower() not in {'y', 'yes'}:
                            print('Plan remains unapproved.')
                            return 0
                    approve(audit)
                run(workspace, config, audit, provider)
                if audit.load()['status'] == 'awaiting_answers' and sys.stdin.isatty():
                    answer_interactively(audit)
                    print('Generate and approve a revised plan before resuming edits.')
        show(audit, workspace)
        return 0
    except (ForgeError, OSError) as exc:
        print(f'forge: {exc}', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        message = ('Setup stopped. Existing files were kept. Run forge init to try again.' if args.command == 'init'
                   else 'Stopped. Saved answers and run checkpoints remain in agentic_audit.')
        print('\n' + message, file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
